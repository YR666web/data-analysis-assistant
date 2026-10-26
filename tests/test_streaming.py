import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api import monitor as monitor_module
from api.monitor import ConnectionManager, MonitorCallbackHandler, ToolMonitor


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = ConnectionManager()
        self.monitor_patch = patch.object(monitor_module, "monitor", ToolMonitor(self.manager))
        self.monitor_patch.start()
        self.callback = MonitorCallbackHandler("stream_test")

    async def asyncTearDown(self):
        await self.callback.close()
        self.monitor_patch.stop()

    async def test_first_chunk_is_immediate_and_tail_flushes_on_end(self):
        await self.callback.on_llm_new_token("第一段", run_id="a")
        self.assertEqual(self.manager.stream_snapshot("stream_test")[0]["text"], "第一段")
        await self.callback.on_llm_new_token("第二段", run_id="a")
        await self.callback.on_llm_new_token("结尾", run_id="a")
        await self.callback.on_llm_end(None, run_id="a")
        block = self.manager.stream_snapshot("stream_test")[0]
        self.assertEqual(block["text"], "第一段第二段结尾")
        self.assertEqual(block["status"], "completed")
        self.assertEqual(block["seq"], 3)  # first chunk, batched tail, end
        self.assertFalse(self.callback._flush_tasks)

    async def test_buffer_flushes_even_if_model_pauses(self):
        await self.callback.on_llm_new_token("第一段", run_id="a")
        await self.callback.on_llm_new_token("暂停前的片段", run_id="a")
        await asyncio.sleep(0.12)
        self.assertEqual(self.manager.stream_snapshot("stream_test")[0]["text"], "第一段暂停前的片段")

    async def test_parallel_models_do_not_mix_text(self):
        await asyncio.gather(
            self.callback.on_llm_new_token("模型甲", run_id="a"),
            self.callback.on_llm_new_token("模型乙", run_id="b"),
        )
        await self.callback.close()
        blocks = {b["id"]: b for b in self.manager.stream_snapshot("stream_test")}
        self.assertEqual(blocks["a"]["text"], "模型甲")
        self.assertEqual(blocks["b"]["text"], "模型乙")
        self.assertEqual(blocks["b"]["status"], "interrupted")

    async def test_does_not_publish_tool_json_or_reasoning_fields(self):
        chunk = SimpleNamespace(message=SimpleNamespace(content="", additional_kwargs={"reasoning_content": "private"}, tool_call_chunks=[{"args": "tool JSON"}]))
        await self.callback.on_llm_new_token("tool JSON", chunk=chunk, run_id="a")
        self.assertEqual(self.manager.stream_snapshot("stream_test"), [])

    async def test_snapshot_recovers_text_generated_without_any_connection(self):
        await self.callback.on_llm_new_token("断线期间内容", run_id="a")
        snapshot = self.manager.stream_snapshot("stream_test")
        snapshot[0]["text"] = "modified copy"
        self.assertEqual(self.manager.stream_snapshot("stream_test")[0]["text"], "断线期间内容")
        await self.manager.send_event("stream_test", "task_cancelled", "cancelled")
        self.assertEqual(self.manager.stream_snapshot("stream_test")[0]["status"], "interrupted")

    async def test_retained_output_is_bounded_and_reset_on_rerun(self):
        for i in range(22):
            await self.manager.send_event("stream_test", "model_delta", "", {"id": str(i), "delta": "x" * 33000})
        blocks = self.manager.stream_snapshot("stream_test")
        self.assertEqual(len(blocks), 20)
        self.assertEqual(len(blocks[-1]["text"]), 32000)
        self.assertTrue(blocks[-1]["truncated"])
        self.manager.clear_streams("stream_test")
        self.assertEqual(self.manager.stream_snapshot("stream_test"), [])


if __name__ == "__main__":
    unittest.main()
