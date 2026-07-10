from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

import backend.services.auto_quant.pipeline as pl
from backend.api.routers.agent import (
    AgentUiStatePayload,
    get_agent_auto_quant_run,
    get_agent_backtest_run,
    get_agent_context,
    get_agent_optimizer_run,
    get_agent_strategy_files,
    update_agent_ui_state,
)
from backend.models import (
    OptimizerScoreMetric,
    OptimizerSession,
    OptimizerSessionConfig,
    OptimizerSessionPhase,
    OptimizerTrial,
    OptimizerTrialMetrics,
    OptimizerTrialStatus,
    RunMetadata,
    RunStatus,
    RunType,
)
from backend.services.storage.optimizer_store import OptimizerStore
from backend.services.storage.run_repository import RunRepository
from backend.utils import atomic_write_json


class DummyLogBroadcaster:
    def __init__(self) -> None:
        self.history = ["backend ready", "trial complete"]


class RouteResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self.payload


class DirectAgentClient:
    def __init__(self, request) -> None:
        self.request = request

    def post(self, path: str, json: dict) -> RouteResponse:
        async def _run() -> dict:
            if path == "/api/agent/ui-state":
                return await update_agent_ui_state(AgentUiStatePayload(**json), self.request)
            raise AssertionError(f"Unhandled POST path: {path}")

        return _response_from_async(_run)

    def get(self, path: str) -> RouteResponse:
        async def _run() -> dict:
            parsed = urlparse(path)
            query = parse_qs(parsed.query)
            clean_path = parsed.path
            if clean_path == "/api/agent/context":
                return await get_agent_context(
                    self.request,
                    active_tab=None,
                    active_panel=None,
                    strategy_name=None,
                    auto_quant_run_id=None,
                    optimizer_session_id=None,
                    optimizer_trial_number=None,
                    backtest_run_id=None,
                    api_session_id=None,
                )
            if clean_path.startswith("/api/agent/runs/auto-quant/"):
                return await get_agent_auto_quant_run(clean_path.rsplit("/", 1)[-1], self.request)
            if clean_path.startswith("/api/agent/runs/optimizer/"):
                trial = query.get("optimizer_trial_number", [None])[0]
                return await get_agent_optimizer_run(
                    clean_path.rsplit("/", 1)[-1],
                    self.request,
                    optimizer_trial_number=int(trial) if trial is not None else None,
                )
            if clean_path.startswith("/api/agent/runs/backtest/"):
                return await get_agent_backtest_run(clean_path.rsplit("/", 1)[-1], self.request)
            if clean_path.startswith("/api/agent/files/strategy/"):
                return await get_agent_strategy_files(clean_path.rsplit("/", 1)[-1], self.request)
            raise AssertionError(f"Unhandled GET path: {path}")

        return _response_from_async(_run)


def _response_from_async(func) -> RouteResponse:
    try:
        return RouteResponse(asyncio.run(func()))
    except HTTPException as exc:
        return RouteResponse({"detail": exc.detail}, status_code=exc.status_code)


def _client(tmp_path: Path):

    strategies_dir = tmp_path / "strategies"
    user_data_dir = tmp_path / "user_data"
    strategies_dir.mkdir(parents=True, exist_ok=True)
    user_data_dir.mkdir(parents=True, exist_ok=True)

    settings = SimpleNamespace(
        strategies_directory_path=str(strategies_dir),
        user_data_directory_path=str(user_data_dir),
    )

    services = MagicMock()
    services.root_dir = tmp_path
    services.settings_store.load.return_value = settings
    services.optimizer_store = OptimizerStore(user_data_dir / "optimizer_sessions")
    services.run_repository = RunRepository(user_data_dir / "backtest_results")
    services.run_detail.side_effect = services.run_repository.load_detail
    services.version_manager = None
    services.strategy_optimizer.get_active_session_id.return_value = None
    services.backtest_runner.get_current_run_id.return_value = None

    state = SimpleNamespace()
    state.services = services
    state.log_broadcaster = DummyLogBroadcaster()
    state.session_store = MagicMock()
    state.session_store.get.return_value = None
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    return DirectAgentClient(request), services, settings


