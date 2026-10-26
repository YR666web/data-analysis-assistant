import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from api import server, task_store
from utils import path_utils


class TaskHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [patch.object(path_utils, "OUTPUT_DIR", root / "output"),
                        patch.object(path_utils, "UPLOAD_DIR", root / "upload"),
                        patch.object(server, "_task_statuses", {}), patch.object(server, "_running_tasks", {})]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    async def test_completed_result_and_events_survive_memory_reset(self):
        with patch.object(server, "run_deep_agent", new_callable=AsyncMock, return_value="销售额：210"):
            await server.submit_task(server.TaskRequest(query="销售周报", thread_id="history_complete"))
            await server._running_tasks["history_complete"]
        server._task_statuses.clear()
        server.manager.clear_streams("history_complete")
        restored = await server.task_status("history_complete")
        self.assertEqual(restored["result"], "销售额：210")
        self.assertEqual(restored["query"], "销售周报")
        self.assertEqual(restored["status"], "completed")
        self.assertTrue(any(e["event"] == "task_result" for e in restored["events"]))

    async def test_abandoned_running_task_becomes_failed_without_replay(self):
        task_store.save("history_interrupted", {"thread_id": "history_interrupted", "status": "running", "query": "任务",
            "streams": [{"id": "x", "text": "部分输出", "status": "streaming", "seq": 1}]})
        restored = await server.task_status("history_interrupted")
        self.assertEqual(restored["status"], "failed")
        self.assertIn("中断", restored["error"])
        self.assertEqual(restored["streams"][0]["status"], "interrupted")
        self.assertFalse(server._running_tasks)
        self.assertEqual((await server.list_sessions())["sessions"][0]["status"], "failed")

    async def test_cancel_and_delete_persist(self):
        async def wait_forever(*args, **kwargs):
            await asyncio.Event().wait()
        with patch.object(server, "run_deep_agent", side_effect=wait_forever):
            await server.submit_task(server.TaskRequest(query="长任务", thread_id="history_cancel"))
            running = server._running_tasks["history_cancel"]
            await asyncio.sleep(0)
            await server.cancel_task("history_cancel")
            with self.assertRaises(asyncio.CancelledError):
                await running
        server._task_statuses.clear()
        self.assertEqual((await server.task_status("history_cancel"))["status"], "cancelled")
        await server.delete_session("history_cancel")
        self.assertIsNone(task_store.get("history_cancel"))
        self.assertEqual((await server.list_sessions())["sessions"], [])

    async def test_cancel_before_task_starts_does_not_leave_running_entry(self):
        with patch.object(server, "run_deep_agent", new_callable=AsyncMock) as run:
            await server.submit_task(server.TaskRequest(query="任务", thread_id="history_early_cancel"))
            running = server._running_tasks["history_early_cancel"]
            await server.cancel_task("history_early_cancel")
            with self.assertRaises(asyncio.CancelledError):
                await running
            await asyncio.sleep(0)
            self.assertNotIn("history_early_cancel", server._running_tasks)
            self.assertEqual(task_store.get("history_early_cancel")["status"], "cancelled")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
