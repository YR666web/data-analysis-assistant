"""REST 路由 + WebSocket 端点 + 启动引导（TDD §4.1 / §8）。"""
from __future__ import annotations

import asyncio
import json
import shutil
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from agent.main_agent import run_deep_agent
from api.monitor import manager, monitor
from api import task_store
from utils import path_utils

app = FastAPI(title="数据分析助手 · 多智能体数据分析系统")
_running_tasks: dict[str, asyncio.Task] = {}
_task_statuses: dict[str, dict] = {}


def _save_task(thread_id: str) -> None:
    previous = task_store.get(thread_id) or {"thread_id": thread_id}
    state = _task_statuses.get(thread_id, {})
    task_store.save(thread_id, {**previous, **state,
        "session_dir": str(_session_dir(thread_id)),
        "events": manager.event_snapshot(thread_id), "streams": manager.stream_snapshot(thread_id)})


def _restore_task(thread_id: str) -> dict | None:
    if thread_id in _task_statuses:
        return _task_statuses[thread_id]
    saved = task_store.get(thread_id)
    if saved and saved.get("status") in {"running", "cancelling"} and thread_id not in _running_tasks:
        saved.update(status="failed", error="服务重启导致任务中断，请点击重跑；未自动重复执行。")
        for block in saved.get("streams", []):
            if block.get("status") == "streaming":
                block["status"] = "interrupted"
        saved.setdefault("events", []).append({"event": "error", "message": saved["error"], "data": {},
                                                "timestamp": datetime.now(timezone.utc).isoformat()})
        task_store.save(thread_id, saved)
    return saved


def _task_done(thread_id: str, task: asyncio.Task) -> None:
    # Cancellation before the coroutine first runs does not enter its finally block.
    if task.cancelled() and _running_tasks.get(thread_id) is task:
        _running_tasks.pop(thread_id, None)
        _task_statuses[thread_id] = {"status": "cancelled", "result": ""}
        _save_task(thread_id)
        asyncio.create_task(monitor.report(thread_id, "task_cancelled", "任务已终止"))


class TaskRequest(BaseModel):
    query: str
    thread_id: str | None = None
    require_pdf: bool = False


