"""Stage lifecycle helpers for runtime state management."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..logging import logger
from ..state import PipelineState, StageState, _now, record_event


def _start_stage(run_id: str, state: PipelineState, stage_idx: int) -> None:
    """Mark a stage as running and persist a structured stage envelope."""
    state.current_stage = stage_idx
    total_stages = len(state.stages)
    state.progress_percent = int((stage_idx - 1) / total_stages * 100) if total_stages else 0
    s = state.stages[stage_idx - 1]
    s.status = "running"
    s.message = ""
    s.started_at = _now()
    s.duration_s = None
    s.data = build_stage_payload(
        state,
        s,
        status="running",
        message="",
        raw_data={},
    )
    logger.info("[%s] ▶ STAGE %d/%d STARTED: %s", run_id, stage_idx, total_stages, s.name)
    from ..state import _save_state_to_disk

    _save_state_to_disk(state)
    _emit(run_id, stage_idx, "running", "", -1, s.data, started_at=s.started_at)


def _pass_stage(
    run_id: str,
    state: PipelineState,
    stage_idx: int,
    message: str,
    data: dict | None = None,
) -> None:
    """Mark a stage as passed while preserving raw result fields."""
    s = state.stages[stage_idx - 1]
    s.status = "passed"
    s.message = message
    if s.started_at:
        try:
            started = datetime.fromisoformat(s.started_at)
            s.duration_s = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
        except Exception:
            s.duration_s = None
    s.data = build_stage_payload(
        state,
        s,
        status="passed",
        message=message,
        raw_data=data or {},
    )
    total_stages = len(state.stages)
    progress = int(stage_idx / total_stages * 100) if total_stages else 100
    state.progress_percent = progress
    logger.info(
        "[%s] ✔ STAGE %d/%d PASSED: %s  progress=%d%%",
        run_id,
        stage_idx,
        total_stages,
        s.name,
        progress,
    )
    from ..state import _save_state_to_disk

    _save_state_to_disk(state)
    _emit(run_id, stage_idx, "passed", message, progress, s.data, duration_s=s.duration_s)


def _fail_stage(
    run_id: str,
    state: PipelineState,
    stage_idx: int,
    message: str,
    data: dict | None = None,
) -> None:
    """Mark a stage as failed and persist a structured stage envelope."""
    s = state.stages[stage_idx - 1]
    s.status = "failed"
    s.message = message
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
    logger.error(
        "[%s] ✘ STAGE %d/%d FAILED: %s | error=%r",
        run_id,
        stage_idx,
        total_stages,
        s.name,
        message,
    )
    from ..state import _save_state_to_disk

    _save_state_to_disk(state)
    _emit(run_id, stage_idx, "failed", message, -1, s.data, duration_s=s.duration_s)


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
) -> None:
    """Emit a WebSocket event for stage updates."""
    from ..logging import get_queues

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
    record_event(run_id, {"run_id": run_id, **payload})
    for q in list(get_queues().get(run_id, [])):
        try:
            q.put_nowait(payload)
        except Exception:
            pass


def build_stage_payload(
    state: PipelineState,
    stage: StageState,
    *,
    status: str,
    message: str,
    raw_data: dict[str, Any],
) -> dict[str, Any]:
    """Build a structured stage payload for UI consumption."""
    from .normalization_helpers import (
        _input_summary_for,
        _metrics_from,
        _output_summary_for,
        _stage_progress_for,
        _status_kind,
        _strip_ui_keys,
    )

    raw = _strip_ui_keys(raw_data)
    return {
        "schema_version": "stage_payload_v1",
        "stage": stage.name,
        "status": status,
        "status_kind": _status_kind(status, raw.get("errors", [])),
        "message": message,
        "progress": _stage_progress_for(state, stage.index, status),
        "input": _input_summary_for(state, stage.index, raw),
        "output": _output_summary_for(stage.index, raw),
        "metrics": _metrics_from(raw),
        "errors": raw.get("errors", []),
        "warnings": raw.get("warnings", []),
        "retry_attempts": raw.get("retry_history", []),
        "auto_fix": raw.get("auto_fix", {}),
        "suggestions": raw.get("suggestions", []),
        "started_at": stage.started_at,
        "duration_s": stage.duration_s,
        "raw": raw,
    }
