"""Portfolio and pair sweep orchestrator tests."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.strategy_spec import StrategySpec
from backend.services.candidate.models import CandidateConfig
from backend.services.execution.backtest_gate import BacktestGateResult
from backend.services.candidate.orchestrator import evaluate_candidate
from backend.services.strategy.strategy_code_writer import SaveResult


def _save_result(errors=None, path=None):
    return SaveResult(
        errors=errors or [],
        path=Path(path) if path else None,
        warnings=[],
    )


@pytest.mark.asyncio
async def test_injected_deps_prevent_real_calls():
    """When deps are injected, mocks are called instead of real helpers — full pipeline."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [],
        "warnings": [],
        "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(
        path="/tmp/path.py",
    ))
    mock_quality = MagicMock(return_value={
        "passed": True,
        "errors": [],
        "warnings": [],
        "details": {},
    })
    mock_backtest = MagicMock(return_value=BacktestGateResult(
        gate_status="passed",
        run_id="gate_123",
        metrics={"total_trades": 20, "win_rate_pct": 55.0, "profit_factor": 1.2},
        failures=[], errors=[], warnings=[],
    ))
    mock_pair_sweep = AsyncMock(return_value=[
        {"pair": "ETH/USDT", "status": "passed", "score": 0.5, "total_trades": 10,
         "profit_factor": 1.2, "win_rate": 60.0, "max_drawdown": 10.0, "expectancy": 0.1},
    ])
    mock_portfolio = MagicMock(return_value={
        "status": "passed",
        "failure_reasons": [],
        "run_id": "portfolio_001",
        "portfolio_summary": {
            "total_trades": 10, "profit_factor": 1.2, "win_rate_pct": 60.0,
            "max_drawdown_pct": 10.0, "sharpe_ratio": 1.0, "expectancy": 0.1,
            "profit_total_pct": 5.0, "profit_total_abs": 50.0,
        },
        "per_pair_metrics": [
            {"pair": "ETH/USDT", "trades": 10, "profit_factor": 2.0, "win_rate_pct": 60.0},
        ],
        "config_used": {"pairs_count": 1, "max_open_trades": 5},
    })
    mock_decision = MagicMock(return_value={
        "verdict": "approved",
        "approved_pairs": ["ETH/USDT"],
        "approved_count": 1,
        "rejection_reason": None,
        "combined_scores": [],
    })

    config = CandidateConfig(
        timerange="20230101-20231231",
        timeframe="5m",
        pairs=["ETH/USDT"],
        user_data_dir="/tmp/user_data",
        exchange="coinbase",
        max_repair_iterations=5,
        risk_profile="low",
    )
    spec = StrategySpec(
        name="mocktest",
        trading_style="momentum",
        timeframe="5m",
        max_open_trades=7,
    )

    verdict = await evaluate_candidate(
        spec, config,
        deps={
            "render_strategy": mock_render,
            "save_rendered_strategy": mock_save,
            "check_data_quality": mock_quality,
            "run_backtest_gate": mock_backtest,
            "run_individual_pair_sweep": mock_pair_sweep,
            "run_portfolio_backtest": mock_portfolio,
            "decide_final_pair_set": mock_decision,
        },
    )

    mock_render.assert_called_once_with(spec)
    mock_save.assert_called_once()
    mock_quality.assert_called_once()
    mock_backtest.assert_called_once()
    mock_pair_sweep.assert_awaited_once()
    mock_portfolio.assert_called_once()
    mock_decision.assert_called_once()
    assert mock_backtest.call_args.kwargs["max_open_trades"] == 7
    assert mock_portfolio.call_args.kwargs["max_open_trades"] == 7
    assert mock_decision.call_args.kwargs["risk_profile"] == "low"
    assert verdict.passed is True
    assert verdict.failure_reason is None
    assert verdict.final_pair_set == ["ETH/USDT"]
    assert verdict.portfolio_metrics["profit_factor"] == 1.2


