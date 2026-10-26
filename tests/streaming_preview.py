"""Local-only streaming smoke server. No real model or business database access.

Run from project root: .venv/Scripts/python.exe tests/streaming_preview.py
Open http://127.0.0.1:8012/index.html after building frontend. Stop this process afterwards.
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_openai import ChatOpenAI
import uvicorn

from api import server
from api.monitor import MonitorCallbackHandler
from utils import path_utils


async def local_run(query, thread_id, *, require_pdf=False):
    callback = MonitorCallbackHandler(thread_id)
    llm = ChatOpenAI(model="local-stream-test", api_key="local-test-only",
                     base_url="http://127.0.0.1:8012/v1", streaming=True)
    try:
        response = await llm.ainvoke(query, config={"callbacks": [callback]})
        return response.content
    finally:
        await callback.close()


@server.app.post("/v1/chat/completions")
async def local_model():
    async def chunks():
        lines = ["本地流式验证：这是一段测试输出，用来检查无需刷新时的增量显示。\n"]
        lines += [f"第 {i} 段：内容正在持续追加。向上滚动查看前文时，应保留你的阅读位置。\n" for i in range(1, 31)]
        for line in lines:
            for start in range(0, len(line), 6):
                chunk = {"id": "local-test", "object": "chat.completion.chunk", "model": "local-stream-test",
                         "choices": [{"index": 0, "delta": {"content": line[start:start + 6]}, "finish_reason": None}]}
                yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
                await asyncio.sleep(0.045)
        yield 'data: {"id":"local-test","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
        yield "data: [DONE]\n\n"
    return StreamingResponse(chunks(), media_type="text/event-stream")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="data-analysis-stream-test-") as tmp:
        path_utils.OUTPUT_DIR = Path(tmp) / "output"
        path_utils.UPLOAD_DIR = Path(tmp) / "upload"
        server.run_deep_agent = local_run
        server.app.mount("/", StaticFiles(directory=ROOT / "frontend/dist", html=True), name="preview")
        # The normal API root is a health check; serve the UI at /index.html.
        uvicorn.run(server.app, host="127.0.0.1", port=8012)
