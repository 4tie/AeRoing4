"""Tests for run_individual_pair_sweep in PairSweepRunner.

Covers:
  - each pair is tested individually
  - max_open_trades is forced to 1
  - results are sorted by score descending
  - failed pair includes rejection reason
  - missing metric does not crash
  - backtest failure marks pair as backtest_failed
  - no PairSelectorService writes happen
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.models import (
    ParsedSummary,
    RunDetail,
    RunMetadata,
    RunRequest,
    RunStatus,
    RunType,
    SweepPhase,
)
from backend.services.execution.pair_sweep_runner import PairSweepRunner


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_now():
    return datetime.now(timezone.utc)


def _make_metadata(run_id: str, run_status: RunStatus) -> RunMetadata:
    return RunMetadata(
        run_id=run_id,
        strategy_name="TestStrategy",
        strategy_version_id="v1",
        parent_version_id=None,
        baseline_run_id=None,
        run_type=RunType.BASELINE,
        run_status=run_status,
        created_at=_make_now(),
        completed_at=_make_now() if run_status in (
            RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED
        ) else None,
        freqtrade_exit_code=0,
        config_file="/fake/config.json",
        timerange="20230101-20230601",
        timeframe="1h",
        pairs=["BTC/USDT"],
        max_open_trades=1,
    )


def _make_detail(run_id: str, **summary_overrides) -> RunDetail:
    defaults = {
        "total_trades": 50,
        "profit_factor": 2.5,
        "win_rate_pct": 55.0,
        "max_drawdown_pct": 12.0,
        "expectancy": 0.03,
        "net_profit_pct": 15.0,
    }
    defaults.update(summary_overrides)
    summary = ParsedSummary(
        run_id=run_id,
        starting_balance=1000.0,
        final_balance=1150.0,
        net_profit_currency=150.0,
        net_profit_pct=defaults["net_profit_pct"],
        total_trades=defaults["total_trades"],
        trades_per_day=2.0,
        win_rate_pct=defaults["win_rate_pct"],
            loss_rate_pct=100.0 - defaults["win_rate_pct"] if defaults["win_rate_pct"] is not None else None,
        max_drawdown_pct=defaults["max_drawdown_pct"],
        max_drawdown_currency=100.0,
        avg_trade_duration_minutes=120.0,
        profit_factor=defaults["profit_factor"],
        expectancy=defaults["expectancy"],
        sharpe_ratio=1.5,
        sortino_ratio=2.0,
        calmar_ratio=3.0,
        exit_reason_distribution=[],
    )
    return RunDetail(
        metadata=_make_metadata(run_id, RunStatus.COMPLETED),
        parsed_summary=summary,
        pair_results=[],
        freqtrade_command="freqtrade backtesting ...",
        artifacts={},
    )


@pytest.fixture
def runner():
    """Build a PairSweepRunner with all dependencies mocked."""
    sweep_store = MagicMock()
    backtest_runner = MagicMock()
    backtest_runner.queue_strategy_backtest = AsyncMock()
    run_repository = MagicMock()
    registry = MagicMock()
    settings_store = MagicMock()
    settings_store.load.return_value = MagicMock(
        default_config_file_path="/fake/config.json"
    )
    version_manager = MagicMock()
    pair_selector = MagicMock()
    data_download_runner = MagicMock()

    pointer = MagicMock()
    pointer.accepted_version_id = "v1"
    version_manager.get_current_pointer.return_value = pointer
    registry.get_strategy.return_value = MagicMock(strategy_name="TestStrategy")

    obj = PairSweepRunner(
        sweep_store=sweep_store,
        backtest_runner=backtest_runner,
        run_repository=run_repository,
        registry=registry,
        settings_store=settings_store,
        version_manager=version_manager,
        pair_selector=pair_selector,
        data_download_runner=data_download_runner,
    )
    return obj, backtest_runner, run_repository, pair_selector


class TestIndividualPairSweep:
    """Tests for run_individual_pair_sweep."""

    def test_each_pair_tested_individually(self, runner):
        """Each pair runs in a separate backtest with max_open_trades=1."""
        obj, bt, rr, ps = runner
        pairs = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

        # Each call returns a distinct run_id
        bt.queue_strategy_backtest.side_effect = [
            "run_btc", "run_eth", "run_sol"
        ]

        def _load_metadata(run_id):
            return _make_metadata(run_id, RunStatus.COMPLETED)
        rr.load_metadata.side_effect = _load_metadata

        def _load_detail(run_id):
            return _make_detail(run_id)
        rr.load_detail.side_effect = _load_detail

        result = _run(obj.run_individual_pair_sweep(
            pairs=pairs,
            strategy_name="TestStrategy",
            config_file="/fake/config.json",
            timerange="20230101-20230601",
            timeframe="1h",
        ))

        assert len(result) == 3
        # Verify each pair was tested with its own call
        assert bt.queue_strategy_backtest.call_count == 3
        for call_args in bt.queue_strategy_backtest.call_args_list:
            _strategy, _version, run_req = call_args[0]
            assert isinstance(run_req, RunRequest)
            assert run_req.max_open_trades == 1
            assert len(run_req.pairs) == 1

    def test_results_sorted_by_score_descending(self, runner):
        """Results are sorted highest score first."""
        obj, bt, rr, ps = runner
        pairs = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

        bt.queue_strategy_backtest.side_effect = [
            "run_btc", "run_eth", "run_sol"
        ]

        rr.load_metadata.return_value = _make_metadata("rid", RunStatus.COMPLETED)

        # Different performance per pair
        rr.load_detail.side_effect = [
            _make_detail("r1", profit_factor=3.0, win_rate_pct=60.0, max_drawdown_pct=5.0),
            _make_detail("r2", profit_factor=1.5, win_rate_pct=45.0, max_drawdown_pct=20.0),
            _make_detail("r3", profit_factor=2.0, win_rate_pct=50.0, max_drawdown_pct=10.0),
        ]

        result = _run(obj.run_individual_pair_sweep(
            pairs=pairs,
            strategy_name="TestStrategy",
            config_file="/fake/config.json",
            timerange="20230101-20230601",
            timeframe="1h",
        ))

        assert len(result) == 3
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True), "Scores not sorted descending"

    def test_backtest_failure_marks_pair(self, runner):
        """A failed backtest queue raises backtest_failed status."""
        obj, bt, rr, ps = runner
        pairs = ["BTC/USDT", "ETH/USDT"]

        # First pair fails to queue, second succeeds
        bt.queue_strategy_backtest.side_effect = [
            Exception("Freqtrade crashed"),
            "run_eth",
        ]
        rr.load_metadata.return_value = _make_metadata("run_eth", RunStatus.COMPLETED)
        rr.load_detail.return_value = _make_detail("run_eth")

        result = _run(obj.run_individual_pair_sweep(
            pairs=pairs,
            strategy_name="TestStrategy",
            config_file="/fake/config.json",
            timerange="20230101-20230601",
            timeframe="1h",
        ))

        assert len(result) == 2
        # Failed pair (score 0.0) sorts to the end
        assert result[1]["pair"] == "BTC/USDT"
        assert result[1]["status"] == "backtest_failed"
        assert result[1]["rejection_reason"] is not None
        assert result[0]["status"] == "passed"

    def test_backtest_completes_but_fails_to_run(self, runner):
        """Backtest runs but process returns failed status."""
        obj, bt, rr, ps = runner
        pairs = ["BTC/USDT"]

        bt.queue_strategy_backtest.return_value = "run_btc"

        def _load_metadata_sequence(run_id):
            return _make_metadata(run_id, RunStatus.FAILED)
        rr.load_metadata.side_effect = _load_metadata_sequence

        rr.load_detail.return_value = _make_detail("run_btc")

        result = _run(obj.run_individual_pair_sweep(
            pairs=pairs,
            strategy_name="TestStrategy",
            config_file="/fake/config.json",
            timerange="20230101-20230601",
            timeframe="1h",
        ))

        assert len(result) == 1
        assert result[0]["status"] == "backtest_failed"

    def test_zero_trades_is_data_quality_failed(self, runner):
        """Zero trades results in data_quality_failed status."""
        obj, bt, rr, ps = runner
        pairs = ["BTC/USDT"]

        bt.queue_strategy_backtest.return_value = "run_btc"
        rr.load_metadata.return_value = _make_metadata("run_btc", RunStatus.COMPLETED)

        detail = _make_detail("run_btc", total_trades=0)
        rr.load_detail.return_value = detail

        result = _run(obj.run_individual_pair_sweep(
            pairs=pairs,
            strategy_name="TestStrategy",
            config_file="/fake/config.json",
            timerange="20230101-20230601",
            timeframe="1h",
        ))

        assert result[0]["status"] == "data_quality_failed"
        assert result[0]["total_trades"] == 0

    def test_missing_metric_does_not_crash(self, runner):
        """A missing parsed_summary field does not crash the helper."""
        obj, bt, rr, ps = runner
        pairs = ["BTC/USDT"]

        bt.queue_strategy_backtest.return_value = "run_btc"
        rr.load_metadata.return_value = _make_metadata("run_btc", RunStatus.COMPLETED)

        # Simulate a detail with minimal data (some fields None)
        detail = _make_detail(
            "run_btc",
            profit_factor=None,
            win_rate_pct=None,
            max_drawdown_pct=None,
            expectancy=None,
            net_profit_pct=None,
        )
        rr.load_detail.return_value = detail

        result = _run(obj.run_individual_pair_sweep(
            pairs=pairs,
            strategy_name="TestStrategy",
            config_file="/fake/config.json",
            timerange="20230101-20230601",
            timeframe="1h",
        ))

        # Should not crash — result should have the pair with status data_quality_failed
        # (pairs with missing profit_factor should be rejected)
        assert len(result) == 1
        assert result[0]["pair"] == "BTC/USDT"
        assert result[0]["status"] == "data_quality_failed"
        assert "profit factor" in result[0]["rejection_reason"].lower()

    def test_passed_pair_includes_all_metrics(self, runner):
        """A successfully tested pair includes all expected metric fields."""
        obj, bt, rr, ps = runner
        pairs = ["BTC/USDT"]

        bt.queue_strategy_backtest.return_value = "run_btc"
        rr.load_metadata.return_value = _make_metadata("run_btc", RunStatus.COMPLETED)
        rr.load_detail.return_value = _make_detail("run_btc")

        result = _run(obj.run_individual_pair_sweep(
            pairs=pairs,
            strategy_name="TestStrategy",
            config_file="/fake/config.json",
            timerange="20230101-20230601",
            timeframe="1h",
        ))

        entry = result[0]
        assert entry["status"] == "passed"
        assert entry["score"] > 0
        assert entry["total_trades"] is not None
        assert entry["profit_factor"] is not None
        assert entry["win_rate"] is not None
        assert entry["max_drawdown"] is not None
        assert entry["expectancy"] is not None
        assert entry["profit_total"] is not None

    def test_no_pair_selector_writes(self, runner):
        """PairSelectorService should never be called to save state."""
        obj, bt, rr, ps = runner

        bt.queue_strategy_backtest.return_value = "run_btc"
        rr.load_metadata.return_value = _make_metadata("run_btc", RunStatus.COMPLETED)
        rr.load_detail.return_value = _make_detail("run_btc")

        _run(obj.run_individual_pair_sweep(
            pairs=["BTC/USDT"],
            strategy_name="TestStrategy",
            config_file="/fake/config.json",
            timerange="20230101-20230601",
            timeframe="1h",
        ))

        # The pair_selector mock should not have had any state-changing calls
        for method_name in ("save_state", "set_selected", "randomize_pairs",
                            "toggle_favorite", "toggle_lock", "clear_selection"):
            method = getattr(ps, method_name, None)
            if method is not None:
                method.assert_not_called()

    def test_empty_pairs_returns_empty(self, runner):
        """Empty pair list returns empty list."""
        obj, bt, rr, ps = runner
        result = _run(obj.run_individual_pair_sweep(
            pairs=[],
            strategy_name="TestStrategy",
            config_file="/fake/config.json",
            timerange="20230101-20230601",
            timeframe="1h",
        ))
        assert result == []

    def test_profit_factor_below_one_is_failed(self, runner):
        """Profit factor < 1.0 results in failed status with rejection reason."""
        obj, bt, rr, ps = runner
        pairs = ["BTC/USDT"]

        bt.queue_strategy_backtest.return_value = "run_btc"
        rr.load_metadata.return_value = _make_metadata("run_btc", RunStatus.COMPLETED)
        rr.load_detail.return_value = _make_detail(
            "run_btc", profit_factor=0.8, total_trades=30
        )

        result = _run(obj.run_individual_pair_sweep(
            pairs=pairs,
            strategy_name="TestStrategy",
            config_file="/fake/config.json",
            timerange="20230101-20230601",
            timeframe="1h",
        ))

        assert result[0]["status"] == "failed"
        assert "below 1.0" in result[0]["rejection_reason"]
