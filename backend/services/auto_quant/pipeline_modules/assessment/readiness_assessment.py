"""Readiness assessment and gate summary helpers."""

from __future__ import annotations

from ..state import PipelineState
from .data_helpers import _first_float


def _validate_existing_gate_summary(
    state: PipelineState,
    *,
    oos_result: dict,
    portfolio_result: dict,
    score_result: dict,
) -> dict:
    portfolio_metrics = portfolio_result.get("portfolio_metrics", {}) if isinstance(portfolio_result, dict) else {}
    oos = oos_result or {}
    sensitivity = state.sensitivity or {}
    monte_carlo = portfolio_result.get("monte_carlo", {}) if isinstance(portfolio_result, dict) else {}
    profit_giveback = portfolio_result.get("profit_giveback", {}) if isinstance(portfolio_result, dict) else {}
    per_pair = portfolio_result.get("per_pair_metrics", []) if isinstance(portfolio_result, dict) else []

    net_profit = _first_float(portfolio_metrics, "profit_total", "profit_total_abs")
    if net_profit is None:
        net_profit = _first_float(oos, "profit_total", "profit_total_abs")
    expectancy = _first_float(portfolio_metrics, "expectancy", "profit_mean", "profit_mean_pct")
    if expectancy is None:
        expectancy = _first_float(oos, "expectancy", "profit_mean", "profit_mean_pct")
    profit_factor = _first_float(portfolio_metrics, "profit_factor")
    if profit_factor is None:
        profit_factor = _first_float(oos, "profit_factor")
    max_drawdown = _first_float(portfolio_metrics, "max_drawdown_account")
    if max_drawdown is None:
        max_drawdown = _first_float(oos, "max_drawdown_account")
    trade_count = int(_first_float(portfolio_metrics, "total_trades") or _first_float(oos, "total_trades") or 0)

    wfo_passed = True
    wfo_reason = "WFO disabled"
    if state.wfo_enabled:
        if state.wfo_windows:
            failed_windows = [w for w in state.wfo_windows if not w.get("passed")]
            wfo_passed = not failed_windows
            wfo_reason = "All WFO windows passed" if wfo_passed else f"{len(failed_windows)} WFO window(s) failed"
        else:
            wfo_passed = False
            wfo_reason = state.wfo_skip_reason or "WFO enabled but no WFO windows were recorded"

    sensitivity_label = str(sensitivity.get("label", "") or "")
    sensitivity_passed = bool(sensitivity.get("passed")) and "sharp peak" not in sensitivity_label.lower()
    oos_profit = _first_float(oos, "profit_total")
    oos_trades = int(_first_float(oos, "total_trades") or 0)
    score_explanation = score_result.get("score_explanation", {}) if isinstance(score_result, dict) else {}
    trade_gate = score_explanation.get("trade_activity_gate", {}) if isinstance(score_explanation, dict) else {}
    required_trades = int(trade_gate.get("required_oos_trades") or 1)
    actual_trades_for_gate = int(trade_gate.get("actual_oos_trades") or trade_count or 0)

    checks = [
        {
            "name": "positive_net_profit",
            "passed": (net_profit or 0.0) > 0,
            "value": net_profit,
            "reason": "Final portfolio or OOS net profit must be positive.",
        },
        {
            "name": "positive_expectancy",
            "passed": (expectancy or 0.0) > 0,
            "value": expectancy,
            "reason": "Per-trade expectancy must be positive.",
        },
        {
            "name": "profit_factor",
            "passed": profit_factor is not None and profit_factor >= state.min_profit_factor,
            "value": profit_factor,
            "threshold": state.min_profit_factor,
            "reason": "Profit factor must pass configured threshold.",
        },
        {
            "name": "max_drawdown",
            "passed": max_drawdown is not None and max_drawdown <= state.max_drawdown_threshold,
            "value": max_drawdown,
            "threshold": state.max_drawdown_threshold,
            "reason": "Max drawdown must stay below configured threshold.",
        },
        {
            "name": "minimum_trade_count",
            "passed": actual_trades_for_gate >= required_trades,
            "value": actual_trades_for_gate,
            "threshold": required_trades,
            "reason": "Trade count must satisfy policy minimum for the selected timeframe.",
        },
        {
            "name": "oos_validation",
            "passed": oos_trades > 0 and oos_profit is not None and oos_profit >= state.min_oos_profit,
            "value": {"profit_total": oos_profit, "total_trades": oos_trades},
            "threshold": {"min_oos_profit": state.min_oos_profit},
            "reason": "Out-of-sample validation must pass.",
        },
        {
            "name": "wfo_consistency",
            "passed": wfo_passed,
            "value": {"enabled": state.wfo_enabled, "windows": len(state.wfo_windows or [])},
            "reason": wfo_reason,
        },
        {
            "name": "sensitivity",
            "passed": sensitivity_passed,
            "value": sensitivity,
            "reason": "Sensitivity must pass without Sharp Peak behavior.",
        },
        {
            "name": "portfolio_multi_pair",
            "passed": bool(per_pair) and bool(monte_carlo.get("passed", True)) and not profit_giveback.get("peak_to_loss_count"),
            "value": {
                "pairs": len(per_pair),
                "monte_carlo_passed": monte_carlo.get("passed"),
                "profit_giveback": profit_giveback,
            },
            "reason": "Portfolio or multi-pair validation must pass.",
        },
        {
            "name": "readiness_scoring",
            "passed": bool(score_result.get("accepted")),
            "value": {
                "validation_status": score_result.get("validation_status"),
                "readiness_label": score_result.get("readiness_label"),
                "score": score_result.get("score"),
            },
            "reason": "Readiness scoring must accept the strategy.",
        },
    ]

    failed = [c for c in checks if not c["passed"]]
    passed = [c for c in checks if c["passed"]]

    return {
        "checks": checks,
        "failed_checks": failed,
        "passed_checks": passed,
        "summary": {
            "net_profit": net_profit,
            "expectancy": expectancy,
            "profit_factor": profit_factor,
            "max_drawdown": max_drawdown,
            "trade_count": trade_count,
            "wfo_passed": wfo_passed,
            "sensitivity_passed": sensitivity_passed,
            "oos_profit": oos_profit,
            "oos_trades": oos_trades,
        },
        "recommendation": (
            "The selected strategy passed OOS, robustness, portfolio, risk, and scoring gates."
            if not failed else []
        ),
    }
