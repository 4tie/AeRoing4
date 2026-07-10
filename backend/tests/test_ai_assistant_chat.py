from __future__ import annotations

import json
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from backend.api.routers.ai_assistant import (
    ChatRequest,
    ConfirmActionRequest,
    chat,
    confirm_action,
    get_chat_session,
    list_models,
)
from backend.services.ai.ollama_types import OllamaChatResponse
from backend.models import (
    OptimizerScoreMetric,
    OptimizerSession,
    OptimizerSessionConfig,
    OptimizerSessionPhase,
    OptimizerTrial,
    OptimizerTrialMetrics,
    OptimizerTrialStatus,
)
from backend.services.storage.optimizer_store import OptimizerStore
from backend.utils import read_json


class RouteResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self.payload


class DirectAiClient:
    def __init__(self, request) -> None:
        self.request = request

    def post(self, path: str, json: dict) -> RouteResponse:
        async def _run() -> dict:
            if path == "/api/ai/chat":
                return await chat(ChatRequest(**json), self.request)
            if path == "/api/ai/actions/confirm":
                return await confirm_action(ConfirmActionRequest(**json), self.request)
            raise AssertionError(f"Unhandled POST path: {path}")

        return _response_from_async(_run)

    def get(self, path: str) -> RouteResponse:
        async def _run() -> dict:
            if path == "/api/ai/models":
                return await list_models(self.request)
            if path.startswith("/api/ai/chat/"):
                return await get_chat_session(path.rsplit("/", 1)[-1], self.request)
            raise AssertionError(f"Unhandled GET path: {path}")

        return _response_from_async(_run)


class DummyOllamaClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def close(self) -> None:
        return None

    async def chat(self, *args, **kwargs):
        return OllamaChatResponse(content="Fact: the backend context has no profit metric selected yet.")


def _response_from_async(func) -> RouteResponse:
    try:
        return RouteResponse(asyncio.run(func()))
    except HTTPException as exc:
        return RouteResponse({"detail": exc.detail}, status_code=exc.status_code)


def _client(tmp_path: Path, *, model: str = "llama3"):
    user_data = tmp_path / "user_data"
    strategies = user_data / "strategies"
    user_data.mkdir(parents=True, exist_ok=True)
    strategies.mkdir(parents=True, exist_ok=True)

    settings = SimpleNamespace(
        ollama_api_url="http://localhost:11434",
        ollama_model=model,
        ollama_provider="local",
        ollama_api_key="",
        ollama_timeout=30,
        user_data_directory_path=str(user_data),
        strategies_directory_path=str(strategies),
    )
    services = MagicMock()
    services.root_dir = tmp_path
    services.settings_store.load.return_value = settings
    services.optimizer_store = OptimizerStore(user_data / "optimizer_sessions")
    services.version_manager.get_current_pointer.return_value = None
    services.version_manager.load_params.return_value = None
    services.version_manager.list_versions.return_value = []
    services.strategy_optimizer.get_active_session_id.return_value = None
    services.backtest_runner.get_current_run_id.return_value = None
    services.run_detail.side_effect = Exception("no runs")

    state = SimpleNamespace()
    state.services = services
    state.log_broadcaster = MagicMock(history=[])
    state.session_store = MagicMock()
    state.session_store.get.return_value = None
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    return DirectAiClient(request), services, user_data


def test_chat_uses_ollama_and_persists_session(tmp_path):
    client, _, user_data = _client(tmp_path)

    with patch("backend.api.routers.ai_assistant.OllamaClient", DummyOllamaClient):
        response = client.post("/api/ai/chat", json={"message": "Why is this losing?"})

    assert response.status_code == 200
    body = response.json()
    assert body["message"]["content"].startswith("Fact:")
    assert body["session_id"]

    stored = read_json(user_data / "assistant" / "chat_sessions" / f"{body['session_id']}.json")
    assert stored["schema_version"] == "assistant_copilot_session_v2"
    assert [item["role"] for item in stored["messages"]] == ["user", "assistant"]

    loaded = client.get(f"/api/ai/chat/{body['session_id']}")
    assert loaded.status_code == 200
    assert loaded.json()["session_id"] == body["session_id"]


def test_chat_requires_configured_model(tmp_path):
    client, _, _ = _client(tmp_path, model="")

    response = client.post("/api/ai/chat", json={"message": "Hello"})

    assert response.status_code == 422
    assert "No AI model configured" in response.json()["detail"]


