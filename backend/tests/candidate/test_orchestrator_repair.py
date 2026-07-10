"""Repair loop orchestrator tests."""

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
async def test_backtest_fail_triggers_failure_analyzer():
    """Backtest fail adds failure_analyzer and repair_plan gates."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [], "warnings": [], "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(path="/tmp/path.py"))
    mock_quality = MagicMock(return_value={
        "passed": True, "errors": [], "warnings": [], "details": {},
    })
    mock_backtest = MagicMock(return_value=BacktestGateResult(
        gate_status="failed",
        run_id="gate_002",
        metrics={"total_trades": 5, "win_rate_pct": 30.0, "profit_factor": 0.8,
                 "max_drawdown_pct": 35.0, "expectancy": -0.2, "sharpe_ratio": 0.2},
        failures=["MIN_TRADES", "MIN_WIN_RATE"],
        errors=[], warnings=[],
    ))

    spec = StrategySpec(name="strat_b", trading_style="trend_following", timeframe="1h")
    config = CandidateConfig(
        timerange="20230101-20231231", timeframe="1h",
        pairs=["BTC/USDT"], user_data_dir="/tmp/ud",
    )

    verdict = await evaluate_candidate(spec, config, deps={
        "render_strategy": mock_render,
        "save_rendered_strategy": mock_save,
        "check_data_quality": mock_quality,
        "run_backtest_gate": mock_backtest,
    })

    assert verdict.passed is False
    assert len(verdict.gate_results) == 6
    gates = {g.gate_name: g for g in verdict.gate_results}
    assert gates["backtest_gate"].passed is False
    assert gates["failure_analyzer"].passed is False
    assert gates["failure_analyzer"].details["primary_class"] is not None
    assert "repair_plan" in gates
    mock_backtest.assert_called_once()


@pytest.mark.asyncio
async def test_repair_plan_can_repair_true_recorded_not_executed():
    """can_repair=True is recorded in repair_plan gate but repair is not executed."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [], "warnings": [], "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(path="/tmp/path.py"))
    mock_quality = MagicMock(return_value={
        "passed": True, "errors": [], "warnings": [], "details": {},
    })
    mock_backtest = MagicMock(return_value=BacktestGateResult(
        gate_status="failed",
        run_id="gate_003",
        metrics={"total_trades": 5, "win_rate_pct": 30.0, "profit_factor": 0.8,
                 "max_drawdown_pct": 35.0, "expectancy": -0.2, "sharpe_ratio": 0.2},
        failures=["MIN_TRADES"],
        errors=[], warnings=[],
    ))

    spec = StrategySpec(name="strat_c", trading_style="trend_following", timeframe="1h")
    config = CandidateConfig(
        timerange="20230101-20231231", timeframe="1h",
        pairs=["BTC/USDT"], user_data_dir="/tmp/ud",
    )

    verdict = await evaluate_candidate(spec, config, deps={
        "render_strategy": mock_render,
        "save_rendered_strategy": mock_save,
        "check_data_quality": mock_quality,
        "run_backtest_gate": mock_backtest,
    })

    gates = {g.gate_name: g for g in verdict.gate_results}
    rp = gates["repair_plan"]
    assert rp.passed is True
    assert rp.details["can_repair"] is True
    assert verdict.passed is False


