"""API-facing normalization helpers for stage data."""

from __future__ import annotations

import re
from typing import Any

from ..state import PipelineState, StageState, _now


_STAGE_SCHEMA_VERSION = "stage_payload_v1"


_STAGE_INPUT_KEYS: dict[int, tuple[str, ...]] = {
    1: (
        "strategy",
        "strategy_source",
        "timeframe",
        "in_sample_range",
        "pair_universe_count",
        "trading_style",
        "risk_profile",
    ),
    2: ("strategy", "selected_pairs_count", "max_open_trades", "config_file"),
    3: (
        "strategy",
        "selected_pairs_count",
        "hyperopt_loss",
        "hyperopt_spaces",
        "hyperopt_epochs",
        "wfo_enabled",
    ),
    4: (
        "strategy",
        "optimized_strategy",
        "out_sample_range",
        "selected_pairs_count",
        "thresholds",
    ),
    5: ("optimized_strategy", "selected_pairs_count", "max_open_trades"),
    6: ("optimized_strategy", "artifact_versions"),
}


def build_stage_cards(state: PipelineState) -> list[dict[str, Any]]:
    """Return UI-ready cards for all pipeline stages."""
    return [build_stage_card(state, stage) for stage in state.stages]


def build_workflow_summary(state: PipelineState) -> dict[str, Any]:
    """Return a compact workflow summary for status responses."""
    total = max(1, len(state.stages))
    completed = sum(1 for s in state.stages if s.status == "passed")
    failed = sum(1 for s in state.stages if s.status == "failed")
    running = next((s for s in state.stages if s.status == "running"), None)
    return {
        "schema_version": "workflow_summary_v1",
        "status": state.status,
        "validation_status": state.validation_status,
        "readiness_label": state.readiness_label,
        "current_stage": state.current_stage,
        "total_stages": total,
        "completed_stages": completed,
        "failed_stages": failed,
        "running_stage": running.index if running else None,
        "progress_percent": state.progress_percent,
        "retry_count": state.retry_count,
        "max_retries": state.max_retries,
        "has_controlled_failure": bool(derive_error_object(state, prefer_controlled=True)),
    }


def derive_error_object(
    state: PipelineState,
    *,
    prefer_controlled: bool = False,
) -> dict[str, Any] | None:
    """Derive a top-level clean error object from the failed stage or state error."""
    failed_stage = next((s for s in state.stages if s.status == "failed"), None)
    if failed_stage is not None:
        data = failed_stage.data if isinstance(failed_stage.data, dict) else {}
        errors = data.get("errors") or []
        if errors and isinstance(errors, list) and isinstance(errors[0], dict):
            return errors[0]
        kind = "controlled_validation" if prefer_controlled else "stage_failure"
        return make_error_object(
            failed_stage.index,
            failed_stage.name,
            failed_stage.message or state.error or "Stage failed.",
            kind=kind,
            recoverable=True,
        )
    if state.status == "failed" and state.error:
        stage_idx = state.current_stage or 0
        stage_name = state.stages[stage_idx - 1].name if 0 < stage_idx <= len(state.stages) else "Pipeline"
        return make_error_object(
            stage_idx,
            stage_name,
            str(state.error),
            kind="system_error",
            recoverable=False,
            suggestions=[
                "Check backend logs for the traceback.",
                "Retry the run after fixing the system error.",
            ],
        )
    return None