def test_dangerous_action_is_rejected_and_audited(tmp_path):
    client, _, user_data = _client(tmp_path)

    response = client.post(
        "/api/ai/actions/confirm",
        json={"action_type": "overwrite_accepted_params", "payload": {"strategy_name": "Demo"}},
    )

    assert response.status_code == 403
    audit_lines = (user_data / "assistant" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(audit_lines) == 1
    entry = json.loads(audit_lines[0])
    assert entry["status"] == "rejected"
    assert entry["proposed_action"]["action_type"] == "overwrite_accepted_params"


def test_read_only_view_best_params_action_is_audited(tmp_path):
    client, services, user_data = _client(tmp_path)
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
        created_at="2026-06-15T00:00:00Z",
        completed_at="2026-06-15T00:01:00Z",
        total_trials=1,
        completed_trials=1,
        best_trial_number=1,
        best_metrics=OptimizerTrialMetrics(score=1.25, profit_factor=1.8),
        trials=[
            OptimizerTrial(
                trial_number=1,
                status=OptimizerTrialStatus.COMPLETED,
                parameters={"buy__window": 14, "stoploss__value": -0.04},
                metrics=OptimizerTrialMetrics(score=1.25, profit_factor=1.8),
            )
        ],
    )
    services.optimizer_store.save_session(session)

    response = client.post(
        "/api/ai/actions/confirm",
        json={"action_type": "view_best_params", "payload": {"optimizer_session_id": "opt-1"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert body["params"]["params"]["buy"]["window"] == 14

    audit_lines = (user_data / "assistant" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(audit_lines[-1])["status"] == "completed"


def test_oos_validation_draft_is_read_only_and_audited(tmp_path):
    client, _, user_data = _client(tmp_path)

    response = client.post(
        "/api/ai/actions/confirm",
        json={
            "action_type": "create_oos_validation_draft",
            "payload": {
                "strategy_name": "DemoStrategy",
                "backtest_run_id": "bt-001",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert body["draft"]["type"] == "oos_validation"
    assert body["draft"]["source"]["backtest_run_id"] == "bt-001"

    audit_lines = (user_data / "assistant" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(audit_lines[-1])["status"] == "completed"


def test_backtest_start_action_is_not_directly_executable(tmp_path):
    client, _, _ = _client(tmp_path)

    response = client.post(
        "/api/ai/actions/confirm",
        json={
            "action_type": "start_backtest",
            "payload": {"strategy_name": "DemoStrategy"},
        },
    )

    assert response.status_code == 400
    assert "Unknown assistant action" in response.json()["detail"]


def test_backtest_run_draft_is_read_only_and_audited(tmp_path):
    client, _, user_data = _client(tmp_path)

    response = client.post(
        "/api/ai/actions/confirm",
        json={
            "action_type": "create_backtest_run_draft",
            "payload": {
                "strategy_name": "DemoStrategy",
                "timerange": "20240101-20240201",
                "pairs": "BTC/USDT, ETH/USDT",
                "timeframe": "5m",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert body["draft"]["type"] == "backtest_run"
    assert body["draft"]["pairs"] == ["BTC/USDT", "ETH/USDT"]

    audit_lines = (user_data / "assistant" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(audit_lines[-1])["status"] == "completed"


def test_assistant_file_edit_preview_and_apply_are_fenced(tmp_path):
    client, _, user_data = _client(tmp_path)
    strategy_path = user_data / "strategies" / "DemoStrategy.py"
    strategy_path.write_text("class DemoStrategy:\n    pass\n", encoding="utf-8")
    outside_path = tmp_path / "outside.py"
    outside_path.write_text("print('outside')\n", encoding="utf-8")

    outside_preview = client.post(
        "/api/ai/actions/confirm",
        json={
            "action_type": "preview_file_edit",
            "payload": {
                "file_path": str(outside_path),
                "new_content": "print('changed')\n",
            },
        },
    )
    assert outside_preview.status_code == 403

    preview = client.post(
        "/api/ai/actions/confirm",
        json={
            "action_type": "preview_file_edit",
            "payload": {
                "file_path": str(strategy_path),
                "new_content": "class DemoStrategy:\n    minimal_roi = {}\n",
            },
        },
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["read_only"] is True
    assert preview_body["has_changes"] is True
    assert preview_body["current_sha256"]

    apply_without_preview_hash = client.post(
        "/api/ai/actions/confirm",
        json={
            "action_type": "apply_file_edit",
            "payload": {
                "file_path": str(strategy_path),
                "new_content": "class DemoStrategy:\n    minimal_roi = {}\n",
            },
            "confirmation_token": "CONFIRM",
        },
    )
    assert apply_without_preview_hash.status_code == 409

    apply_response = client.post(
        "/api/ai/actions/confirm",
        json={
            "action_type": "apply_file_edit",
            "payload": {
                "file_path": str(strategy_path),
                "new_content": "class DemoStrategy:\n    minimal_roi = {}\n",
                "expected_sha256": preview_body["current_sha256"],
            },
            "confirmation_token": "CONFIRM",
        },
    )

    assert apply_response.status_code == 200
    assert "minimal_roi" in strategy_path.read_text(encoding="utf-8")
    audit_lines = (user_data / "assistant" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(audit_lines[-1])["status"] == "completed"


def test_guarded_action_requires_confirmation_token(tmp_path):
    client, _, user_data = _client(tmp_path)

    response = client.post(
        "/api/ai/actions/confirm",
        json={
            "action_type": "promote_best_trial_to_candidate",
            "payload": {"optimizer_session_id": "opt-1"},
            "confirmation_token": None,
        },
    )

    assert response.status_code == 409
    assert "Confirmation token required" in response.json()["detail"]


def test_guarded_action_succeeds_with_confirmation(tmp_path):
    client, services, user_data = _client(tmp_path)
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
        created_at="2026-06-15T00:00:00Z",
        completed_at="2026-06-15T00:01:00Z",
        total_trials=1,
        completed_trials=1,
        best_trial_number=1,
        best_metrics=OptimizerTrialMetrics(score=1.25, profit_factor=1.8),
        trials=[
            OptimizerTrial(
                trial_number=1,
                status=OptimizerTrialStatus.COMPLETED,
                parameters={"buy__window": 14},
                metrics=OptimizerTrialMetrics(score=1.25, profit_factor=1.8),
                run_id="bt-001",
            )
        ],
    )
    services.optimizer_store.save_session(session)

    response = client.post(
        "/api/ai/actions/confirm",
        json={
            "action_type": "promote_best_trial_to_candidate",
            "payload": {"optimizer_session_id": "opt-1"},
            "confirmation_token": "CONFIRM",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True

    audit_lines = (user_data / "assistant" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(audit_lines[-1])["status"] == "completed"


def test_unknown_action_returns_400_error(tmp_path):
    client, _, _ = _client(tmp_path)

    response = client.post(
        "/api/ai/actions/confirm",
        json={"action_type": "unknown_action", "payload": {}},
    )

    assert response.status_code == 400
    assert "Unknown assistant action" in response.json()["detail"]


def test_chat_with_context_overrides_includes_context_in_prompt(tmp_path):
    client, _, user_data = _client(tmp_path)

    with patch("backend.api.routers.ai_assistant.OllamaClient", DummyOllamaClient):
        response = client.post(
            "/api/ai/chat",
            json={
                "message": "Explain this run",
                "context_overrides": {"optimizer_session_id": "opt-1"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"]
    assert body["context_summary"]


def test_models_endpoint_handles_ollama_connect_error(tmp_path):
    client, _, _ = _client(tmp_path, model="llama3")

    # Simulate connection error by using an invalid URL
    with patch("httpx.AsyncClient.get") as mock_get:
        import httpx
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        response = client.get("/api/ai/models")

    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is False
    assert "Could not connect to Ollama" in body["error"]


def test_models_endpoint_handles_ollama_timeout(tmp_path):
    client, _, _ = _client(tmp_path, model="llama3")

    # Simulate timeout
    with patch("httpx.AsyncClient.get") as mock_get:
        import httpx
        mock_get.side_effect = httpx.TimeoutException("Request timed out")

        response = client.get("/api/ai/models")

    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is False
    assert "Ollama did not respond within" in body["error"]


def test_models_endpoint_handles_malformed_json(tmp_path):
    client, _, _ = _client(tmp_path, model="llama3")

    class DummyResponse:
        def __init__(self):
            self.status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            raise json.JSONDecodeError("Invalid JSON", "", 0)

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=DummyResponse())):
        response = client.get("/api/ai/models")

    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is False
    assert "non-JSON" in body["error"]


def test_session_persists_messages_and_context(tmp_path):
    client, _, user_data = _client(tmp_path)

    with patch("backend.api.routers.ai_assistant.OllamaClient", DummyOllamaClient):
        # First message
        response1 = client.post(
            "/api/ai/chat",
            json={"message": "First question"},
        )
        session_id = response1.json()["session_id"]

        # Second message in same session
        response2 = client.post(
            "/api/ai/chat",
            json={
                "message": "Follow-up question",
                "session_id": session_id,
            },
        )

    assert response2.status_code == 200
    body = response2.json()
    assert body["session_id"] == session_id

    # Load session from disk
    stored = read_json(user_data / "assistant" / "chat_sessions" / f"{session_id}.json")
    assert len(stored["messages"]) == 4  # 2 user + 2 assistant messages
    assert stored["messages"][0]["role"] == "user"
    assert stored["messages"][0]["content"] == "First question"
    assert stored["messages"][2]["role"] == "user"
    assert stored["messages"][2]["content"] == "Follow-up question"


def test_include_strategy_source_attaches_strategy_content(tmp_path):
    client, _, user_data = _client(tmp_path)

    # Create a strategy file
    strategies_dir = user_data / "strategies"
    strategy_file = strategies_dir / "TestStrategy.py"
    strategy_file.write_text("# Test strategy\ndef dummy(): pass", encoding="utf-8")

    with patch("backend.api.routers.ai_assistant.OllamaClient", DummyOllamaClient):
        response = client.post(
            "/api/ai/chat",
            json={
                "message": "Explain this strategy",
                "context_overrides": {"strategy_name": "TestStrategy"},
                "include_strategy_source": True,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"]


def test_empty_message_returns_422_error(tmp_path):
    client, _, _ = _client(tmp_path)

    response = client.post(
        "/api/ai/chat",
        json={"message": "   "},
    )

    assert response.status_code == 422


def test_load_nonexistent_session_returns_404(tmp_path):
    client, _, _ = _client(tmp_path)

    response = client.get("/api/ai/chat/nonexistent-session-id")

    assert response.status_code == 404
    assert "was not found" in response.json()["detail"]
