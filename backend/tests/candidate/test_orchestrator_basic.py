"""Basic orchestrator tests - happy path, early exits, and progress sink."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.strategy_spec import StrategySpec
from backend.services.candidate.models import CandidateConfig
from backend.services.execution.backtest_gate import BacktestGateResult
from backend.services.candidate.orchestrator import evaluate_candidate
from backend.services.candidate.run_manager import CandidateRunManager
from backend.services.strategy.strategy_code_writer import SaveResult


def _save_result(errors=None, path=None):
    return SaveResult(
        errors=errors or [],
        path=Path(path) if path else None,
        warnings=[],
    )


@pytest.mark.asyncio
async def test_happy_path_all_gates_pass():
    """Happy path: render -> save -> data quality -> backtest gate all pass."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [],
        "warnings": [],
        "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(
        path="/tmp/ud/strategies/rendered/test_strat/test_strat.py",
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

    spec = StrategySpec(
        name="test_strat",
        trading_style="trend_following",
        timeframe="1h",
    )
    config = CandidateConfig(
        timerange="20230101-20231231",
        timeframe="1h",
        pairs=["BTC/USDT"],
        user_data_dir="/tmp/user_data",
    )

    verdict = await evaluate_candidate(spec, config, deps={
        "render_strategy": mock_render,
        "save_rendered_strategy": mock_save,
        "check_data_quality": mock_quality,
        "run_backtest_gate": mock_backtest,
    })

    assert verdict.passed is False
    assert verdict.failure_reason == "individual_pair_sweep"
    assert len(verdict.gate_results) == 5

    gates = {g.gate_name: g for g in verdict.gate_results}
    assert gates["render_strategy"].passed is True
    assert gates["save_working_copy"].passed is True
    assert gates["data_quality"].passed is True
    assert gates["backtest_gate"].passed is True
    assert gates["individual_pair_sweep"].passed is False

    mock_render.assert_called_once_with(spec)
    mock_save.assert_called_once()
    mock_quality.assert_called_once()
    mock_backtest.assert_called_once()