def test_ui_state_persists_and_context_handles_no_active_run(tmp_path):
    client, _, _ = _client(tmp_path)

    response = client.post(
        "/api/agent/ui-state",
        json={"active_tab": "optimizer", "strategy_name": "DemoStrategy"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "agent_ui_state_v1"
    assert body["active_tab"] == "optimizer"

    context = client.get("/api/agent/context").json()
    assert context["schema_version"] == "agent_context_v1"
    assert context["app"]["active_tab"] == "optimizer"
    assert context["active"]["strategy_name"] == "DemoStrategy"
    assert "No active run or optimizer session is selected." in context["warnings"]


def test_auto_quant_context_includes_bounded_event_history(tmp_path):
    client, _, settings = _client(tmp_path)
    user_data = Path(settings.user_data_directory_path)

    with patch("backend.services.auto_quant.pipeline._save_state_to_disk"):
        run_id = pl.create_run(
            strategy="ObservedStrategy",
            timeframe="5m",
            in_sample_range="20230101-20231201",
            out_sample_range="20240101-20240601",
            exchange="binance",
            config_file=str(tmp_path / "config.json"),
            freqtrade_path="freqtrade",
            user_data_dir=str(user_data),
        )

    for idx in range(505):
        pl._emit(run_id, 1, "running", f"event {idx}", idx, {"idx": idx})

    response = client.get(f"/api/agent/runs/auto-quant/{run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["strategy_name"] == "ObservedStrategy"
    assert body["events"]["source"] == "auto_quant_event_history"
    assert len(body["events"]["recent"]) == 200
    assert len(pl.get_event_history(run_id, limit=1000)) == 500


def test_optimizer_context_copies_best_metrics_from_session(tmp_path):
    client, services, _ = _client(tmp_path)
    session = OptimizerSession(
        session_id="opt-1",
        strategy_name="DemoStrategy",
        config=OptimizerSessionConfig(
            strategy_name="DemoStrategy",
            timeframe="1h",
            timerange="20240101-20240201",
            pairs=["BTC/USDT"],
            config_file="config.json",
            score_metric=OptimizerScoreMetric.COMPOSITE,
        ),
        phase=OptimizerSessionPhase.COMPLETED,
        created_at=datetime.now(tz=UTC),
        completed_at=datetime.now(tz=UTC),
        total_trials=1,
        completed_trials=1,
        best_trial_number=1,
        best_metrics=OptimizerTrialMetrics(score=1.25, profit_factor=1.8),
        trials=[
            OptimizerTrial(
                trial_number=1,
                status=OptimizerTrialStatus.COMPLETED,
                parameters={"buy_window": 14},
                metrics=OptimizerTrialMetrics(score=1.25, profit_factor=1.8),
            )
        ],
    )
    services.optimizer_store.save_session(session)

    response = client.get("/api/agent/runs/optimizer/opt-1?optimizer_trial_number=1")

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "opt-1"
    assert body["metrics"]["source"] == "optimizer_session.best_metrics"
    assert body["metrics"]["best_metrics"]["profit_factor"] == 1.8
    assert body["selected_trial_number"] == 1
    assert body["selected_trial"]["parameters"]["buy_window"] == 14


def test_backtest_context_copies_persisted_summary_and_logs(tmp_path):
    client, services, _ = _client(tmp_path)
    run_id = "bt-1"
    run_dir = services.run_repository.run_dir("DemoStrategy", run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    metadata = RunMetadata(
        run_id=run_id,
        strategy_name="DemoStrategy",
        strategy_version_id="v1",
        parent_version_id=None,
        baseline_run_id=None,
        run_type=RunType.BASELINE,
        run_status=RunStatus.COMPLETED,
        created_at=datetime.now(tz=UTC),
        completed_at=datetime.now(tz=UTC),
        freqtrade_exit_code=0,
        config_file="config.json",
        timerange="20240101-20240201",
        timeframe="1h",
        pairs=["BTC/USDT"],
        max_open_trades=1,
    )
    atomic_write_json(run_dir / "metadata.json", metadata.model_dump(mode="json"))
    atomic_write_json(run_dir / "pair_results.json", [])
    atomic_write_json(
        run_dir / "trades.json",
        [
            {
                "pair": "BTC/USDT",
                "open_date": "2024-01-01 00:00:00",
                "close_date": "2024-01-01 01:00:00",
                "profit_ratio": 0.01,
            }
            for _ in range(35)
        ],
    )
    atomic_write_json(
        run_dir / "parsed_summary.json",
        {
            "run_id": run_id,
            "starting_balance": 1000,
            "final_balance": 1100,
            "net_profit_currency": 100,
            "net_profit_pct": 10,
            "total_trades": 4,
            "trades_per_day": 1,
            "win_rate_pct": 75,
            "loss_rate_pct": 25,
            "max_drawdown_pct": 3,
            "max_drawdown_currency": 30,
            "avg_trade_duration_minutes": 20,
            "profit_factor": 1.6,
            "expectancy": 0.2,
            "sharpe_ratio": 1.1,
            "sortino_ratio": 1.2,
            "calmar_ratio": 1.3,
            "exit_reason_distribution": [],
        },
    )
    (run_dir / "logs.txt").write_text("line one\nline two\n", encoding="utf-8")

    response = client.get(f"/api/agent/runs/backtest/{run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["parsed_summary"]["source"] == "parsed_summary.json"
    assert body["metrics"]["parsed_summary"]["value"]["profit_factor"] == 1.6
    assert body["metrics"]["trades"]["value"]["total"] == 35
    assert body["metrics"]["trades"]["value"]["sample_count"] == 30
    assert body["metrics"]["trades"]["value"]["truncated"] is True
    assert body["logs"]["recent"] == ["line one", "line two"]


def test_strategy_file_endpoint_is_allowlisted(tmp_path):
    client, _, settings = _client(tmp_path)
    strategy_path = Path(settings.strategies_directory_path) / "DemoStrategy.py"
    strategy_path.write_text("class DemoStrategy:\n    pass\n", encoding="utf-8")

    response = client.get("/api/agent/files/strategy/DemoStrategy")

    assert response.status_code == 200
    body = response.json()
    assert body["content"]["python"].startswith("class DemoStrategy")

    bad_response = client.get("/api/agent/files/strategy/DemoStrategy.py")
    assert bad_response.status_code == 400


def test_context_includes_strategy_version_metadata(tmp_path):
    client, services, settings = _client(tmp_path)
    strategy_path = Path(settings.strategies_directory_path) / "DemoStrategy.py"
    strategy_path.write_text("class DemoStrategy:\n    pass\n", encoding="utf-8")

    class VersionRecord(SimpleNamespace):
        def to_dict(self):
            return dict(self.__dict__)

    services.version_manager = SimpleNamespace(
        get_current_pointer=lambda name: VersionRecord(
            strategy_name=name,
            accepted_version_id="v001",
            accepted_at="2026-06-15T00:00:00Z",
        ),
        load_params=lambda name, version_id: VersionRecord(
            strategy_name=name,
            version_id=version_id,
            buy_params={"buy_window": 14},
        ),
        list_versions=lambda name: [
            {"strategy_name": name, "version_id": "v001", "acceptance_status": "accepted"},
            {"strategy_name": name, "version_id": "v002", "acceptance_status": "candidate"},
        ],
    )

    client.post("/api/agent/ui-state", json={"active_tab": "strategy-editor", "strategy_name": "DemoStrategy"})
    response = client.get("/api/agent/context")

    assert response.status_code == 200
    versions = response.json()["strategy"]["versions"]
    assert versions["current_accepted"]["accepted_version_id"] == "v001"
    assert versions["accepted_params"]["buy_params"]["buy_window"] == 14
    assert versions["candidate_versions"][0]["version_id"] == "v002"
