"""Failure analyzer — classifies BacktestGate failures into actionable classes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .backtest_gate import GATE_THRESHOLDS, BacktestGateResult

FailureClass = Literal[
    "data_quality_failed",
    "backtest_failed",
    "no_trades",
    "too_few_trades",
    "negative_expectancy",
    "high_drawdown",
    "weak_profit_factor",
    "weak_sharpe",
    "weak_win_rate",
    "multiple_metric_failure",
]

NextRoute = Literal[
    "none_needed",
    "check_data",
    "inspect_logs",
    "discard_strategy",
    "extend_timerange_or_discard",
    "adjust_stoploss_or_roi",
    "tighten_stoploss_or_position_sizing",
    "adjust_exit_conditions",
    "review_entry_consistency",
    "review_entry_logic",
    "fundamental_rework",
]


@dataclass
class FailureClassification:
    primary_class: FailureClass | None = None
    next_route: NextRoute = "none_needed"
    secondary_classes: list[FailureClass] = field(default_factory=list)
    failed_metrics: list[str] = field(default_factory=list)
    metric_values: dict[str, Any] = field(default_factory=dict)
    gate_passed: bool = False


_ROUTE_MAP: dict[FailureClass, NextRoute] = {
    "data_quality_failed": "check_data",
    "backtest_failed": "inspect_logs",
    "no_trades": "discard_strategy",
    "too_few_trades": "extend_timerange_or_discard",
    "negative_expectancy": "adjust_stoploss_or_roi",
    "high_drawdown": "tighten_stoploss_or_position_sizing",
    "weak_profit_factor": "adjust_exit_conditions",
    "weak_sharpe": "review_entry_consistency",
    "weak_win_rate": "review_entry_logic",
    "multiple_metric_failure": "fundamental_rework",
}


def _check_individual_metrics(metrics: dict[str, Any]) -> list[FailureClass]:
    """Check the 5 individual metric-based failure classes only."""
    t = GATE_THRESHOLDS
    failures: list[FailureClass] = []

    val = metrics.get("expectancy")
    if val is not None and not (val > 0):
        failures.append("negative_expectancy")

    val = metrics.get("max_drawdown_pct")
    if val is not None and val > t["max_drawdown_pct"]:
        failures.append("high_drawdown")

    val = metrics.get("profit_factor")
    if val is not None and val < t["min_profit_factor"]:
        failures.append("weak_profit_factor")

    val = metrics.get("sharpe_ratio")
    if val is not None and val < t["min_sharpe_ratio"]:
        failures.append("weak_sharpe")

    val = metrics.get("win_rate_pct")
    if val is not None and val < t["min_win_rate_pct"]:
        failures.append("weak_win_rate")

    return failures


def analyze_gate_failure(result: BacktestGateResult) -> FailureClassification:
    """Classify a BacktestGateResult into a failure class with next route.

    Classification order (deterministic):
      1. passed
      2. data_quality_failed
      3. backtest_failed
      4. no_trades (short-circuits metric checks)
      5. too_few_trades (short-circuits metric checks)
      6. individual metric failures (negative_expectancy, high_drawdown,
         weak_profit_factor, weak_sharpe, weak_win_rate)
      7. multiple_metric_failure override when 2+ of the 5 metric
         classes apply
    """
    metrics = result.metrics
    failed_metrics = list(result.failures)
    metric_values = dict(metrics)

    if result.gate_status == "passed":
        return FailureClassification(
            gate_passed=True,
            next_route="none_needed",
            failed_metrics=failed_metrics,
            metric_values=metric_values,
        )

    if result.gate_status == "data_quality_failed":
        return FailureClassification(
            primary_class="data_quality_failed",
            next_route="check_data",
            failed_metrics=failed_metrics,
            metric_values=metric_values,
        )

    if result.gate_status == "backtest_failed":
        return FailureClassification(
            primary_class="backtest_failed",
            next_route="inspect_logs",
            failed_metrics=failed_metrics,
            metric_values=metric_values,
        )

    total_trades = metrics.get("total_trades")
    if total_trades is None or total_trades == 0:
        return FailureClassification(
            primary_class="no_trades",
            next_route="discard_strategy",
            failed_metrics=failed_metrics,
            metric_values=metric_values,
        )

    if total_trades is not None and total_trades < GATE_THRESHOLDS["min_trades"]:
        return FailureClassification(
            primary_class="too_few_trades",
            next_route="extend_timerange_or_discard",
            failed_metrics=failed_metrics,
            metric_values=metric_values,
        )

    metric_classes = _check_individual_metrics(metrics)

    if len(metric_classes) >= 2:
        return FailureClassification(
            primary_class="multiple_metric_failure",
            next_route="fundamental_rework",
            secondary_classes=metric_classes,
            failed_metrics=failed_metrics,
            metric_values=metric_values,
        )

    if len(metric_classes) == 1:
        cls = metric_classes[0]
        return FailureClassification(
            primary_class=cls,
            next_route=_ROUTE_MAP[cls],
            failed_metrics=failed_metrics,
            metric_values=metric_values,
        )

    return FailureClassification(
        primary_class="backtest_failed",
        next_route="inspect_logs",
        failed_metrics=failed_metrics,
        metric_values=metric_values,
    )
