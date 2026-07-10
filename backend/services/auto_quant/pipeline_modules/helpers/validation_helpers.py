"""Stage lifecycle and WebSocket emission helpers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from ..logging import _rlog, get_queues, logger
from ..state import PipelineState, _now, record_event


def _start_stage(run_id: str, state: PipelineState, stage_idx: int) -> None:
    state.current_stage = stage_idx
    total_stages = len(state.stages)
    state.progress_percent = int((stage_idx - 1) / total_stages * 100) if total_stages else 0
    s = state.stages[stage_idx - 1]
    s.status = "running"
    s.started_at = _now()
    s.duration_s = None
    logger.info("[%s] ▶ STAGE %d/%d STARTED: %s", run_id, stage_idx, total_stages, s.name)
    _emit(run_id, stage_idx, "running", "", -1, started_at=s.started_at)


def _pass_stage(
    run_id: str, state: PipelineState, stage_idx: int,
    message: str, data: dict | None = None,
) -> None:
    s = state.stages[stage_idx - 1]
    s.status = "passed"
    s.message = message
    s.data = data or {}
    if s.started_at:
        try:
            started = datetime.fromisoformat(s.started_at)
            s.duration_s = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
        except Exception:
            s.duration_s = None
    total_stages = len(state.stages)
    progress = int(stage_idx / total_stages * 100)
    state.progress_percent = progress
    logger.info("[%s] ✔ STAGE %d/%d PASSED: %s  progress=%d%%",
                run_id, stage_idx, total_stages, s.name, progress)
    from ..state import _save_state_to_disk
    _save_state_to_disk(state)
    _emit(run_id, stage_idx, "passed", message, progress, data, duration_s=s.duration_s)


def _fail_stage(
    run_id: str, state: PipelineState, stage_idx: int,
    message: str, data: dict | None = None,
) -> None:
    s = state.stages[stage_idx - 1]
    s.status = "failed"
    s.message = message
    s.data = data or {}
    if s.started_at:
        try:
            started = datetime.fromisoformat(s.started_at)
            s.duration_s = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
        except Exception:
            s.duration_s = None
    state.status = "failed"
    state.error = message
    state.completed_at = _now()
    total_stages = len(state.stages)
    state.progress_percent = int((stage_idx - 1) / total_stages * 100) if total_stages else 0
    logger.error("[%s] ✘ STAGE %d/%d FAILED: %s | error=%r",
                 run_id, stage_idx, total_stages, s.name, message)
    from ..state import _save_state_to_disk
    _save_state_to_disk(state)
    _emit(run_id, stage_idx, "failed", message, -1, data, duration_s=s.duration_s)
    # NOTE: the sentinel (None) that closes WebSocket connections is sent by
    # run_pipeline's finally block — do NOT duplicate it here.


def _emit(
    run_id: str,
    stage: int,
    status: str,
    message: str,
    progress: int,
    data: dict | None = None,
    msg_type: str | None = None,
    started_at: str | None = None,
    duration_s: float | None = None,
    extra: dict | None = None,
) -> None:
    payload: dict[str, Any] = {
        "stage": stage,
        "status": status,
        "message": message,
        "progress": progress,
        "data": data or {},
        "ts": _now(),
    }
    if msg_type is not None:
        payload["type"] = msg_type
    if started_at is not None:
        payload["started_at"] = started_at
    if duration_s is not None:
        payload["duration_s"] = duration_s
    if extra:
        payload.update(extra)
    record_event(run_id, {"run_id": run_id, **payload})
    for q in list(get_queues().get(run_id, [])):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass
        except Exception:
            pass
