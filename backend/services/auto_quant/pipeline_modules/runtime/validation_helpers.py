"""Validation workflow helpers for validate-existing mode."""

from __future__ import annotations

from typing import Any

from ..state import PipelineState, _now


def is_validate_existing(state: PipelineState) -> bool:
    return getattr(state, "workflow_mode", "auto_quant") == "validate_existing"


def ensure_validation_attempt(
    state: PipelineState,
    *,
    reason: str = "initial",
    trigger: str | None = None,
) -> dict[str, Any] | None:
    """Ensure one user-facing validation attempt exists for the current retry.

    Internal stage retries (data healing, baseline mutations, WFO windows, or
    hyperopt subprocess retries) do not call this. For validate-existing runs,
    attempt N is the initial full validation pass plus each approved AI retry.
    """
    if not is_validate_existing(state):
        return None
    attempt_number = min(
        max(1, int(getattr(state, "retry_count", 0) or 0) + 1),
        max(1, int(getattr(state, "max_attempts", 3) or 3)),
    )
    attempts = list(getattr(state, "validation_attempts", []) or [])
    existing = next((item for item in attempts if item.get("attempt") == attempt_number), None)
    if existing is None:
        existing = {
            "attempt": attempt_number,
            "kind": "full_validation",
            "status": "running",
            "reason": reason,
            "trigger": trigger or reason,
            "retry_count_at_start": int(getattr(state, "retry_count", 0) or 0),
            "started_at": _now(),
            "notes": [],
        }
        attempts.append(existing)
        state.validation_attempts = attempts
    elif existing.get("status") in {"pending", "awaiting_retry"}:
        existing["status"] = "running"
        existing.setdefault("started_at", _now())
    return existing


def update_validation_attempt(
    state: PipelineState,
    *,
    status: str,
    stage_idx: int | None = None,
    reason: str | None = None,
    metrics: dict[str, Any] | None = None,
    ai_suggestion_id: str | None = None,
) -> None:
    if not is_validate_existing(state):
        return
    attempt = ensure_validation_attempt(state)
    if attempt is None:
        return
    attempt["status"] = status
    if stage_idx is not None:
        attempt["stage"] = stage_idx
        if 0 < stage_idx <= len(state.stages):
            attempt["stage_name"] = state.stages[stage_idx - 1].name
    if reason:
        attempt["reason"] = reason
    if metrics:
        attempt["metrics"] = metrics
        from .metrics_helpers import _record_best_observed
        _record_best_observed(state, metrics, attempt.get("attempt"))
    if ai_suggestion_id:
        attempt["ai_suggestion_id"] = ai_suggestion_id
    if status in {"failed", "rejected", "passed"}:
        attempt["completed_at"] = _now()


def finalize_rejection_report(
    state: PipelineState,
    *,
    stage_idx: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the validate-existing rejection report used by state and report.json."""
    from .metrics_helpers import _metrics_from, _recommended_next_experiment

    raw = dict(data or {})
    failed_stages = [
        {
            "index": stage.index,
            "name": stage.name,
            "message": stage.message,
            "data": stage.data,
        }
        for stage in state.stages
        if stage.status == "failed"
    ]
    if not failed_stages and 0 < stage_idx <= len(state.stages):
        stage = state.stages[stage_idx - 1]
        failed_stages.append(
            {"index": stage.index, "name": stage.name, "message": message, "data": raw}
        )

    suggestions = list(getattr(state, "ai_suggestions", []) or [])
    approved = [item for item in suggestions if item.get("status") == "approved"]
    rejected = [item for item in suggestions if item.get("status") == "rejected"]

    update_validation_attempt(
        state,
        status="rejected",
        stage_idx=stage_idx,
        reason=message,
        metrics=_metrics_from(raw),
    )

    report = {
        "schema_version": "validate_existing_rejection_v1",
        "final_verdict": "rejected",
        "candidate_label": "Rejected",
        "reason": message,
        "failed_stages": failed_stages,
        "repairs_attempted": {
            "validation_attempts": getattr(state, "validation_attempts", []),
            "internal_baseline_heal_attempts": getattr(state, "phase1_heal_attempts", 0),
            "approved_retry_history": getattr(state, "retry_history", []),
            "strategy_variants": getattr(state, "strategy_variants", []),
        },
        "ai_suggestions": {
            "approved": approved,
            "rejected": rejected,
            "pending": [item for item in suggestions if item.get("status") == "pending"],
        },
        "best_observed_result": getattr(state, "best_observed_result", {}) or {},
        "recommended_next_experiment": _recommended_next_experiment(state, message, raw),
    }
    state.final_verdict = "rejected"
    state.candidate_label = "Rejected"
    state.validation_status = "Rejected"
    state.readiness_label = "Rejected"
    state.rejection_report = report
    state.report = {
        "run_id": state.run_id,
        "strategy": state.strategy,
        "original_strategy": state.original_strategy,
        "original_strategy_hash": state.original_strategy_hash,
        "workflow_mode": state.workflow_mode,
        "status": "rejected",
        "validation_status": state.validation_status,
        "readiness_label": state.readiness_label,
        "final_verdict": state.final_verdict,
        "candidate_label": state.candidate_label,
        "created_at": state.created_at,
        "completed_at": _now(),
        "stages": [
            {"index": s.index, "name": s.name, "status": s.status, "message": s.message, "data": s.data}
            for s in state.stages
        ],
        "rejection_report": report,
    }
    return report
