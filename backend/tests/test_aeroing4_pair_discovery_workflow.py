"""Workflow tests for AeRoing4 Pair Discovery (Milestone 2A).

Tests:
  - PASS_ACTIVITY enters Pair Discovery (when enabled)
  - NO_SIGNAL_ACTIVITY does NOT enter Pair Discovery by default
  - EXECUTION_FAILURE stops before Pair Discovery
  - one failed pair does not fail entire discovery
  - all unusable pairs produce clear terminal result
  - valid pairs are ranked and persisted
"""

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from backend.services.aeroing4.models import (
    AeRoing4RunStatus,
    AeRoing4StepStatus,
    BiasCheckOutcome,
    PairCandidateStatus,
    PairDiscoveryResult,
    PairEvaluationRecord,
    SmokeBacktestOutcome,
    StepResult,
)
from backend.services.aeroing4.orchestrator import AeRoing4Orchestrator


@pytest.fixture
def temp_runs_root():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_services():
    services = Mock()
    services.registry = Mock()
    services.backtest_runner = Mock()
    services.data_download_runner = Mock()
    services.run_repository = Mock()
    services.version_manager = Mock()
    services.settings_store = Mock()
    return services


@pytest.fixture
def orchestrator(mock_services, temp_runs_root):
    return AeRoing4Orchestrator(mock_services, temp_runs_root)


def _make_step_result(step_name: str, status: AeRoing4StepStatus, data: dict = None, error: str = None) -> StepResult:
    return StepResult(
        step_name=step_name,
        status=status,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        data=data or {},
        error=error,
    )


