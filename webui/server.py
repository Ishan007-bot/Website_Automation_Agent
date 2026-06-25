"""FastAPI Web-UI server.

Endpoints:
  GET  /            -> the single-page UI (static/index.html)
  POST /run         -> start an agent run (task + options); streams nothing, just kicks off
  GET  /stream      -> Server-Sent Events: live StepEvents from the active run
  POST /stop        -> cancel the active run

Design: one active run at a time (perfect for a demo). The agent's EventSink pushes
StepEvents into an asyncio.Queue; the /stream endpoint drains the queue to the browser.
Run it with:  uvicorn webui.server:app --reload
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from agent.agent import Agent
from browser.session import BrowserSession
from config import settings
from logging_conf import StepEvent, configure_logging

configure_logging()
logger = logging.getLogger("agent")

app = FastAPI(title="Website Automation Agent")
_STATIC = os.path.join(os.path.dirname(__file__), "static")


class RunManager:
    """Holds the single active run, its event queue, and its asyncio task."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[StepEvent] | None = None
        self.task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def start(self, task: str, url: str | None, headless: bool, max_steps: int) -> None:
        if self.running:
            raise RuntimeError("A run is already in progress.")
        self.queue = asyncio.Queue()

        def sink(event: StepEvent) -> None:
            # Called from the agent loop (same event loop) — safe, non-blocking.
            if self.queue is not None:
                self.queue.put_nowait(event)

        session = BrowserSession(headless=headless)
        agent = Agent(task=task, start_url=url, sink=sink, max_steps=max_steps, session=session)

        async def runner() -> None:
            try:
                await agent.run()
            except asyncio.CancelledError:
                self._safe_put(StepEvent(type="result", message="Run cancelled by user.", success=False))
                await session.close()
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("Run failed")
                self._safe_put(StepEvent(type="error", message=f"Run failed: {exc}"))
            finally:
                # Sentinel so the SSE stream knows to close.
                self._safe_put(StepEvent(type="__end__"))

        self.task = asyncio.create_task(runner())

    def _safe_put(self, event: StepEvent) -> None:
        if self.queue is not None:
            self.queue.put_nowait(event)

    async def stop(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()


manager = RunManager()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(os.path.join(_STATIC, "index.html"))


@app.post("/run")
async def run(request: Request) -> JSONResponse:
    body = await request.json()
    task = (body.get("task") or "").strip()
    if not task:
        return JSONResponse({"ok": False, "error": "Task is required."}, status_code=400)
    if not settings.gemini_api_key:
        return JSONResponse({"ok": False, "error": "GEMINI_API_KEY not configured on server."}, status_code=400)
    if manager.running:
        return JSONResponse({"ok": False, "error": "A run is already in progress."}, status_code=409)

    url = (body.get("url") or "").strip() or None
    headless = bool(body.get("headless", settings.headless))
    max_steps = int(body.get("max_steps") or settings.max_steps)
    try:
        await manager.start(task, url, headless, max_steps)
    except RuntimeError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    return JSONResponse({"ok": True})


@app.post("/stop")
async def stop() -> JSONResponse:
    await manager.stop()
    return JSONResponse({"ok": True})


@app.get("/stream")
async def stream() -> StreamingResponse:
    async def event_generator():
        if manager.queue is None:
            yield _sse({"type": "error", "message": "No active run. Click Run first."})
            return
        while True:
            event = await manager.queue.get()
            if event.type == "__end__":
                yield _sse({"type": "end"})
                break
            yield _sse(event.to_dict())

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"
