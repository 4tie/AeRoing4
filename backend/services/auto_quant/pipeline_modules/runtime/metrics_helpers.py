"""Metrics tracking and analysis helpers."""

from __future__ import annotations

from typing import Any

from ..state import PipelineState, _now


_METRIC_KEYS = (
    "profit_total",
    "profit_total_abs",
    "profit_mean_pct",
    "max_drawdown_account",
    "total_trades",
    "wins",
    "losses",
    "draws",
    "win_rate",
    "win_rate_pct",
    "profit_factor",
    "sharpe_ratio",
    "calmar_ratio",
    "sortino_ratio",
    "baseline_attempts",
    "weighted_profit",
    "portfolio_profit",
    "score",
)


def _record_best_observed(state: PipelineState, metrics: dict[str, Any], attempt_number: int | None) -> None:
    if not metrics:
        return
    current = getattr(state, "best_observed_result", {}) or {}
    current_score = _best_observed_sort_key(current.get("metrics", {}))
    candidate_score = _best_observed_sort_key(metrics)
    if not current or candidate_score > current_score:
        state.best_observed_result = {
            "attempt": attempt_number,
            "metrics": metrics,
            "recorded_at": _now(),
        }


def _best_observed_sort_key(metrics: dict[str, Any]) -> tuple[float, float, float]:
    profit = _first_number(metrics, "profit_total", "profit_total_abs", "portfolio_profit", "oos_profit")
    profit_factor = _first_number(metrics, "profit_factor")
    drawdown = _first_number(metrics, "max_drawdown_account", "drawdown", "failed_drawdown")
    return (
        profit if profit is not None else -999999.0,
        profit_factor if profit_factor is not None else 0.0,
        -(drawdown if drawdown is not None else 999999.0),
    )


def _first_number(metrics: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key not in metrics:
            continue
        try:
            return float(metrics[key])
        except (TypeError, ValueError):
            continue
    return None


def _recommended_next_experiment(state: PipelineState, message: str, raw: dict[str, Any]) -> str:
    text = f"{message} {raw.get('_failed_metrics', '')}".lower()
    if "pair" in text:
        return "Try a different pair universe or run pair screening before another validation attempt."
    if "drawdown" in text:
        return "Try a more conservative risk profile, drawdown-aware loss function, or wider timeframe."
    if "profit" in text or "expectancy" in text:
        return "Try a different timeframe, pair universe, or base strategy logic before increasing optimization budget."
    if "sharp peak" in text or "sensitivity" in text:
        return "Enable or widen WFO and reduce parameter search aggressiveness before retrying."
    return "Start a new validation run with different strategy, timeframe, risk profile, or pair universe."


def _metrics_from(raw: dict[str, Any]) -> dict[str, Any]:
    metrics = {key: raw[key] for key in _METRIC_KEYS if key in raw}
    failed_metrics = raw.get("_failed_metrics")
    if isinstance(failed_metrics, dict):
        metrics.update(failed_metrics)
    return metrics