@pytest.mark.asyncio
async def test_repair_plan_can_repair_false_final_failure():
    """can_repair=False returns final failure with repair_plan gate passed=False."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [], "warnings": [], "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(path="/tmp/path.py"))
    mock_quality = MagicMock(return_value={
        "passed": True, "errors": [], "warnings": [], "details": {},
    })
    mock_backtest = MagicMock(return_value=BacktestGateResult(
        gate_status="backtest_failed",
        run_id="gate_004",
        metrics={},
        failures=[], errors=["Freqtrade exited with code 1"], warnings=[],
    ))

    spec = StrategySpec(name="strat_d", trading_style="trend_following", timeframe="1h")
    config = CandidateConfig(
        timerange="20230101-20231231", timeframe="1h",
        pairs=["BTC/USDT"], user_data_dir="/tmp/ud",
    )

    verdict = await evaluate_candidate(spec, config, deps={
        "render_strategy": mock_render,
        "save_rendered_strategy": mock_save,
        "check_data_quality": mock_quality,
        "run_backtest_gate": mock_backtest,
    })

    assert verdict.passed is False
    gates = {g.gate_name: g for g in verdict.gate_results}
    assert gates["repair_plan"].passed is False
    assert gates["repair_plan"].details["can_repair"] is False
    assert verdict.failure_reason is not None


@pytest.mark.asyncio
async def test_repair_loop_success_proceeds_to_pair_workflow():
    """Backtest fails -> repair succeeds -> rerun backtest passes -> pair workflow."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [], "warnings": [], "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(path="/tmp/path.py"))
    mock_quality = MagicMock(return_value={
        "passed": True, "errors": [], "warnings": [], "details": {},
    })
    mock_backtest = MagicMock(side_effect=[
        BacktestGateResult(
            gate_status="failed", run_id="gate_001",
            metrics={"total_trades": 5, "win_rate_pct": 30.0, "profit_factor": 0.8,
                     "max_drawdown_pct": 35.0, "expectancy": -0.2, "sharpe_ratio": 0.2},
            failures=["MIN_TRADES"], errors=[], warnings=[],
        ),
        BacktestGateResult(
            gate_status="passed", run_id="gate_002",
            metrics={"total_trades": 20, "win_rate_pct": 55.0, "profit_factor": 1.2},
            failures=[], errors=[], warnings=[],
        ),
    ])
    mock_analyzer = MagicMock(return_value=MagicMock(
        primary_class="too_few_trades",
        next_route="extend_timerange_or_discard",
        failed_metrics=["MIN_TRADES"],
    ))
    mock_repair_plan = MagicMock(return_value=MagicMock(
        scope="entry_parameter",
        can_repair=True,
        reason="Mock repair reason",
    ))
    mock_ollama = MagicMock()
    mock_ask_ai = AsyncMock(return_value={
        "repair_scope": "entry_parameter",
        "change": {"indicator": "rsi", "parameter": "period", "new_value": 10},
        "reasoning": "Increase RSI period to generate more signals",
    })
    new_spec = StrategySpec(
        name="repaired_strat", trading_style="trend_following",
        timeframe="1h", iteration_count=1, max_open_trades=4,
    )
    mock_apply = MagicMock(return_value=(new_spec, []))
    mock_pair_sweep = AsyncMock(return_value=[
        {"pair": "ETH/USDT", "status": "passed", "score": 0.5, "total_trades": 10,
         "profit_factor": 1.2, "win_rate": 60.0, "max_drawdown": 10.0, "expectancy": 0.1},
    ])
    mock_portfolio = MagicMock(return_value={
        "status": "passed", "failure_reasons": [], "run_id": "portfolio_001",
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
        "verdict": "approved", "approved_pairs": ["ETH/USDT"],
        "approved_count": 1, "rejection_reason": None, "combined_scores": [],
    })

    spec = StrategySpec(name="rep_test", trading_style="trend_following", timeframe="1h")
    config = CandidateConfig(
        timerange="20230101-20231231", timeframe="1h",
        pairs=["ETH/USDT"], user_data_dir="/tmp/ud",
    )

    verdict = await evaluate_candidate(spec, config, deps={
        "render_strategy": mock_render,
        "save_rendered_strategy": mock_save,
        "check_data_quality": mock_quality,
        "run_backtest_gate": mock_backtest,
        "analyze_gate_failure": mock_analyzer,
        "build_repair_plan": mock_repair_plan,
        "ollama_client": mock_ollama,
        "ask_ai_for_repair_proposal": mock_ask_ai,
        "apply_repair_proposal": mock_apply,
        "run_individual_pair_sweep": mock_pair_sweep,
        "run_portfolio_backtest": mock_portfolio,
        "decide_final_pair_set": mock_decision,
    })

    assert verdict.passed is True
    assert verdict.failure_reason is None
    assert len(verdict.repair_attempts) == 1
    assert verdict.repair_attempts[0].outcome == "applied_and_retested"
    assert verdict.repair_attempts[0].scope == "entry_parameter"
    assert verdict.final_pair_set == ["ETH/USDT"]
    assert verdict.portfolio_metrics["profit_factor"] == 1.2

    # Gate dedup: backtest_gate appears only once (the latest passed=True)
    assert len(verdict.gate_results) == 9
    gates = {g.gate_name: g for g in verdict.gate_results}
    assert gates["backtest_gate"].passed is True

    assert mock_render.call_count == 2
    mock_render.assert_any_call(spec)
    mock_render.assert_any_call(new_spec)
    assert mock_save.call_count == 2
    assert mock_quality.call_count == 2
    assert mock_backtest.call_count == 2
    assert mock_backtest.call_args_list[0].kwargs["max_open_trades"] == spec.max_open_trades
    assert mock_backtest.call_args_list[1].kwargs["max_open_trades"] == new_spec.max_open_trades
    mock_ask_ai.assert_awaited_once()
    mock_apply.assert_called_once()
    mock_pair_sweep.assert_awaited_once()
    mock_portfolio.assert_called_once()
    mock_decision.assert_called_once()


