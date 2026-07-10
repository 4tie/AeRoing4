"""Regression tests for optimizer router workflow contracts."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from backend.api.routers import optimizer as optimizer_router
from backend.api.models import OptimizerApiRequest
from backend.api.session_store import SessionStore
from backend.core.errors import BackendError
from backend.services.optimizer import api_service as optimizer_api
from backend.models import (
    OptimizerScoreMetric,
    OptimizerSession,
    OptimizerSessionConfig,
    OptimizerSessionPhase,
    OptimizerTrial,
    OptimizerTrialMetrics,
    OptimizerTrialStatus,
    ParameterSearchSpace,
    ParameterSearchType,
)


def _space(name: str, space: str) -> ParameterSearchSpace:
    return ParameterSearchSpace(
        name=name,
        param_type=ParameterSearchType.INT,
        space=space,
        default=10,
        enabled=True,
        min_value=1,
        max_value=30,
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
            search_spaces=[_space("buy_window", "buy"), _space("sell_window", "sell")],
        ),
        "phase": OptimizerSessionPhase.COMPLETED,
        "created_at": datetime.now(tz=UTC),
        "completed_at": datetime.now(tz=UTC),
        "total_trials": 1,
        "completed_trials": 1,
        "failed_trials": 0,
        "best_trial_number": 1,
        "best_metrics": OptimizerTrialMetrics(score=12.5),
        "trials": [
            OptimizerTrial(
                trial_number=1,
                status=OptimizerTrialStatus.COMPLETED,
                parameters={"buy_window": 14, "sell_window": 22},
                run_id="run-1",
                metrics=OptimizerTrialMetrics(score=12.5, net_profit_pct=8.2),
            )
        ],
    }
    base.update(overrides)
    return OptimizerSession(**base)


def _payload(**overrides) -> dict:
    base = {
        "strategy_name": "DemoStrategy",
        "timerange": "20240101-20240131",
        "timeframe": "1h",
        "pairs": ["BTC/USDT"],
        "total_trials": 1,
        "search_strategy": "random",
        "parameter_mode": "manual",
        "score_metric": "composite",
        "max_open_trades": 1,
        "dry_run_wallet": 1000,
        "fee_rate": 0.001,
        "search_spaces": [
            {
                "name": "buy_window",
                "param_type": "int",
                "space": "buy",
                "default": 10,
                "enabled": True,
                "min_value": 5,
                "max_value": 20,
                "step": 1,
            }
        ],
    }
    base.update(overrides)
    return base


def _request(services: SimpleNamespace | None = None):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                services=services or _services(),
                session_store=SessionStore(),
            )
        )
    )


def _services() -> SimpleNamespace:
    session = _session()
    strategy_optimizer = MagicMock()
    strategy_optimizer.is_running.return_value = False
    strategy_optimizer.start_session = AsyncMock(return_value=session)
    strategy_optimizer.build_search_spaces_from_strategy.return_value = [_space("buy_window", "buy")]
    strategy_optimizer.cancel_session = AsyncMock(
        return_value=session.model_copy(update={"phase": OptimizerSessionPhase.CANCELLED})
    )
    strategy_optimizer.trial_executor = SimpleNamespace(
        build_trial_params=MagicMock(return_value=SimpleNamespace(model_dump=lambda mode="json": {"buy": {"buy_window": 14}}))
    )

    version_manager = MagicMock()
    version_manager.get_current_pointer.return_value = SimpleNamespace(accepted_version_id="v1")
    version_manager.load_params.return_value = SimpleNamespace()
    version_manager.overwrite_accepted_params.return_value = {
        "version_params_path": "versions/DemoStrategy/v1/params.json",
        "version_source_path": "versions/DemoStrategy/v1/strategy.py",
        "live_source_path": "user_data/strategies/DemoStrategy.py",
        "live_sidecar_path": "user_data/strategies/DemoStrategy.json",
    }
    version_manager.apply_optimizer_trial_to_new_version.return_value = {"version_id": "candidate-1"}
    version_manager.preview_optimizer_trial_application.return_value = {"modified_json": {"buy": {"buy_window": 14}}}

    return SimpleNamespace(
        strategy_optimizer=strategy_optimizer,
        registry=SimpleNamespace(get_strategy=MagicMock(return_value=SimpleNamespace(strategy_name="DemoStrategy"))),
        version_manager=version_manager,
        settings_store=SimpleNamespace(load=MagicMock(return_value=SimpleNamespace(default_config_file_path="config.json"))),
        optimizer_store=SimpleNamespace(load_session=MagicMock(return_value=session), list_sessions=MagicMock(return_value=[])),
        backtest_runner=SimpleNamespace(is_busy=MagicMock(return_value=False)),
        run_repository=SimpleNamespace(),
        exported_trial_store=SimpleNamespace(append=MagicMock(return_value={"id": "export-1"}), list_all=MagicMock(return_value=[])),
    )


def _body(**overrides) -> OptimizerApiRequest:
    return OptimizerApiRequest(**_payload(**overrides))


def test_run_requires_pairs():
    services = _services()
    store = SessionStore()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            optimizer_router.run_optimizer(
                _body(pairs=[]),
                services=services,
                store=store,
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "At least one trading pair is required."


def test_run_returns_conflict_when_optimizer_is_active():
    services = _services()
    services.strategy_optimizer.is_running.return_value = True
    store = SessionStore()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            optimizer_router.run_optimizer(
                _body(),
                services=services,
                store=store,
            )
        )

    assert exc_info.value.status_code == 409
    assert "already running" in exc_info.value.detail


def test_run_returns_conflict_when_strategy_has_no_accepted_version():
    services = _services()
    services.version_manager.get_current_pointer.return_value = None
    store = SessionStore()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            optimizer_router.run_optimizer(
                _body(),
                services=services,
                store=store,
            )
        )

    assert exc_info.value.status_code == 409
    assert "has no accepted version" in exc_info.value.detail


def test_apply_trial_syncs_accepted_and_live_strategy_files():
    services = _services()

    result = asyncio.run(
        optimizer_router.apply_trial(
            optimizer_router.ApplyTrialRequest(
                strategy_name="DemoStrategy",
                parameters={"buy_window": 14},
            ),
            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=services))),
        )
    )

    services.strategy_optimizer.trial_executor.build_trial_params.assert_called_once()
    services.version_manager.overwrite_accepted_params.assert_called_once()
    assert result["ok"] is True
    assert result["accepted_version_id"] == "v1"
    assert result["written_paths"]["live_sidecar_path"].endswith("DemoStrategy.json")


def test_run_maps_invalid_search_spaces_to_bad_request():
    services = _services()
    store = SessionStore()
    bad_space = _payload()["search_spaces"][0] | {"param_type": "unsupported"}

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            optimizer_router.run_optimizer(
                _body(search_spaces=[bad_space]),
                services=services,
                store=store,
            )
        )

    assert exc_info.value.status_code == 400
    assert "Invalid optimizer search spaces" in exc_info.value.detail


def test_run_maps_backend_errors_to_http_exception():
    services = _services()
    services.registry.get_strategy.side_effect = BackendError("Strategy missing", status_code=404)
    store = SessionStore()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            optimizer_router.run_optimizer(
                _body(),
                services=services,
                store=store,
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Strategy missing"


def test_run_passes_vectorbt_config_to_optimizer_request(monkeypatch):
    services = _services()
    store = SessionStore()

    def close_background_task(coro):
        coro.close()
        return None

    monkeypatch.setattr(optimizer_router.asyncio, "create_task", close_background_task)

    body = _body(
        enable_vectorbt_screening=False,
        vectorbt_candidate_count=250,
        vectorbt_keep_ratio=0.25,
        vectorbt_timeout_seconds=45,
    )

    response = asyncio.run(
        optimizer_router.run_optimizer(
            body,
            services=services,
            store=store,
        )
    )

    assert response.status == "running"
    internal_request = services.strategy_optimizer.start_session.await_args.args[0]
    assert internal_request.enable_vectorbt_screening is False
    assert internal_request.vectorbt_candidate_count == 250
    assert internal_request.vectorbt_keep_ratio == 0.25
    assert internal_request.vectorbt_timeout_seconds == 45


def test_session_fetch_returns_saved_session():
    services = _services()
    request = _request(services)

    response = asyncio.run(optimizer_router.get_optimizer_session("opt-1", request))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["session_id"] == "opt-1"
    services.optimizer_store.load_session.assert_called_with("opt-1")


def test_session_response_sanitizer_replaces_non_finite_numbers():
    payload = {
        "score": float("nan"),
        "top_candidates": [
            {"metrics": {"profit_factor": float("inf"), "sharpe_ratio": float("-inf")}},
            {"metrics": {"score": 1.25}},
        ],
    }

    assert optimizer_router._json_safe(payload) == {
        "score": None,
        "top_candidates": [
            {"metrics": {"profit_factor": None, "sharpe_ratio": None}},
            {"metrics": {"score": 1.25}},
        ],
    }


def test_best_trial_params_routes_unprefixed_values_by_search_space():
    request = _request()

    body = asyncio.run(optimizer_router.get_best_trial_params("opt-1", request))

    assert body["params"]["buy"] == {"buy_window": 14}
    assert body["params"]["sell"] == {"sell_window": 22}


def test_promote_best_accepts_enum_or_string_phase_and_trial_status():
    services = _services()
    trial = SimpleNamespace(
        trial_number=1,
        status=OptimizerTrialStatus.COMPLETED,
        parameters={"buy_window": 14},
        run_id="run-1",
        metrics=OptimizerTrialMetrics(score=12.5),
    )
    services.optimizer_store.load_session.return_value = SimpleNamespace(
        session_id="opt-1",
        config=SimpleNamespace(strategy_name="DemoStrategy"),
        phase=OptimizerSessionPhase.COMPLETED,
        best_trial_number=1,
        trials=[trial],
    )
    request = _request(services)

    body = asyncio.run(optimizer_router.promote_best_trial_to_candidate("opt-1", request))

    assert body["candidate_version_id"] == "candidate-1"


def test_cancel_returns_normalized_phase():
    services = _services()
    services.strategy_optimizer.cancel_session = AsyncMock(
        return_value=SimpleNamespace(phase=OptimizerSessionPhase.CANCELLED)
    )
    request = _request(services)

    body = asyncio.run(optimizer_router.cancel_optimizer_session("opt-1", request))

    assert body["phase"] == "cancelled"


def test_monitor_maps_completed_and_failed_sessions(monkeypatch):
    async def fast_sleep(_seconds):
        return None

    monkeypatch.setattr(optimizer_api.asyncio, "sleep", fast_sleep)

    for phase, expected_status in [
        (OptimizerSessionPhase.COMPLETED, "completed"),
        (OptimizerSessionPhase.FAILED, "failed"),
    ]:
        session = _session(phase=phase, stop_reason="done")
        services = SimpleNamespace(optimizer_store=SimpleNamespace(load_session=lambda _session_id: session))
        store = SessionStore()
        api_record = store.create("optimizer")

        asyncio.run(optimizer_router._monitor_optimizer(services, store, api_record.session_id, session.session_id))

        record = store.get(api_record.session_id)
        assert record.status == expected_status
        assert record.result["phase"] == phase.value
        assert record.result["optimizer_session_id"] == session.session_id
