"""Tests for enhanced optimizer session/trial execution services."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.optimizer_errors import SessionAlreadyRunningError, TrialExecutionError
from backend.models import (
    OptimizerParameterMode,
    OptimizerScoreMetric,
    OptimizerSession,
    OptimizerSessionConfig,
    OptimizerSessionPhase,
    OptimizerTrial,
    OptimizerTrialMetrics,
    OptimizerTrialStatus,
    ParameterSearchSpace,
    ParameterSearchType,
    ParamsSchema,
    SearchStrategy,
    StartOptimizerRequest,
)
from backend.services.optimizer.enhanced_session_manager import EnhancedSessionManager
from backend.services.optimizer.enhanced_trial_execution import EnhancedTrialExecutionService
from backend.services.optimizer.session_validator import SessionValidator


def _params(version_id: str, buy_window: int = 10) -> ParamsSchema:
    return ParamsSchema(
        strategy_name="DemoStrategy",
        version_id=version_id,
        extracted_at=datetime.now(tz=UTC),
        pair_list=["BTC/USDT"],
        buy_params={"buy_window": buy_window},
        sell_params={},
        protection_params={},
        roi_table={},
        stoploss=-0.1,
        trailing_stop=False,
        trailing_stop_positive=None,
        trailing_stop_positive_offset=None,
        trailing_only_offset_is_reached=None,
        custom_params={},
    )


def _space() -> ParameterSearchSpace:
    return ParameterSearchSpace(
        name="buy_window",
        param_type=ParameterSearchType.INT,
        space="buy",
        default=10,
        enabled=True,
        min_value=5,
        max_value=20,
        step=1,
    )


def _session(**overrides) -> OptimizerSession:
    base = {
        "session_id": "opt-1",
        "strategy_name": "DemoStrategy",
        "config": OptimizerSessionConfig(
            strategy_name="DemoStrategy",
            timeframe="1h",
            timerange="20240101-20240131",
            pairs=["BTC/USDT"],
            config_file="config.json",
            total_trials=1,
            search_spaces=[_space()],
            score_metric=OptimizerScoreMetric.COMPOSITE,
        ),
        "phase": OptimizerSessionPhase.RUNNING,
        "created_at": datetime.now(tz=UTC),
        "started_at": datetime.now(tz=UTC),
        "total_trials": 1,
    }
    base.update(overrides)
    return OptimizerSession(**base)


def _trial(**overrides) -> OptimizerTrial:
    base = {
        "trial_number": 1,
        "status": OptimizerTrialStatus.RUNNING,
        "parameters": {"buy_window": 14},
        "started_at": datetime.now(tz=UTC),
    }
    base.update(overrides)
    return OptimizerTrial(**base)


def _service(*, run_status="completed", timeout_seconds=3600):
    parent = _params("v1", 10)
    trial_params = _params("trial-v1", 14)
    backtest_runner = MagicMock()
    backtest_runner.is_busy.return_value = False
    backtest_runner.queue_strategy_backtest = AsyncMock(return_value="run-1")
    backtest_runner.active_run_id = None
    backtest_runner.cancel = MagicMock()

    run_repository = MagicMock()
    run_repository.load_metadata.return_value = SimpleNamespace(run_status=run_status)

    version_manager = MagicMock()
    version_manager.get_current_pointer.return_value = SimpleNamespace(accepted_version_id="v1")
    version_manager.load_strategy_source.return_value = "class DemoStrategy: pass\n"
    version_manager.load_params.return_value = parent
    version_manager.reject_version = MagicMock()

    trial_executor = MagicMock()
    trial_executor.build_trial_params.return_value = trial_params
    trial_executor.create_trial_version.return_value = SimpleNamespace(version_id="trial-v1")
    trial_executor.extract_run_failure_reason.return_value = "freqtrade failed"
    trial_executor.extract_trial_metrics.return_value = OptimizerTrialMetrics(score=9.5, net_profit_pct=4.2)

    registry = SimpleNamespace(get_strategy=MagicMock(return_value=SimpleNamespace(strategy_name="DemoStrategy")))

    service = EnhancedTrialExecutionService(
        backtest_runner=backtest_runner,
        run_repository=run_repository,
        version_manager=version_manager,
        trial_executor=trial_executor,
        validator=SessionValidator(),
        registry=registry,
        settings_store=SimpleNamespace(load=MagicMock(return_value=SimpleNamespace(default_config_file_path="config.json"))),
        trial_timeout_seconds=timeout_seconds,
    )
    return service, backtest_runner, run_repository, version_manager, trial_executor, registry


def test_successful_trial_runs_real_backtest_flow_and_cleans_temp_version():
    service, backtest_runner, _repo, version_manager, trial_executor, registry = _service()

    run_id, error = asyncio.run(service.run_existing_trial_backtest(_session(), _trial()))

    assert (run_id, error) == ("run-1", None)
    registry.get_strategy.assert_called_with("DemoStrategy")
    version_manager.load_strategy_source.assert_called_with("DemoStrategy", "v1")
    trial_executor.build_trial_params.assert_called_once()
    backtest_runner.queue_strategy_backtest.assert_awaited_once()
    version_manager.reject_version.assert_called_with("trial-v1", "Trial completed")


def test_failed_backtest_returns_failure_reason_and_cleans_temp_version():
    service, _runner, _repo, version_manager, trial_executor, _registry = _service(run_status="failed")

    run_id, error = asyncio.run(service.run_existing_trial_backtest(_session(), _trial()))

    assert run_id is None
    assert error == "Backtest failed: freqtrade failed"
    trial_executor.extract_run_failure_reason.assert_called_with("run-1")
    version_manager.reject_version.assert_called_with("trial-v1", "Trial completed")


def test_execute_trial_raises_when_metrics_are_missing():
    service, _runner, _repo, _version_manager, trial_executor, _registry = _service()
    service.run_existing_trial_backtest = AsyncMock(return_value=("run-1", None))
    trial_executor.extract_trial_metrics.return_value = None

    with pytest.raises(TrialExecutionError) as exc_info:
        asyncio.run(
            service.execute_trial(
                session=_session(),
                trial_number=1,
                trial_parameters={"buy_window": 14},
                strategy_source="class DemoStrategy: pass\n",
                parent_version_id="v1",
            )
        )

    assert "Failed to extract metrics" in str(exc_info.value)


def test_trial_timeout_cancels_active_backtest_and_rejects_temp_version():
    service, backtest_runner, _repo, version_manager, _trial_executor, _registry = _service(timeout_seconds=0.01)
    backtest_runner.active_run_id = "active-run"

    async def slow_backtest(*_args, **_kwargs):
        await asyncio.sleep(1)
        return "late-run"

    service._execute_backtest_with_timeout = slow_backtest

    run_id, error = asyncio.run(service.run_existing_trial_backtest(_session(), _trial()))

    assert run_id is None
    assert "timed out" in error
    backtest_runner.cancel.assert_called_with("active-run")
    version_manager.reject_version.assert_called_with("trial-v1", "Trial completed")


def test_cancel_requested_while_waiting_for_busy_runner_short_circuits():
    service, backtest_runner, _repo, version_manager, trial_executor, _registry = _service()
    backtest_runner.is_busy.return_value = True

    run_id, error = asyncio.run(
        service.run_existing_trial_backtest(
            _session(),
            _trial(),
            cancel_requested=lambda: True,
        )
    )

    assert (run_id, error) == (None, "Cancelled")
    trial_executor.create_trial_version.assert_not_called()
    version_manager.reject_version.assert_not_called()


def test_session_validator_handles_enum_strings_and_naive_datetimes():
    session = _session(
        phase="running",
        started_at=datetime.now() - timedelta(seconds=5),
        completed_trials=1,
        failed_trials=1,
        trials=[
            _trial(status="completed", metrics=OptimizerTrialMetrics(score=1)),
            _trial(trial_number=2, status="failed", parameters={}, error="boom"),
        ],
    )

    validator = SessionValidator()
    validator.validate_session_state(session)
    validator.validate_trial_consistency(session)
    validator.validate_session_for_operation(session, "cancel")


def test_enhanced_session_manager_does_not_swallow_active_running_conflict():
    active = _session(phase=OptimizerSessionPhase.RUNNING)
    store = SimpleNamespace(
        load_session=MagicMock(return_value=active),
        save_session=MagicMock(),
    )
    manager = EnhancedSessionManager(
        optimizer_store=store,
        registry=SimpleNamespace(get_strategy=MagicMock(return_value=SimpleNamespace(strategy_name="DemoStrategy"))),
        version_manager=SimpleNamespace(get_current_pointer=MagicMock(return_value=SimpleNamespace(accepted_version_id="v1"))),
    )
    manager._active_session_id = "opt-1"

    request = StartOptimizerRequest(
        strategy_name="DemoStrategy",
        timeframe="1h",
        timerange="20240101-20240131",
        pairs=["BTC/USDT"],
        config_file="config.json",
        total_trials=1,
        search_strategy=SearchStrategy.RANDOM,
        parameter_mode=OptimizerParameterMode.MANUAL,
        search_spaces=[_space()],
    )

    with pytest.raises(SessionAlreadyRunningError):
        asyncio.run(manager.create_session(request))