@pytest.mark.asyncio
async def test_repair_loop_missing_ollama_client():
    """No ollama_client in deps -> stops with repair_ai_unavailable."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [], "warnings": [], "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(path="/tmp/path.py"))
    mock_quality = MagicMock(return_value={
        "passed": True, "errors": [], "warnings": [], "details": {},
    })
    mock_backtest = MagicMock(return_value=BacktestGateResult(
        gate_status="failed", run_id="gate_001",
        metrics={"total_trades": 5, "win_rate_pct": 30.0, "profit_factor": 0.8},
        failures=["MIN_TRADES"], errors=[], warnings=[],
    ))

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
    })

    assert verdict.passed is False
    assert verdict.failure_reason == "repair_ai_unavailable"
    assert len(verdict.repair_attempts) == 0


@pytest.mark.asyncio
async def test_repair_loop_ai_returns_none():
    """AI returns None -> stops with ai_returned_none attempt."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [], "warnings": [], "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(path="/tmp/path.py"))
    mock_quality = MagicMock(return_value={
        "passed": True, "errors": [], "warnings": [], "details": {},
    })
    mock_backtest = MagicMock(return_value=BacktestGateResult(
        gate_status="failed", run_id="gate_001",
        metrics={"total_trades": 5, "win_rate_pct": 30.0, "profit_factor": 0.8},
        failures=["MIN_TRADES"], errors=[], warnings=[],
    ))
    mock_analyzer = MagicMock(return_value=MagicMock(
        primary_class="too_few_trades",
        next_route="extend_timerange_or_discard",
        failed_metrics=["MIN_TRADES"],
    ))
    mock_repair_plan = MagicMock(return_value=MagicMock(
        scope="entry_parameter",
        can_repair=True,
        reason="Mock repair reason",
    ))
    mock_ollama = MagicMock()
    mock_ask_ai = AsyncMock(return_value=None)

    spec = StrategySpec(name="strat_b", trading_style="trend_following", timeframe="1h")
    config = CandidateConfig(
        timerange="20230101-20231231", timeframe="1h",
        pairs=["BTC/USDT"], user_data_dir="/tmp/ud",
    )

    verdict = await evaluate_candidate(spec, config, deps={
        "render_strategy": mock_render,
        "save_rendered_strategy": mock_save,
        "check_data_quality": mock_quality,
        "run_backtest_gate": mock_backtest,
        "analyze_gate_failure": mock_analyzer,
        "build_repair_plan": mock_repair_plan,
        "ollama_client": mock_ollama,
        "ask_ai_for_repair_proposal": mock_ask_ai,
    })

    assert verdict.passed is False
    assert len(verdict.repair_attempts) == 1
    assert verdict.repair_attempts[0].outcome == "ai_returned_none"
    assert verdict.repair_attempts[0].scope == "entry_parameter"
    mock_ask_ai.assert_awaited_once()
    mock_render.assert_called_once()  # repair render never called


