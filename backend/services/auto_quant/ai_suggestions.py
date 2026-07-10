"""Advisor-only AutoQuant AI suggestion helpers.

This module owns the safe boundary between AI/fallback recommendations and
pipeline mutation. Suggestions are persisted as reviewable records; approved
changes are applied only to pipeline state for the existing retry/patch flow.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .pipeline_modules.config import STAGE_NAMES

ALLOWED_CHANGE_KEYS = {"hyperopt_loss", "hyperopt_spaces", "hyperopt_epochs", "param_overrides"}
VALID_HYPEROPT_LOSSES = {
    "ProfitLockinHyperOptLoss",
    "SharpeHyperOptLoss",
    "ProfitDrawDownHyperOptLoss",
    "CalmarHyperOptLoss",
    "OnlyProfitHyperOptLoss",
}
VALID_HYPEROPT_SPACES = {"buy", "sell", "roi", "stoploss", "trailing", "protection"}
VALID_PARAM_OVERRIDE_KEYS = {
    "use_ema_cross",
    "use_atr",
    "use_rsi",
    "use_macd",
    "use_bb",
    "use_adx",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_ai_suggestions(value: Any) -> list[dict[str, Any]]:
    """Return a backward-compatible list of suggestion dictionaries."""
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        if not value:
            return []
        if "id" in value or "proposed_changes" in value:
            return [value]
        normalized: list[dict[str, Any]] = []
        for key, item in value.items():
            if isinstance(item, dict):
                normalized.append({"id": str(item.get("id") or key), **item})
        return normalized
    return []


def resolve_stage_index(name: str, *, default: int | None = None) -> int:
    """Resolve a stage index by configured stage name instead of hardcoding."""
    lowered = name.casefold()
    # Handle legacy "WFA Hyperopt" reference by mapping to "Standard Hyperopt"
    if lowered == "wfa hyperopt":
        lowered = "standard hyperopt"
    for index, stage_name in enumerate(STAGE_NAMES, start=1):
        if stage_name.casefold() == lowered:
            return index
    for index, stage_name in enumerate(STAGE_NAMES, start=1):
        if lowered in stage_name.casefold() or stage_name.casefold() in lowered:
            return index
    if default is not None:
        return default
    raise ValueError(f"Unknown AutoQuant stage: {name} (available stages: {STAGE_NAMES})")


def optimization_stage_index() -> int:
    return resolve_stage_index("Standard Hyperopt")


def _current_config(state: Any) -> dict[str, Any]:
    return {
        "hyperopt_loss": state.hyperopt_loss,
        "hyperopt_spaces": list(state.hyperopt_spaces or []),
        "hyperopt_epochs": state.hyperopt_epochs,
        "param_overrides": deepcopy(getattr(state, "param_overrides", {}) or {}),
    }


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False
    raise ValueError("param_overrides values must be booleans")


def validate_proposed_changes(changes: Any) -> dict[str, Any]:
    if not isinstance(changes, dict):
        raise ValueError("proposed_changes must be an object")
    unsupported = sorted(set(changes) - ALLOWED_CHANGE_KEYS)
    if unsupported:
        raise ValueError(f"Unsupported proposed change keys: {', '.join(unsupported)}")

    validated: dict[str, Any] = {}
    if "hyperopt_loss" in changes:
        loss = str(changes["hyperopt_loss"])
        if loss not in VALID_HYPEROPT_LOSSES:
            raise ValueError(f"Unsupported hyperopt_loss: {loss}")
        validated["hyperopt_loss"] = loss

    if "hyperopt_spaces" in changes:
        raw_spaces = changes["hyperopt_spaces"]
        if not isinstance(raw_spaces, list):
            raise ValueError("hyperopt_spaces must be a list")
        spaces = [str(space) for space in raw_spaces]
        invalid = sorted(set(spaces) - VALID_HYPEROPT_SPACES)
        if invalid:
            raise ValueError(f"Unsupported hyperopt_spaces: {', '.join(invalid)}")
        if not spaces:
            raise ValueError("hyperopt_spaces cannot be empty")
        validated["hyperopt_spaces"] = spaces

    if "hyperopt_epochs" in changes:
        try:
            epochs = int(changes["hyperopt_epochs"])
        except (TypeError, ValueError) as exc:
            raise ValueError("hyperopt_epochs must be an integer") from exc
        validated["hyperopt_epochs"] = max(50, min(epochs, 500))

    if "param_overrides" in changes:
        raw_overrides = changes["param_overrides"]
        if not isinstance(raw_overrides, dict):
            raise ValueError("param_overrides must be an object")
        invalid = sorted(set(raw_overrides) - VALID_PARAM_OVERRIDE_KEYS)
        if invalid:
            raise ValueError(f"Unsupported param_overrides: {', '.join(invalid)}")
        validated["param_overrides"] = {
            str(key): _coerce_bool(value)
            for key, value in raw_overrides.items()
        }

    return validated


def deterministic_changes(trigger: str, state: Any) -> dict[str, Any]:
    current_epochs = int(getattr(state, "hyperopt_epochs", 100) or 100)
    if trigger == "negative_baseline":
        return {
            "hyperopt_loss": "OnlyProfitHyperOptLoss",
            "hyperopt_spaces": ["buy", "stoploss", "roi"],
            "hyperopt_epochs": min(500, max(50, current_epochs * 2)),
            "param_overrides": {
                "use_ema_cross": True,
                "use_atr": True,
                "use_adx": True,
            },
        }
    if trigger == "wfo_pass_rate":
        return {
            "hyperopt_loss": "SharpeHyperOptLoss",
            "hyperopt_spaces": ["buy", "stoploss", "roi"],
            "hyperopt_epochs": min(500, max(50, current_epochs + 50)),
            "param_overrides": {
                "use_ema_cross": True,
                "use_atr": True,
                "use_adx": True,
            },
        }
    return {
        "hyperopt_loss": "OnlyProfitHyperOptLoss",
        "hyperopt_spaces": ["roi", "stoploss"],
        "hyperopt_epochs": min(500, max(50, current_epochs)),
        "param_overrides": {},
    }


def create_pending_suggestion(
    *,
    state: Any,
    trigger: str,
    failure_reason: str,
    retry_attempt: int,
    source: str,
    proposed_changes: dict[str, Any] | None = None,
    summary: str | None = None,
    explanation: str | None = None,
    risk_notes: list[str] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if proposed_changes is None:
        proposed_changes = deterministic_changes(trigger, state)
        source = source or "deterministic"
    try:
        validated_changes = validate_proposed_changes(proposed_changes)
    except ValueError:
        proposed_changes = deterministic_changes(trigger, state)
        source = "deterministic"
        validated_changes = validate_proposed_changes(proposed_changes)
    suggestion = {
        "id": f"aqai_{uuid4().hex[:12]}",
        "run_id": state.run_id,
        "created_at": utc_now(),
        "trigger": trigger,
        "summary": summary or _default_summary(trigger),
        "explanation": explanation or _default_explanation(trigger, failure_reason),
        "risk_notes": risk_notes or _default_risk_notes(trigger),
        "failure_reason": failure_reason,
        "retry_attempt": retry_attempt,
        "source": source or "deterministic",
        "status": "pending",
        "original_config": _current_config(state),
        "proposed_changes": validated_changes,
        "evidence": evidence or {},
        "decision": None,
    }
    state.ai_suggestions = normalize_ai_suggestions(getattr(state, "ai_suggestions", []))
    state.ai_suggestions.append(suggestion)
    state.pending_ai_suggestion_id = suggestion["id"]
    return suggestion


def get_suggestion(state: Any, suggestion_id: str) -> dict[str, Any] | None:
    for suggestion in normalize_ai_suggestions(getattr(state, "ai_suggestions", [])):
        if suggestion.get("id") == suggestion_id:
            return suggestion
    return None


def approve_suggestion(state: Any, suggestion_id: str) -> dict[str, Any]:
    suggestion = get_suggestion(state, suggestion_id)
    if suggestion is None:
        raise KeyError(suggestion_id)
    if suggestion.get("status") != "pending" or state.pending_ai_suggestion_id != suggestion_id:
        raise RuntimeError("Suggestion is not pending")

    changes = validate_proposed_changes(suggestion.get("proposed_changes"))
    if "hyperopt_loss" in changes:
        state.hyperopt_loss = changes["hyperopt_loss"]
    if "hyperopt_spaces" in changes:
        state.hyperopt_spaces = list(changes["hyperopt_spaces"])
    if "hyperopt_epochs" in changes:
        state.hyperopt_epochs = changes["hyperopt_epochs"]
    if "param_overrides" in changes:
        current = deepcopy(getattr(state, "param_overrides", {}) or {})
        current.update(changes["param_overrides"])
        state.param_overrides = current

    decision = {
        "decision": "approved",
        "decided_at": utc_now(),
        "applied_changes": deepcopy(changes),
    }
    suggestion["status"] = "approved"
    suggestion["decision"] = decision
    state.pending_ai_suggestion_id = None
    state.current_stage = optimization_stage_index()
    state.status = "running"
    _reset_retry_stages(state)
    state.retry_count += 1
    state.retry_history.append({
        "attempt": state.retry_count,
        "label": f"AI approved retry {state.retry_count}",
        "loss": state.hyperopt_loss,
        "spaces": list(state.hyperopt_spaces or []),
        "epochs": state.hyperopt_epochs,
        "reason": suggestion.get("failure_reason") or suggestion.get("trigger"),
        "passed": False,
        "ai_suggestion_id": suggestion_id,
        "approved": True,
    })
    return suggestion


def reject_suggestion(state: Any, suggestion_id: str) -> dict[str, Any]:
    suggestion = get_suggestion(state, suggestion_id)
    if suggestion is None:
        raise KeyError(suggestion_id)
    if suggestion.get("status") != "pending" or state.pending_ai_suggestion_id != suggestion_id:
        raise RuntimeError("Suggestion is not pending")
    suggestion["status"] = "rejected"
    suggestion["decision"] = {
        "decision": "rejected",
        "decided_at": utc_now(),
        "manual_next_actions": manual_next_actions(state),
    }
    state.pending_ai_suggestion_id = None
    state.status = "awaiting_user_approval"
    return suggestion


def manual_next_actions(state: Any) -> list[dict[str, str]]:
    return [
        {
            "id": "inspect_logs",
            "label": "Inspect logs and failure details",
            "description": "Review the stage logs, retry history, and failure evidence before choosing another path.",
        },
        {
            "id": "cancel_run",
            "label": "Cancel this run",
            "description": "Stop the paused run without applying AI changes.",
        },
        {
            "id": "new_run",
            "label": "Start a new run with manual settings",
            "description": "Use the AutoQuant form to choose different hyperopt settings, timeframe, pairs, or WFO options.",
        },
    ]


def ai_assistance_summary(state: Any) -> dict[str, Any]:
    suggestions = normalize_ai_suggestions(getattr(state, "ai_suggestions", []))
    return {
        "pending_ai_suggestion_id": getattr(state, "pending_ai_suggestion_id", None),
        "suggestions": suggestions,
        "manual_next_actions": manual_next_actions(state)
        if state.status == "awaiting_user_approval" and not getattr(state, "pending_ai_suggestion_id", None)
        else [],
    }


def _reset_retry_stages(state: Any) -> None:
    start = optimization_stage_index()
    for stage in state.stages:
        if stage.index >= start:
            stage.status = "pending"
            stage.message = ""
            stage.data = {}


def _default_summary(trigger: str) -> str:
    if trigger == "negative_baseline":
        return "Negative baseline detected; review a stricter retry configuration."
    if trigger == "wfo_pass_rate":
        return "WFO pass rate is below threshold; review a more robust retry configuration."
    return "Sharp optimization peak detected; review a safer retry configuration."


def _default_explanation(trigger: str, failure_reason: str) -> str:
    if trigger == "negative_baseline":
        return "The current search produced losing baseline behavior. The suggestion widens the search and enables core filters for the next retry only."
    if trigger == "wfo_pass_rate":
        return "The strategy did not generalize across enough walk-forward windows. The suggestion targets a more robust loss and broader validated search."
    return f"The sensitivity check failed ({failure_reason or 'sharp_peak'}). The suggestion changes retry settings without editing the original strategy."


def _default_risk_notes(trigger: str) -> list[str]:
    notes = [
        "Approval runs another validation pass; it does not approve a strategy for trading.",
        "Parameter overrides apply only through the existing retry/patch flow.",
    ]
    if trigger == "negative_baseline":
        notes.append("This is a larger retry change because the baseline was unprofitable.")
    return notes