@pytest.mark.asyncio
async def test_progress_sink_updates_gate_snapshots():
    """Progress sink updates Candidate run gates without real backtests."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [],
        "warnings": [],
        "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(path="/tmp/path.py"))
    mock_quality = MagicMock(return_value={
        "passed": True,
        "errors": [],
        "warnings": [],
        "details": {},
    })
    mock_backtest = MagicMock(return_value=BacktestGateResult(
        gate_status="passed",
        run_id="gate_123",
        metrics={"total_trades": 20, "profit_factor": 1.2},
        failures=[], errors=[], warnings=[],
    ))

    spec = StrategySpec(
        name="progress_strat",
        trading_style="trend_following",
        timeframe="1h",
    )
    config = CandidateConfig(
        timerange="20230101-20231231",
        timeframe="1h",
        pairs=["BTC/USDT"],
        user_data_dir="/tmp/user_data",
    )
    manager = CandidateRunManager()
    run = manager.create_run(spec, config)
    manager.mark_running(run.run_id)

    verdict = await evaluate_candidate(spec, config, deps={
        "render_strategy": mock_render,
        "save_rendered_strategy": mock_save,
        "check_data_quality": mock_quality,
        "run_backtest_gate": mock_backtest,
    }, progress_sink=lambda update: manager.update_gate(run.run_id, update))
    manager.mark_completed(run.run_id, verdict)

    snapshot = manager.get_run(run.run_id)
    assert snapshot is not None
    assert snapshot.status == "completed"
    gates = {gate.gate_name: gate for gate in snapshot.gates}
    assert gates["render_strategy"].status == "passed"
    assert gates["save_working_copy"].status == "passed"
    assert gates["data_quality"].status == "passed"
    assert gates["backtest_gate"].status == "passed"
    assert gates["backtest_gate"].metrics["profit_factor"] == 1.2
    assert gates["individual_pair_sweep"].status == "failed"
    assert gates["portfolio_backtest"].status == "skipped"


@pytest.mark.asyncio
async def test_render_failure_early_exit():
    """Render failure returns early with render_strategy gate failed."""
    mock_render = MagicMock(return_value={
        "source": None,
        "errors": ["Invalid trading_style: unknown"],
        "warnings": [],
        "template": None,
    })

    config = CandidateConfig(
        timerange="20230101-20231231",
        timeframe="1h",
        pairs=["BTC/USDT"],
        user_data_dir="/tmp/ud",
    )
    spec = StrategySpec(
        name="test",
        trading_style="trend_following",
        timeframe="1h",
    )

    verdict = await evaluate_candidate(
        spec, config,
        deps={"render_strategy": mock_render},
    )

    assert verdict.passed is False
    assert verdict.failure_reason == "render_strategy"
    assert len(verdict.gate_results) == 1
    assert verdict.gate_results[0].gate_name == "render_strategy"
    assert verdict.gate_results[0].passed is False
    mock_render.assert_called_once_with(spec)


@pytest.mark.asyncio
async def test_save_failure_early_exit():
    """Save failure returns early with save_working_copy gate failed."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [],
        "warnings": [],
        "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(errors=["Write failed"]))

    config = CandidateConfig(
        timerange="20230101-20231231",
        timeframe="1h",
        pairs=["BTC/USDT"],
        user_data_dir="/tmp/ud",
    )
    spec = StrategySpec(
        name="test",
        trading_style="trend_following",
        timeframe="1h",
    )

    verdict = await evaluate_candidate(
        spec, config,
        deps={
            "render_strategy": mock_render,
            "save_rendered_strategy": mock_save,
        },
    )

    assert verdict.passed is False
    assert verdict.failure_reason == "save_working_copy"
    assert len(verdict.gate_results) == 2
    assert verdict.gate_results[0].gate_name == "render_strategy"
    assert verdict.gate_results[0].passed is True
    assert verdict.gate_results[1].gate_name == "save_working_copy"
    assert verdict.gate_results[1].passed is False
    mock_render.assert_called_once_with(spec)
    mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_data_quality_failure_early_exit():
    """Data quality failure returns early with data_quality gate failed."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [],
        "warnings": [],
        "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(
        path="/tmp/some/path.py",
    ))
    mock_quality = MagicMock(return_value={
        "passed": False,
        "errors": ["MISSING_DATA_FILE: BTC/USDT"],
        "warnings": [],
        "details": {
            "BTC/USDT": {
                "exists": False,
                "data_file": "/tmp/ud/data/binance/BTC_USDT-1h.feather",
            },
        },
    })
    mock_backtest = MagicMock()

    config = CandidateConfig(
        timerange="20230101-20231231",
        timeframe="1h",
        pairs=["BTC/USDT"],
        user_data_dir="/tmp/ud",
    )
    spec = StrategySpec(
        name="test",
        trading_style="trend_following",
        timeframe="1h",
    )

    verdict = await evaluate_candidate(
        spec, config,
        deps={
            "render_strategy": mock_render,
            "save_rendered_strategy": mock_save,
            "check_data_quality": mock_quality,
            "run_backtest_gate": mock_backtest,
        },
    )

    assert verdict.passed is False
    assert verdict.failure_reason == "data_quality"
    assert len(verdict.gate_results) == 3
    assert verdict.gate_results[0].gate_name == "render_strategy"
    assert verdict.gate_results[0].passed is True
    assert verdict.gate_results[1].gate_name == "save_working_copy"
    assert verdict.gate_results[1].passed is True
    assert verdict.gate_results[2].gate_name == "data_quality"
    assert verdict.gate_results[2].passed is False
    assert verdict.gate_results[2].details["missing_pairs"] == ["BTC/USDT"]
    assert verdict.gate_results[2].details["timeframe"] == "1h"
    assert "freqtrade download-data" in verdict.gate_results[2].details["download_command_hint"]
    mock_render.assert_called_once_with(spec)
    mock_save.assert_called_once()
    mock_quality.assert_called_once()
    mock_backtest.assert_not_called()