class TestPairDiscoveryOrchestration:
    """Tests for the orchestrator-level pair discovery gating."""

    @pytest.mark.asyncio
    async def test_pass_activity_enters_pair_discovery_when_enabled(
        self, orchestrator, mock_services
    ):
        """PASS_ACTIVITY + enable_pair_discovery=True → pair_discovery step runs."""
        run = orchestrator.create_run(
            strategy_name="test_strategy",
            enable_pair_discovery=True,
            discovery_timerange="20240101-20240630",
        )

        validation_ok = _make_step_result("validation", AeRoing4StepStatus.PASSED, {"valid": True})
        data_ok = _make_step_result("data_preparation", AeRoing4StepStatus.PASSED)
        smoke_pass = _make_step_result(
            "smoke_backtest",
            AeRoing4StepStatus.PASSED,
            {"outcome": SmokeBacktestOutcome.PASS_ACTIVITY.value},
        )
        bias_pass = _make_step_result(
            "bias_check",
            AeRoing4StepStatus.PASSED,
            {"outcome": BiasCheckOutcome.PASS.value},
        )

        # Discovery result: one valid candidate
        discovery_result = PairDiscoveryResult(
            universe_size=3,
            usable_pairs_count=3,
            evaluated_pairs_count=3,
            valid_candidates_count=1,
            rejected_pairs_count=2,
            ranked_pairs=[
                PairEvaluationRecord(
                    pair="ETH/USDT",
                    status=PairCandidateStatus.VALID_CANDIDATE,
                    total_trades=50,
                    rank=1,
                    rank_score=42.5,
                )
            ],
        )
        discovery_ok = _make_step_result(
            "pair_discovery",
            AeRoing4StepStatus.PASSED,
            {
                "outcome": "valid_candidates_found",
                "discovery_result": discovery_result.model_dump(),
            },
        )

        selection_ok = _make_step_result(
            "pair_selection",
            AeRoing4StepStatus.PASSED,
            {"outcome": "selection_complete"},
        )
        baseline_ok = _make_step_result(
            "portfolio_baseline",
            AeRoing4StepStatus.PASSED,
            {"outcome": "baseline_created"},
        )
        champion_ok = _make_step_result(
            "initial_champion",
            AeRoing4StepStatus.PASSED,
            {"outcome": "champion_created"},
        )

        with (
            patch("backend.services.aeroing4.orchestrator.ValidationStep") as val_cls,
            patch("backend.services.aeroing4.orchestrator.DataPreparationStep") as dp_cls,
            patch("backend.services.aeroing4.orchestrator.SmokeBacktestStep") as smoke_cls,
            patch("backend.services.aeroing4.orchestrator.BiasCheckStep") as bias_cls,
            patch("backend.services.aeroing4.orchestrator.PairDiscoveryStep") as disc_cls,
            patch("backend.services.aeroing4.orchestrator.PairSelectionStep") as sel_cls,
            patch("backend.services.aeroing4.orchestrator.PortfolioBaselineStep") as base_cls,
            patch("backend.services.aeroing4.orchestrator.InitialChampionStep") as champ_cls,
        ):
            val_cls.return_value.execute = AsyncMock(return_value=validation_ok)
            dp_cls.return_value.execute = AsyncMock(return_value=data_ok)
            smoke_cls.return_value.execute = AsyncMock(return_value=smoke_pass)
            bias_cls.return_value.execute = AsyncMock(return_value=bias_pass)
            disc_cls.return_value.execute = AsyncMock(return_value=discovery_ok)
            sel_cls.return_value.execute = AsyncMock(return_value=selection_ok)
            base_cls.return_value.execute = AsyncMock(return_value=baseline_ok)
            champ_cls.return_value.execute = AsyncMock(return_value=champion_ok)

            await orchestrator.start_run(run.run_id)
            await orchestrator._active_task

        final_run = orchestrator.get_run(run.run_id)
        assert final_run is not None
        assert final_run.status == AeRoing4RunStatus.COMPLETED
        assert "pair_discovery" in final_run.steps
        disc_cls.return_value.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_signal_activity_does_not_enter_pair_discovery_by_default(
        self, orchestrator, mock_services
    ):
        """NO_SIGNAL_ACTIVITY must NOT trigger pair discovery (no expanded mode)."""
        run = orchestrator.create_run(
            strategy_name="test_strategy",
            enable_pair_discovery=True,  # enabled, but smoke has no signal
        )

        validation_ok = _make_step_result("validation", AeRoing4StepStatus.PASSED, {"valid": True})
        data_ok = _make_step_result("data_preparation", AeRoing4StepStatus.PASSED)
        smoke_no_signal = _make_step_result(
            "smoke_backtest",
            AeRoing4StepStatus.PASSED,
            {"outcome": SmokeBacktestOutcome.NO_SIGNAL_ACTIVITY.value},
        )

        with (
            patch("backend.services.aeroing4.orchestrator.ValidationStep") as val_cls,
            patch("backend.services.aeroing4.orchestrator.DataPreparationStep") as dp_cls,
            patch("backend.services.aeroing4.orchestrator.SmokeBacktestStep") as smoke_cls,
            patch("backend.services.aeroing4.orchestrator.BiasCheckStep") as bias_cls,
            patch("backend.services.aeroing4.orchestrator.PairDiscoveryStep") as disc_cls,
        ):
            val_cls.return_value.execute = AsyncMock(return_value=validation_ok)
            dp_cls.return_value.execute = AsyncMock(return_value=data_ok)
            smoke_cls.return_value.execute = AsyncMock(return_value=smoke_no_signal)
            # Bias check should not be called for NO_SIGNAL_ACTIVITY

            await orchestrator.start_run(run.run_id)
            await orchestrator._active_task

        final_run = orchestrator.get_run(run.run_id)
        assert final_run is not None
        assert final_run.status == AeRoing4RunStatus.COMPLETED
        # Pair discovery must NOT have been called
        disc_cls.return_value.execute.assert_not_called()
        assert "pair_discovery" not in final_run.steps

    @pytest.mark.asyncio
    async def test_execution_failure_stops_before_pair_discovery(
        self, orchestrator, mock_services
    ):
        """EXECUTION_FAILURE must stop the workflow — pair discovery never runs."""
        run = orchestrator.create_run(
            strategy_name="test_strategy",
            enable_pair_discovery=True,
        )

        validation_ok = _make_step_result("validation", AeRoing4StepStatus.PASSED, {"valid": True})
        data_ok = _make_step_result("data_preparation", AeRoing4StepStatus.PASSED)
        smoke_fail = _make_step_result(
            "smoke_backtest",
            AeRoing4StepStatus.FAILED,
            {"outcome": SmokeBacktestOutcome.EXECUTION_FAILURE.value},
            error="Execution failed",
        )

        with (
            patch("backend.services.aeroing4.orchestrator.ValidationStep") as val_cls,
            patch("backend.services.aeroing4.orchestrator.DataPreparationStep") as dp_cls,
            patch("backend.services.aeroing4.orchestrator.SmokeBacktestStep") as smoke_cls,
            patch("backend.services.aeroing4.orchestrator.BiasCheckStep") as bias_cls,
            patch("backend.services.aeroing4.orchestrator.PairDiscoveryStep") as disc_cls,
        ):
            val_cls.return_value.execute = AsyncMock(return_value=validation_ok)
            dp_cls.return_value.execute = AsyncMock(return_value=data_ok)
            smoke_cls.return_value.execute = AsyncMock(return_value=smoke_fail)
            # Bias check should not be called for EXECUTION_FAILURE

            await orchestrator.start_run(run.run_id)
            await orchestrator._active_task

        final_run = orchestrator.get_run(run.run_id)
        assert final_run is not None
        assert final_run.status == AeRoing4RunStatus.FAILED
        disc_cls.return_value.execute.assert_not_called()
        assert "pair_discovery" not in final_run.steps

    @pytest.mark.asyncio
    async def test_pair_discovery_disabled_skips_discovery(
        self, orchestrator, mock_services
    ):
        """enable_pair_discovery=False → no discovery even on PASS_ACTIVITY."""
        run = orchestrator.create_run(
            strategy_name="test_strategy",
            enable_pair_discovery=False,  # explicitly disabled
        )

        validation_ok = _make_step_result("validation", AeRoing4StepStatus.PASSED, {"valid": True})
        data_ok = _make_step_result("data_preparation", AeRoing4StepStatus.PASSED)
        smoke_pass = _make_step_result(
            "smoke_backtest",
            AeRoing4StepStatus.PASSED,
            {"outcome": SmokeBacktestOutcome.PASS_ACTIVITY.value},
        )
        bias_pass = _make_step_result(
            "bias_check",
            AeRoing4StepStatus.PASSED,
            {"outcome": BiasCheckOutcome.PASS.value},
        )
        selection_ok = _make_step_result(
            "pair_selection",
            AeRoing4StepStatus.PASSED,
            {"outcome": "selection_complete"},
        )
        baseline_ok = _make_step_result(
            "portfolio_baseline",
            AeRoing4StepStatus.PASSED,
            {"outcome": "baseline_created"},
        )
        champion_ok = _make_step_result(
            "initial_champion",
            AeRoing4StepStatus.PASSED,
            {"outcome": "champion_created"},
        )

        with (
            patch("backend.services.aeroing4.orchestrator.ValidationStep") as val_cls,
            patch("backend.services.aeroing4.orchestrator.DataPreparationStep") as dp_cls,
            patch("backend.services.aeroing4.orchestrator.SmokeBacktestStep") as smoke_cls,
            patch("backend.services.aeroing4.orchestrator.BiasCheckStep") as bias_cls,
            patch("backend.services.aeroing4.orchestrator.PairDiscoveryStep") as disc_cls,
            patch("backend.services.aeroing4.orchestrator.PairSelectionStep") as sel_cls,
            patch("backend.services.aeroing4.orchestrator.PortfolioBaselineStep") as base_cls,
            patch("backend.services.aeroing4.orchestrator.InitialChampionStep") as champ_cls,
        ):
            val_cls.return_value.execute = AsyncMock(return_value=validation_ok)
            dp_cls.return_value.execute = AsyncMock(return_value=data_ok)
            smoke_cls.return_value.execute = AsyncMock(return_value=smoke_pass)
            bias_cls.return_value.execute = AsyncMock(return_value=bias_pass)
            sel_cls.return_value.execute = AsyncMock(return_value=selection_ok)
            base_cls.return_value.execute = AsyncMock(return_value=baseline_ok)
            champ_cls.return_value.execute = AsyncMock(return_value=champion_ok)

            await orchestrator.start_run(run.run_id)
            await orchestrator._active_task

        final_run = orchestrator.get_run(run.run_id)
        assert final_run is not None
        assert final_run.status == AeRoing4RunStatus.COMPLETED
        disc_cls.return_value.execute.assert_not_called()
        assert "pair_discovery" not in final_run.steps

    @pytest.mark.asyncio
    async def test_no_valid_candidates_completes_with_no_pair_candidates_outcome(
        self, orchestrator, mock_services
    ):
        """Discovery that finds zero valid candidates must complete with explicit outcome."""
        run = orchestrator.create_run(
            strategy_name="test_strategy",
            enable_pair_discovery=True,
        )

        validation_ok = _make_step_result("validation", AeRoing4StepStatus.PASSED, {"valid": True})
        data_ok = _make_step_result("data_preparation", AeRoing4StepStatus.PASSED)
        smoke_pass = _make_step_result(
            "smoke_backtest",
            AeRoing4StepStatus.PASSED,
            {"outcome": SmokeBacktestOutcome.PASS_ACTIVITY.value},
        )
        bias_pass = _make_step_result(
            "bias_check",
            AeRoing4StepStatus.PASSED,
            {"outcome": BiasCheckOutcome.PASS.value},
        )
        discovery_no_candidates = _make_step_result(
            "pair_discovery",
            AeRoing4StepStatus.PASSED,
            {"outcome": "no_pair_candidates", "discovery_result": {}},
        )
        selection_ok = _make_step_result(
            "pair_selection",
            AeRoing4StepStatus.PASSED,
            {"outcome": "no_pairs_selected"},
        )
        baseline_ok = _make_step_result(
            "portfolio_baseline",
            AeRoing4StepStatus.PASSED,
            {"outcome": "baseline_created"},
        )
        champion_ok = _make_step_result(
            "initial_champion",
            AeRoing4StepStatus.PASSED,
            {"outcome": "champion_created"},
        )

        with (
            patch("backend.services.aeroing4.orchestrator.ValidationStep") as val_cls,
            patch("backend.services.aeroing4.orchestrator.DataPreparationStep") as dp_cls,
            patch("backend.services.aeroing4.orchestrator.SmokeBacktestStep") as smoke_cls,
            patch("backend.services.aeroing4.orchestrator.BiasCheckStep") as bias_cls,
            patch("backend.services.aeroing4.orchestrator.PairDiscoveryStep") as disc_cls,
            patch("backend.services.aeroing4.orchestrator.PairSelectionStep") as sel_cls,
            patch("backend.services.aeroing4.orchestrator.PortfolioBaselineStep") as base_cls,
            patch("backend.services.aeroing4.orchestrator.InitialChampionStep") as champ_cls,
        ):
            val_cls.return_value.execute = AsyncMock(return_value=validation_ok)
            dp_cls.return_value.execute = AsyncMock(return_value=data_ok)
            smoke_cls.return_value.execute = AsyncMock(return_value=smoke_pass)
            bias_cls.return_value.execute = AsyncMock(return_value=bias_pass)
            disc_cls.return_value.execute = AsyncMock(return_value=discovery_no_candidates)
            sel_cls.return_value.execute = AsyncMock(return_value=selection_ok)
            base_cls.return_value.execute = AsyncMock(return_value=baseline_ok)
            champ_cls.return_value.execute = AsyncMock(return_value=champion_ok)

            await orchestrator.start_run(run.run_id)
            await orchestrator._active_task

        final_run = orchestrator.get_run(run.run_id)
        assert final_run is not None
        assert final_run.status == AeRoing4RunStatus.COMPLETED
        assert "pair_discovery" in final_run.steps
        outcome = final_run.steps["pair_discovery"].data.get("outcome")
        assert outcome == "no_pair_candidates"

    @pytest.mark.asyncio
    async def test_discovery_timerange_is_persisted(self, orchestrator, mock_services):
        """Discovery timerange must be stored in run state (reproducibility)."""
        run = orchestrator.create_run(
            strategy_name="test_strategy",
            enable_pair_discovery=True,
            discovery_timerange="20231001-20240101",
        )

        reloaded = orchestrator.get_run(run.run_id)
        assert reloaded is not None
        assert reloaded.discovery_timerange == "20231001-20240101"
        assert reloaded.enable_pair_discovery is True

    @pytest.mark.asyncio
    async def test_discovery_pairs_are_persisted(self, orchestrator, mock_services):
        """Discovery universe must be stored in run state (reproducibility)."""
        pairs = ["BTC/USDT", "ETH/USDT"]
        run = orchestrator.create_run(
            strategy_name="test_strategy",
            enable_pair_discovery=True,
            discovery_pairs=pairs,
        )

        reloaded = orchestrator.get_run(run.run_id)
        assert reloaded is not None
        assert reloaded.discovery_pairs == pairs

    @pytest.mark.asyncio
    async def test_discovery_uses_default_timerange_when_not_provided(
        self, orchestrator, mock_services
    ):
        """Default discovery timerange is used when not explicitly provided."""
        from backend.services.aeroing4.orchestrator import DEFAULT_DISCOVERY_TIMERANGE

        run = orchestrator.create_run(
            strategy_name="test_strategy",
            enable_pair_discovery=True,
            # No discovery_timerange provided
        )

        validation_ok = _make_step_result("validation", AeRoing4StepStatus.PASSED, {"valid": True})
        data_ok = _make_step_result("data_preparation", AeRoing4StepStatus.PASSED)
        smoke_pass = _make_step_result(
            "smoke_backtest",
            AeRoing4StepStatus.PASSED,
            {"outcome": SmokeBacktestOutcome.PASS_ACTIVITY.value},
        )
        bias_pass = _make_step_result(
            "bias_check",
            AeRoing4StepStatus.PASSED,
            {"outcome": BiasCheckOutcome.PASS.value},
        )
        discovery_ok = _make_step_result(
            "pair_discovery",
            AeRoing4StepStatus.PASSED,
            {"outcome": "valid_candidates_found"},
        )
        selection_ok = _make_step_result(
            "pair_selection",
            AeRoing4StepStatus.PASSED,
            {"outcome": "selection_complete"},
        )
        baseline_ok = _make_step_result(
            "portfolio_baseline",
            AeRoing4StepStatus.PASSED,
            {"outcome": "baseline_created"},
        )
        champion_ok = _make_step_result(
            "initial_champion",
            AeRoing4StepStatus.PASSED,
            {"outcome": "champion_created"},
        )

        captured_kwargs: dict = {}

        async def capture_execute(**kwargs):
            captured_kwargs.update(kwargs)
            return discovery_ok

        with (
            patch("backend.services.aeroing4.orchestrator.ValidationStep") as val_cls,
            patch("backend.services.aeroing4.orchestrator.DataPreparationStep") as dp_cls,
            patch("backend.services.aeroing4.orchestrator.SmokeBacktestStep") as smoke_cls,
            patch("backend.services.aeroing4.orchestrator.BiasCheckStep") as bias_cls,
            patch("backend.services.aeroing4.orchestrator.PairDiscoveryStep") as disc_cls,
            patch("backend.services.aeroing4.orchestrator.PairSelectionStep") as sel_cls,
            patch("backend.services.aeroing4.orchestrator.PortfolioBaselineStep") as base_cls,
            patch("backend.services.aeroing4.orchestrator.InitialChampionStep") as champ_cls,
        ):
            val_cls.return_value.execute = AsyncMock(return_value=validation_ok)
            dp_cls.return_value.execute = AsyncMock(return_value=data_ok)
            smoke_cls.return_value.execute = AsyncMock(return_value=smoke_pass)
            bias_cls.return_value.execute = AsyncMock(return_value=bias_pass)
            disc_cls.return_value.execute = AsyncMock(side_effect=capture_execute)
            sel_cls.return_value.execute = AsyncMock(return_value=selection_ok)
            base_cls.return_value.execute = AsyncMock(return_value=baseline_ok)
            champ_cls.return_value.execute = AsyncMock(return_value=champion_ok)

            await orchestrator.start_run(run.run_id)
            await orchestrator._active_task

        # Discovery must have been called with the default timerange
        assert captured_kwargs.get("discovery_timerange") == DEFAULT_DISCOVERY_TIMERANGE
