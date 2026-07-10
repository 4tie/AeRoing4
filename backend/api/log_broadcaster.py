"""Global log broadcaster for Server-Sent Events streaming.

All subprocess runners that accept a log_callback route their output
through this broadcaster so every SSE subscriber receives the same stream.

Usage
-----
    broadcaster = LogBroadcaster()
    some_runner.set_log_callback(broadcaster.write)

    # In an async SSE handler:
    q = broadcaster.subscribe()
    try:
        line = await asyncio.wait_for(q.get(), timeout=15.0)
    finally:
        broadcaster.unsubscribe(q)
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any


class LogBroadcaster:
    """Fan-out sink that routes log lines to all connected SSE subscribers.

    - ``write()`` is safe to call from synchronous callbacks or background threads.
    - Each subscriber gets its own ``asyncio.Queue`` so a slow reader never
      blocks other subscribers.
    - The last ``maxlen`` lines are kept in a circular history buffer so new
      subscribers can receive a replay on connect.
    """

    def __init__(self, maxlen: int = 500) -> None:
        self._subscribers: list[asyncio.Queue[str | None]] = []
        self._history: deque[str] = deque(maxlen=maxlen)

    def write(self, line: str) -> None:
        """Accept a log line and fan it out to every subscriber queue.

        Safe to call from synchronous runner callbacks.
        """
        line = line.rstrip("\n")
        if not line:
            return
        self._history.append(line)
        for q in list(self._subscribers):
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                pass

    def subscribe(self, replay_history: bool = True) -> asyncio.Queue[str | None]:
        """Register a new subscriber and return its dedicated queue.

        Args:
            replay_history: When ``True`` (default), recent buffered lines are
                pushed into the queue immediately so the client does not miss
                output that arrived before it connected.
        """
        q: asyncio.Queue[str | None] = asyncio.Queue(maxsize=1000)
        if replay_history:
            for buffered_line in self._history:
                try:
                    q.put_nowait(buffered_line)
                except asyncio.QueueFull:
                    break
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str | None]) -> None:
        """Deregister a subscriber queue (call in a ``finally`` block)."""
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    @property
    def history(self) -> list[str]:
        """Snapshot of the current circular history buffer."""
        return list(self._history)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


def wire_service_callbacks(services: Any, broadcaster: LogBroadcaster) -> None:
    """Attach ``broadcaster.write`` to every runner that supports a log callback.

    Call this once after ``create_services()`` and again after any
    ``services.reload()`` call, because reload() creates new runner instances.
    """
    services.backtest_runner.set_log_callback(broadcaster.write)
    services.data_download_runner.set_log_callback(broadcaster.write)
    services.strategy_optimizer.set_log_callback(broadcaster.write)