@pytest.mark.asyncio
async def test_portfolio_backtest_failed_fails():
    """Portfolio backtest failure returns failed verdict with portfolio metrics."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [], "warnings": [], "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(path="/tmp/path.py"))
    mock_quality = MagicMock(return_value={
        "passed": True, "errors": [], "warnings": [], "details": {},
    })
    mock_backtest = MagicMock(return_value=BacktestGateResult(
        gate_status="passed",
        run_id="gate_001",
        metrics={"total_trades": 20, "win_rate_pct": 55.0, "profit_factor": 1.2},
        failures=[], errors=[], warnings=[],
    ))
    mock_pair_sweep = AsyncMock(return_value=[
        {"pair": "BTC/USDT", "status": "passed", "score": 0.5, "total_trades": 10,
         "profit_factor": 1.2, "win_rate": 60.0, "max_drawdown": 10.0, "expectancy": 0.1},
    ])
    mock_portfolio = MagicMock(return_value={
        "status": "failed",
        "failure_reasons": ["MIN_PROFIT_FACTOR"],
        "portfolio_summary": {
            "total_trades": 5, "profit_factor": 0.8, "win_rate_pct": 30.0,
            "max_drawdown_pct": 25.0,
        },
        "per_pair_metrics": [],
        "config_used": {"pairs_count": 1, "max_open_trades": 5},
    })

    spec = StrategySpec(name="strat_a", trading_style="trend_following", timeframe="1h")
    config = CandidateConfig(
        timerange="20230101-20231231", timeframe="1h",
        pairs=["BTC/USDT"], user_data_dir="/tmp/ud",
    )

    verdict = await evaluate_candidate(spec, config, deps={
        "render_strategy": mock_render,
        "save_rendered_strategy": mock_save,
        "check_data_quality": mock_quality,
        "run_backtest_gate": mock_backtest,
        "run_individual_pair_sweep": mock_pair_sweep,
        "run_portfolio_backtest": mock_portfolio,
    })

    assert verdict.passed is False
    assert verdict.failure_reason == "portfolio_backtest"
    assert len(verdict.gate_results) == 6
    assert verdict.portfolio_metrics["profit_factor"] == 0.8
    gates = {g.gate_name: g for g in verdict.gate_results}
    assert gates["portfolio_backtest"].passed is False
    mock_pair_sweep.assert_awaited_once()
    mock_portfolio.assert_called_once()


@pytest.mark.asyncio
async def test_pair_sweep_no_passed_pairs_fails():
    """Individual pair sweep returns no passed pairs -> failed verdict."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [], "warnings": [], "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(path="/tmp/path.py"))
    mock_quality = MagicMock(return_value={
        "passed": True, "errors": [], "warnings": [], "details": {},
    })
    mock_backtest = MagicMock(return_value=BacktestGateResult(
        gate_status="passed", run_id="gate_001",
        metrics={"total_trades": 20, "win_rate_pct": 55.0, "profit_factor": 1.2},
        failures=[], errors=[], warnings=[],
    ))
    mock_pair_sweep = AsyncMock(return_value=[
        {"pair": "BTC/USDT", "status": "failed", "score": 0.0, "total_trades": 0,
         "profit_factor": 0.5, "rejection_reason": "Profit factor 0.50 below 1.0"},
    ])

    spec = StrategySpec(name="strat_f", trading_style="trend_following", timeframe="1h")
    config = CandidateConfig(
        timerange="20230101-20231231", timeframe="1h",
        pairs=["BTC/USDT"], user_data_dir="/tmp/ud",
    )

    verdict = await evaluate_candidate(spec, config, deps={
        "render_strategy": mock_render,
        "save_rendered_strategy": mock_save,
        "check_data_quality": mock_quality,
        "run_backtest_gate": mock_backtest,
        "run_individual_pair_sweep": mock_pair_sweep,
    })

    assert verdict.passed is False
    assert verdict.failure_reason == "individual_pair_sweep"
    assert len(verdict.gate_results) == 5
    assert verdict.gate_results[4].gate_name == "individual_pair_sweep"
    assert verdict.gate_results[4].passed is False
    assert verdict.portfolio_metrics == {}
    assert verdict.final_pair_set == []
    mock_pair_sweep.assert_awaited_once()


