import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile

from api import server
from api.server import cancel_task, delete_session, download, list_files, root, upload
from utils import path_utils


class ApiSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root_dir = Path(self.temp.name)
        self.output_patch = patch.object(path_utils, "OUTPUT_DIR", root_dir / "output")
        self.upload_patch = patch.object(path_utils, "UPLOAD_DIR", root_dir / "upload")
        self.output_patch.start()
        self.upload_patch.start()

    def tearDown(self):
        self.upload_patch.stop()
        self.output_patch.stop()
        self.temp.cleanup()

    def test_server_imports_and_responds(self):
        self.assertEqual(root()["status"], "ok")

    def test_rejects_invalid_thread_id(self):
        with self.assertRaises(ValueError):
            path_utils.get_session_dir("../../other")

    def test_upload_is_available_to_same_session_only(self):
        file = UploadFile(filename="input.txt", file=io.BytesIO(b"hello"))
        result = asyncio.run(upload(thread_id="session_a", files=[file]))
        self.assertEqual(result["status"], "uploaded")
        own_file = path_utils.get_session_dir("session_a") / "input.txt"
        self.assertEqual(own_file.read_bytes(), b"hello")

        own = asyncio.run(download(thread_id="session_a", path=str(own_file)))
        self.assertEqual(Path(own.path), own_file)
        other = asyncio.run(download(thread_id="session_b", path=str(own_file)))
        self.assertEqual(other.status_code, 403)

        listing = asyncio.run(list_files(thread_id="session_a", path=str(own_file.parent)))
        self.assertEqual(listing["files"][0]["name"], "input.txt")

    def test_rejects_upload_filename_with_path(self):
        file = UploadFile(filename="../escape.txt", file=io.BytesIO(b"bad"))
        with self.assertRaises(HTTPException) as error:
            asyncio.run(upload(thread_id="session_a", files=[file]))
        self.assertEqual(error.exception.status_code, 400)

    def test_delete_session_cleans_local_and_uploaded_files(self):
        session_dir = path_utils.get_session_dir("session_a")
        upload_dir = path_utils.get_upload_dir("session_a")
        session_dir.mkdir(parents=True)
        upload_dir.mkdir(parents=True)
        (session_dir / "report.md").write_text("report", encoding="utf-8")
        (upload_dir / "input.txt").write_text("input", encoding="utf-8")
        server._task_statuses["session_a"] = {"status": "completed", "result": "done"}

        result = asyncio.run(delete_session("session_a"))

        self.assertEqual(result["status"], "deleted")
        self.assertFalse(session_dir.exists())
        self.assertFalse(upload_dir.exists())
        self.assertNotIn("session_a", server._task_statuses)

    def test_delete_session_refuses_running_task(self):
        async def scenario():
            task = asyncio.create_task(asyncio.sleep(10))
            server._running_tasks["session_busy"] = task
            try:
                with self.assertRaises(HTTPException) as error:
                    await delete_session("session_busy")
                self.assertEqual(error.exception.status_code, 409)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                server._running_tasks.pop("session_busy", None)

        asyncio.run(scenario())

    def test_cancel_completed_task_is_idempotent(self):
        server._task_statuses["session_done"] = {"status": "completed", "result": "done"}
        result = asyncio.run(cancel_task("session_done"))
        self.assertEqual(result["status"], "completed")

    def test_status_recovers_result_and_directory_without_socket(self):
        server._task_statuses["session_recovery"] = {"status": "completed", "result": "report body"}
        try:
            result = asyncio.run(server.task_status("session_recovery"))
            self.assertEqual(result["result"], "report body")
            self.assertEqual(result["session_dir"], str(path_utils.get_session_dir("session_recovery")))
        finally:
            server._task_statuses.pop("session_recovery", None)


if __name__ == "__main__":
    unittest.main()
