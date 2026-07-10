"""Scoring module for AutoQuant robustness-first workflow.

This module computes final strategy scores, validation status, and readiness tiers
using explicit, risk-profile-aware validation gates.  Scores rank only after the
validation gates are evaluated; a high score cannot override a blocking failure.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

from ..policy import latest_complete_day, load_policy
from .logging import _rlog


DEFAULT_SCORE_WEIGHTS: dict[str, float] = {
    "expectancy": 0.20,
    "profit_factor": 0.20,
    "drawdown": 0.15,
    "risk_adjusted": 0.10,
    "robustness": 0.10,
    "oos": 0.10,
    "walk_forward": 0.05,
    "pair_consistency": 0.05,
    "trade_quality": 0.05,
}

TIMEFRAME_MIN_TRADES_PER_YEAR: tuple[tuple[set[str], int], ...] = (
    ({"1m", "3m", "5m"}, 500),
    ({"15m", "30m", "1h"}, 250),
    ({"2h", "4h", "6h", "8h", "12h"}, 120),
    ({"1d", "3d", "1w"}, 30),
)

# Minimum trades per year for scalping/intraday activity warning
SCALPING_MIN_TRADES_PER_YEAR = 180

VALIDATED_SCORE = 75.0
PROMISING_SCORE = 65.0
CANDIDATE_SCORE = 50.0
ELITE_SCORE = 85.0


class _Missing:
    pass


MISSING = _Missing()


def compute_score(
    run_id: str,
    state: Any,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    """Compute validation-first strategy score and robustness tier.

    Internal units are decimals for rates and drawdowns:
    - 0.15 means 15% drawdown.
    - 0.001 means 0.1% average profit per trade / expectancy.
    Display fields expose percentages separately so the UI does not need to
    guess whether a value is decimal or percent.
    """
    policy = load_policy()
    style = str(getattr(state, "trading_style", "swing") or "swing")
    risk_profile = str(getattr(state, "risk_profile", "balanced") or "balanced")
    validation_timerange = str(
        getattr(state, "out_sample_range", None)
        or getattr(state, "in_sample_range", None)
        or ""
    )
    validation_gates = dict(
        policy.thresholds_for(
            style,
            risk_profile,
            "validation",
            timerange=validation_timerange,
        )
    )
    elite_gates = dict(
        policy.thresholds_for(
            style,
            risk_profile,
            "elite_validation",
            timerange=validation_timerange,
        )
    )
    weights = _score_weights(policy.score_weights)

    normalized = _normalize_metrics(state, metrics, validation_gates)
    components = _build_components(normalized, validation_gates, elite_gates, weights)
    gate_checks = _build_gate_checks(state, normalized, validation_gates, elite_gates)
    score_100 = _weighted_score(components, weights)
    tier_info = _classify_tier(score_100, gate_checks, normalized, validation_gates, elite_gates)

    score_explanation = {
        "formula_version": "validation_first_v3",
        "units": {
            "internal_rates": "decimal: 0.10 means 10%",
            "display_rates": "percent: 10.0 means 10%",
            "profit_factor": "ratio",
            "sharpe_ratio": "ratio, optional",
            "calmar_ratio": "ratio, optional",
        },
        "time_range": {
            "in_sample": str(getattr(state, "in_sample_range", "unknown")),
            "out_of_sample": str(getattr(state, "out_sample_range", "unknown")),
            "oos_years": normalized.get("oos_years", 1.0),
            "latest_complete_day": latest_complete_day().strftime("%Y-%m-%d"),
        },
        "trade_activity_gate": {
            "required_oos_trades": normalized.get("min_trades_required", 0),
            "actual_oos_trades": normalized.get("oos_total_trades") if normalized.get("oos_total_trades") is not None else normalized.get("total_trades", 0),
            "in_sample_trades": normalized.get("in_sample_total_trades"),
            "portfolio_trades": normalized.get("portfolio_total_trades"),
            "basis": "Duration-adjusted policy min_trades resolved from JSON thresholds.",
        },
        "formulas": {
            "profit_factor": "70 points at validation min PF; 100 points at elite min PF.",
            "expectancy": "Per-trade expectancy in decimal return; 70 points at validation min expectancy; 100 at elite min expectancy.",
            "drawdown": "Lower is better; 100 at <= 50% of max drawdown gate, 70 at the gate, 0 at >= 150% of the gate.",
            "risk_adjusted": "Average of available Sharpe and Calmar scores; skipped when neither is available.",
            "oos": "OOS retention or explicit OOS pass/fail when available; missing OOS caps the tier below Validated.",
            "walk_forward": "Walk-forward pass-rate score when WFO windows are available; otherwise marked unavailable.",
            "pair_consistency": "Multi-pair pass rate when per-pair results exist, otherwise selected-pair coverage versus policy target.",
            "trade_quality": "Trade-count score versus duration-adjusted policy min_trades.",
        },
        "thresholds": _threshold_summary(validation_gates, elite_gates, normalized),
        "components": components,
        "gate_checks": gate_checks,
        "failed_gates": [check for check in gate_checks if check["blocking"] and not check["passed"]],
        "warnings": _score_warnings(gate_checks, normalized),
        "suggestions": _score_suggestions(gate_checks, normalized),
        "final_score": round(score_100, 2),
        "tier": tier_info["tier"],
        "accepted": tier_info["accepted"],
        "status_reason": tier_info["reason"],
        "weights_used": {
            key: round(float(value), 4)
            for key, value in weights.items()
            if components.get(key, {}).get("score") is not None
        },
        "raw_metrics_normalized": normalized,
    }

    _rlog(
        run_id,
        5,
        logging.INFO,
        "Score Computation | "
        f"Score={score_100:.1f}/100 | Tier={tier_info['tier']} | "
        f"Accepted={tier_info['accepted']} | Reason={tier_info['reason']}",
    )

    return {
        "score": round(score_100, 2),
        "score_explanation": score_explanation,
        "validation_status": tier_info["validation_status"],
        "readiness_label": tier_info["readiness_label"],
        "robustness_classification": tier_info["tier"],
        "accepted": tier_info["accepted"],
    }


def determine_validation_status(
    state: Any,
    metrics: dict[str, Any],
    score: float,
) -> str:
    """Return the validation status for callers that still use the legacy API."""
    policy = load_policy()
    style = str(getattr(state, "trading_style", "swing") or "swing")
    risk_profile = str(getattr(state, "risk_profile", "balanced") or "balanced")
    validation_timerange = str(
        getattr(state, "out_sample_range", None)
        or getattr(state, "in_sample_range", None)
        or ""
    )
    gates = dict(
        policy.thresholds_for(
            style,
            risk_profile,
            "validation",
            timerange=validation_timerange,
        )
    )
    elite_gates = dict(
        policy.thresholds_for(
            style,
            risk_profile,
            "elite_validation",
            timerange=validation_timerange,
        )
    )
    normalized = _normalize_metrics(state, metrics, gates)
    checks = _build_gate_checks(state, normalized, gates, elite_gates)
    return _classify_tier(score, checks, normalized, gates, elite_gates)["validation_status"]


def aggregate_validation_notes(state: Any) -> list[str]:
    """Aggregate validation notes from pipeline stages."""
    notes = list(state.validation_notes)

    for stage in state.stages:
        if stage.message and "warning" in stage.message.lower():
            notes.append(f"Stage {stage.index}: {stage.message}")

    return list(dict.fromkeys(notes))


def _score_weights(policy_weights: dict[str, Any]) -> dict[str, float]:
    configured = policy_weights.get("weights", policy_weights) if isinstance(policy_weights, dict) else {}
    weights = dict(DEFAULT_SCORE_WEIGHTS)
    for key, value in configured.items():
        try:
            weights[key] = float(value)
        except (TypeError, ValueError):
            continue
    return {key: value for key, value in weights.items() if value > 0}


def _normalize_metrics(state: Any, metrics: dict[str, Any], gates: dict[str, Any]) -> dict[str, Any]:
    timeframe = str(getattr(state, "selected_timeframe", None) or getattr(state, "timeframe", "") or "")

    # Calculate OOS years from date ranges
    oos_range = str(getattr(state, "out_sample_range", "") or "")
    oos_years = _calculate_oos_years(oos_range)

    min_trades = max(1, int(gates.get("min_trades") or 1))

    expectancy = _first_decimal_metric(
        metrics,
        decimal_keys=("expectancy", "profit_mean", "expectancy_decimal"),
        percent_keys=("expectancy_pct", "profit_mean_pct"),
    )
    profit_factor = _to_float(metrics.get("profit_factor"), None)
    drawdown = _as_decimal(
        _first_present(metrics, "max_drawdown_account", "max_drawdown", "drawdown"),
        default=None,
    )
    total_trades = _to_int(_first_present(metrics, "total_trades", "trades", "trade_count"), 0)
    win_rate = _as_decimal(_first_present(metrics, "win_rate", "win_rate_pct"), default=None)

    sharpe = _to_float(_first_present(metrics, "sharpe_ratio", "sharpe"), None)
    calmar = _to_float(_first_present(metrics, "calmar_ratio", "calmar"), None)

    oos_retention = _as_decimal(metrics.get("oos_retention"), default=None)
    oos_profit = _as_decimal(metrics.get("oos_profit"), default=None)
    oos_passed = _to_bool_or_none(metrics.get("oos_passed"))
    if oos_passed is None and oos_profit is not None:
        oos_passed = oos_profit >= float(gates.get("min_oos_profit", 0.0) or 0.0)
    if oos_passed is None and oos_retention is not None:
        oos_passed = oos_retention >= float(gates.get("min_oos_retention", 0.0) or 0.0)

    # Extract explicit OOS trade count for validation (preferred over generic total_trades)
    oos_total_trades = _to_int(metrics.get("oos_total_trades"), None)
    in_sample_total_trades = _to_int(metrics.get("in_sample_total_trades"), None)
    portfolio_total_trades = _to_int(metrics.get("portfolio_total_trades"), None)

    wfo_pass_rate = _as_decimal(
        _first_present(metrics, "wfo_pass_rate", "walk_forward_score", "walk_forward_pass_rate"),
        default=None,
    )
    pair_pass_rate = _as_decimal(_first_present(metrics, "pair_pass_rate", "multi_pair_pass_rate"), default=None)
    pair_consistency = _as_decimal(metrics.get("pair_consistency"), default=None)
    if pair_consistency is None:
        pair_consistency = pair_pass_rate

    robustness_score = _as_decimal(metrics.get("robustness_score"), default=None)

    return {
        "timeframe": timeframe,
        "min_trades_required": min_trades,
        "oos_years": oos_years,
        "required_oos_trades": min_trades,
        "min_trades_per_year": gates.get("min_trades_per_year"),
        "min_trades_floor": gates.get("min_trades_floor"),
        "min_trades_cap": gates.get("min_trades_cap"),
        "expectancy": expectancy,
        "expectancy_display_pct": _display_pct(expectancy),
        "profit_factor": profit_factor,
        "max_drawdown": drawdown,
        "max_drawdown_display_pct": _display_pct(drawdown),
        "total_trades": total_trades,
        "win_rate": win_rate,
        "win_rate_display_pct": _display_pct(win_rate),
        "sharpe_ratio": sharpe,
        "calmar_ratio": calmar,
        "oos_retention": oos_retention,
        "oos_retention_display_pct": _display_pct(oos_retention),
        "oos_profit": oos_profit,
        "oos_profit_display_pct": _display_pct(oos_profit),
        "oos_passed": oos_passed,
        "oos_total_trades": oos_total_trades,
        "in_sample_total_trades": in_sample_total_trades,
        "portfolio_total_trades": portfolio_total_trades,
        "wfo_pass_rate": wfo_pass_rate,
        "wfo_pass_rate_display_pct": _display_pct(wfo_pass_rate),
        "pair_pass_rate": pair_pass_rate,
        "pair_pass_rate_display_pct": _display_pct(pair_pass_rate),
        "pair_consistency": pair_consistency,
        "pair_consistency_display_pct": _display_pct(pair_consistency),
        "robustness_score": robustness_score,
        "robustness_score_display_pct": _display_pct(robustness_score),
    }


def _build_components(
    normalized: dict[str, Any],
    gates: dict[str, Any],
    elite_gates: dict[str, Any],
    weights: dict[str, float],
) -> dict[str, dict[str, Any]]:
    min_pf = float(gates.get("min_profit_factor") or 1.0)
    elite_pf = float(elite_gates.get("min_profit_factor") or max(min_pf + 0.2, min_pf * 1.15))
    min_exp = float(gates.get("min_expectancy") or 0.0)
    elite_exp = float(elite_gates.get("min_expectancy") or max(min_exp * 1.5, min_exp + 0.0001))
    max_dd = float(gates.get("max_drawdown") or 1.0)
    min_oos_retention = float(gates.get("min_oos_retention") or 0.5)
    min_wfo = float(elite_gates.get("min_walk_forward_pass_rate") or 0.6)
    min_pair = float(gates.get("min_pair_pass_rate") or 0.6)
    min_robustness = float(elite_gates.get("min_robustness_score") or 0.6)

    sharpe = normalized.get("sharpe_ratio")
    calmar = normalized.get("calmar_ratio")
    risk_adjusted_scores: list[float] = []
    if sharpe is not None:
        risk_adjusted_scores.append(_threshold_score(sharpe, float(gates.get("min_sharpe", 0.5) or 0.5), float(gates.get("min_sharpe", 0.5) or 0.5) + 0.75))
    if calmar is not None:
        risk_adjusted_scores.append(_threshold_score(calmar, 0.5, 1.5))
    risk_adjusted = sum(risk_adjusted_scores) / len(risk_adjusted_scores) if risk_adjusted_scores else None

    oos_score: float | None = None
    if normalized.get("oos_retention") is not None:
        oos_score = _threshold_score(normalized["oos_retention"], min_oos_retention, max(0.75, min_oos_retention + 0.25))
    elif normalized.get("oos_passed") is not None:
        oos_score = 100.0 if normalized["oos_passed"] else 0.0

    components = {
        "expectancy": _component(
            normalized.get("expectancy"),
            _threshold_score(normalized.get("expectancy"), min_exp, elite_exp),
            weights.get("expectancy", 0.0),
            ">=",
            min_exp,
            "decimal_rate",
            display_value=normalized.get("expectancy_display_pct"),
            display_threshold=_display_pct(min_exp),
        ),
        "profit_factor": _component(
            normalized.get("profit_factor"),
            _threshold_score(normalized.get("profit_factor"), min_pf, elite_pf),
            weights.get("profit_factor", 0.0),
            ">=",
            min_pf,
            "ratio",
        ),
        "drawdown": _component(
            normalized.get("max_drawdown"),
            _drawdown_score(normalized.get("max_drawdown"), max_dd),
            weights.get("drawdown", 0.0),
            "<=",
            max_dd,
            "decimal_rate",
            display_value=normalized.get("max_drawdown_display_pct"),
            display_threshold=_display_pct(max_dd),
        ),
        "risk_adjusted": _component(
            {"sharpe_ratio": sharpe, "calmar_ratio": calmar},
            risk_adjusted,
            weights.get("risk_adjusted", 0.0),
            ">=",
            float(gates.get("min_sharpe", 0.5) or 0.5),
            "ratio",
        ),
        "robustness": _component(
            normalized.get("robustness_score"),
            _threshold_score(normalized.get("robustness_score"), min_robustness, 0.9),
            weights.get("robustness", 0.0),
            ">=",
            min_robustness,
            "decimal_rate",
            display_value=normalized.get("robustness_score_display_pct"),
            display_threshold=_display_pct(min_robustness),
        ),
        "oos": _component(
            normalized.get("oos_retention") if normalized.get("oos_retention") is not None else normalized.get("oos_passed"),
            oos_score,
            weights.get("oos", 0.0),
            ">=",
            min_oos_retention,
            "decimal_rate_or_boolean",
            display_value=normalized.get("oos_retention_display_pct"),
            display_threshold=_display_pct(min_oos_retention),
        ),
        "walk_forward": _component(
            normalized.get("wfo_pass_rate"),
            _threshold_score(normalized.get("wfo_pass_rate"), min_wfo, 0.85),
            weights.get("walk_forward", 0.0),
            ">=",
            min_wfo,
            "decimal_rate",
            display_value=normalized.get("wfo_pass_rate_display_pct"),
            display_threshold=_display_pct(min_wfo),
        ),
        "pair_consistency": _component(
            normalized.get("pair_consistency"),
            _threshold_score(normalized.get("pair_consistency"), min_pair, 0.8),
            weights.get("pair_consistency", 0.0),
            ">=",
            min_pair,
            "decimal_rate",
            display_value=normalized.get("pair_consistency_display_pct"),
            display_threshold=_display_pct(min_pair),
        ),
        "trade_quality": _component(
            normalized.get("oos_total_trades") if normalized.get("oos_total_trades") is not None else normalized.get("total_trades"),
            _threshold_score(normalized.get("oos_total_trades") if normalized.get("oos_total_trades") is not None else normalized.get("total_trades"), normalized.get("min_trades_required", 1), normalized.get("min_trades_required", 1) * 2),
            weights.get("trade_quality", 0.0),
            ">=",
            normalized.get("min_trades_required"),
            "count",
            display_value=normalized.get("oos_total_trades") if normalized.get("oos_total_trades") is not None else normalized.get("total_trades"),
        ),
    }

    for key, value in components.items():
        score = value.get("score")
        weight = value.get("weight", 0.0)
        value["contribution"] = round(score * weight, 4) if score is not None else None
        value["available"] = score is not None
    return components


def _build_gate_checks(
    state: Any,
    normalized: dict[str, Any],
    gates: dict[str, Any],
    elite_gates: dict[str, Any],
) -> list[dict[str, Any]]:
    min_exp = float(gates.get("min_expectancy") or 0.0)
    min_pf = float(gates.get("min_profit_factor") or 1.0)
    max_dd = float(gates.get("max_drawdown") or 1.0)
    min_trades = int(normalized.get("min_trades_required") or gates.get("min_trades") or 1)
    min_pair_pass_rate = float(gates.get("min_pair_pass_rate") or 0.6)
    min_oos_retention = float(gates.get("min_oos_retention") or 0.5)
    min_wfo_pass_rate = float(elite_gates.get("min_walk_forward_pass_rate") or 0.6)
    min_sharpe = float(gates.get("min_sharpe", getattr(state, "min_sharpe", 0.0)) or 0.0)

    checks = [
        _gate("profit_factor", normalized.get("profit_factor"), min_pf, ">=", _passes_min(normalized.get("profit_factor"), min_pf), True, "Profit factor must clear the validation threshold."),
        _gate("expectancy", normalized.get("expectancy"), min_exp, ">=", _passes_min(normalized.get("expectancy"), min_exp), True, "Expectancy must be positive enough after costs."),
        _gate("max_drawdown", normalized.get("max_drawdown"), max_dd, "<=", _passes_max(normalized.get("max_drawdown"), max_dd), True, "Drawdown must stay within the risk-profile limit."),
        _gate("min_trades", normalized.get("total_trades"), min_trades, ">=", int(normalized.get("total_trades") or 0) >= min_trades, True, "Trade count must meet the timeframe minimum."),
    ]

    oos_passed = normalized.get("oos_passed")
    if oos_passed is not None:
        checks.append(_gate("oos_pass", oos_passed, True, "==", bool(oos_passed), True, "Out-of-sample validation must pass when OOS data is available."))
    elif normalized.get("oos_retention") is not None:
        checks.append(_gate("oos_retention", normalized.get("oos_retention"), min_oos_retention, ">=", _passes_min(normalized.get("oos_retention"), min_oos_retention), True, "OOS retention must clear the policy threshold."))
    else:
        checks.append(_gate("oos_available", None, "required for Validated", "available", None, False, "OOS data is missing, so the strategy cannot be marked Validated or Elite."))

    pair_pass_rate = normalized.get("pair_pass_rate")
    if pair_pass_rate is not None:
        checks.append(_gate("multi_pair_pass_rate", pair_pass_rate, min_pair_pass_rate, ">=", _passes_min(pair_pass_rate, min_pair_pass_rate), True, "Multi-pair pass rate must clear the policy threshold."))
    else:
        checks.append(_gate("multi_pair_available", None, "required for Validated", "available", None, False, "Multi-pair pass-rate data is missing, so the tier is capped below Validated."))

    wfo_pass_rate = normalized.get("wfo_pass_rate")
    if wfo_pass_rate is not None:
        checks.append(_gate("wfo_stability", wfo_pass_rate, min_wfo_pass_rate, ">=", _passes_min(wfo_pass_rate, min_wfo_pass_rate), True, "WFO pass rate must be stable when WFO runs."))
    
    # Latest window collapse check - blocks Validated/Elite if latest WFO window failed
    latest_window_passed = normalized.get("latest_window_passed")
    if latest_window_passed is not None:
        checks.append(_gate("latest_window_collapse", latest_window_passed, True, "==", bool(latest_window_passed), True, "Latest WFO window must not fail catastrophically for Validated/Elite status."))

    sharpe = normalized.get("sharpe_ratio")
    if sharpe is not None and sharpe != 0.0 and min_sharpe > 0:
        checks.append(_gate("sharpe_ratio", sharpe, min_sharpe, ">=", _passes_min(sharpe, min_sharpe), False, "Sharpe is advisory unless the risk profile explicitly makes it blocking."))

    failed_stages = [
        getattr(stage, "name", f"Stage {getattr(stage, 'index', '?')}")
        for stage in getattr(state, "stages", [])
        if getattr(stage, "status", None) == "failed"
    ]
    if failed_stages:
        checks.append(_gate("pipeline_stages", failed_stages, "no failed stages", "==", False, True, "A failed pipeline stage always blocks acceptance."))

    return checks


def _classify_tier(
    score: float,
    checks: list[dict[str, Any]],
    normalized: dict[str, Any],
    gates: dict[str, Any],
    elite_gates: dict[str, Any],
) -> dict[str, Any]:
    blocking_failures = [check for check in checks if check["blocking"] and check["passed"] is False]
    if blocking_failures:
        return {
            "tier": "Rejected",
            "validation_status": "failed",
            "readiness_label": "Not Ready",
            "accepted": False,
            "reason": "Blocking validation gate failed: " + ", ".join(check["name"] for check in blocking_failures),
        }

    has_oos = any(check["name"] in {"oos_pass", "oos_retention"} and check["passed"] for check in checks)
    has_multi_pair = any(check["name"] == "multi_pair_pass_rate" and check["passed"] for check in checks)
    wfo_checks = [check for check in checks if check["name"] == "wfo_stability"]
    wfo_ok = not wfo_checks or all(check["passed"] for check in wfo_checks)

    elite_ok = (
        score >= ELITE_SCORE
        and has_oos
        and has_multi_pair
        and wfo_ok
        and _passes_min(normalized.get("profit_factor"), float(elite_gates.get("min_profit_factor") or gates.get("min_profit_factor") or 1.0))
        and _passes_min(normalized.get("expectancy"), float(elite_gates.get("min_expectancy") or gates.get("min_expectancy") or 0.0))
        and _passes_max(normalized.get("max_drawdown"), float(elite_gates.get("max_drawdown") or gates.get("max_drawdown") or 1.0))
        and _passes_min(normalized.get("robustness_score"), float(elite_gates.get("min_robustness_score") or 0.0))
    )
    if elite_ok:
        return {
            "tier": "Elite",
            "validation_status": "elite",
            "readiness_label": "Elite",
            "accepted": True,
            "reason": "Validation and elite robustness gates passed.",
        }

    if score >= VALIDATED_SCORE and has_oos and has_multi_pair and wfo_ok:
        return {
            "tier": "Validated",
            "validation_status": "validated",
            "readiness_label": "Validated",
            "accepted": True,
            "reason": "Core validation, OOS, and multi-pair gates passed.",
        }

    if score >= PROMISING_SCORE:
        return {
            "tier": "Promising",
            "validation_status": "promising",
            "readiness_label": "Promising",
            "accepted": False,
            "reason": "Core gates passed, but OOS/multi-pair/WFO evidence is incomplete or score is below Validated.",
        }

    return {
        "tier": "Candidate",
        "validation_status": "candidate",
        "readiness_label": "Candidate",
        "accepted": False,
        "reason": "Core gates passed, but the robustness score is still early-stage.",
    }


def _threshold_summary(gates: dict[str, Any], elite_gates: dict[str, Any], normalized: dict[str, Any]) -> dict[str, Any]:
    return {
        "validation": {
            "min_profit_factor": gates.get("min_profit_factor"),
            "min_expectancy": gates.get("min_expectancy"),
            "min_expectancy_display_pct": _display_pct(gates.get("min_expectancy")),
            "max_drawdown": gates.get("max_drawdown"),
            "max_drawdown_display_pct": _display_pct(gates.get("max_drawdown")),
            "min_trades": normalized.get("min_trades_required"),
            "min_trades_per_year": normalized.get("min_trades_per_year"),
            "min_trades_floor": normalized.get("min_trades_floor"),
            "min_trades_cap": normalized.get("min_trades_cap"),
            "min_pair_pass_rate": gates.get("min_pair_pass_rate"),
            "min_pair_pass_rate_display_pct": _display_pct(gates.get("min_pair_pass_rate")),
            "min_oos_retention": gates.get("min_oos_retention"),
            "min_oos_retention_display_pct": _display_pct(gates.get("min_oos_retention")),
        },
        "elite": {
            "min_profit_factor": elite_gates.get("min_profit_factor"),
            "min_expectancy": elite_gates.get("min_expectancy"),
            "min_expectancy_display_pct": _display_pct(elite_gates.get("min_expectancy")),
            "max_drawdown": elite_gates.get("max_drawdown"),
            "max_drawdown_display_pct": _display_pct(elite_gates.get("max_drawdown")),
            "min_walk_forward_pass_rate": elite_gates.get("min_walk_forward_pass_rate"),
            "min_walk_forward_pass_rate_display_pct": _display_pct(elite_gates.get("min_walk_forward_pass_rate")),
            "min_robustness_score": elite_gates.get("min_robustness_score"),
            "min_robustness_score_display_pct": _display_pct(elite_gates.get("min_robustness_score")),
        },
    }


def _score_warnings(checks: list[dict[str, Any]], normalized: dict[str, Any]) -> list[str]:
    warnings = []
    for check in checks:
        if check["passed"] is None:
            warnings.append(check["message"])
        elif not check["passed"] and not check["blocking"]:
            warnings.append(check["message"])
    if normalized.get("sharpe_ratio") is None and normalized.get("calmar_ratio") is None:
        warnings.append("Sharpe/Calmar were not available; risk-adjusted score component was skipped, not assumed.")
    
    # Scalping/intraday activity warning for low trade counts
    timeframe = normalized.get("timeframe", "").lower()
    total_trades = normalized.get("total_trades", 0)
    oos_years = normalized.get("oos_years", 1.0)
    scalping_timeframes = {"1m", "3m", "5m", "15m", "30m", "1h"}
    
    if timeframe in scalping_timeframes and oos_years > 0:
        trades_per_year = total_trades / oos_years
        if trades_per_year < SCALPING_MIN_TRADES_PER_YEAR:
            warnings.append(
                f"Low trade activity for {timeframe} timeframe: {trades_per_year:.0f} trades/year vs "
                f"recommended {SCALPING_MIN_TRADES_PER_YEAR}+ trades/year for scalping/intraday strategies. "
                f"This may indicate insufficient signal frequency."
            )
    
    return warnings


def _score_suggestions(checks: list[dict[str, Any]], normalized: dict[str, Any]) -> list[str]:
    suggestions: list[str] = []
    failed_names = {check["name"] for check in checks if check["passed"] is False}
    if "profit_factor" in failed_names or "expectancy" in failed_names:
        suggestions.append("Improve edge quality before accepting: review fees, exits, and whether the signal survives OOS.")
    if "max_drawdown" in failed_names:
        suggestions.append("Reduce drawdown before acceptance: tighten risk controls, position sizing, or market-regime filters.")
    if "min_trades" in failed_names:
        suggestions.append(f"Increase sample size: {normalized.get('timeframe')} requires at least {normalized.get('min_trades_required')} trades.")
    if "oos_pass" in failed_names or "oos_retention" in failed_names:
        suggestions.append("Do not promote this strategy until OOS performance clears the policy gate.")
    if "multi_pair_pass_rate" in failed_names:
        suggestions.append("Improve pair generalization; avoid accepting a single-pair-only backtest as robust.")
    if not suggestions:
        suggestions.append("Continue with dry-run or forward-test validation before any live-risk decision.")
    return suggestions


def _weighted_score(components: dict[str, dict[str, Any]], weights: dict[str, float]) -> float:
    weighted = 0.0
    total_weight = 0.0
    for key, component in components.items():
        score = component.get("score")
        weight = float(weights.get(key, 0.0))
        if score is None or weight <= 0:
            continue
        weighted += float(score) * weight
        total_weight += weight
    if total_weight <= 0:
        return 0.0
    return max(0.0, min(100.0, weighted / total_weight))


def _component(
    value: Any,
    score: float | None,
    weight: float,
    operator: str,
    threshold: Any,
    unit: str,
    *,
    display_value: Any = None,
    display_threshold: Any = None,
) -> dict[str, Any]:
    return {
        "value": value,
        "display_value": display_value,
        "unit": unit,
        "operator": operator,
        "threshold": threshold,
        "display_threshold": display_threshold,
        "score": round(score, 2) if score is not None else None,
        "weight": float(weight),
    }


def _gate(name: str, value: Any, threshold: Any, operator: str, passed: bool | None, blocking: bool, message: str) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "threshold": threshold,
        "operator": operator,
        "passed": passed,
        "blocking": blocking,
        "message": message,
    }


def _threshold_score(value: Any, validation_target: float, elite_target: float) -> float | None:
    numeric = _to_float(value, None)
    if numeric is None:
        return None
    if validation_target <= 0:
        return 100.0 if numeric > 0 else 0.0
    if numeric < validation_target:
        return max(0.0, min(70.0, numeric / validation_target * 70.0))
    if elite_target <= validation_target:
        return 100.0
    return max(70.0, min(100.0, 70.0 + ((numeric - validation_target) / (elite_target - validation_target) * 30.0)))


def _drawdown_score(value: Any, max_drawdown: float) -> float | None:
    drawdown = _to_float(value, None)
    if drawdown is None:
        return None
    if max_drawdown <= 0:
        return 0.0
    excellent = max_drawdown * 0.5
    failure = max_drawdown * 1.5
    if drawdown <= excellent:
        return 100.0
    if drawdown <= max_drawdown:
        return 100.0 - ((drawdown - excellent) / (max_drawdown - excellent) * 30.0)
    if drawdown >= failure:
        return 0.0
    return 70.0 - ((drawdown - max_drawdown) / (failure - max_drawdown) * 70.0)


def _passes_min(value: Any, threshold: float) -> bool:
    numeric = _to_float(value, None)
    return numeric is not None and numeric >= threshold


def _passes_max(value: Any, threshold: float) -> bool:
    numeric = _to_float(value, None)
    return numeric is not None and numeric <= threshold


def _min_trades_for_timeframe(timeframe: str, gates: dict[str, Any]) -> int:
    policy_min = int(gates.get("min_trades") or 1)
    tf = timeframe.lower().strip()
    timeframe_min = 1
    for names, minimum in TIMEFRAME_MIN_TRADES_PER_YEAR:
        if tf in names:
            timeframe_min = minimum
            break
    return max(policy_min, timeframe_min)


def _min_trades_per_year_for_timeframe(timeframe: str) -> int:
    """Return minimum trades per year for a given timeframe."""
    tf = timeframe.lower().strip()
    for names, minimum in TIMEFRAME_MIN_TRADES_PER_YEAR:
        if tf in names:
            return minimum
    return 100  # Default fallback


def _calculate_oos_years(oos_range: str) -> float:
    """Calculate OOS years from Freqtrade timerange string using exact calendar months.

    This uses calendar-month arithmetic to ensure accurate month counting
    (e.g., 12 months = 1.0 year, not 360 days).

    Args:
        oos_range: Freqtrade timerange format (YYYYMMDD-YYYYMMDD)

    Returns:
        OOS years as a float (e.g., 0.5 for 6 months, 1.0 for 12 months)
    """
    import calendar
    try:
        parts = oos_range.split("-")
        if len(parts) != 2:
            return 1.0  # Default to 1 year if parsing fails

        start_str, end_str = parts
        start_date = datetime.strptime(start_str, "%Y%m%d")
        end_date = datetime.strptime(end_str, "%Y%m%d")

        # Calculate months using calendar arithmetic
        total_months = (end_date.year * 12 + end_date.month) - (start_date.year * 12 + start_date.month)
        oos_months = total_months + (end_date.day - start_date.day) / calendar.monthrange(end_date.year, end_date.month)[1]
        return round(oos_months / 12.0, 2)
    except (ValueError, AttributeError):
        return 1.0  # Default to 1 year on error


def _first_present(values: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in values and values[key] is not None:
            return values[key]
    return MISSING


def _first_decimal_metric(
    values: dict[str, Any],
    *,
    decimal_keys: tuple[str, ...],
    percent_keys: tuple[str, ...],
) -> float | None:
    decimal_value = _first_present(values, *decimal_keys)
    if decimal_value is not MISSING:
        return _as_decimal(decimal_value, default=None)
    percent_value = _first_present(values, *percent_keys)
    if percent_value is not MISSING:
        numeric = _to_float(percent_value, None)
        return numeric / 100.0 if numeric is not None else None
    return None


def _as_decimal(value: Any, default: float | None = 0.0) -> float | None:
    if value is MISSING or value is None:
        return default
    numeric = _to_float(value, default)
    if numeric is None:
        return default
    return numeric / 100.0 if abs(numeric) > 1 else numeric


def _to_float(value: Any, default: float | None = 0.0) -> float | None:
    if value is MISSING or value is None:
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    return numeric


def _to_int(value: Any, default: int = 0) -> int:
    numeric = _to_float(value, None)
    return default if numeric is None else int(numeric)


def _to_bool_or_none(value: Any) -> bool | None:
    if value is None or value is MISSING:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip().lower() in {"true", "passed", "pass", "yes", "1"}:
            return True
        if value.strip().lower() in {"false", "failed", "fail", "no", "0"}:
            return False
    return bool(value)


def _display_pct(value: Any) -> float | None:
    numeric = _to_float(value, None)
    return None if numeric is None else round(numeric * 100.0, 4)


__all__ = [
    "compute_score",
    "determine_validation_status",
    "aggregate_validation_notes",
]
