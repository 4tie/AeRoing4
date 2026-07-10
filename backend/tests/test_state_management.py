"""State Management Tests

Tests for PipelineState, thread safety, memory leaks, and cleanup.
"""

import pytest
import asyncio
from backend.services.auto_quant.pipeline_modules.state import (
    PipelineState,
    StageState,
    create_run,
    get_state,
    get_queue,
    release_queue,
    request_cancel,
    list_runs,
    _states,
    _queues,
    _cancel_flags,
)


class TestStateManagement:
    """Test state management, thread safety, and cleanup."""

    def test_create_run_initializes_state(self):
        """Test that create_run properly initializes a new run state."""
        run_id = create_run(
            strategy="TestStrategy",
            timeframe="1h",
            in_sample_range="20240101-20240301",
            out_sample_range="20240301-20240401",
            exchange="binance",
            config_file="config.json",
            freqtrade_path="freqtrade",
            user_data_dir="/tmp/user_data",
        )
        
        assert run_id is not None
        assert run_id in _states
        assert run_id in _queues
        assert run_id in _cancel_flags
        
        state = get_state(run_id)
        assert state is not None
        assert state.strategy == "TestStrategy"
        assert state.status == "pending"
        assert state.current_stage == 0
        assert len(state.stages) == 6

    def test_queue_management(self):
        """Test queue creation and release."""
        run_id = create_run(
            strategy="TestStrategy",
            timeframe="1h",
            in_sample_range="20240101-20240301",
            out_sample_range="20240301-20240401",
            exchange="binance",
            config_file="config.json",
            freqtrade_path="freqtrade",
            user_data_dir="/tmp/user_data",
        )
        
        # Create a queue
        q1 = get_queue(run_id)
        assert q1 is not None
        assert len(_queues[run_id]) == 1
        
        # Create another queue
        q2 = get_queue(run_id)
        assert q2 is not None
        assert len(_queues[run_id]) == 2
        
        # Release one queue
        release_queue(run_id, q1)
        assert len(_queues[run_id]) == 1
        
        # Release non-existent queue (should not raise error)
        release_queue(run_id, asyncio.Queue())
        assert len(_queues[run_id]) == 1

    def test_cancel_flag_management(self):
        """Test cancel flag setting and checking."""
        run_id = create_run(
            strategy="TestStrategy",
            timeframe="1h",
            in_sample_range="20240101-20240301",
            out_sample_range="20240301-20240401",
            exchange="binance",
            config_file="config.json",
            freqtrade_path="freqtrade",
            user_data_dir="/tmp/user_data",
        )
        
        # Initially not cancelled
        from backend.services.auto_quant.pipeline_modules.state import _cancelled
        assert _cancelled(run_id) is False
        
        # Request cancel
        result = request_cancel(run_id)
        assert result is True
        assert _cancelled(run_id) is True
        
        # Request cancel for non-existent run
        result = request_cancel("non-existent-run-id")
        assert result is False

    def test_list_runs(self):
        """Test listing all runs."""
        # Clear existing states
        _states.clear()
        _queues.clear()
        _cancel_flags.clear()
        
        run_id1 = create_run(
            strategy="Strategy1",
            timeframe="1h",
            in_sample_range="20240101-20240301",
            out_sample_range="20240301-20240401",
            exchange="binance",
            config_file="config.json",
            freqtrade_path="freqtrade",
            user_data_dir="/tmp/user_data",
        )
        
        run_id2 = create_run(
            strategy="Strategy2",
            timeframe="4h",
            in_sample_range="20240101-20240301",
            out_sample_range="20240301-20240401",
            exchange="binance",
            config_file="config.json",
            freqtrade_path="freqtrade",
            user_data_dir="/tmp/user_data",
        )
        
        runs = list_runs()
        assert len(runs) == 2
        run_ids = [r["run_id"] for r in runs]
        assert run_id1 in run_ids
        assert run_id2 in run_ids

    def test_state_persistence_fields(self):
        """Test that all critical fields are included in state snapshot."""
        run_id = create_run(
            strategy="TestStrategy",
            timeframe="1h",
            in_sample_range="20240101-20240301",
            out_sample_range="20240301-20240401",
            exchange="binance",
            config_file="config.json",
            freqtrade_path="freqtrade",
            user_data_dir="/tmp/user_data",
            max_drawdown_threshold=30.0,
            min_win_rate=40.0,
        )
        
        state = get_state(run_id)
        assert state.max_drawdown_threshold == 0.3
        assert state.min_win_rate == 0.4
        assert state.retry_count == 0
        assert state.max_retries == 3
        assert state.hyperopt_loss == "ProfitLockinHyperOptLoss"
        assert state.hyperopt_spaces == ["stoploss", "roi"]
        assert state.hyperopt_epochs == 100

    def test_memory_leak_potential_queues(self):
        """Test that queues accumulate if not released (memory leak potential)."""
        run_id = create_run(
            strategy="TestStrategy",
            timeframe="1h",
            in_sample_range="20240101-20240301",
            out_sample_range="20240301-20240401",
            exchange="binance",
            config_file="config.json",
            freqtrade_path="freqtrade",
            user_data_dir="/tmp/user_data",
        )
        
        # Simulate multiple queue creations without releases
        for _ in range(10):
            get_queue(run_id)
        
        # Queues accumulate
        assert len(_queues[run_id]) == 10
        
        # This demonstrates potential memory leak if release_queue is not called

    def test_thread_safety_concurrent_access(self):
        """Test concurrent access to global state dictionaries (thread safety concern)."""
        # This test documents the thread safety concern
        # The global _states, _queues, _cancel_flags dictionaries are accessed
        # without explicit locking, which could cause race conditions in multi-threaded scenarios
        
        run_id = create_run(
            strategy="TestStrategy",
            timeframe="1h",
            in_sample_range="20240101-20240301",
            out_sample_range="20240301-20240401",
            exchange="binance",
            config_file="config.json",
            freqtrade_path="freqtrade",
            user_data_dir="/tmp/user_data",
        )
        
        # In a real multi-threaded scenario, concurrent access to these dicts
        # could cause race conditions. Consider using threading.Lock or asyncio.Lock.

    def test_cleanup_missing_completed_runs(self):
        """Test that completed runs are not automatically cleaned up (memory leak)."""
        # Create a run
        run_id = create_run(
            strategy="TestStrategy",
            timeframe="1h",
            in_sample_range="20240101-20240301",
            out_sample_range="20240301-20240401",
            exchange="binance",
            config_file="config.json",
            freqtrade_path="freqtrade",
            user_data_dir="/tmp/user_data",
        )
        
        # Mark as completed
        state = get_state(run_id)
        state.status = "completed"
        
        # Run still exists in memory
        assert run_id in _states
        assert run_id in _queues
        assert run_id in _cancel_flags
        
        # There's no automatic cleanup for completed runs
        # This could lead to memory accumulation over time

    def test_stage_state_transitions(self):
        """Test stage state transitions."""
        run_id = create_run(
            strategy="TestStrategy",
            timeframe="1h",
            in_sample_range="20240101-20240301",
            out_sample_range="20240301-20240401",
            exchange="binance",
            config_file="config.json",
            freqtrade_path="freqtrade",
            user_data_dir="/tmp/user_data",
        )
        
        state = get_state(run_id)
        
        # Initial state
        assert state.current_stage == 0
        assert state.stages[0].status == "pending"
        
        # Transition to running
        state.current_stage = 1
        state.stages[0].status = "running"
        state.stages[0].started_at = "2024-01-01T00:00:00Z"
        
        assert state.current_stage == 1
        assert state.stages[0].status == "running"
        
        # Transition to passed
        state.stages[0].status = "passed"
        state.stages[0].duration_s = 60.0
        
        assert state.stages[0].status == "passed"
        assert state.stages[0].duration_s == 60.0

    def test_retry_history_tracking(self):
        """Test retry history tracking for self-healing."""
        run_id = create_run(
            strategy="TestStrategy",
            timeframe="1h",
            in_sample_range="20240101-20240301",
            out_sample_range="20240301-20240401",
            exchange="binance",
            config_file="config.json",
            freqtrade_path="freqtrade",
            user_data_dir="/tmp/user_data",
        )
        
        state = get_state(run_id)
        
        # Add retry attempt
        state.retry_count = 1
        state.retry_history.append({
            "attempt": 0,
            "label": "Initial attempt",
            "loss": "ProfitLockinHyperOptLoss",
            "spaces": ["stoploss", "roi"],
            "epochs": 100,
            "profit": 0.05,
            "reason": "sensitivity",
            "passed": False,
        })
        
        assert state.retry_count == 1
        assert len(state.retry_history) == 1
        assert state.retry_history[0]["reason"] == "sensitivity"
