"""Tests for AeRoing4 workflow orchestration."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch

import pytest

from backend.core.errors import BackendError
from backend.services.aeroing4.models import (
    AeRoing4Run,
    AeRoing4RunStatus,
    AeRoing4StepStatus,
    SmokeBacktestOutcome,
)
from backend.services.aeroing4.orchestrator import AeRoing4Orchestrator
from backend.services.aeroing4.state_store import AeRoing4StateStore


@pytest.fixture
def temp_runs_root():
    """Create a temporary directory for test runs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_services():
    """Create mock services."""
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
    """Create orchestrator with mock services and temporary directory."""
    return AeRoing4Orchestrator(mock_services, temp_runs_root)


class TestAeRoing4Orchestrator:
    """Test AeRoing4Orchestrator functionality."""

    def test_create_run(self, orchestrator):
        """Test creating a new run."""
        run = orchestrator.create_run(
            strategy_name="test_strategy",
            timeframe="5m",
            smoke_timerange="20240101-20240131",
            smoke_pairs=["BTC/USDT", "ETH/USDT"],
        )

        assert run.strategy_name == "test_strategy"
        assert run.status == AeRoing4RunStatus.PENDING
        assert run.run_id is not None

    def test_create_run_with_conflict(self, orchestrator):
        """Test creating a run when another is active."""
        # Create first run
        run1 = orchestrator.create_run(strategy_name="strategy1")

        # Mark as active
        orchestrator.state_store.set_active_run(run1.run_id)
        run1.mark_running()
        orchestrator.state_store.save_run(run1)

        # Try to create second run
        with pytest.raises(BackendError) as exc_info:
            orchestrator.create_run(strategy_name="strategy2")

        assert "already active" in str(exc_info.value)

    def test_get_run(self, orchestrator):
        """Test getting a run by ID."""
        run = orchestrator.create_run(strategy_name="test_strategy")
        run_id = run.run_id

        retrieved = orchestrator.get_run(run_id)

        assert retrieved is not None
        assert retrieved.run_id == run_id
        assert retrieved.strategy_name == "test_strategy"

    def test_get_unknown_run(self, orchestrator):
        """Test getting unknown run returns None."""
        run = orchestrator.get_run("unknown_id")
        assert run is None

    def test_list_runs(self, orchestrator):
        """Test listing runs."""
        run1 = orchestrator.create_run(strategy_name="strategy1")
        run2 = orchestrator.create_run(strategy_name="strategy2")

        runs = orchestrator.list_runs()

        assert len(runs) == 2
        # Should be sorted by created_at descending (run2 created after run1)
        run_ids = [r.run_id for r in runs]
        assert run2.run_id in run_ids
        assert run1.run_id in run_ids

    @pytest.mark.asyncio
    async def test_validation_failure_stops_workflow(self, orchestrator, mock_services):
        """Test that validation failure stops the workflow."""
        run = orchestrator.create_run(strategy_name="test_strategy")

        # Mock the ValidationStep.execute method to return a failure
        from backend.services.aeroing4.models import StepResult

        mock_validation_result = StepResult(
            step_name="validation",
            status=AeRoing4StepStatus.FAILED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            error="Validation failed",
            data={"valid": False, "errors": ["Validation failed"]}
        )

        with patch("backend.services.aeroing4.orchestrator.ValidationStep") as mock_step_class:
            mock_step = AsyncMock()
            mock_step.execute.return_value = mock_validation_result
            mock_step_class.return_value = mock_step

            await orchestrator.start_run(run.run_id)

            # Wait for task to complete
            await orchestrator._active_task

            # Verify run failed
            final_run = orchestrator.get_run(run.run_id)
            assert final_run is not None
            assert final_run.status == AeRoing4RunStatus.FAILED
            assert "Validation failed" in final_run.error

    @pytest.mark.asyncio
    async def test_data_failure_stops_workflow(self, orchestrator, mock_services):
        """Test that data preparation failure stops the workflow."""
        run = orchestrator.create_run(strategy_name="test_strategy")

        from backend.services.aeroing4.models import StepResult

        # Mock validation to pass
        mock_validation_result = StepResult(
            step_name="validation",
            status=AeRoing4StepStatus.PASSED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            data={"valid": True}
        )

        # Mock data preparation to fail
        mock_data_result = StepResult(
            step_name="data_preparation",
            status=AeRoing4StepStatus.FAILED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            error="Data preparation failed",
            data={}
        )

        with patch("backend.services.aeroing4.orchestrator.ValidationStep") as mock_validation_class:
            mock_validation = AsyncMock()
            mock_validation.execute.return_value = mock_validation_result
            mock_validation_class.return_value = mock_validation

            with patch("backend.services.aeroing4.orchestrator.DataPreparationStep") as mock_data_class:
                mock_data = AsyncMock()
                mock_data.execute.return_value = mock_data_result
                mock_data_class.return_value = mock_data

                await orchestrator.start_run(run.run_id)
                await orchestrator._active_task

                final_run = orchestrator.get_run(run.run_id)
                assert final_run is not None
                assert final_run.status == AeRoing4RunStatus.FAILED
                assert "Data preparation failed" in final_run.error

    @pytest.mark.asyncio
    async def test_successful_activity_flow_completes(self, orchestrator, mock_services):
        """Test that successful activity flow completes the run."""
        run = orchestrator.create_run(strategy_name="test_strategy")

        from backend.services.aeroing4.models import StepResult

        # Mock validation to pass
        mock_validation_result = StepResult(
            step_name="validation",
            status=AeRoing4StepStatus.PASSED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            data={"valid": True}
        )

        # Mock data preparation to pass
        mock_data_result = StepResult(
            step_name="data_preparation",
            status=AeRoing4StepStatus.PASSED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            data={}
        )

        # Mock smoke backtest with trades
        mock_smoke_result = StepResult(
            step_name="smoke_backtest",
            status=AeRoing4StepStatus.PASSED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            data={"outcome": SmokeBacktestOutcome.PASS_ACTIVITY.value}
        )

        from backend.services.aeroing4.models import BiasCheckOutcome
        # Mock bias check to pass
        mock_bias_result = StepResult(
            step_name="bias_check",
            status=AeRoing4StepStatus.PASSED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            data={"outcome": BiasCheckOutcome.PASS.value}
        )

        # Mock version manager for smoke backtest step
        mock_pointer = Mock()
        mock_pointer.accepted_version_id = "v1"
        mock_services.version_manager.get_current_pointer.return_value = mock_pointer

        with patch("backend.services.aeroing4.orchestrator.ValidationStep") as mock_validation_class:
            mock_validation = AsyncMock()
            mock_validation.execute.return_value = mock_validation_result
            mock_validation_class.return_value = mock_validation

            with patch("backend.services.aeroing4.orchestrator.DataPreparationStep") as mock_data_class:
                mock_data = AsyncMock()
                mock_data.execute.return_value = mock_data_result
                mock_data_class.return_value = mock_data

                with patch("backend.services.aeroing4.orchestrator.SmokeBacktestStep") as mock_smoke_class:
                    mock_smoke = AsyncMock()
                    mock_smoke.execute.return_value = mock_smoke_result
                    mock_smoke_class.return_value = mock_smoke

                    with patch("backend.services.aeroing4.orchestrator.BiasCheckStep") as mock_bias_class:
                        mock_bias = AsyncMock()
                        mock_bias.execute.return_value = mock_bias_result
                        mock_bias_class.return_value = mock_bias

                        await orchestrator.start_run(run.run_id)
                        await orchestrator._active_task

                        final_run = orchestrator.get_run(run.run_id)
                    assert final_run is not None
                    assert final_run.status == AeRoing4RunStatus.COMPLETED
                    assert final_run.completed_at is not None

    @pytest.mark.asyncio
    async def test_cancellation_persists_correctly(self, orchestrator, mock_services):
        """Test that cancellation persists correctly."""
        run = orchestrator.create_run(strategy_name="test_strategy")

        from backend.services.aeroing4.models import StepResult

        # Mock slow validation to allow cancellation
        import asyncio

        async def slow_validation(*args, **kwargs):
            await asyncio.sleep(0.1)
            return StepResult(
                step_name="validation",
                status=AeRoing4StepStatus.PASSED,
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                data={"valid": True}
            )

        mock_validation = AsyncMock()
        mock_validation.execute.side_effect = slow_validation

        with patch("backend.services.aeroing4.orchestrator.ValidationStep", return_value=mock_validation):
            await orchestrator.start_run(run.run_id)

            # Cancel immediately
            await asyncio.sleep(0.01)
            await orchestrator.cancel_run(run.run_id)

            # Wait for task to complete
            try:
                await orchestrator._active_task
            except asyncio.CancelledError:
                pass

            final_run = orchestrator.get_run(run.run_id)
            assert final_run is not None
            assert final_run.status == AeRoing4RunStatus.CANCELLED
            assert final_run.completed_at is not None

    @pytest.mark.asyncio
    async def test_no_signal_activity_completes(self, orchestrator, mock_services):
        """Test that NO_SIGNAL_ACTIVITY still completes the run."""
        run = orchestrator.create_run(strategy_name="test_strategy")

        from backend.services.aeroing4.models import StepResult

        # Mock validation to pass
        mock_validation_result = StepResult(
            step_name="validation",
            status=AeRoing4StepStatus.PASSED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            data={"valid": True}
        )

        # Mock data preparation to pass
        mock_data_result = StepResult(
            step_name="data_preparation",
            status=AeRoing4StepStatus.PASSED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            data={}
        )

        # Mock smoke backtest with no trades
        mock_smoke_result = StepResult(
            step_name="smoke_backtest",
            status=AeRoing4StepStatus.PASSED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            data={"outcome": SmokeBacktestOutcome.NO_SIGNAL_ACTIVITY.value}
        )

        # Mock version manager for smoke backtest step
        mock_pointer = Mock()
        mock_pointer.accepted_version_id = "v1"
        mock_services.version_manager.get_current_pointer.return_value = mock_pointer

        with patch("backend.services.aeroing4.orchestrator.ValidationStep") as mock_validation_class:
            mock_validation = AsyncMock()
            mock_validation.execute.return_value = mock_validation_result
            mock_validation_class.return_value = mock_validation

            with patch("backend.services.aeroing4.orchestrator.DataPreparationStep") as mock_data_class:
                mock_data = AsyncMock()
                mock_data.execute.return_value = mock_data_result
                mock_data_class.return_value = mock_data

                with patch("backend.services.aeroing4.orchestrator.SmokeBacktestStep") as mock_smoke_class:
                    mock_smoke = AsyncMock()
                    mock_smoke.execute.return_value = mock_smoke_result
                    mock_smoke_class.return_value = mock_smoke

                    await orchestrator.start_run(run.run_id)
                    await orchestrator._active_task

                    final_run = orchestrator.get_run(run.run_id)
                    assert final_run is not None
                    assert final_run.status == AeRoing4RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execution_failure_fails_run(self, orchestrator, mock_services):
        """Test that EXECUTION_FAILURE fails the run."""
        run = orchestrator.create_run(strategy_name="test_strategy")

        from backend.services.aeroing4.models import StepResult

        # Mock validation to pass
        mock_validation_result = StepResult(
            step_name="validation",
            status=AeRoing4StepStatus.PASSED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            data={"valid": True}
        )

        # Mock data preparation to pass
        mock_data_result = StepResult(
            step_name="data_preparation",
            status=AeRoing4StepStatus.PASSED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            data={}
        )

        # Mock smoke backtest with execution failure
        mock_smoke_result = StepResult(
            step_name="smoke_backtest",
            status=AeRoing4StepStatus.FAILED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            data={"outcome": SmokeBacktestOutcome.EXECUTION_FAILURE.value},
            error="Execution failed"
        )

        # Mock version manager for smoke backtest step
        mock_pointer = Mock()
        mock_pointer.accepted_version_id = "v1"
        mock_services.version_manager.get_current_pointer.return_value = mock_pointer

        with patch("backend.services.aeroing4.orchestrator.ValidationStep") as mock_validation_class:
            mock_validation = AsyncMock()
            mock_validation.execute.return_value = mock_validation_result
            mock_validation_class.return_value = mock_validation

            with patch("backend.services.aeroing4.orchestrator.DataPreparationStep") as mock_data_class:
                mock_data = AsyncMock()
                mock_data.execute.return_value = mock_data_result
                mock_data_class.return_value = mock_data

                with patch("backend.services.aeroing4.orchestrator.SmokeBacktestStep") as mock_smoke_class:
                    mock_smoke = AsyncMock()
                    mock_smoke.execute.return_value = mock_smoke_result
                    mock_smoke_class.return_value = mock_smoke

                    await orchestrator.start_run(run.run_id)
                    await orchestrator._active_task

                    final_run = orchestrator.get_run(run.run_id)
                    assert final_run is not None
                    assert final_run.status == AeRoing4RunStatus.FAILED