@pytest.mark.asyncio
async def test_final_pair_decision_rejected_fails():
    """Final pair decision rejects -> failed verdict with rejection reason."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [], "warnings": [], "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(path="/tmp/path.py"))
    mock_quality = MagicMock(return_value={
        "passed": True, "errors": [], "warnings": [], "details": {},
    })
    mock_backtest = MagicMock(return_value=BacktestGateResult(
        gate_status="passed", run_id="gate_001",
        metrics={"total_trades": 20, "win_rate_pct": 55.0, "profit_factor": 1.2},
        failures=[], errors=[], warnings=[],
    ))
    mock_pair_sweep = AsyncMock(return_value=[
        {"pair": "BTC/USDT", "status": "passed", "score": 0.5, "total_trades": 10,
         "profit_factor": 1.2, "win_rate": 60.0, "max_drawdown": 10.0, "expectancy": 0.1},
        {"pair": "ETH/USDT", "status": "passed", "score": 0.3, "total_trades": 5,
         "profit_factor": 1.1, "win_rate": 55.0, "max_drawdown": 12.0, "expectancy": 0.05},
    ])
    mock_portfolio = MagicMock(return_value={
        "status": "passed",
        "failure_reasons": [],
        "run_id": "portfolio_001",
        "portfolio_summary": {
            "total_trades": 15, "profit_factor": 1.15, "win_rate_pct": 58.0,
            "max_drawdown_pct": 12.0, "sharpe_ratio": 0.8, "expectancy": 0.08,
            "profit_total_pct": 3.5, "profit_total_abs": 35.0,
        },
        "per_pair_metrics": [
            {"pair": "BTC/USDT", "trades": 10, "profit_factor": 2.0, "win_rate_pct": 60.0},
            {"pair": "ETH/USDT", "trades": 5, "profit_factor": 1.5, "win_rate_pct": 55.0},
        ],
        "config_used": {"pairs_count": 2, "max_open_trades": 5},
    })
    mock_decision = MagicMock(return_value={
        "verdict": "rejected",
        "approved_pairs": [],
        "approved_count": 0,
        "rejection_reason": "Only 1 pair(s) qualified (minimum 3)",
        "combined_scores": [],
    })

    spec = StrategySpec(name="strat_g", trading_style="trend_following", timeframe="1h")
    config = CandidateConfig(
        timerange="20230101-20231231", timeframe="1h",
        pairs=["BTC/USDT", "ETH/USDT"], user_data_dir="/tmp/ud",
    )

    verdict = await evaluate_candidate(spec, config, deps={
        "render_strategy": mock_render,
        "save_rendered_strategy": mock_save,
        "check_data_quality": mock_quality,
        "run_backtest_gate": mock_backtest,
        "run_individual_pair_sweep": mock_pair_sweep,
        "run_portfolio_backtest": mock_portfolio,
        "decide_final_pair_set": mock_decision,
    })

    assert verdict.passed is False
    assert verdict.failure_reason == "Only 1 pair(s) qualified (minimum 3)"
    assert len(verdict.gate_results) == 7
    assert verdict.final_pair_set == []
    gates = {g.gate_name: g for g in verdict.gate_results}
    assert gates["final_pair_decision"].passed is False
    assert gates["final_pair_decision"].details["rejection_reason"] == "Only 1 pair(s) qualified (minimum 3)"
    assert verdict.portfolio_metrics["profit_factor"] == 1.15
    mock_decision.assert_called_once()
