"""Tests for AeRoing4 state store."""

import json
import tempfile
from pathlib import Path

import pytest

from backend.services.aeroing4.models import (
    AeRoing4Run,
    AeRoing4RunStatus,
    AeRoing4StepStatus,
    StepResult,
)
from backend.services.aeroing4.state_store import AeRoing4StateStore


@pytest.fixture
def temp_runs_root():
    """Create a temporary directory for test runs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def state_store(temp_runs_root):
    """Create a state store with temporary directory."""
    return AeRoing4StateStore(temp_runs_root)


class TestAeRoing4StateStore:
    """Test AeRoing4StateStore functionality."""

    def test_create_run(self, state_store):
        """Test creating a new run."""
        run = state_store.create_run(
            strategy_name="test_strategy",
            timeframe="5m",
            smoke_timerange="20240101-20240131",
            smoke_pairs=["BTC/USDT", "ETH/USDT"],
        )

        assert run.strategy_name == "test_strategy"
        assert run.timeframe == "5m"
        assert run.smoke_timerange == "20240101-20240131"
        assert run.smoke_pairs == ["BTC/USDT", "ETH/USDT"]
        assert run.status == AeRoing4RunStatus.PENDING
        assert run.current_step == "validation"
        assert run.run_id is not None

    def test_persist_and_reload_run(self, state_store):
        """Test persisting and reloading a run."""
        run = state_store.create_run(strategy_name="test_strategy")
        run_id = run.run_id

        # Modify run
        run.mark_running()
        state_store.save_run(run)

        # Reload
        reloaded = state_store.load_run(run_id)

        assert reloaded is not None
        assert reloaded.run_id == run_id
        assert reloaded.status == AeRoing4RunStatus.RUNNING
        assert reloaded.strategy_name == "test_strategy"

    def test_atomic_state_update(self, state_store):
        """Test atomic state update."""
        run = state_store.create_run(strategy_name="test_strategy")
        run_id = run.run_id

        # Update via state store
        updated = state_store.update_run(run_id, status=AeRoing4RunStatus.RUNNING)

        assert updated is not None
        assert updated.status == AeRoing4RunStatus.RUNNING

        # Verify persistence
        reloaded = state_store.load_run(run_id)
        assert reloaded.status == AeRoing4RunStatus.RUNNING

    def test_unknown_run_id(self, state_store):
        """Test loading unknown run ID returns None."""
        run = state_store.load_run("unknown_id")
        assert run is None

    def test_list_runs(self, state_store):
        """Test listing runs."""
        # Create multiple runs
        run1 = state_store.create_run(strategy_name="strategy1")
        run2 = state_store.create_run(strategy_name="strategy2")

        runs = state_store.list_runs()

        assert len(runs) == 2
        # Should be sorted by created_at descending
        assert runs[0].run_id == run2.run_id
        assert runs[1].run_id == run1.run_id

    def test_list_runs_filter_by_status(self, state_store):
        """Test listing runs filtered by status."""
        run1 = state_store.create_run(strategy_name="strategy1")
        run2 = state_store.create_run(strategy_name="strategy2")

        # Mark one as completed
        run1.mark_completed()
        state_store.save_run(run1)

        # Filter by completed status
        completed_runs = state_store.list_runs(status=AeRoing4RunStatus.COMPLETED)
        assert len(completed_runs) == 1
        assert completed_runs[0].run_id == run1.run_id

        # Filter by pending status
        pending_runs = state_store.list_runs(status=AeRoing4RunStatus.PENDING)
        assert len(pending_runs) == 1
        assert pending_runs[0].run_id == run2.run_id

    def test_delete_run(self, state_store):
        """Test deleting a run."""
        run = state_store.create_run(strategy_name="test_strategy")
        run_id = run.run_id

        # Verify run exists
        assert state_store.load_run(run_id) is not None

        # Delete run
        result = state_store.delete_run(run_id)
        assert result is True

        # Verify run is gone
        assert state_store.load_run(run_id) is None

    def test_delete_unknown_run(self, state_store):
        """Test deleting unknown run returns False."""
        result = state_store.delete_run("unknown_id")
        assert result is False

    def test_active_run_management(self, state_store):
        """Test active run management."""
        run1 = state_store.create_run(strategy_name="strategy1")
        run2 = state_store.create_run(strategy_name="strategy2")

        # Set active run
        state_store.set_active_run(run1.run_id)
        assert state_store.get_active_run() == run1.run_id
        assert state_store.is_active_run(run1.run_id) is True
        assert state_store.is_active_run(run2.run_id) is False

        # Change active run
        state_store.set_active_run(run2.run_id)
        assert state_store.get_active_run() == run2.run_id
        assert state_store.is_active_run(run1.run_id) is False
        assert state_store.is_active_run(run2.run_id) is True

        # Clear active run
        state_store.set_active_run(None)
        assert state_store.get_active_run() is None
        assert state_store.is_active_run(run1.run_id) is False

    def test_step_result_persistence(self, state_store):
        """Test persisting step results."""
        run = state_store.create_run(strategy_name="test_strategy")

        step_result = StepResult(
            step_name="validation",
            status=AeRoing4StepStatus.PASSED,
            data={"valid": True, "class_name": "TestStrategy"},
        )

        run.update_step("validation", step_result)
        state_store.save_run(run)

        # Reload and verify
        reloaded = state_store.load_run(run.run_id)
        assert "validation" in reloaded.steps
        assert reloaded.steps["validation"].status == AeRoing4StepStatus.PASSED
        assert reloaded.steps["validation"].data["valid"] is True

    def test_mark_completed(self, state_store):
        """Test marking run as completed."""
        run = state_store.create_run(strategy_name="test_strategy")
        run.mark_completed()
        state_store.save_run(run)

        reloaded = state_store.load_run(run.run_id)
        assert reloaded.status == AeRoing4RunStatus.COMPLETED
        assert reloaded.completed_at is not None

    def test_mark_failed(self, state_store):
        """Test marking run as failed."""
        run = state_store.create_run(strategy_name="test_strategy")
        run.mark_failed("Test error")
        state_store.save_run(run)

        reloaded = state_store.load_run(run.run_id)
        assert reloaded.status == AeRoing4RunStatus.FAILED
        assert reloaded.error == "Test error"
        assert reloaded.completed_at is not None

    def test_mark_cancelled(self, state_store):
        """Test marking run as cancelled."""
        run = state_store.create_run(strategy_name="test_strategy")
        run.mark_cancelled()
        state_store.save_run(run)

        reloaded = state_store.load_run(run.run_id)
        assert reloaded.status == AeRoing4RunStatus.CANCELLED
        assert reloaded.completed_at is not None

    def test_atomic_write_prevents_corruption(self, state_store):
        """Test that atomic writes prevent corruption."""
        run = state_store.create_run(strategy_name="test_strategy")
        run_id = run.run_id

        # Save multiple times rapidly
        for i in range(10):
            run.update_step(f"step_{i}", StepResult(
                step_name=f"step_{i}",
                status=AeRoing4StepStatus.PASSED,
            ))
            state_store.save_run(run)

        # Verify final state is consistent
        reloaded = state_store.load_run(run_id)
        assert len(reloaded.steps) == 10
        assert all(
            step.status == AeRoing4StepStatus.PASSED
            for step in reloaded.steps.values()
        )