@pytest.mark.asyncio
async def test_repair_loop_max_iterations_exhausted():
    """Repair exhausted -> max iterations reached -> final failure."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [], "warnings": [], "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(path="/tmp/path.py"))
    mock_quality = MagicMock(return_value={
        "passed": True, "errors": [], "warnings": [], "details": {},
    })
    mock_backtest = MagicMock(return_value=BacktestGateResult(
        gate_status="failed", run_id="gate_fail",
        metrics={"total_trades": 5, "win_rate_pct": 30.0, "profit_factor": 0.8},
        failures=["MIN_TRADES"], errors=[], warnings=[],
    ))
    mock_analyzer = MagicMock(return_value=MagicMock(
        primary_class="too_few_trades",
        next_route="extend_timerange_or_discard",
        failed_metrics=["MIN_TRADES"],
    ))
    mock_repair_plan = MagicMock(return_value=MagicMock(
        scope="entry_parameter",
        can_repair=True,
        reason="Mock repair reason",
    ))
    mock_ollama = MagicMock()
    mock_ask_ai = AsyncMock(return_value={
        "repair_scope": "entry_parameter",
        "change": {"indicator": "rsi", "parameter": "period", "new_value": 10},
        "reasoning": "Increase RSI period to generate more signals",
    })
    def make_spec():
        return StrategySpec(
            name="rep_iter", trading_style="trend_following",
            timeframe="1h", iteration_count=99,
        )
    mock_apply = MagicMock(return_value=(make_spec(), []))

    spec = StrategySpec(name="strat_e", trading_style="trend_following", timeframe="1h",
                        max_iterations=1)
    config = CandidateConfig(
        timerange="20230101-20231231", timeframe="1h",
        pairs=["BTC/USDT"], user_data_dir="/tmp/ud",
        max_repair_iterations=1,
    )

    verdict = await evaluate_candidate(spec, config, deps={
        "render_strategy": mock_render,
        "save_rendered_strategy": mock_save,
        "check_data_quality": mock_quality,
        "run_backtest_gate": mock_backtest,
        "analyze_gate_failure": mock_analyzer,
        "build_repair_plan": mock_repair_plan,
        "ollama_client": mock_ollama,
        "ask_ai_for_repair_proposal": mock_ask_ai,
        "apply_repair_proposal": mock_apply,
    })

    assert verdict.passed is False
    assert len(verdict.repair_attempts) == 1
    assert verdict.repair_attempts[0].outcome == "applied_and_retested"


@pytest.mark.asyncio
async def test_repair_not_allowed_fallback():
    """When can_repair=False and primary_class is None, failure_reason is repair_not_allowed."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [], "warnings": [], "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(path="/tmp/ud/strategies/rendered/strat.py"))
    mock_quality = MagicMock(return_value={
        "passed": True, "errors": [], "warnings": [], "details": {},
    })
    mock_backtest = MagicMock(return_value=BacktestGateResult(
        gate_status="failed", run_id="g1",
        metrics={"total_trades": 5, "win_rate_pct": 30.0, "profit_factor": 0.8},
        failures=["MIN_TRADES"], errors=[], warnings=[],
    ))
    mock_analyzer = MagicMock(return_value=MagicMock(
        primary_class=None,
        next_route="unknown",
        failed_metrics=[],
    ))
    mock_repair = MagicMock(return_value=MagicMock(
        scope="unknown", can_repair=False, reason="Cannot repair",
    ))

    spec = StrategySpec(name="strat_x", trading_style="trend_following", timeframe="1h")
    config = CandidateConfig(
        timerange="20230101-20231231", timeframe="1h",
        pairs=["BTC/USDT"], user_data_dir="/tmp/ud",
    )

    verdict = await evaluate_candidate(spec, config, deps={
        "render_strategy": mock_render,
        "save_rendered_strategy": mock_save,
        "check_data_quality": mock_quality,
        "run_backtest_gate": mock_backtest,
        "analyze_gate_failure": mock_analyzer,
        "build_repair_plan": mock_repair,
    })

    assert verdict.passed is False
    assert verdict.failure_reason == "repair_not_allowed"
