"""事件上报 + 连接管理（TDD §4.1 / §8.2）。"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket
from langchain_core.callbacks import AsyncCallbackHandler


def tool_outcome(output: Any) -> str:
    """Recognize structured outcomes and legacy errors, including ToolMessage."""
    if getattr(output, "status", None) == "error":
        return "error"
    value = getattr(output, "content", output)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            compact = value.strip().replace(" ", "")
            if compact.startswith(("错误：", "错误:", "PDF转换失败", "查询药品表失败", "连接数据库失败",
                                   "网络检索失败", "知识库检索失败", "不支持的文件类型", "禁止执行写操作")):
                return "error"
    if isinstance(value, dict):
        if value.get("status") in {"error", "failed"} or value.get("success") is False:
            return "error"
        if value.get("status") == "no_data":
            return "no_data"
    return "ok"


def build_event(event: str, message: str, data: dict[str, Any] | None = None) -> dict:
    """按 TDD §8.2 组装统一推送结构。"""
    return {
        "type": "monitor_event",
        "event": event,
        "message": message,
        "data": data or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


class ConnectionManager:
    """按会话（thread_id）路由的 WebSocket 连接管理（TDD §4.1 / §8.2）。"""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}
        self._streams: dict[str, dict[str, dict]] = {}
        self._events: dict[str, list[dict]] = {}

    def clear_streams(self, thread_id: str) -> None:
        self._streams.pop(thread_id, None)
        self._events.pop(thread_id, None)

    def event_snapshot(self, thread_id: str) -> list[dict]:
        return list(self._events.get(thread_id, []))

    def stream_snapshot(self, thread_id: str) -> list[dict]:
        return [dict(block) for block in self._streams.get(thread_id, {}).values()]

    def _record_stream(self, thread_id: str, event: str, data: dict) -> dict:
        """Keep bounded snapshots so REST can repair missed WebSocket deltas."""
        if event not in {"model_start", "model_delta", "model_end"}:
            return data
        blocks = self._streams.setdefault(thread_id, {})
        block_id = data["id"]
        block = blocks.setdefault(block_id, {
            "id": block_id, "text": "", "status": "streaming", "seq": 0, "truncated": False,
        })
        if event == "model_delta":
            text = block["text"] + data.get("delta", "")
            block["truncated"] = block["truncated"] or len(text) > 32000
            block["text"] = text[-32000:]
            block["seq"] += 1
        elif event == "model_end":
            block["status"] = data.get("status", "completed")
            block["seq"] += 1
        while len(blocks) > 20:
            blocks.pop(next(iter(blocks)))
        return {**data, "seq": block["seq"], **({"block": dict(block)} if event != "model_delta" else {})}

    async def connect(self, thread_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.setdefault(thread_id, []).append(ws)

    def disconnect(self, thread_id: str, ws: WebSocket) -> None:
        conns = self._connections.get(thread_id)
        if conns is None:
            return
        if ws in conns:
            conns.remove(ws)
        if not conns:
            self._connections.pop(thread_id, None)

    async def send_event(
        self, thread_id: str, event: str, message: str, data: dict | None = None
    ) -> None:
        """把事件推送到指定会话的所有连接。

        ensure_ascii=True 让 JSON 走纯 ASCII（中文转 \\uXXXX），
        规避 Vite 的 WS 代理对非 ASCII 帧的 UTF-8 转写问题。
        """
        data = self._record_stream(thread_id, event, dict(data or {}))
        if event in {"task_result", "task_cancelled", "error"}:
            for block in self._streams.get(thread_id, {}).values():
                if block["status"] == "streaming":
                    block["status"] = "interrupted"
                    block["seq"] += 1
            data["streams"] = self.stream_snapshot(thread_id)
        envelope = build_event(event, message, data)
        if event not in {"model_start", "model_delta", "model_end"}:
            events = self._events.setdefault(thread_id, [])
            events.append({**envelope, "data": {k: v for k, v in data.items() if k != "streams"}})
            del events[:-300]
        text = json.dumps(envelope, ensure_ascii=True)
        for ws in list(self._connections.get(thread_id, [])):
            try:
                await ws.send_text(text)
            except Exception:  # noqa: BLE001
                self.disconnect(thread_id, ws)


class ToolMonitor:
    """事件上报单例（TDD §4.1）。"""

    def __init__(self, manager: ConnectionManager) -> None:
        self._manager = manager

    async def report(
        self, thread_id: str, event: str, message: str, data: dict | None = None
    ) -> None:
        await self._manager.send_event(thread_id, event, message, data)


# 模块级单例：全项目共享同一份连接管理与事件上报
manager = ConnectionManager()
monitor = ToolMonitor(manager)


class MonitorCallbackHandler(AsyncCallbackHandler):
    """把主智能体的工具调用事件实时上报（TDD §8.2）。

    - 工具名为 ``task`` → 判定为子智能体调度（assistant_call）
    - 其他工具 → 普通工具调用（tool_start）
    """

    def __init__(self, thread_id: str) -> None:
        self._thread_id = thread_id
        self._tool_names: dict[Any, str] = {}
        self._pending: dict[str, str] = {}
        self._flush_tasks: dict[str, asyncio.Task] = {}
        self._model_runs: set[str] = set()
        self._has_text: set[str] = set()

    async def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        key = str(run_id)
        if key not in self._model_runs:
            self._model_runs.add(key)
            await monitor.report(self._thread_id, "model_start", "模型正在生成输出", {"id": key})

    async def _flush(self, key: str) -> None:
        delta = self._pending.pop(key, "")
        if delta:
            await monitor.report(self._thread_id, "model_delta", "模型输出更新", {"id": key, "delta": delta})

    async def _flush_later(self, key: str) -> None:
        try:
            await asyncio.sleep(0.08)
            await self._flush(key)
        finally:
            self._flush_tasks.pop(key, None)
            if self._pending.get(key) and key in self._model_runs:
                self._flush_tasks[key] = asyncio.create_task(self._flush_later(key))

    async def on_llm_new_token(self, token: str, *, run_id, chunk=None, **kwargs):
        # Only public message content. Tool JSON and provider reasoning fields
        # are not presented as an answer or fabricated "thinking" text.
        content = getattr(getattr(chunk, "message", None), "content", token if chunk is None else "")
        if isinstance(content, list):
            content = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        if not isinstance(content, str) or not content:
            return
        key = str(run_id)
        await self.on_chat_model_start(None, [], run_id=run_id)
        self._pending[key] = self._pending.get(key, "") + content
        if key not in self._has_text:
            self._has_text.add(key)
            await self._flush(key)
        elif key not in self._flush_tasks:
            self._flush_tasks[key] = asyncio.create_task(self._flush_later(key))

    async def _finish_model(self, key: str, status: str) -> None:
        if key not in self._model_runs:
            return
        self._model_runs.discard(key)
        task = self._flush_tasks.pop(key, None)
        if task:
            # Let a pending send finish so model_end cannot overtake its delta.
            await task
        await self._flush(key)
        self._has_text.discard(key)
        await monitor.report(self._thread_id, "model_end", "本轮模型输出结束", {"id": key, "status": status})

    async def on_llm_end(self, response, *, run_id, **kwargs):
        usage = None
        for group in getattr(response, "generations", []) or []:
            for generation in group:
                candidate = getattr(getattr(generation, "message", None), "usage_metadata", None)
                if candidate:
                    usage = candidate
                    break
            if usage:
                break
        await monitor.report(self._thread_id, "model_usage", "模型用量", {
            "id": str(run_id), "usage": usage,
        })
        await self._finish_model(str(run_id), "completed")

    async def on_llm_error(self, error, *, run_id, **kwargs):
        await monitor.report(self._thread_id, "model_usage", "模型调用未完成，用量未知", {
            "id": str(run_id), "usage": None,
        })
        await self._finish_model(str(run_id), "interrupted")

    async def close(self) -> None:
        for key in list(self._model_runs):
            await self._finish_model(key, "interrupted")

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        tool_name = serialized.get("name", "")
        if run_id is not None:
            self._tool_names[run_id] = tool_name
        args = inputs or {}
        if tool_name == "task":
            subtype = args.get("subagent_type", "")
            await monitor.report(
                self._thread_id,
                "assistant_call",
                f"调度子智能体：{subtype}",
                {"assistant_name": subtype, "args": args.get("description", "")},
            )
        else:
            await monitor.report(
                self._thread_id,
                "tool_start",
                f"调用工具：{tool_name}",
                {"tool_name": tool_name, "args": args},
            )

    async def on_tool_end(
        self,
        output: Any,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        tool_name = self._tool_names.pop(run_id, "")
        if tool_name:
            outcome = tool_outcome(output)
            description = {"error": "工具执行失败", "no_data": "查询完成，无匹配数据", "ok": "工具执行完成"}[outcome]
            await monitor.report(
                self._thread_id,
                "tool_result",
                f"{description}：{tool_name}",
                {"tool_name": tool_name, "success": outcome != "error", "status": outcome},
            )

    async def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        tool_name = self._tool_names.pop(run_id, "")
        if tool_name:
            await monitor.report(
                self._thread_id,
                "tool_result",
                f"工具执行失败：{tool_name}",
                {"tool_name": tool_name, "success": False},
            )
