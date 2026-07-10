"""backend/tests/test_state_machine.py — State machine transition tests.

Tests for the pipeline state machine, including:
- Stage 1-7 transitions
- Status updates
- Data attachment
- Pipeline completion
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import backend.services.auto_quant.pipeline as pl
from backend.services.auto_quant.pipeline import (
    MAX_DRAWDOWN_THRESHOLD,
    MIN_OOS_PROFIT,
    MIN_PROFIT_FACTOR,
    MIN_SHARPE,
    MIN_WIN_RATE,
    PipelineState,
    STAGE_NAMES,
)

from .test_helpers import _backtest_result, _hyperopt_best, _make_state, _run, _write_strategy

MOD = "backend.services.auto_quant.pipeline"


class TestStateMachineTransitions:
    """Verify stage status transitions and data attachment across the full pipeline."""

    def _run_full_pipeline(self, tmp_path: Path) -> PipelineState:
        """
        Run the complete 7-stage pipeline with all subprocesses and I/O mocked.
        Returns the PipelineState after completion.
        """
        user_data = tmp_path / "user_data"
        strategies_dir = user_data / "strategies"
        strategies_dir.mkdir(parents=True)
        config_path = user_data / "config.json"
        config_path.write_text(
            '{"exchange": {"name": "binance"}, "stake_currency": "USDT"}',
            encoding="utf-8",
        )
        _write_strategy(strategies_dir, "AuditStrategy")

        state = _make_state(str(user_data))
        run_id = state.run_id
        out_dir = user_data / "auto_quant" / run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        s1_result = _backtest_result("AuditStrategy")
        s4_result = _backtest_result("AuditStrategy_Optimized")
        s5_result = _backtest_result("AuditStrategy_Optimized")

        def _bt_side_effect(_out_dir, prefix, *args, **kwargs):
            if "stage1" in str(prefix):
                return s1_result
            elif "stage4" in str(prefix):
                return s4_result
            return s5_result

        with (
            patch(f"{MOD}._auto_download_data", new=AsyncMock()),
            patch(f"{MOD}._run_subprocess", new=AsyncMock(return_value=(0, "", ""))),
            patch(f"{MOD}._extract_hyperopt_best", new=AsyncMock(return_value=_hyperopt_best())),
            patch(f"{MOD}._find_backtest_result", side_effect=_bt_side_effect),
            patch(f"{MOD}._save_state_to_disk"),
        ):
            _run(pl.run_pipeline(run_id))

        return pl.get_state(run_id)

    def test_pipeline_reaches_completed_status(self, tmp_path):
        """Full happy-path pipeline must finish with status='completed'."""
        state = self._run_full_pipeline(tmp_path)
        assert state is not None
        assert state.status == "completed", (
            f"Expected 'completed', got {state.status!r}. error={state.error!r}"
        )

    def test_all_seven_stages_pass(self, tmp_path):
        """Every stage (1-7) must have status='passed' after a successful run."""
        state = self._run_full_pipeline(tmp_path)
        for s in state.stages:
            assert s.status == "passed", (
                f"Stage {s.index} ({s.name}) has status {s.status!r}, expected 'passed'"
            )

    def test_current_stage_is_7_on_completion(self, tmp_path):
        """current_stage must be 7 at the end of a completed pipeline."""
        state = self._run_full_pipeline(tmp_path)
        assert state.current_stage == 7

    def test_stage_names_are_correct(self, tmp_path):
        """Stage names must match STAGE_NAMES in order."""
        state = self._run_full_pipeline(tmp_path)
        for i, s in enumerate(state.stages):
            assert s.name == STAGE_NAMES[i], (
                f"Stage {i+1} name mismatch: got {s.name!r}, expected {STAGE_NAMES[i]!r}"
            )

    def test_stage_indices_are_1_based(self, tmp_path):
        """Stage indices must be 1-7, not 0-based."""
        state = self._run_full_pipeline(tmp_path)
        for i, s in enumerate(state.stages):
            assert s.index == i + 1, f"Stage index {s.index} != {i+1}"

    def test_stage_messages_are_non_empty_on_completion(self, tmp_path):
        """Each passed stage must have a non-empty status message."""
        state = self._run_full_pipeline(tmp_path)
        for s in state.stages:
            assert s.message, f"Stage {s.index} ({s.name}) has empty message after passing"

    def test_stage_data_attached_for_key_stages(self, tmp_path):
        """Stages 1, 2, 4, 5, 6, 7 must have non-empty data dicts."""
        state = self._run_full_pipeline(tmp_path)
        for idx in (1, 2, 4, 5, 6, 7):
            s = state.stages[idx - 1]
            assert s.data, f"Stage {idx} ({s.name}) has empty data dict"

    def test_report_is_populated(self, tmp_path):
        """state.report must be populated after completion."""
        state = self._run_full_pipeline(tmp_path)
        assert state.report is not None
        assert "run_id" in state.report
        assert "optimized_strategy" in state.report

    def test_completed_at_is_set(self, tmp_path):
        """state.completed_at must be non-None after completion."""
        state = self._run_full_pipeline(tmp_path)
        assert state.completed_at is not None

    def test_start_stage_sets_running_status(self, tmp_path):
        """_start_stage() must mark the target stage as 'running' immediately."""
        state = _make_state(str(tmp_path))
        pl._start_stage(state.run_id, state, 3)
        assert state.stages[2].status == "running"
        assert state.current_stage == 3

    def test_pass_stage_sets_passed_status_and_message(self, tmp_path):
        """_pass_stage() must set status='passed', message, and data."""
        state = _make_state(str(tmp_path))
        with patch(f"{MOD}._save_state_to_disk"):
            pl._pass_stage(state.run_id, state, 2, "Unit test pass", {"key": "val"})
        s = state.stages[1]
        assert s.status == "passed"
        assert s.message == "Unit test pass"
        assert s.data == {"key": "val"}

    def test_fail_stage_sets_failed_status_and_pipeline_failed(self, tmp_path):
        """_fail_stage() must mark stage and pipeline status as 'failed'."""
        state = _make_state(str(tmp_path))
        with patch(f"{MOD}._save_state_to_disk"):
            pl._fail_stage(state.run_id, state, 5, "Unit test fail")
        assert state.stages[4].status == "failed"
        assert state.status == "failed"
        assert state.error == "Unit test fail"

    def test_stage1_failure_stops_pipeline(self, tmp_path):
        """Non-zero subprocess exit in Stage 1 must halt the pipeline at stage 1."""
        user_data = tmp_path / "user_data"
        strategies_dir = user_data / "strategies"
        strategies_dir.mkdir(parents=True)
        (user_data / "config.json").write_text("{}", encoding="utf-8")
        _write_strategy(strategies_dir, "AuditStrategy")

        state = _make_state(str(user_data))

        with (
            patch(f"{MOD}._auto_download_data", new=AsyncMock()),
            patch(f"{MOD}._run_subprocess", new=AsyncMock(return_value=(1, "ERROR: fail", ""))),
            patch(f"{MOD}._save_state_to_disk"),
        ):
            _run(pl.run_pipeline(state.run_id))

        assert state.status == "failed"
        assert state.current_stage == 1
        assert state.stages[0].status == "failed"
        for i in range(1, 7):
            assert state.stages[i].status == "pending", (
                f"Stage {i+1} should be pending but is {state.stages[i].status!r}"
            )

    def test_create_run_initialises_all_stages_pending(self, tmp_path):
        """create_run() must produce 7 stages all at 'pending' status."""
        user_data = tmp_path / "user_data"
        user_data.mkdir(parents=True)
        (user_data / "config.json").write_text("{}", encoding="utf-8")

        with patch(f"{MOD}._save_state_to_disk"):
            run_id = pl.create_run(
                strategy="S",
                timeframe="5m",
                in_sample_range="20230101-20231201",
                out_sample_range="20240101-20240601",
                exchange="binance",
                config_file=str(user_data / "config.json"),
                freqtrade_path="freqtrade",
                user_data_dir=str(user_data),
            )
        state = pl.get_state(run_id)
        assert state is not None
        assert len(state.stages) == 7
        assert all(s.status == "pending" for s in state.stages)
        assert state.status == "pending"

    def test_create_run_defaults_to_profit_lockin_loss(self, tmp_path):
        """Auto-Quant runs should default to the profit lock-in Hyperopt loss."""
        user_data = tmp_path / "user_data"
        user_data.mkdir(parents=True)
        config_file = user_data / "config.json"
        config_file.write_text("{}", encoding="utf-8")

        with patch(f"{MOD}._save_state_to_disk"):
            run_id = pl.create_run(
                strategy="S",
                timeframe="5m",
                in_sample_range="20230101-20231201",
                out_sample_range="20240101-20240601",
                exchange="binance",
                config_file=str(config_file),
                freqtrade_path="freqtrade",
                user_data_dir=str(user_data),
            )

        assert pl.get_state(run_id).hyperopt_loss == "ProfitLockinHyperOptLoss"
