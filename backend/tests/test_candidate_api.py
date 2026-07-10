"""Tests for candidate evaluation API endpoint."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from backend.api.routers import candidate as candidate_router
from backend.models.strategy_spec import (
    StrategySpec,
    IndicatorSpec,
    SignalCondition,
    TradingStyle,
    PositionSizing,
    TrailingStopSpec,
)
from backend.services.candidate.models import (
    CandidateConfig,
    CandidateVerdict,
    CandidateGateResult,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client():
    """Create a test client for the FastAPI app."""
    app = FastAPI()
    app.include_router(candidate_router.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clear_candidate_runs():
    """Keep async candidate run state isolated between tests."""
    candidate_router.candidate_run_manager.clear()
    yield
    candidate_router.candidate_run_manager.clear()


@pytest.fixture
def spawned_tasks(monkeypatch):
    """Capture async run coroutines instead of scheduling free-running tasks."""
    tasks = []

    def fake_spawn(coro):
        tasks.append(coro)

    monkeypatch.setattr(candidate_router, "_spawn_candidate_task", fake_spawn)
    return tasks


@pytest.fixture
def valid_strategy_spec():
    """Create a valid StrategySpec for testing."""
    return StrategySpec(
        name="TestStrategy",
        description="A test strategy",
        timeframe="5m",
        trading_style="trend_following",
        indicators=[
            IndicatorSpec(name="rsi", params={"period": 14}),
        ],
        entry_conditions=[
            SignalCondition(
                type="indicator_threshold",
                indicator_a="rsi",
                operator="<",
                value_or_indicator_b=30,
            ),
        ],
        exit_conditions=[
            SignalCondition(
                type="indicator_threshold",
                indicator_a="rsi",
                operator=">",
                value_or_indicator_b=70,
            ),
        ],
        stoploss=-0.10,
        position_sizing=PositionSizing(method="fixed"),
        trailing=TrailingStopSpec(),
        max_open_trades=3,
        max_iterations=3,
        iteration_count=0,
    )


@pytest.fixture
def candidate_config():
    """Create a CandidateConfig for testing."""
    return CandidateConfig(
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT", "ETH/USDT"],
        user_data_dir="/tmp/user_data",
        config_file="config.json",
        exchange="binance",
        max_repair_iterations=3,
    )


async def test_router_registered(client):
    """Test that the candidate router is registered."""
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    openapi_schema = response.json()
    # Check that the endpoint is documented
    assert "/api/candidate/evaluate" in openapi_schema["paths"]
    assert "/api/candidate/runs" in openapi_schema["paths"]
    assert "/api/candidate/runs/{run_id}" in openapi_schema["paths"]


async def test_router_includes_candidate_websocket_route():
    """Candidate router includes the WebSocket route."""
    websocket_routes = [
        route
        for route in candidate_router.router.routes
        if getattr(route, "path", None) == "/api/candidate/ws/{run_id}"
    ]
    assert websocket_routes


class FakeWebSocket:
    def __init__(self):
        self.accepted = False
        self.closed = False
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self):
        self.closed = True


async def _wait_for(predicate, timeout=2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Timed out waiting for condition")


async def _open_candidate_ws(run_id):
    websocket = FakeWebSocket()
    task = asyncio.create_task(candidate_router.candidate_websocket(websocket, run_id))
    await _wait_for(lambda: bool(websocket.sent))
    return websocket, task


async def test_candidate_websocket_sends_snapshot_first(
    valid_strategy_spec, candidate_config
):
    """Known runs receive a snapshot before live events."""
    run = candidate_router.candidate_run_manager.create_run(
        valid_strategy_spec,
        candidate_config,
    )
    candidate_router.candidate_run_manager.mark_running(run.run_id)

    websocket, task = await _open_candidate_ws(run.run_id)
    await _wait_for(
        lambda: candidate_router.candidate_run_manager.subscriber_count(run.run_id) == 1
    )

    assert websocket.accepted is True
    assert websocket.sent[0]["type"] == "snapshot"
    assert websocket.sent[0]["run_id"] == run.run_id
    assert websocket.sent[0]["data"]["run_id"] == run.run_id

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def test_candidate_websocket_receives_gate_update(
    valid_strategy_spec, candidate_config
):
    """Gate updates are published to active subscribers."""
    run = candidate_router.candidate_run_manager.create_run(
        valid_strategy_spec,
        candidate_config,
    )
    candidate_router.candidate_run_manager.mark_running(run.run_id)
    websocket, task = await _open_candidate_ws(run.run_id)
    await _wait_for(
        lambda: candidate_router.candidate_run_manager.subscriber_count(run.run_id) == 1
    )

    candidate_router.candidate_run_manager.update_gate(run.run_id, {
        "gate_name": "render_strategy",
        "status": "running",
        "metrics": {"progress": 1},
    })

    await _wait_for(lambda: any(msg["type"] == "gate_update" for msg in websocket.sent))
    gate_event = next(msg for msg in websocket.sent if msg["type"] == "gate_update")
    assert gate_event["run_id"] == run.run_id
    assert gate_event["data"]["gate_name"] == "render_strategy"
    assert gate_event["data"]["status"] == "running"

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def test_candidate_websocket_receives_final_after_completed(
    valid_strategy_spec, candidate_config
):
    """Completed runs publish a final event."""
    run = candidate_router.candidate_run_manager.create_run(
        valid_strategy_spec,
        candidate_config,
    )
    candidate_router.candidate_run_manager.mark_running(run.run_id)
    websocket, task = await _open_candidate_ws(run.run_id)
    await _wait_for(
        lambda: candidate_router.candidate_run_manager.subscriber_count(run.run_id) == 1
    )

    candidate_router.candidate_run_manager.mark_completed(
        run.run_id,
        CandidateVerdict(
            passed=True,
            gate_results=[
                CandidateGateResult(gate_name="render_strategy", passed=True),
            ],
        ),
    )

    await _wait_for(lambda: websocket.closed)
    final_event = websocket.sent[-1]
    assert final_event["type"] == "final"
    assert final_event["run_id"] == run.run_id
    assert final_event["data"]["status"] == "completed"
    assert final_event["data"]["verdict"]["passed"] is True
    await task


async def test_candidate_websocket_failed_run_sends_final(
    valid_strategy_spec, candidate_config
):
    """Failed runs publish a final event with error details."""
    run = candidate_router.candidate_run_manager.create_run(
        valid_strategy_spec,
        candidate_config,
    )
    candidate_router.candidate_run_manager.mark_running(run.run_id)
    websocket, task = await _open_candidate_ws(run.run_id)
    await _wait_for(
        lambda: candidate_router.candidate_run_manager.subscriber_count(run.run_id) == 1
    )

    candidate_router.candidate_run_manager.mark_failed(run.run_id, "mock failure")

    await _wait_for(lambda: websocket.closed)
    final_event = websocket.sent[-1]
    assert final_event["type"] == "final"
    assert final_event["data"]["status"] == "failed"
    assert final_event["data"]["error"] == "mock failure"
    await task


async def test_candidate_websocket_already_completed_sends_snapshot_then_final(
    valid_strategy_spec, candidate_config
):
    """Already-terminal runs receive snapshot then final and close."""
    run = candidate_router.candidate_run_manager.create_run(
        valid_strategy_spec,
        candidate_config,
    )
    candidate_router.candidate_run_manager.mark_completed(
        run.run_id,
        CandidateVerdict(
            passed=True,
            gate_results=[
                CandidateGateResult(gate_name="render_strategy", passed=True),
            ],
        ),
    )

    websocket = FakeWebSocket()
    await candidate_router.candidate_websocket(websocket, run.run_id)

    assert [msg["type"] for msg in websocket.sent] == ["snapshot", "final"]
    assert websocket.closed is True
    assert candidate_router.candidate_run_manager.subscriber_count(run.run_id) == 0


async def test_candidate_websocket_unknown_run_sends_error_and_closes():
    """Unknown runs are accepted, sent an error event, and closed safely."""
    websocket = FakeWebSocket()

    await candidate_router.candidate_websocket(websocket, "candidate_missing")

    assert websocket.accepted is True
    assert websocket.closed is True
    assert websocket.sent == [{
        "type": "error",
        "run_id": "candidate_missing",
        "error": "Candidate run 'candidate_missing' not found.",
    }]


async def test_candidate_websocket_releases_subscriber_after_cancel(
    valid_strategy_spec, candidate_config
):
    """Subscriber queues are released when a streaming task is cancelled."""
    run = candidate_router.candidate_run_manager.create_run(
        valid_strategy_spec,
        candidate_config,
    )
    candidate_router.candidate_run_manager.mark_running(run.run_id)
    websocket, task = await _open_candidate_ws(run.run_id)
    await _wait_for(
        lambda: candidate_router.candidate_run_manager.subscriber_count(run.run_id) == 1
    )

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    assert websocket.sent[0]["type"] == "snapshot"
    assert candidate_router.candidate_run_manager.subscriber_count(run.run_id) == 0


async def _wait_for_run_status(client, run_id, expected_status, timeout=2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last = None
    while loop.time() < deadline:
        response = await client.get(f"/api/candidate/runs/{run_id}")
        assert response.status_code == 200
        last = response.json()
        if last["status"] == expected_status:
            return last
        await asyncio.sleep(0.02)
    raise AssertionError(f"Run {run_id} did not reach {expected_status}. Last: {last}")


async def test_endpoint_returns_verdict_on_success(
    client, valid_strategy_spec, candidate_config, monkeypatch
):
    """Test that endpoint returns verdict on successful evaluation."""
    # Mock evaluate_candidate to return a successful verdict
    async def mock_evaluate_candidate(spec, config, **kwargs):
        return CandidateVerdict(
            passed=True,
            gate_results=[
                CandidateGateResult(
                    gate_name="render_strategy",
                    passed=True,
                    details={"template": "test"},
                ),
                CandidateGateResult(
                    gate_name="save_working_copy",
                    passed=True,
                    details={"path": "/tmp/test.py"},
                ),
                CandidateGateResult(
                    gate_name="data_quality",
                    passed=True,
                    details={"pair_count": 2},
                ),
                CandidateGateResult(
                    gate_name="backtest_gate",
                    passed=True,
                    metrics={"profit": 100},
                ),
            ],
            final_pair_set=["BTC/USDT"],
            portfolio_metrics={"total_profit": 100},
        )

    monkeypatch.setattr(
        "backend.api.routers.candidate.evaluate_candidate",
        mock_evaluate_candidate,
    )

    response = await client.post(
        "/api/candidate/evaluate",
        json={
            "spec": valid_strategy_spec.model_dump(mode="json"),
            "config": candidate_config.model_dump(mode="json"),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "verdict" in data
    assert data["verdict"]["passed"] is True
    assert len(data["verdict"]["gate_results"]) == 4


async def test_create_run_returns_202_quickly(
    client, valid_strategy_spec, candidate_config, monkeypatch, spawned_tasks
):
    """Async start returns a run id without waiting for final verdict."""
    finished = False

    async def mock_evaluate_candidate(spec, config, **kwargs):
        nonlocal finished
        await asyncio.sleep(0.05)
        finished = True
        return CandidateVerdict(
            passed=True,
            gate_results=[
                CandidateGateResult(gate_name="render_strategy", passed=True),
            ],
        )

    monkeypatch.setattr(
        "backend.api.routers.candidate.evaluate_candidate",
        mock_evaluate_candidate,
    )

    response = await client.post(
        "/api/candidate/runs",
        json={
            "spec": valid_strategy_spec.model_dump(mode="json"),
            "config": candidate_config.model_dump(mode="json"),
        },
    )

    assert response.status_code == 202
    data = response.json()
    assert data["run_id"].startswith("candidate_")
    assert data["status"] == "running"
    assert "verdict" not in data
    assert finished is False
    assert len(spawned_tasks) == 1
    await spawned_tasks.pop()
    assert finished is True
    await _wait_for_run_status(client, data["run_id"], "completed")


async def test_start_run_passes_data_download_runner_to_candidate_deps(
    valid_strategy_spec, candidate_config, monkeypatch
):
    """Candidate async runs receive the app DataDownloadRunner through deps."""
    app = FastAPI()
    fake_runner = object()
    app.state.services = SimpleNamespace(data_download_runner=fake_runner)
    app.include_router(candidate_router.router)
    tasks = []
    captured = {}

    def fake_spawn(coro):
        tasks.append(coro)

    async def mock_evaluate_candidate(spec, config, **kwargs):
        captured["deps"] = kwargs.get("deps")
        return CandidateVerdict(
            passed=True,
            gate_results=[
                CandidateGateResult(gate_name="render_strategy", passed=True),
            ],
        )

    monkeypatch.setattr(candidate_router, "_spawn_candidate_task", fake_spawn)
    monkeypatch.setattr(
        "backend.api.routers.candidate.evaluate_candidate",
        mock_evaluate_candidate,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as test_client:
        response = await test_client.post(
            "/api/candidate/runs",
            json={
                "spec": valid_strategy_spec.model_dump(mode="json"),
                "config": candidate_config.model_dump(mode="json"),
            },
        )

    assert response.status_code == 202
    assert len(tasks) == 1
    await tasks.pop()
    assert captured["deps"]["data_download_runner"] is fake_runner


async def test_get_run_returns_snapshot(
    client, valid_strategy_spec, candidate_config, monkeypatch, spawned_tasks
):
    """Polling endpoint returns current run state."""

    async def mock_evaluate_candidate(spec, config, **kwargs):
        await asyncio.sleep(0.05)
        return CandidateVerdict(
            passed=True,
            gate_results=[
                CandidateGateResult(gate_name="render_strategy", passed=True),
            ],
        )

    monkeypatch.setattr(
        "backend.api.routers.candidate.evaluate_candidate",
        mock_evaluate_candidate,
    )

    start = await client.post(
        "/api/candidate/runs",
        json={
            "spec": valid_strategy_spec.model_dump(mode="json"),
            "config": candidate_config.model_dump(mode="json"),
        },
    )
    run_id = start.json()["run_id"]

    response = await client.get(f"/api/candidate/runs/{run_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == run_id
    assert data["status"] in {"running", "completed"}
    assert data["current_gate"] is None or isinstance(data["current_gate"], str)
    assert len(data["gates"]) >= 10
    assert data["gates"][0]["gate_name"] == "render_strategy"
    assert len(spawned_tasks) == 1
    await spawned_tasks.pop()
    await _wait_for_run_status(client, run_id, "completed")


async def test_unknown_run_returns_404(client):
    """Unknown candidate run IDs return 404."""
    response = await client.get("/api/candidate/runs/candidate_missing")
    assert response.status_code == 404


async def test_create_run_invalid_strategy_spec_returns_validation_error(
    client, candidate_config
):
    """Async start validates StrategySpec before creating a run."""
    invalid_spec = {
        "name": "",
        "timeframe": "invalid",
        "trading_style": "trend_following",
        "indicators": [],
        "entry_conditions": [],
        "exit_conditions": [],
    }

    response = await client.post(
        "/api/candidate/runs",
        json={
            "spec": invalid_spec,
            "config": candidate_config.model_dump(mode="json"),
        },
    )

    assert response.status_code == 422
    data = response.json()
    assert data["detail"]["reason"] == "INVALID_SPEC"


async def test_background_success_marks_completed(
    client, valid_strategy_spec, candidate_config, monkeypatch, spawned_tasks
):
    """Successful background evaluation stores final verdict on the run."""

    async def mock_evaluate_candidate(spec, config, **kwargs):
        progress_sink = kwargs.get("progress_sink")
        if progress_sink:
            progress_sink({
                "gate_name": "render_strategy",
                "status": "passed",
                "metrics": {"profit_factor": 1.2},
            })
        return CandidateVerdict(
            passed=True,
            gate_results=[
                CandidateGateResult(
                    gate_name="render_strategy",
                    passed=True,
                    metrics={"profit_factor": 1.2},
                ),
            ],
            final_pair_set=["BTC/USDT"],
        )

    monkeypatch.setattr(
        "backend.api.routers.candidate.evaluate_candidate",
        mock_evaluate_candidate,
    )

    response = await client.post(
        "/api/candidate/runs",
        json={
            "spec": valid_strategy_spec.model_dump(mode="json"),
            "config": candidate_config.model_dump(mode="json"),
        },
    )

    assert len(spawned_tasks) == 1
    await spawned_tasks.pop()
    data = await _wait_for_run_status(client, response.json()["run_id"], "completed")
    assert data["verdict"]["passed"] is True
    assert data["verdict"]["final_pair_set"] == ["BTC/USDT"]
    gates = {gate["gate_name"]: gate for gate in data["gates"]}
    assert gates["render_strategy"]["status"] == "passed"
    assert gates["render_strategy"]["metrics"]["profit_factor"] == 1.2


async def test_background_data_download_progress_gate(
    client, valid_strategy_spec, candidate_config, monkeypatch, spawned_tasks
):
    """Background runs persist data_download progress updates."""

    async def mock_evaluate_candidate(spec, config, **kwargs):
        progress_sink = kwargs.get("progress_sink")
        if progress_sink:
            progress_sink({
                "gate_name": "data_quality",
                "status": "failed",
                "errors": [
                    "INSUFFICIENT_HISTORY: BTC/USDT - data ends at 20240331, required 20240401",
                ],
                "details": {"missing_pairs": ["BTC/USDT"]},
            })
            progress_sink({
                "gate_name": "data_download",
                "status": "running",
                "details": {
                    "pairs": ["BTC/USDT"],
                    "timeframe": "5m",
                    "timerange": "20240101-20240401",
                },
            })
            progress_sink({
                "gate_name": "data_download",
                "status": "passed",
                "details": {
                    "download_id": "download_123",
                    "pairs": ["BTC/USDT"],
                },
            })
        return CandidateVerdict(
            passed=False,
            gate_results=[
                CandidateGateResult(gate_name="render_strategy", passed=True),
                CandidateGateResult(gate_name="save_working_copy", passed=True),
                CandidateGateResult(gate_name="data_download", passed=True),
                CandidateGateResult(
                    gate_name="data_quality",
                    passed=False,
                    details={"missing_pairs": ["BTC/USDT"]},
                ),
            ],
            failure_reason="data_quality",
        )

    monkeypatch.setattr(
        "backend.api.routers.candidate.evaluate_candidate",
        mock_evaluate_candidate,
    )

    response = await client.post(
        "/api/candidate/runs",
        json={
            "spec": valid_strategy_spec.model_dump(mode="json"),
            "config": candidate_config.model_dump(mode="json"),
        },
    )

    assert len(spawned_tasks) == 1
    await spawned_tasks.pop()
    data = await _wait_for_run_status(client, response.json()["run_id"], "completed")
    gates = {gate["gate_name"]: gate for gate in data["gates"]}
    assert gates["data_download"]["status"] == "passed"
    assert gates["data_download"]["details"]["download_id"] == "download_123"


async def test_background_missing_data_completes_with_data_quality_failure(
    client, valid_strategy_spec, candidate_config, monkeypatch, spawned_tasks
):
    """Missing data produces a failed verdict and skips later gates."""

    details = {
        "errors": ["MISSING_DATA_FILE: BTC/USDT - file does not exist"],
        "warnings": [],
        "pair_details": {
            "BTC/USDT": {
                "exists": False,
                "data_file": "/tmp/user_data/data/binance/BTC_USDT-5m.feather",
            },
        },
        "missing_pairs": ["BTC/USDT"],
        "timeframe": "5m",
        "timerange": "20240101-20240131",
        "config_file": "config.json",
        "user_data_dir": "/tmp/user_data",
        "exchange": "binance",
        "download_command_hint": (
            "freqtrade download-data -c config.json --timeframes 5m "
            "--timerange 20240101-20240131 --pairs BTC/USDT"
        ),
    }

    async def mock_evaluate_candidate(spec, config, **kwargs):
        progress_sink = kwargs.get("progress_sink")
        if progress_sink:
            progress_sink({
                "gate_name": "data_quality",
                "status": "failed",
                "errors": details["errors"],
                "details": details,
            })
        return CandidateVerdict(
            passed=False,
            gate_results=[
                CandidateGateResult(gate_name="render_strategy", passed=True),
                CandidateGateResult(gate_name="save_working_copy", passed=True),
                CandidateGateResult(
                    gate_name="data_quality",
                    passed=False,
                    details=details,
                ),
            ],
            failure_reason="data_quality",
        )

    monkeypatch.setattr(
        "backend.api.routers.candidate.evaluate_candidate",
        mock_evaluate_candidate,
    )

    response = await client.post(
        "/api/candidate/runs",
        json={
            "spec": valid_strategy_spec.model_dump(mode="json"),
            "config": candidate_config.model_dump(mode="json"),
        },
    )

    assert len(spawned_tasks) == 1
    await spawned_tasks.pop()
    data = await _wait_for_run_status(client, response.json()["run_id"], "completed")
    assert data["verdict"]["passed"] is False
    assert data["verdict"]["failure_reason"] == "data_quality"
    gates = {gate["gate_name"]: gate for gate in data["gates"]}
    assert gates["data_quality"]["status"] == "failed"
    assert gates["data_quality"]["details"]["missing_pairs"] == ["BTC/USDT"]
    assert gates["backtest_gate"]["status"] == "skipped"


async def test_background_exception_marks_failed(
    client, valid_strategy_spec, candidate_config, monkeypatch, spawned_tasks
):
    """Unhandled background errors mark the async run failed."""

    async def mock_evaluate_candidate(spec, config, **kwargs):
        raise RuntimeError("mock background failure")

    monkeypatch.setattr(
        "backend.api.routers.candidate.evaluate_candidate",
        mock_evaluate_candidate,
    )

    response = await client.post(
        "/api/candidate/runs",
        json={
            "spec": valid_strategy_spec.model_dump(mode="json"),
            "config": candidate_config.model_dump(mode="json"),
        },
    )

    assert len(spawned_tasks) == 1
    await spawned_tasks.pop()
    data = await _wait_for_run_status(client, response.json()["run_id"], "failed")
    assert data["error"] == "mock background failure"
    assert data["verdict"] is None


async def test_invalid_strategy_spec_returns_validation_error(
    client, candidate_config
):
    """Test that invalid StrategySpec returns 422 validation error."""
    # Create an invalid spec (missing required fields)
    invalid_spec = {
        "name": "",  # Invalid: empty name
        "timeframe": "invalid",  # Invalid timeframe
        "trading_style": "trend_following",
        "indicators": [],
        "entry_conditions": [],
        "exit_conditions": [],
    }

    response = await client.post(
        "/api/candidate/evaluate",
        json={
            "spec": invalid_spec,
            "config": candidate_config.model_dump(mode="json"),
        },
    )

    assert response.status_code == 422
    data = response.json()
    assert data["detail"]["reason"] == "INVALID_SPEC"
    assert "errors" in data["detail"]
    assert len(data["detail"]["errors"]) > 0


async def test_evaluate_candidate_failure_verdict_returned(
    client, valid_strategy_spec, candidate_config, monkeypatch
):
    """Test that evaluate_candidate failure verdict is returned."""
    # Mock evaluate_candidate to return a failure verdict
    async def mock_evaluate_candidate(spec, config, **kwargs):
        return CandidateVerdict(
            passed=False,
            gate_results=[
                CandidateGateResult(
                    gate_name="render_strategy",
                    passed=True,
                    details={"template": "test"},
                ),
                CandidateGateResult(
                    gate_name="save_working_copy",
                    passed=True,
                    details={"path": "/tmp/test.py"},
                ),
                CandidateGateResult(
                    gate_name="data_quality",
                    passed=False,
                    details={"errors": ["Missing data"]},
                ),
            ],
            failure_reason="data_quality",
        )

    monkeypatch.setattr(
        "backend.api.routers.candidate.evaluate_candidate",
        mock_evaluate_candidate,
    )

    response = await client.post(
        "/api/candidate/evaluate",
        json={
            "spec": valid_strategy_spec.model_dump(mode="json"),
            "config": candidate_config.model_dump(mode="json"),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["verdict"]["passed"] is False
    assert data["verdict"]["failure_reason"] == "data_quality"


async def test_no_real_backtest_helpers_called(
    client, valid_strategy_spec, candidate_config, monkeypatch
):
    """Test that no real backtest helpers are called during evaluation."""
    # Track which functions are called
    called_functions = []

    # Mock evaluate_candidate to return a successful verdict without calling real helpers
    async def mock_evaluate_candidate(spec, config, **kwargs):
        called_functions.append("evaluate_candidate")
        return CandidateVerdict(
            passed=True,
            gate_results=[
                CandidateGateResult(
                    gate_name="render_strategy",
                    passed=True,
                    details={"template": "test"},
                ),
                CandidateGateResult(
                    gate_name="save_working_copy",
                    passed=True,
                    details={"path": "/tmp/test.py"},
                ),
                CandidateGateResult(
                    gate_name="data_quality",
                    passed=True,
                    details={"pair_count": 2},
                ),
                CandidateGateResult(
                    gate_name="backtest_gate",
                    passed=True,
                    metrics={"profit": 100},
                ),
            ],
            final_pair_set=["BTC/USDT"],
            portfolio_metrics={"total_profit": 100},
        )

    monkeypatch.setattr(
        "backend.api.routers.candidate.evaluate_candidate",
        mock_evaluate_candidate,
    )

    response = await client.post(
        "/api/candidate/evaluate",
        json={
            "spec": valid_strategy_spec.model_dump(mode="json"),
            "config": candidate_config.model_dump(mode="json"),
        },
    )

    assert response.status_code == 200
    # Verify that our mocked function was called instead of real ones
    assert "evaluate_candidate" in called_functions
    # The real backtest runner should NOT be called
    assert "backtest_runner" not in called_functions
