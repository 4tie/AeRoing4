import pytest
from unittest.mock import MagicMock, patch

from backend.services.ai.workflow_tool_models import ToolSafety
from backend.tests.test_workflow_copilot_integration import (
    _make_copilot,
    RecordingOllamaClient,
)


@pytest.mark.asyncio
async def test_pair_discovery_session_continuity_scenario(tmp_path):
    """Integration test for the exact Pair Discovery user scenario.
    
    Verifies that the copilot:
    1. Reads the strategy when mentioned.
    2. Uses the same session across multiple turns.
    3. Asks for missing information (timerange).
    4. Calls get_pair_universe before proposing pair explorer.
    5. Proposes run_pair_explorer without asking for config file.
    """
    
    # ── Turn 1 ─────────────────────────────────────────────────────────────
    # "Find more profitable pairs for aistrategy.py alongside JTO/USDT"
    
    # Create the strategy file
    strategies = tmp_path / "user_data" / "strategies"
    strategies.mkdir(parents=True, exist_ok=True)
    (strategies / "AIStrategy.py").write_text(
        "class AIStrategy:\n    timeframe = '1h'\n", encoding="utf-8"
    )
    
    ollama_turn1 = RecordingOllamaClient(
        [
            {
                "content": "I'll read the strategy first.",
                "tool_calls": [
                    {
                        "id": "call-read",
                        "name": "read_strategy_file",
                        "arguments": {"strategy_name": "aistrategy.py"},
                    }
                ],
            },
            {
                "content": "I read the strategy and found the timeframe is 1h. What timerange do you want to backtest?",
                "tool_calls": [],
            },
        ]
    )
    
    copilot = _make_copilot(tmp_path, ollama_turn1)
    
    # Mock pair selector so get_pair_universe works in turn 2
    mock_state = MagicMock()
    mock_state.available_pairs = {"BTC/USDT", "ETH/USDT", "JTO/USDT"}
    mock_state.extended_pairs = []
    mock_pair_selector = MagicMock()
    mock_pair_selector.get_state.return_value = mock_state
    copilot.services.pair_selector = mock_pair_selector

    events_turn1 = []
    async for event in copilot.process_turn(
        session_id="session-pair-discovery",
        user_message="Find more profitable pairs for aistrategy.py alongside JTO/USDT",
        model="llama3",
        mode="analysis",
    ):
        events_turn1.append(event)

    assert any(event["type"] == "tool_started" and event.get("tool_name") == "read_strategy_file" for event in events_turn1)
    assert events_turn1[-1]["type"] == "final"
    assert "timerange" in events_turn1[-1]["content"].lower()

    # ── Turn 2 ─────────────────────────────────────────────────────────────
    # "2025" (providing timerange)
    
    ollama_turn2 = RecordingOllamaClient(
        [
            {
                "content": "I'll fetch available pairs first.",
                "tool_calls": [
                    {
                        "id": "call-universe",
                        "name": "get_pair_universe",
                        "arguments": {"quote_currency": "USDT"},
                    }
                ],
            },
            {
                "content": "I will run the Pair Explorer now.",
                "tool_calls": [
                    {
                        "id": "call-explore",
                        "name": "run_pair_explorer",
                        "arguments": {
                            "strategy_name": "AIStrategy",
                            "pairs": ["BTC/USDT", "ETH/USDT", "JTO/USDT"],
                            "timeframe": "1h",
                            "timerange": "20250101-20251231",
                        },
                    }
                ],
            },
        ]
    )
    
    # We create a new copilot object to simulate a new request, but it will load the same session from disk
    copilot2 = _make_copilot(tmp_path, ollama_turn2)
    copilot2.services.pair_selector = mock_pair_selector

    events_turn2 = []
    async for event in copilot2.process_turn(
        session_id="session-pair-discovery",
        user_message="2025",
        model="llama3",
        mode="analysis",
    ):
        events_turn2.append(event)
        
    # Should fetch universe and then require confirmation for pair explorer
    assert any(event["type"] == "tool_started" and event.get("tool_name") == "get_pair_universe" for event in events_turn2)
    confirmation_event = next(event for event in events_turn2 if event["type"] == "tool_confirmation_required")
    
    assert confirmation_event["tool_name"] == "run_pair_explorer"
    assert confirmation_event["arguments"]["strategy_name"] == "AIStrategy"
    assert confirmation_event["arguments"]["timerange"] == "20250101-20251231"
    
    # Verify the session contains the history of both turns
    session = copilot2.copilot_store.load_session("session-pair-discovery")
    roles = [msg["role"] for msg in session["messages"]]
    # turn 1: user -> assistant(call) -> tool -> assistant(final)
    # turn 2: user -> assistant(call) -> tool -> assistant(call) -> pending
    assert roles.count("user") == 2
    assert "aistrategy.py" in session["messages"][0]["content"].lower()
    assert session["messages"][4]["content"] == "2025"
