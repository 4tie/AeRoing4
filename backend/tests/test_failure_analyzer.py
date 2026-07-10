"""Tests for backtest gate failure analyzer."""

from __future__ import annotations

from backend.services.execution.backtest_gate import BacktestGateResult
from backend.services.execution.failure_analyzer import analyze_gate_failure


def test_analyzer_passed_gate():
    result = BacktestGateResult(
        gate_status="passed",
        metrics={
            "total_trades": 50,
            "win_rate_pct": 55.0,
            "profit_factor": 1.5,
            "max_drawdown_pct": 15.0,
            "expectancy": 10.0,
            "sharpe_ratio": 1.0,
        },
    )
    c = analyze_gate_failure(result)
    assert c.gate_passed is True
    assert c.primary_class is None
    assert c.next_route == "none_needed"
    assert len(c.secondary_classes) == 0


def test_analyzer_data_quality_failed():
    result = BacktestGateResult(
        gate_status="data_quality_failed",
        errors=["MISSING_DATA_FILE: BTC/USDT"],
    )
    c = analyze_gate_failure(result)
    assert c.gate_passed is False
    assert c.primary_class == "data_quality_failed"
    assert c.next_route == "check_data"


def test_analyzer_backtest_failed():
    result = BacktestGateResult(
        gate_status="backtest_failed",
        errors=["Freqtrade exited with code 1"],
    )
    c = analyze_gate_failure(result)
    assert c.gate_passed is False
    assert c.primary_class == "backtest_failed"
    assert c.next_route == "inspect_logs"


def test_analyzer_no_trades():
    result = BacktestGateResult(
        gate_status="failed",
        failures=["MIN_TRADES"],
        metrics={
            "total_trades": 0,
            "win_rate_pct": 55.0,
            "profit_factor": 1.5,
            "max_drawdown_pct": 15.0,
            "expectancy": 10.0,
            "sharpe_ratio": 1.0,
        },
    )
    c = analyze_gate_failure(result)
    assert c.primary_class == "no_trades"
    assert c.next_route == "discard_strategy"
    assert len(c.secondary_classes) == 0


def test_analyzer_no_trades_none_metric():
    result = BacktestGateResult(
        gate_status="failed",
        failures=[],
        metrics={},
    )
    c = analyze_gate_failure(result)
    assert c.primary_class == "no_trades"
    assert c.next_route == "discard_strategy"


def test_analyzer_too_few_trades():
    result = BacktestGateResult(
        gate_status="failed",
        failures=["MIN_TRADES"],
        metrics={
            "total_trades": 3,
            "win_rate_pct": 55.0,
            "profit_factor": 1.5,
            "max_drawdown_pct": 15.0,
            "expectancy": 10.0,
            "sharpe_ratio": 1.0,
        },
    )
    c = analyze_gate_failure(result)
    assert c.primary_class == "too_few_trades"
    assert c.next_route == "extend_timerange_or_discard"
    assert len(c.secondary_classes) == 0


def test_analyzer_negative_expectancy():
    result = BacktestGateResult(
        gate_status="failed",
        failures=["POSITIVE_EXPECTANCY"],
        metrics={
            "total_trades": 20,
            "win_rate_pct": 55.0,
            "profit_factor": 1.5,
            "max_drawdown_pct": 15.0,
            "expectancy": -5.0,
            "sharpe_ratio": 1.0,
        },
    )
    c = analyze_gate_failure(result)
    assert c.primary_class == "negative_expectancy"
    assert c.next_route == "adjust_stoploss_or_roi"
    assert len(c.secondary_classes) == 0


def test_analyzer_high_drawdown():
    result = BacktestGateResult(
        gate_status="failed",
        failures=["MAX_DRAWDOWN"],
        metrics={
            "total_trades": 20,
            "win_rate_pct": 55.0,
            "profit_factor": 1.5,
            "max_drawdown_pct": 45.0,
            "expectancy": 10.0,
            "sharpe_ratio": 1.0,
        },
    )
    c = analyze_gate_failure(result)
    assert c.primary_class == "high_drawdown"
    assert c.next_route == "tighten_stoploss_or_position_sizing"
    assert len(c.secondary_classes) == 0


def test_analyzer_weak_profit_factor():
    result = BacktestGateResult(
        gate_status="failed",
        failures=["MIN_PROFIT_FACTOR"],
        metrics={
            "total_trades": 20,
            "win_rate_pct": 55.0,
            "profit_factor": 1.01,
            "max_drawdown_pct": 15.0,
            "expectancy": 10.0,
            "sharpe_ratio": 1.0,
        },
    )
    c = analyze_gate_failure(result)
    assert c.primary_class == "weak_profit_factor"
    assert c.next_route == "adjust_exit_conditions"
    assert len(c.secondary_classes) == 0


