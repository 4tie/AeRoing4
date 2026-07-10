"""Data quality and download orchestrator tests."""

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
async def test_data_quality_insufficient_history_downloads_and_retries_before_backtest():
    """Insufficient data triggers one download, retries data quality, then backtests."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [],
        "warnings": [],
        "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(path="/tmp/some/path.py"))
    initial_quality_failure = {
        "passed": False,
        "errors": ["INSUFFICIENT_HISTORY: BTC/USDT - data ends at 20240331, required 20240401"],
        "warnings": [],
        "details": {
            "BTC/USDT": {
                "exists": True,
                "covers_timerange": False,
                "start_date": "20240101",
                "end_date": "20240331",
                "data_file": "/tmp/ud/data/binance/BTC_USDT-5m.feather",
            },
        },
    }
    passing_quality = {
        "passed": True,
        "errors": [],
        "warnings": [],
        "details": {
            "BTC/USDT": {
                "exists": True,
                "covers_timerange": True,
                "start_date": "20240101",
                "end_date": "20240401",
            },
        },
    }
    mock_quality = MagicMock(side_effect=[initial_quality_failure, passing_quality])
    mock_download = MagicMock(return_value="download_123")
    mock_backtest = MagicMock(return_value=BacktestGateResult(
        gate_status="passed",
        run_id="gate_123",
        metrics={"total_trades": 20, "win_rate_pct": 55.0, "profit_factor": 1.2},
        failures=[],
        errors=[],
        warnings=[],
    ))

    config = CandidateConfig(
        timerange="20240101-20240401",
        timeframe="5m",
        pairs=["BTC/USDT"],
        user_data_dir="/tmp/ud",
    )
    spec = StrategySpec(name="test", trading_style="trend_following", timeframe="5m")

    verdict = await evaluate_candidate(
        spec,
        config,
        deps={
            "render_strategy": mock_render,
            "save_rendered_strategy": mock_save,
            "check_data_quality": mock_quality,
            "run_data_download": mock_download,
            "run_backtest_gate": mock_backtest,
        },
    )

    gates = {g.gate_name: g for g in verdict.gate_results}
    assert gates["data_download"].passed is True
    assert gates["data_download"].details["download_id"] == "download_123"
    assert gates["data_download"].details["prepend"] is False
    assert gates["data_quality"].passed is True
    assert gates["backtest_gate"].passed is True
    assert verdict.failure_reason == "individual_pair_sweep"
    assert mock_quality.call_count == 2
    mock_download.assert_called_once()
    download_request = mock_download.call_args.args[0]
    assert download_request.config_file == "config.json"
    assert download_request.timerange == "20240101-20240401"
    assert download_request.timeframes == ["5m"]
    assert download_request.pairs == ["BTC/USDT"]
    assert download_request.prepend is False
    mock_backtest.assert_called_once()


@pytest.mark.asyncio
async def test_data_quality_start_gap_download_uses_prepend():
    """When data starts after the requested start, auto-download uses prepend."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [],
        "warnings": [],
        "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(path="/tmp/some/path.py"))
    mock_quality = MagicMock(side_effect=[
        {
            "passed": False,
            "errors": [
                "INSUFFICIENT_HISTORY: BTC/USDT - data starts at 20240103, required 20240101",
            ],
            "warnings": [],
            "details": {
                "BTC/USDT": {
                    "exists": True,
                    "covers_timerange": False,
                    "start_date": "20240103",
                    "end_date": "20240401",
                },
            },
        },
        {
            "passed": True,
            "errors": [],
            "warnings": [],
            "details": {},
        },
    ])
    mock_download = MagicMock(return_value="download_123")
    mock_backtest = MagicMock(return_value=BacktestGateResult(
        gate_status="passed",
        run_id="gate_123",
        metrics={"total_trades": 20, "profit_factor": 1.2},
        failures=[],
        errors=[],
        warnings=[],
    ))

    config = CandidateConfig(
        timerange="20240101-20240401",
        timeframe="5m",
        pairs=["BTC/USDT"],
        user_data_dir="/tmp/ud",
    )
    spec = StrategySpec(name="test", trading_style="trend_following", timeframe="5m")

    await evaluate_candidate(
        spec,
        config,
        deps={
            "render_strategy": mock_render,
            "save_rendered_strategy": mock_save,
            "check_data_quality": mock_quality,
            "run_data_download": mock_download,
            "run_backtest_gate": mock_backtest,
        },
    )

    download_request = mock_download.call_args.args[0]
    assert download_request.prepend is True


@pytest.mark.asyncio
async def test_data_download_failure_stops_before_backtest():
    """A failed auto-download marks data_download failed and does not backtest."""
    mock_render = MagicMock(return_value={
        "source": "def test(): pass",
        "errors": [],
        "warnings": [],
        "template": "omni",
    })
    mock_save = MagicMock(return_value=_save_result(path="/tmp/some/path.py"))
    mock_quality = MagicMock(return_value={
        "passed": False,
        "errors": ["MISSING_DATA_FILE: BTC/USDT - file does not exist"],
        "warnings": [],
        "details": {
            "BTC/USDT": {
                "exists": False,
                "data_file": "/tmp/ud/data/binance/BTC_USDT-5m.feather",
            },
        },
    })
    mock_download = MagicMock(side_effect=RuntimeError("download failed"))
    mock_backtest = MagicMock()

    config = CandidateConfig(
        timerange="20240101-20240401",
        timeframe="5m",
        pairs=["BTC/USDT"],
        user_data_dir="/tmp/ud",
    )
    spec = StrategySpec(name="test", trading_style="trend_following", timeframe="5m")

    verdict = await evaluate_candidate(
        spec,
        config,
        deps={
            "render_strategy": mock_render,
            "save_rendered_strategy": mock_save,
            "check_data_quality": mock_quality,
            "run_data_download": mock_download,
            "run_backtest_gate": mock_backtest,
        },
    )

    gates = {g.gate_name: g for g in verdict.gate_results}
    assert verdict.passed is False
    assert verdict.failure_reason == "data_download"
    assert gates["data_download"].passed is False
    assert gates["data_download"].details["error"] == "download failed"
    assert "freqtrade download-data" in gates["data_download"].details["download_command_hint"]
    mock_download.assert_called_once()
    mock_backtest.assert_not_called()