def build_stage_card(state: PipelineState, stage: StageState) -> dict[str, Any]:
    """Normalize a StageState into a stable card shape for the frontend."""
    from .lifecycle_helpers import build_stage_payload

    raw_data = stage.data if isinstance(stage.data, dict) else {}
    status = stage.status
    message = stage.message
    synthetic_stage = StageState(
        index=stage.index,
        name=stage.name,
        status=status,
        message=message,
        data=raw_data,
        started_at=stage.started_at,
        duration_s=stage.duration_s,
    )
    payload = build_stage_payload(
        state,
        synthetic_stage,
        status=status,
        message=message,
        raw_data=raw_data,
    )
    return {
        "index": stage.index,
        "name": stage.name,
        "status": status,
        "message": message,
        "started_at": stage.started_at,
        "duration_s": stage.duration_s,
        "input_summary": payload.get("input", {}),
        "output_summary": payload.get("output", {}),
        "metrics": payload.get("metrics", []),
        "warnings": payload.get("warnings", []),
        "errors": payload.get("errors", []),
        "retry_attempts": payload.get("retry_attempts", []),
        "suggestions": payload.get("suggestions", []),
        "auto_fix": payload.get("auto_fix", {}),
        "stage_progress": payload.get("progress", None),
        "status_kind": payload.get("status_kind", "neutral"),
        "raw_data": _strip_ui_keys(raw_data),
    }


