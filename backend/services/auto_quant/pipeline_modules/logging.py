"""Logging setup for the Auto-Quant pipeline.

Provides structured logging that fans records to WebSocket queues.
"""

from __future__ import annotations

import asyncio
import logging

# ── In-memory queue registry (run_id -> list of Queue) ────────────────────────

_queues: dict[str, list[asyncio.Queue]] = {}


def get_queues() -> dict[str, list[asyncio.Queue]]:
    """Return the in-memory queue registry."""
    return _queues


# ── Structured logging ─────────────────────────────────────────────────────────
#
# Every stage transition, subprocess spawn, config read and file write emits a
# structured log record through the standard Python `logging` hierarchy so that:
#   (a) records appear on the server terminal via the root handler, AND
#   (b) records are fanned out to all active WebSocket queues for the run.
#
# Usage inside the pipeline:  _rlog(run_id, stage_idx, logging.INFO, "msg…")

logger = logging.getLogger("auto_quant.pipeline")
logger.setLevel(logging.DEBUG)

# Ensure at least a stderr handler exists so records appear in the terminal.
if not logger.handlers:
    _sh = logging.StreamHandler()
    _sh.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [AUTO-QUANT] %(levelname)-8s %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger.addHandler(_sh)


class _AsyncQueueHandler(logging.Handler):
    """Logging handler that fans each record to all active WS queues for a run.

    The handler reads ``run_id`` and ``pipeline_stage`` from the LogRecord
    ``extra`` dict.  Records without a ``run_id`` are silently ignored.
    """

    def emit(self, record: logging.LogRecord) -> None:
        run_id: str | None = getattr(record, "run_id", None)
        if run_id is None:
            return
        stage: int = getattr(record, "pipeline_stage", 0)
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        payload = {
            "stage": stage,
            "status": "log",
            "message": f"[{record.levelname}] {msg}",
            "progress": -1,
            "data": {},
        }
        for q in list(_queues.get(run_id, [])):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass
            except Exception:
                pass


_ws_handler = _AsyncQueueHandler()
_ws_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_ws_handler)


def _rlog(run_id: str, stage: int, level: int, msg: str,
          exc_info: bool = False) -> None:
    """Emit a structured log record tied to a specific run and stage.

    Also writes the record to the server terminal (via the root logger chain)
    and pushes it to all active WebSocket queues for *run_id*.
    """
    logger.log(
        level,
        msg,
        extra={"run_id": run_id, "pipeline_stage": stage},
        exc_info=exc_info,
        stacklevel=2,
    )