def test_analyzer_weak_sharpe():
    result = BacktestGateResult(
        gate_status="failed",
        failures=["MIN_SHARPE"],
        metrics={
            "total_trades": 20,
            "win_rate_pct": 55.0,
            "profit_factor": 1.5,
            "max_drawdown_pct": 15.0,
            "expectancy": 10.0,
            "sharpe_ratio": 0.1,
        },
    )
    c = analyze_gate_failure(result)
    assert c.primary_class == "weak_sharpe"
    assert c.next_route == "review_entry_consistency"
    assert len(c.secondary_classes) == 0


def test_analyzer_weak_win_rate():
    result = BacktestGateResult(
        gate_status="failed",
        failures=["MIN_WIN_RATE"],
        metrics={
            "total_trades": 20,
            "win_rate_pct": 25.0,
            "profit_factor": 1.5,
            "max_drawdown_pct": 15.0,
            "expectancy": 10.0,
            "sharpe_ratio": 1.0,
        },
    )
    c = analyze_gate_failure(result)
    assert c.primary_class == "weak_win_rate"
    assert c.next_route == "review_entry_logic"
    assert len(c.secondary_classes) == 0


def test_analyzer_multiple_metric_failure():
    result = BacktestGateResult(
        gate_status="failed",
        failures=["POSITIVE_EXPECTANCY", "MAX_DRAWDOWN", "MIN_SHARPE"],
        metrics={
            "total_trades": 20,
            "win_rate_pct": 55.0,
            "profit_factor": 1.5,
            "max_drawdown_pct": 45.0,
            "expectancy": -5.0,
            "sharpe_ratio": 0.1,
        },
    )
    c = analyze_gate_failure(result)
    assert c.primary_class == "multiple_metric_failure"
    assert c.next_route == "fundamental_rework"
    assert len(c.secondary_classes) == 3
    assert "negative_expectancy" in c.secondary_classes
    assert "high_drawdown" in c.secondary_classes
    assert "weak_sharpe" in c.secondary_classes


def test_analyzer_no_trades_takes_priority():
    result = BacktestGateResult(
        gate_status="failed",
        failures=["MIN_TRADES", "MIN_WIN_RATE"],
        metrics={
            "total_trades": 0,
            "win_rate_pct": 25.0,
            "profit_factor": 1.5,
            "max_drawdown_pct": 15.0,
            "expectancy": -5.0,
            "sharpe_ratio": 1.0,
        },
    )
    c = analyze_gate_failure(result)
    assert c.primary_class == "no_trades"
    assert c.next_route == "discard_strategy"
    assert len(c.secondary_classes) == 0


def test_analyzer_too_few_trades_takes_priority():
    result = BacktestGateResult(
        gate_status="failed",
        failures=["MIN_TRADES", "MIN_WIN_RATE", "POSITIVE_EXPECTANCY"],
        metrics={
            "total_trades": 3,
            "win_rate_pct": 25.0,
            "profit_factor": 1.5,
            "max_drawdown_pct": 15.0,
            "expectancy": -5.0,
            "sharpe_ratio": 1.0,
        },
    )
    c = analyze_gate_failure(result)
    assert c.primary_class == "too_few_trades"
    assert c.next_route == "extend_timerange_or_discard"
    assert len(c.secondary_classes) == 0


def test_analyzer_expectancy_zero_is_failure():
    result = BacktestGateResult(
        gate_status="failed",
        failures=["POSITIVE_EXPECTANCY"],
        metrics={
            "total_trades": 20,
            "win_rate_pct": 55.0,
            "profit_factor": 1.5,
            "max_drawdown_pct": 15.0,
            "expectancy": 0.0,
            "sharpe_ratio": 1.0,
        },
    )
    c = analyze_gate_failure(result)
    assert c.primary_class == "negative_expectancy"
    assert c.next_route == "adjust_stoploss_or_roi"
    assert len(c.secondary_classes) == 0


def test_analyzer_none_metric_skipped():
    result = BacktestGateResult(
        gate_status="failed",
        failures=["MIN_WIN_RATE"],
        metrics={
            "total_trades": 20,
            "win_rate_pct": 25.0,
            "profit_factor": 1.5,
            "max_drawdown_pct": 15.0,
            "expectancy": 10.0,
            "sharpe_ratio": None,
        },
    )
    c = analyze_gate_failure(result)
    assert c.primary_class == "weak_win_rate"
    assert c.next_route == "review_entry_logic"
    assert len(c.secondary_classes) == 0
