"""Repair plan gate — converts failure classification into a safe repair permission plan."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .failure_analyzer import FailureClass, FailureClassification, NextRoute

RepairScope = Literal[
    "no_repair_possible",
    "entry_logic",
    "exit_logic",
    "stoploss",
    "roi",
    "position_sizing",
    "entry_parameter",
    "final_reject",
]


@dataclass
class RepairPlan:
    scope: RepairScope = "no_repair_possible"
    failure_class: FailureClass | None = None
    next_route: NextRoute = "none_needed"
    max_iterations: int = 3
    iteration_used: int = 0
    iterations_remaining: int = 3
    can_repair: bool = False
    reason: str = ""


_SCOPE_MAP: dict[FailureClass, RepairScope] = {
    "data_quality_failed": "no_repair_possible",
    "backtest_failed": "no_repair_possible",
    "no_trades": "entry_logic",
    "too_few_trades": "entry_parameter",
    "negative_expectancy": "stoploss",
    "high_drawdown": "stoploss",
    "weak_profit_factor": "exit_logic",
    "weak_sharpe": "entry_parameter",
    "weak_win_rate": "entry_logic",
    "multiple_metric_failure": "no_repair_possible",
}


def build_repair_plan(
    classification: FailureClassification,
    spec: Any = None,
) -> RepairPlan:
    """Build a repair permission plan from a failure classification.

    Parameters
    ----------
    classification : FailureClassification
        The output of analyze_gate_failure().
    spec : StrategySpec | None
        Optional StrategySpec to read iteration_count and max_iterations.

    Returns
    -------
    RepairPlan
        A deterministic plan defining what AI is allowed to change.
    """
    fc = classification.primary_class
    route = classification.next_route
    max_it = 3
    it_used = 0

    if spec is not None:
        max_it = getattr(spec, "max_iterations", 3)
        it_used = getattr(spec, "iteration_count", 0)

    remaining = max(0, max_it - it_used)

    if fc is None:
        return RepairPlan(
            scope="no_repair_possible",
            failure_class=fc,
            next_route=route,
            max_iterations=max_it,
            iteration_used=it_used,
            iterations_remaining=remaining,
            can_repair=False,
            reason="No failure to repair (gate passed).",
        )

    if it_used >= max_it:
        return RepairPlan(
            scope="final_reject",
            failure_class=fc,
            next_route=route,
            max_iterations=max_it,
            iteration_used=it_used,
            iterations_remaining=remaining,
            can_repair=False,
            reason=f"Max iterations ({max_it}) reached. No further repairs allowed.",
        )

    if fc == "no_trades" and it_used >= 1:
        return RepairPlan(
            scope="final_reject",
            failure_class=fc,
            next_route=route,
            max_iterations=max_it,
            iteration_used=it_used,
            iterations_remaining=remaining,
            can_repair=False,
            reason="no_trades already attempted once. Final reject.",
        )

    scope = _SCOPE_MAP.get(fc, "no_repair_possible")
    can_repair = scope not in ("no_repair_possible", "final_reject")
    reason = _build_reason(fc, scope)

    return RepairPlan(
        scope=scope,
        failure_class=fc,
        next_route=route,
        max_iterations=max_it,
        iteration_used=it_used,
        iterations_remaining=remaining,
        can_repair=can_repair,
        reason=reason,
    )


def _build_reason(fc: FailureClass, scope: RepairScope) -> str:
    reasons: dict[RepairScope, str] = {
        "no_repair_possible": f"{fc} is not repairable by strategy repair.",
        "entry_logic": "One entry condition or indicator param may be changed.",
        "exit_logic": "One exit condition or trailing stop toggle may be changed.",
        "stoploss": "Stoploss value may be adjusted (must stay in [-0.50, -0.01]).",
        "roi": "One ROI table entry may be added/removed/changed.",
        "position_sizing": "One position sizing field may be changed.",
        "entry_parameter": "One indicator parameter value may be changed.",
        "final_reject": "No repair allowed — iteration limit or unrecoverable.",
    }
    return reasons.get(scope, f"No repair scope defined for {fc}.")
