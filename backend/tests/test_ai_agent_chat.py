from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.routers.ai_agent import ChatRequest, chat_with_ai_agent


class FakeSessionManager:
    def __init__(self) -> None:
        self.logs: list[tuple[str, dict]] = []

    def create_session(self, ai_model=None) -> str:
        return "agent-session-1"

    def add_log(self, session_id: str, log_entry: dict) -> None:
        self.logs.append((session_id, log_entry))


def _request(tmp_path):
    settings = SimpleNamespace(
        ollama_model="llama3",
        user_data_directory_path=str(tmp_path / "user_data"),
    )
    services = SimpleNamespace(settings_store=MagicMock())
    services.settings_store.load.return_value = settings
    state = SimpleNamespace(
        services=services,
        ai_agent_session_manager=FakeSessionManager(),
    )
    return SimpleNamespace(app=SimpleNamespace(state=state)), settings, state.ai_agent_session_manager


@pytest.mark.asyncio
async def test_ai_agent_chat_uses_settings_user_data_path_and_normalizes_tools(tmp_path):
    request, settings, session_manager = _request(tmp_path)
    captured: dict = {}

    class FakeAIService:
        async def chat_with_tools(self, *, messages, tools, model):
            captured["messages"] = messages
            captured["tools"] = tools
            captured["model"] = model
            return SimpleNamespace(
                content="Ready to inspect the strategy.",
                tool_calls=[
                    {"name": "list_strategies", "arguments": {"limit": 10}},
                ],
            )

    async def fake_get_ai_service(user_data_dir):
        captured["user_data_dir"] = user_data_dir
        return FakeAIService()

    with patch("backend.services.ai.get_ai_service", AsyncMock(side_effect=fake_get_ai_service)):
        response = await chat_with_ai_agent(ChatRequest(message="Start"), request)

    assert response.response == "Ready to inspect the strategy."
    assert response.session_id == "agent-session-1"
    assert response.tool_calls == [{"name": "list_strategies", "arguments": {"limit": 10}}]
    assert captured["user_data_dir"] == settings.user_data_directory_path
    assert captured["model"] == "llama3"
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][1] == {"role": "user", "content": "Start"}
    assert session_manager.logs[-1][1]["action"] == "chat"


@pytest.mark.asyncio
async def test_ai_agent_chat_uses_model_override(tmp_path):
    request, _, _ = _request(tmp_path)
    captured: dict = {}

    class FakeAIService:
        async def chat_with_tools(self, *, messages, tools, model):
            captured["model"] = model
            return SimpleNamespace(content="Using override.", tool_calls=[])

    with patch("backend.services.ai.get_ai_service", AsyncMock(return_value=FakeAIService())):
        response = await chat_with_ai_agent(
            ChatRequest(message="Use this model", model="mistral", session_id="existing-session"),
            request,
        )

    assert response.response == "Using override."
    assert response.session_id == "existing-session"
    assert response.tool_calls == []
    assert captured["model"] == "mistral"


@pytest.mark.asyncio
async def test_ai_agent_chat_returns_friendly_unavailable_message(tmp_path):
    request, _, _ = _request(tmp_path)

    with patch("backend.services.ai.get_ai_service", AsyncMock(side_effect=RuntimeError("missing settings"))):
        response = await chat_with_ai_agent(
            ChatRequest(message="Hello", session_id="existing-session"),
            request,
        )

    assert response.session_id == "existing-session"
    assert response.tool_calls == []
    assert "Ollama is not configured or unavailable" in response.response

