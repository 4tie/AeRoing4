"""Router: GET /api/logs/stream   (Server-Sent Events)
           GET /api/logs/history  (recent buffered lines)

Streams real-time log output from all running subprocesses — backtest,
data download, optimizer, and stress-lab — to any connected SSE client.

SSE wire format
---------------
    retry: 3000\n\n                             (sent once on connect)
    data: {"message": "...", "ts": "..."}\n\n  (per log line)
    : keepalive\n\n                             (every 15 s when idle)

Connect with ``EventSource`` in a browser or any SSE-capable HTTP client.
Set ``Accept: text/event-stream`` if your client requires it explicitly.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..dependencies import get_log_broadcaster
from ..log_broadcaster import LogBroadcaster

router = APIRouter(prefix="/api/logs", tags=["Logs"])


class LogHistoryResponse(BaseModel):
    lines: list[str]
    count: int


@router.get(
    "/history",
    response_model=LogHistoryResponse,
    summary="Recent buffered log lines",
    description=(
        "Returns up to ``limit`` of the most recent log lines captured since "
        "the server started.  Useful for populating a log console on initial load "
        "before opening the live SSE stream."
    ),
)
async def get_log_history(
    limit: int = 200,
    broadcaster: LogBroadcaster = Depends(get_log_broadcaster),
) -> LogHistoryResponse:
    lines = broadcaster.history[-max(1, limit):]
    return LogHistoryResponse(lines=lines, count=len(lines))


@router.get(
    "/stream",
    summary="Stream live log output (SSE)",
    description=(
        "Server-Sent Events endpoint.  On connect, buffered history is replayed "
        "and then new lines are pushed as they arrive from any active runner. "
        "A keepalive comment is sent every 15 s when the stream is idle so proxies "
        "do not close the connection."
    ),
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_logs(
    request: Request,
    broadcaster: LogBroadcaster = Depends(get_log_broadcaster),
) -> StreamingResponse:
    async def event_generator() -> AsyncGenerator[str, None]:
        q = broadcaster.subscribe(replay_history=True)
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    line: str | None = await asyncio.wait_for(
                        q.get(), timeout=15.0
                    )
                    if line is None:
                        break
                    payload = json.dumps(
                        {
                            "message": line,
                            "ts": datetime.now(tz=UTC).isoformat(),
                        },
                        ensure_ascii=False,
                    )
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            broadcaster.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
