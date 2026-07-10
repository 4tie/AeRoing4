"""Integration tests for the workflow copilot backend boundary."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routers.ai_assistant import router
from backend.api.session_store import SessionStore
from backend.services.agent_context import AgentContextService
from backend.services.ai.copilot_session_store import CopilotSessionStore
from backend.services.ai.ollama_types import OllamaChatResponse
from backend.services.ai.workflow_copilot import WorkflowCopilot
from backend.services.ai.workflow_tool_executor import WorkflowToolExecutor


class RecordingOllamaClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            return SimpleNamespace(content="No more responses.", tool_calls=[])
        response = self.responses.pop(0)
        if isinstance(response, dict):
            return SimpleNamespace(**response)
        return response


class DummyRouterOllamaClient:
    def __init__(self, *args, **kwargs):
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return OllamaChatResponse(content="AutoQuant copilot response.", tool_calls=[])

    async def close(self):
        return None


class SharedScriptedRouterOllamaClient:
    responses: list[dict] = []
    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def chat(self, **kwargs):
        self.__class__.calls.append(kwargs)
        if not self.__class__.responses:
            return OllamaChatResponse(content="No scripted response.", tool_calls=[])
        response = self.__class__.responses.pop(0)
        return OllamaChatResponse(
            content=response.get("content", ""),
            tool_calls=response.get("tool_calls", []),
        )

    async def close(self):
        return None


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        event_name = None
        data_lines = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        payload = json.loads("\n".join(data_lines)) if data_lines else {}
        if event_name and "type" not in payload:
            payload["type"] = event_name
        events.append(payload)
    return events


def _make_services(tmp_path: Path):
    user_data = tmp_path / "user_data"
    strategies = user_data / "strategies"
    strategies.mkdir(parents=True, exist_ok=True)
    (strategies / "DemoStrategy.py").write_text("class DemoStrategy:\n    pass\n", encoding="utf-8")

    settings = SimpleNamespace(
        user_data_directory_path=str(user_data),
        strategies_directory_path=str(strategies),
        freqtrade_executable_path="freqtrade",
        default_config_file_path="config.json",
        ollama_api_url="http://localhost:11434",
        ollama_model="llama3",
        ollama_provider="local",
        ollama_api_key="",
        ollama_timeout=30,
    )

    services = MagicMock()
    services.root_dir = tmp_path
    services.settings_store.load.return_value = settings
    services.run_repository = MagicMock()
    services.version_manager = MagicMock()
    services.version_manager.get_current_pointer.return_value = None
    services.version_manager.load_params.return_value = None
    services.version_manager.list_versions.return_value = []
    services.strategy_optimizer.get_active_session_id.return_value = None
    services.backtest_runner.get_current_run_id.return_value = None
    services.optimizer_store = MagicMock()
    services.sweep_store = MagicMock()
    services.run_detail.side_effect = Exception("no runs")
    return services, user_data, strategies


def _make_copilot(tmp_path: Path, ollama_client: RecordingOllamaClient) -> WorkflowCopilot:
    services, user_data, _ = _make_services(tmp_path)
    session_store = SessionStore(user_data / "api_sessions.json")
    copilot_store = CopilotSessionStore(user_data)
    context_service = AgentContextService(
        root_dir=services.root_dir,
        run_repository=services.run_repository,
        settings_store=services.settings_store,
        version_manager=services.version_manager,
        strategy_optimizer=services.strategy_optimizer,
        backtest_runner=services.backtest_runner,
        optimizer_store=services.optimizer_store,
        sweep_store=services.sweep_store,
        run_detail_callable=services.run_detail,
        session_store=session_store,
    )
    context_service.build_context = MagicMock(
        return_value={
            "schema_version": "agent_context_v1",
            "active": {"strategy_name": None},
            "warnings": [],
        }
    )
    executor = WorkflowToolExecutor(
        services=services,
        session_store=session_store,
        copilot_store=copilot_store,
        root_dir=tmp_path,
    )
    return WorkflowCopilot(
        services=services,
        session_store=session_store,
        copilot_store=copilot_store,
        executor=executor,
        context_service=context_service,
        ollama_client=ollama_client,
        root_dir=tmp_path,
    )


def test_remove_pending_action_return_value_reflects_removal(tmp_path):
    store = CopilotSessionStore(tmp_path / "user_data")
    session = store.create_session(model="llama3")
    session["pending_actions"] = [{"action_id": "action-1"}, {"action_id": "action-2"}]

    assert store.remove_pending_action(session, "action-1") is True
    assert [action["action_id"] for action in session["pending_actions"]] == ["action-2"]
    assert store.remove_pending_action(session, "missing") is False


@pytest.mark.asyncio
async def test_copilot_build_context_uses_real_agent_context_service(tmp_path):
    services, user_data, _ = _make_services(tmp_path)
    context_service = AgentContextService(
        root_dir=services.root_dir,
        run_repository=services.run_repository,
        settings_store=services.settings_store,
        version_manager=services.version_manager,
        strategy_optimizer=services.strategy_optimizer,
        backtest_runner=services.backtest_runner,
        optimizer_store=services.optimizer_store,
        sweep_store=services.sweep_store,
        run_detail_callable=services.run_detail,
        session_store=SessionStore(user_data / "api_sessions.json"),
    )
    copilot = _make_copilot(
        tmp_path,
        RecordingOllamaClient([{"content": "ok", "tool_calls": []}]),
    )
    copilot.context_service = context_service

    context = copilot._build_context(
        {"messages": [], "tool_runs": [], "active_jobs": [], "last_context_overrides": {}},
        "analysis",
    )

    assert context["schema_version"] == "agent_context_v1"
    assert "active" in context


@pytest.mark.asyncio
async def test_process_turn_end_to_end_with_real_store_and_read_only_tool(tmp_path):
    ollama = RecordingOllamaClient(
        [
            {
                "content": "I'll inspect the strategy list.",
                "tool_calls": [
                    {
                        "id": "call-list",
                        "function": {"name": "list_strategies", "arguments": {}},
                    }
                ],
            },
            {"content": "I found DemoStrategy.", "tool_calls": []},
        ]
    )
    copilot = _make_copilot(tmp_path, ollama)

    events = []
    async for event in copilot.process_turn(
        session_id="session-read",
        user_message="What strategies do I have?",
        model="llama3",
        mode="analysis",
    ):
        events.append(event)

    assert [event["type"] for event in events].count("tool_started") == 1
    assert any(event["type"] == "tool_result" for event in events)
    assert events[-1] == {"type": "final", "content": "I found DemoStrategy."}

    session = copilot.copilot_store.load_session("session-read")
    roles = [message["role"] for message in session["messages"]]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert session["messages"][1]["tool_calls"][0]["tool_call_id"] == "call-list"
    assert session["messages"][2]["tool_call_id"] == "call-list"


@pytest.mark.asyncio
async def test_second_ollama_call_preserves_assistant_tool_call_then_tool_result(tmp_path):
    ollama = RecordingOllamaClient(
        [
            {
                "content": "I'll list strategies.",
                "tool_calls": [{"id": "call-a", "name": "list_strategies", "arguments": {}}],
            },
            {"content": "The tool result is available.", "tool_calls": []},
        ]
    )
    copilot = _make_copilot(tmp_path, ollama)

    events = []
    async for event in copilot.process_turn(
        session_id="session-protocol",
        user_message="List strategies",
        model="llama3",
        mode="analysis",
    ):
        events.append(event)

    assert events[-1]["type"] == "final"
    assert len(ollama.calls) == 2
    second_messages = ollama.calls[1]["messages"]
    assistant_index = next(
        idx for idx, message in enumerate(second_messages)
        if message.get("role") == "assistant" and message.get("tool_calls")
    )
    tool_index = next(
        idx for idx, message in enumerate(second_messages)
        if message.get("role") == "tool"
    )

    assert assistant_index < tool_index
    assert second_messages[assistant_index]["tool_calls"][0]["tool_call_id"] == "call-a"
    assert second_messages[tool_index]["tool_call_id"] == "call-a"
    assert "DemoStrategy" in second_messages[tool_index]["content"]


@pytest.mark.asyncio
async def test_confirmation_resume_flow_uses_real_session_and_executor(tmp_path):
    ollama = RecordingOllamaClient(
        [
            {
                "content": "I'll run the guarded backtest.",
                "tool_calls": [
                    {
                        "id": "call-backtest",
                        "name": "run_backtest",
                        "arguments": {
                            "strategy_name": "DemoStrategy",
                            "timerange": "20240101-20240131",
                        },
                    }
                ],
            },
            {"content": "Backtest completed with run bt-123.", "tool_calls": []},
        ]
    )
    copilot = _make_copilot(tmp_path, ollama)

    initial_events = []
    async for event in copilot.process_turn(
        session_id="session-confirm",
        user_message="Run a backtest",
        model="llama3",
        mode="analysis",
    ):
        initial_events.append(event)

    confirmation = next(event for event in initial_events if event["type"] == "tool_confirmation_required")

    async def fake_start_backtest_job(**kwargs):
        return "api-123", "queued"

    async def fake_observe_job(**kwargs):
        yield {
            "type": "job_progress",
            "status": "completed",
            "result": {"run_id": "bt-123", "net_profit_pct": 12.5},
        }

    with patch("backend.services.workflow_jobs.start_backtest_job", fake_start_backtest_job):
        with patch("backend.services.ai.job_observer.observe_job", fake_observe_job):
            resumed_events = []
            async for event in copilot.resume_after_confirmation(
                session_id="session-confirm",
                action_id=confirmation["action_id"],
            ):
                resumed_events.append(event)

    assert any(event["type"] == "tool_result" for event in resumed_events)
    assert resumed_events[-1] == {
        "type": "final",
        "content": "Backtest completed with run bt-123.",
    }
    session = copilot.copilot_store.load_session("session-confirm")
    assert not session["pending_actions"]
    assert session["tool_runs"][-1]["status"] == "completed"
    assert session["messages"][1]["tool_calls"][0]["tool_call_id"] == "call-backtest"
    assert session["messages"][2]["tool_call_id"] == "call-backtest"


def test_autoquant_endpoint_delegates_to_workflow_copilot_via_fastapi(tmp_path):
    services, _, _ = _make_services(tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.state.services = services
    app.state.session_store = SessionStore(tmp_path / "api_sessions.json")
    app.state.log_broadcaster = MagicMock(history=[])

    with patch("backend.api.routers.ai_assistant.OllamaClient", DummyRouterOllamaClient):
        response = TestClient(app).post(
            "/api/ai/autoquant",
            json={
                "message": "Start by explaining the AutoQuant state.",
                "context_overrides": {"strategy_name": "DemoStrategy"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["response"] == "AutoQuant copilot response."
    assert body["session_id"]
    assert body["tool_calls"] == []


@pytest.mark.parametrize(
    ("terminal_status", "expected_terminal_event", "final_text"),
    [
        ("completed", "tool_result", "Backtest finished successfully."),
        ("failed", "tool_failed", "Backtest failed and needs attention."),
        ("timed_out", "observation_timeout", "Backtest is still running after timeout."),
    ],
)
def test_public_assistant_confirmation_lifecycle_streams_progress_and_resumes_model(
    tmp_path,
    terminal_status,
    expected_terminal_event,
    final_text,
):
    services, _, _ = _make_services(tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.state.services = services
    app.state.session_store = SessionStore(tmp_path / "api_sessions.json")
    app.state.log_broadcaster = MagicMock(history=[])

    SharedScriptedRouterOllamaClient.calls = []
    SharedScriptedRouterOllamaClient.responses = [
        {
            "content": "I need to run a guarded backtest.",
            "tool_calls": [
                {
                    "id": "call-public-backtest",
                    "name": "run_backtest",
                    "arguments": {
                        "strategy_name": "DemoStrategy",
                        "timerange": "20240101-20240131",
                    },
                }
            ],
        },
        {"content": final_text, "tool_calls": []},
    ]

    async def fake_start_backtest_job(**kwargs):
        return "api-public-123", "queued"

    async def fake_observe_job(**kwargs):
        yield {
            "type": "job_progress",
            "status": "queued",
            "result": {"message": "queued"},
        }
        yield {
            "type": "job_progress",
            "status": "running",
            "result": {"message": "running"},
        }
        if terminal_status == "timed_out":
            yield {
                "type": "observation_timeout",
                "api_session_id": "api-public-123",
                "job_type": "backtest",
                "elapsed_seconds": 300,
            }
            return
        yield {
            "type": "job_progress",
            "status": terminal_status,
            "result": {
                "run_id": "bt-public-123",
                "net_profit_pct": 7.5,
                "error": "freqtrade failed" if terminal_status == "failed" else None,
            },
        }

    with patch("backend.api.routers.ai_assistant.OllamaClient", SharedScriptedRouterOllamaClient):
        with patch("backend.services.workflow_jobs.start_backtest_job", fake_start_backtest_job):
            with patch("backend.services.ai.job_observer.observe_job", fake_observe_job):
                client = TestClient(app)
                chat_response = client.post(
                    "/api/ai/chat/stream",
                    json={"message": "Run a backtest for DemoStrategy."},
                )
                chat_events = _parse_sse(chat_response.text)
                confirmation_event = next(
                    event for event in chat_events
                    if event.get("type") == "tool_confirmation_required"
                )
                session_id = next(event["session_id"] for event in chat_events if event.get("type") == "meta")

                confirm_response = client.post(
                    "/api/ai/actions/confirm",
                    json={
                        "action_type": confirmation_event["confirmation_action_type"],
                        "session_id": session_id,
                        "payload": confirmation_event["confirmation_payload"],
                    },
                )

    confirm_events = _parse_sse(confirm_response.text)
    event_types = [event.get("type") for event in confirm_events]

    assert confirmation_event["confirmation_endpoint"] == "/api/ai/actions/confirm"
    assert "tool_started" in event_types
    assert "job_active" in event_types
    assert expected_terminal_event in event_types
    assert confirm_events[-1] == {"type": "final", "content": final_text}

    assert len(SharedScriptedRouterOllamaClient.calls) == 2
    second_messages = SharedScriptedRouterOllamaClient.calls[1]["messages"]
    tool_message = next(message for message in second_messages if message.get("role") == "tool")
    assistant_message = next(
        message for message in second_messages
        if message.get("role") == "assistant" and message.get("tool_calls")
    )

    assert assistant_message["tool_calls"][0]["tool_call_id"] == "call-public-backtest"
    assert tool_message["tool_call_id"] == "call-public-backtest"
    assert terminal_status in tool_message["content"]