def make_error_object(
    stage_idx: int,
    stage_name: str,
    message: str,
    *,
    kind: str,
    code: str | None = None,
    severity: str = "error",
    recoverable: bool = True,
    suggestions: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a clean machine-readable error object."""
    return {
        "schema_version": "auto_quant_error_v1",
        "code": code or _slug_code(message),
        "kind": kind,
        "severity": severity,
        "controlled": kind != "system_error",
        "recoverable": recoverable,
        "message": message,
        "stage": {"index": stage_idx, "name": stage_name},
        "details": details or {},
        "suggestions": _dedupe(suggestions or _suggestions_for(stage_idx, message, {}, [], None)),
        "ts": _now(),
    }


def _input_summary_for(state: PipelineState, stage_idx: int, raw: dict[str, Any]) -> dict[str, Any]:
    pair_universe = state.selected_pair_universe or state.pair_universe or []
    selected_pairs = state.selected_pairs or []
    optimized_strategy = raw.get("optimized_strategy") or raw.get("optimized_strategy_name")
    optimized_file = raw.get("optimized_file") or raw.get("optimized_path")
    if not optimized_strategy and optimized_file:
        optimized_strategy = str(optimized_file).rsplit("/", 1)[-1].replace(".py", "")

    base: dict[str, Any] = {
        "strategy": state.strategy,
        "strategy_source": state.strategy_source,
        "timeframe": state.selected_timeframe or state.timeframe,
        "in_sample_range": state.in_sample_range,
        "out_sample_range": state.out_sample_range,
        "pair_universe_count": len(pair_universe),
        "selected_pairs_count": len(selected_pairs),
        "selected_pairs": [p.get("key", p) if isinstance(p, dict) else p for p in selected_pairs][:12],
        "trading_style": state.trading_style,
        "risk_profile": state.risk_profile,
        "analysis_depth": state.analysis_depth,
        "config_file": state.config_file,
        "hyperopt_loss": state.hyperopt_loss,
        "hyperopt_spaces": list(state.hyperopt_spaces),
        "hyperopt_epochs": state.hyperopt_epochs,
        "wfo_enabled": state.wfo_enabled,
        "max_open_trades": state.max_open_trades,
        "optimized_strategy": optimized_strategy,
        "artifact_versions": state.artifact_versions,
        "thresholds": {
            "max_drawdown": state.max_drawdown_threshold,
            "min_win_rate": state.min_win_rate,
            "min_profit_factor": state.min_profit_factor,
            "min_sharpe": state.min_sharpe,
            "min_oos_profit": state.min_oos_profit,
            "monte_carlo_threshold": state.monte_carlo_threshold,
        },
    }
    keys = _STAGE_INPUT_KEYS.get(stage_idx, tuple(base.keys()))
    return {key: base.get(key) for key in keys if key in base}


def _metrics_from(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract performance metrics from raw stage data."""
    metrics: dict[str, Any] = {}
    
    # Common backtest metrics
    for key in (
        "profit_total",
        "profit_percent",
        "profit_factor",
        "win_rate",
        "drawdown",
        "max_drawdown",
        "sharpe",
        "sortino",
        "calmar",
        "trade_count",
        "avg_profit",
        "avg_loss",
        "expectancy",
    ):
        if key in raw:
            metrics[key] = raw[key]
    
    # Hyperopt-specific metrics
    if "best_trial" in raw:
        metrics["best_trial"] = raw["best_trial"]
    if "total_trials" in raw:
        metrics["total_trials"] = raw["total_trials"]
    
    # Validation-specific metrics
    if raw.get("_failed_metrics"):
        metrics["failed_metrics"] = raw["_failed_metrics"]
    
    return metrics


def _output_summary_for(stage_idx: int, raw: dict[str, Any]) -> dict[str, Any]:
    if not raw:
        return {}
    per_pair = raw.get("per_pair") or raw.get("all_pairs") or []
    passing = raw.get("passing_pairs") or raw.get("winning_pairs") or []
    filtered = raw.get("filtered_pairs") or raw.get("failing_pairs") or []
    artifacts = {
        key: value
        for key, value in raw.items()
        if key.endswith("_file") or key.endswith("_path") or key in {"report", "export_zip"}
    }
    summary = {
        "pairs_tested": len(per_pair) if isinstance(per_pair, list) else None,
        "pairs_passed": len(passing) if isinstance(passing, list) else None,
        "pairs_filtered": len(filtered) if isinstance(filtered, list) else None,
        "baseline_attempts": raw.get("baseline_attempts"),
        "selected_pairs": raw.get("selected_pairs") or raw.get("passing_pairs") or raw.get("winning_pairs"),
        "artifacts": artifacts,
    }
    if raw.get("_failed_metrics"):
        summary["failed_metrics"] = raw["_failed_metrics"]
    if raw.get("validation_notes"):
        summary["validation_notes"] = raw["validation_notes"]
    return {key: value for key, value in summary.items() if value not in (None, {}, [])}


def _derive_warnings(raw: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if raw.get("validation_notes"):
        warnings.extend(_coerce_string_list(raw.get("validation_notes")))
    filtered_pairs = raw.get("filtered_pairs")
    if isinstance(filtered_pairs, list) and filtered_pairs:
        warnings.append(f"{len(filtered_pairs)} pair(s) were filtered out before validation.")
    if raw.get("insufficient_pairs"):
        warnings.append("The strategy did not pass the required number of profitable pairs.")
    if raw.get("healing_exhausted"):
        warnings.append("Auto-fix attempts were exhausted before a robust candidate was found.")
    failed_metrics = raw.get("_failed_metrics")
    if isinstance(failed_metrics, dict) and failed_metrics.get("reason"):
        warnings.append(f"Validation retry was triggered by: {failed_metrics['reason']}.")
    return warnings


def _retry_attempts_for(state: PipelineState, stage_idx: int, raw: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(raw.get("retry_history"), list):
        return raw["retry_history"]
    if stage_idx == 1:
        attempts = int(raw.get("baseline_attempts") or state.phase1_heal_attempts or 0)
        return [
            {
                "attempt": idx + 1,
                "stage": 1,
                "type": "baseline_auto_fix",
                "status": "applied" if idx < attempts - 1 else "latest",
            }
            for idx in range(max(0, attempts))
        ]
    if stage_idx in (3, 4):
        return list(state.retry_history or [])
    return []


def _auto_fix_for(state: PipelineState, stage_idx: int, raw: dict[str, Any]) -> dict[str, Any]:
    hooks: list[dict[str, Any]] = []
    if stage_idx == 1:
        hooks.append(
            {
                "name": "baseline_hard_mutation",
                "enabled": True,
                "attempts": state.phase1_heal_attempts,
                "description": "Force available Boolean indicator switches and rerun pair filtering.",
            }
        )
    if stage_idx in (3, 4):
        hooks.append(
            {
                "name": "sensitivity_self_heal",
                "enabled": True,
                "attempts": state.retry_count,
                "max_attempts": state.max_retries,
                "description": "Adjust hyperopt loss, spaces, epochs, or AI-proposed overrides after robustness failure.",
            }
        )
        hooks.append(
            {
                "name": "ollama_sensitivity_fix",
                "enabled": bool(raw.get("ollama_suggestions") or state.ai_enabled),
                "description": "Optional AI suggestion hook; backend still validates every proposed change.",
            }
        )
    return {"hooks": hooks, "last_action": raw.get("mutation_applied") or raw.get("auto_fix_action")}



def _suggestions_for(
    stage_idx: int,
    message: str,
    raw: dict[str, Any],
    errors: list[dict[str, Any]],
    state: PipelineState | None,
) -> list[str]:
    suggestions: list[str] = []
    text = f"{message} {raw.get('_failed_metrics', '')}".lower()
    for error in errors:
        suggestions.extend(_coerce_string_list(error.get("suggestions")))

    if "no market data" in text or "no data" in text:
        suggestions.append("Download OHLCV data for the selected timeframe and timerange before rerunning.")
    if "0 trades" in text or "zero trades" in text or "no signals" in text:
        suggestions.append("Widen the timerange, change timeframe, or verify entry conditions produce signals.")
    if "insufficient" in text and "pair" in text:
        suggestions.append("Expand the pair universe or loosen discovery gates before rerunning validation.")
    if "drawdown" in text:
        suggestions.append("Try a drawdown-aware loss function such as Calmar or ProfitDrawDown.")
    if "sharp peak" in text or "sensitivity" in text or "robustness" in text:
        suggestions.append("Enable WFO or increase in-sample coverage to reduce overfit parameter peaks.")
    if "negative baseline" in text:
        suggestions.append("Review the base strategy logic before optimizing; hyperopt cannot repair a structurally losing signal.")
    if raw.get("suggestions"):
        suggestions.extend(_coerce_string_list(raw.get("suggestions")))
    if state is not None and stage_idx in (3, 4) and state.retry_count >= state.max_retries:
        suggestions.append("Stop retrying this configuration and test a different strategy/timeframe/pair universe.")
    return suggestions


def _stage_progress_for(state: PipelineState, stage_idx: int, status: str) -> dict[str, Any]:
    return {
        "percent": _event_stage_percent(status),
        "global_percent": state.progress_percent,
        "is_current": state.current_stage == stage_idx,
        "current_stage": state.current_stage,
    }


def _status_kind(status: str, errors: list[dict[str, Any]]) -> str:
    if status == "failed" and errors:
        return errors[0].get("kind", "controlled_validation")
    if status == "failed":
        return "stage_failure"
    return status


def _event_stage_percent(status: str) -> int:
    if status == "passed":
        return 100
    if status == "failed":
        return 100
    if status == "running":
        return 50
    return 0


def _error_details_from_data(raw: dict[str, Any]) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for key in ("_failed_metrics", "thresholds", "baseline_attempts", "healing_exhausted"):
        if key in raw:
            details[key] = raw[key]
    return details


def _slug_code(message: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", message.strip().lower()).strip("_")
    if not text:
        return "auto_quant_stage_failure"
    return text[:80]


def _strip_ui_keys(raw: dict[str, Any]) -> dict[str, Any]:
    ui_keys = {
        "schema_version",
        "status_kind",
        "input_summary",
        "output_summary",
        "metrics",
        "warnings",
        "errors",
        "retry_attempts",
        "suggestions",
        "auto_fix",
        "stage_progress",
    }
    return {key: value for key, value in raw.items() if key not in ui_keys}


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, tuple | set):
        return [str(item) for item in value if item is not None]
    if isinstance(value, str):
        return [value]
    return [str(value)]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