def _session_dir(thread_id: str):
    try:
        return path_utils.get_session_dir(thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _upload_dir(thread_id: str):
    try:
        return path_utils.get_upload_dir(thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/")
def root() -> dict:
    return {"status": "ok", "message": "数据分析助手服务已启动"}


async def _run_task(thread_id: str, query: str, require_pdf: bool) -> None:
    """后台执行任务，结束后推送 task_result / error 事件。"""
    try:
        result = await run_deep_agent(query, thread_id, require_pdf=require_pdf)
        _task_statuses[thread_id] = {"status": "completed", "result": result}
        await monitor.report(thread_id, "task_result", "任务完成", {"result": result})
    except asyncio.CancelledError:
        _task_statuses[thread_id] = {"status": "cancelled", "result": ""}
        await monitor.report(thread_id, "task_cancelled", "任务已终止")
        raise
    except Exception as e:  # noqa: BLE001
        _task_statuses[thread_id] = {"status": "failed", "error": str(e)}
        await monitor.report(thread_id, "error", f"任务失败：{e}")
    finally:
        _running_tasks.pop(thread_id, None)
        _save_task(thread_id)


@app.post("/api/task")
async def submit_task(body: TaskRequest) -> dict:
    """提交任务：创建会话目录、上报 session_created，异步执行并立即返回 thread_id。"""
    thread_id = body.thread_id or uuid4().hex
    session_dir = _session_dir(thread_id)
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="任务内容不能为空")
    if thread_id in _running_tasks:
        raise HTTPException(status_code=409, detail="该会话已有任务在运行")
    session_dir.mkdir(parents=True, exist_ok=True)
    manager.clear_streams(thread_id)
    await monitor.report(
        thread_id, "session_created", "会话工作目录已创建", {"path": str(session_dir)}
    )
    task_store.save(thread_id, {"thread_id": thread_id, "query": body.query,
        "require_pdf": body.require_pdf, "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "running", "result": "", "events": [], "streams": []})
    # 任务异步执行（TDD §8.1）：create_task 后台跑，立即返回
    _running_tasks[thread_id] = asyncio.create_task(
        _run_task(thread_id, body.query, body.require_pdf)
    )
    _running_tasks[thread_id].add_done_callback(lambda task: _task_done(thread_id, task))
    _task_statuses[thread_id] = {"status": "running", "result": ""}
    return {"status": "started", "thread_id": thread_id}


@app.get("/api/task/{thread_id}")
async def task_status(thread_id: str) -> dict:
    """查询任务最新状态，供页面断线或刷新后恢复会话。"""
    _session_dir(thread_id)
    state = _restore_task(thread_id)
    if state is None:
        return {"status": "unknown", "thread_id": thread_id}
    if thread_id in _running_tasks:
        _save_task(thread_id)
    return {**state, "thread_id": thread_id, "session_dir": str(_session_dir(thread_id)),
            "streams": manager.stream_snapshot(thread_id) or state.get("streams", [])}


@app.get("/api/sessions")
async def list_sessions(limit: int = 200, offset: int = 0) -> dict:
    if not 1 <= limit <= 200 or offset < 0:
        raise HTTPException(status_code=400, detail="无效的分页参数")
    records = task_store.list_tasks(limit, offset)
    return {"sessions": [{**record, **(_restore_task(record["thread_id"]) or {})} for record in records],
            "next_offset": offset + limit if len(records) == limit else None}


@app.post("/api/task/{thread_id}/cancel")
async def cancel_task(thread_id: str) -> dict:
    _session_dir(thread_id)
    task = _running_tasks.get(thread_id)
    if task is None or task.done():
        state = _restore_task(thread_id)
        if state:
            return {"status": state.get("status", "unknown"), "thread_id": thread_id}
        raise HTTPException(status_code=404, detail="没有正在运行的任务")
    if task.cancelling():
        return {"status": "cancelling", "thread_id": thread_id}
    task.cancel()
    _task_statuses[thread_id] = {"status": "cancelling", "result": ""}
    return {"status": "cancelling", "thread_id": thread_id}


@app.delete("/api/session/{thread_id}")
async def delete_session(thread_id: str) -> dict:
    """删除已结束会话的工作文件和上传文件。"""
    session_dir = _session_dir(thread_id)
    upload_dir = _upload_dir(thread_id)
    task = _running_tasks.get(thread_id)
    if task is not None and not task.done():
        raise HTTPException(status_code=409, detail="请先终止正在运行的任务")

    # 目录名由已验证的 thread_id 构造；符号链接只删除链接本身，不跟随到其他目录。
    for base, target in (
        (path_utils.OUTPUT_DIR, session_dir),
        (path_utils.UPLOAD_DIR, upload_dir),
    ):
        raw_target = base / f"session_{thread_id}"
        if raw_target.is_symlink():
            raw_target.unlink()
        elif target.exists() and target.is_dir() and path_utils.is_within(target, base):
            shutil.rmtree(target)

    _task_statuses.pop(thread_id, None)
    task_store.delete(thread_id)
    manager.clear_streams(thread_id)
    return {"status": "deleted", "thread_id": thread_id}


@app.post("/api/upload")
async def upload(
    thread_id: str = Form(...), files: list[UploadFile] = File(...)
) -> dict:
    """上传文件：流式写入 upload/session_{thread_id}。"""
    upload_dir = _upload_dir(thread_id)
    session_dir = _session_dir(thread_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    session_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for f in files:
        name = f.filename or ""
        if not name or name in (".", "..") or any(c in name for c in ("/", "\\", "\0", ":")):
            raise HTTPException(status_code=400, detail="无效的文件名")
        target = upload_dir / name
        working_copy = session_dir / name
        with open(target, "wb") as out:
            while chunk := await f.read(1024 * 1024):
                out.write(chunk)
        # 上传完成后立即装配到会话目录；任务开始前上传时也可被读取。
        shutil.copy2(target, working_copy)
        saved.append(name)
    return {"status": "uploaded", "files": saved}


@app.get("/api/files")
async def list_files(thread_id: str, path: str):
    """浏览目录：越界校验后返回目录内容（mtime 倒序，TDD §8.1）。"""
    target = path_utils.validate_path(path, _session_dir(thread_id))
    if target is None:
        return JSONResponse({"error": "拒绝访问"}, status_code=403)
    if not target.exists() or not target.is_dir():
        return JSONResponse({"error": "路径不存在"}, status_code=404)
    entries = []
    for p in sorted(target.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        entries.append(
            {
                "name": p.name,
                "type": "dir" if p.is_dir() else "file",
                "path": str(p),
                "size": p.stat().st_size if p.is_file() else None,
                "mtime": p.stat().st_mtime,
            }
        )
    return {"files": entries}


@app.get("/api/download")
async def download(thread_id: str, path: str):
    """下载文件：越界校验后返回文件流（TDD §8.1）。"""
    target = path_utils.validate_path(path, _session_dir(thread_id))
    if target is None:
        return JSONResponse({"error": "拒绝访问"}, status_code=403)
    if not target.exists() or not target.is_file():
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(target, filename=target.name)


@app.websocket("/ws/{thread_id}")
async def websocket_endpoint(ws: WebSocket, thread_id: str) -> None:
    """WebSocket 端点：心跳（pong）+ 事件推送（TDD §8.2）。"""
    try:
        path_utils.validate_thread_id(thread_id)
    except ValueError:
        await ws.close(code=1008)
        return
    await manager.connect(thread_id, ws)
    try:
        while True:
            data = await ws.receive_text()
            await ws.send_text(
                json.dumps(
                    {"type": "pong", "message": f"服务端已收到: {data}"},
                    ensure_ascii=True,
                )
            )
    except WebSocketDisconnect:
        manager.disconnect(thread_id, ws)


def start_server() -> None:
    """启动服务（默认监听 0.0.0.0:8000，TDD §16.2）。"""
    import uvicorn

    from utils.logger_utils import get_logger

    get_logger("data_analysis_assistant").info("正在启动数据分析助手服务：http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
