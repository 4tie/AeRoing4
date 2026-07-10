"""Tests for workflow copilot orchestration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.ai.workflow_copilot import WorkflowCopilot
from backend.services.ai.workflow_tool_models import ToolRunStatus, WorkflowToolResult


@pytest.mark.asyncio
async def test_model_called_twice_tool_called_once():
    """Test that model is called twice and tool is called exactly once."""
    # Mock dependencies
    services = MagicMock()
    session_store = MagicMock()
    copilot_store = MagicMock()
    executor = MagicMock()
    context_service = MagicMock()
    ollama_client = MagicMock()
    
    # Mock copilot store
    copilot_store.load_session.return_value = {
        "schema_version": "assistant_copilot_session_v2",
        "session_id": "test-session",
        "messages": [],
        "tool_runs": [],
        "pending_actions": [],
        "active_jobs": [],
    }
    copilot_store.save_session = MagicMock()
    
    # Mock context service
    context_service.build_context = MagicMock(return_value={})
    
    # Mock ollama client
    # First call: returns tool call
    mock_response1 = MagicMock()
    mock_response1.content = "I'll check the strategies."
    mock_response1.tool_calls = [
        {"name": "list_strategies", "arguments": {}}
    ]
    
    # Second call: returns final answer
    mock_response2 = MagicMock()
    mock_response2.content = "Found 5 strategies."
    mock_response2.tool_calls = []
    
    ollama_client.chat = AsyncMock(side_effect=[mock_response1, mock_response2])
    
    # Mock executor
    mock_result = WorkflowToolResult(
        tool_run_id="call_list",
        tool_call_id="call_list",
        tool_name="list_strategies",
        status=ToolRunStatus.COMPLETED,
        result_summary={"strategies": ["A", "B", "C"]},
    )
    executor.execute = AsyncMock(return_value=mock_result)
    
    # Create copilot
    copilot = WorkflowCopilot(
        services=services,
        session_store=session_store,
        copilot_store=copilot_store,
        executor=executor,
        context_service=context_service,
        ollama_client=ollama_client,
    )
    
    # Process turn
    events = []
    async for event in copilot.process_turn(
        session_id="test-session",
        user_message="What strategies do I have?",
        model="llama3",
        mode="analysis",
        stream=False,
    ):
        events.append(event)
    
    # Verify model called twice
    assert ollama_client.chat.call_count == 2
    
    # Verify tool called once
    assert executor.execute.call_count == 1
    
    # Verify tool result present in second model input
    second_call_messages = ollama_client.chat.call_args_list[1].kwargs["messages"]
    assistant_tool_message = next(
        msg for msg in second_call_messages
        if msg.get("role") == "assistant" and msg.get("tool_calls")
    )
    tool_result_message = next(
        msg for msg in second_call_messages
        if msg.get("role") == "tool"
    )
    assert assistant_tool_message["tool_calls"][0]["name"] == "list_strategies"
    assert tool_result_message["tool_call_id"] == assistant_tool_message["tool_calls"][0]["tool_call_id"]

    # Verify the executor was called with correct arguments
    executor.execute.assert_called_once()
    call_args = executor.execute.call_args
    assert call_args.kwargs["tool_call"].tool_name == "list_strategies"


@pytest.mark.asyncio
async def test_confirmation_path():
    """Test confirmation path for guarded tools."""
    # Mock dependencies
    services = MagicMock()
    session_store = MagicMock()
    copilot_store = MagicMock()
    executor = MagicMock()
    context_service = MagicMock()
    ollama_client = MagicMock()
    
    # Mock copilot store
    copilot_store.load_session.return_value = {
        "schema_version": "assistant_copilot_session_v2",
        "session_id": "test-session",
        "messages": [],
        "tool_runs": [],
        "pending_actions": [],
        "active_jobs": [],
    }
    copilot_store.save_session = MagicMock()
    copilot_store.add_pending_action = MagicMock()
    
    # Mock context service
    context_service.build_context = MagicMock(return_value={})
    
    # Mock ollama client - returns guarded tool call
    mock_response = MagicMock()
    mock_response.content = "I'll run a backtest."
    mock_response.tool_calls = [
        {
            "name": "run_backtest",
            "arguments": {
                "strategy_name": "DemoStrategy",
                "timerange": "20240101-20240131",
            },
        }
    ]
    ollama_client.chat = AsyncMock(return_value=mock_response)
    
    # Create copilot
    copilot = WorkflowCopilot(
        services=services,
        session_store=session_store,
        copilot_store=copilot_store,
        executor=executor,
        context_service=context_service,
        ollama_client=ollama_client,
    )
    
    # Process turn
    events = []
    async for event in copilot.process_turn(
        session_id="test-session",
        user_message="Run a backtest",
        model="llama3",
        mode="analysis",
        stream=False,
    ):
        events.append(event)
    
    # Should emit confirmation_required event
    confirmation_events = [e for e in events if e["type"] == "tool_confirmation_required"]
    assert len(confirmation_events) == 1
    assert confirmation_events[0]["tool_name"] == "run_backtest"
    
    # Should NOT execute tool
    assert executor.execute.call_count == 0


@pytest.mark.asyncio
async def test_tool_failure():
    """Test that tool failure is handled correctly."""
    # Mock dependencies
    services = MagicMock()
    session_store = MagicMock()
    copilot_store = MagicMock()
    executor = MagicMock()
    context_service = MagicMock()
    ollama_client = MagicMock()
    
    # Mock copilot store
    copilot_store.load_session.return_value = {
        "schema_version": "assistant_copilot_session_v2",
        "session_id": "test-session",
        "messages": [],
        "tool_runs": [],
        "pending_actions": [],
        "active_jobs": [],
    }
    copilot_store.save_session = MagicMock()
    
    # Mock context service
    context_service.build_context = MagicMock(return_value={})
    
    # Mock ollama client
    mock_response1 = MagicMock()
    mock_response1.content = "I'll read the strategy."
    mock_response1.tool_calls = [
        {"name": "read_strategy_file", "arguments": {"strategy_name": "UnknownStrategy"}}
    ]
    mock_response2 = MagicMock()
    mock_response2.content = "The strategy file was not found."
    mock_response2.tool_calls = []
    ollama_client.chat = AsyncMock(side_effect=[mock_response1, mock_response2])
    
    # Mock executor - returns failure
    mock_result = WorkflowToolResult(
        tool_run_id="call_read",
        tool_call_id="call_read",
        tool_name="read_strategy_file",
        status=ToolRunStatus.FAILED,
        error="Strategy file not found",
    )
    executor.execute = AsyncMock(return_value=mock_result)
    
    # Create copilot
    copilot = WorkflowCopilot(
        services=services,
        session_store=session_store,
        copilot_store=copilot_store,
        executor=executor,
        context_service=context_service,
        ollama_client=ollama_client,
    )
    
    # Process turn
    events = []
    async for event in copilot.process_turn(
        session_id="test-session",
        user_message="Read UnknownStrategy",
        model="llama3",
        mode="analysis",
        stream=False,
    ):
        events.append(event)
    
    # Should emit tool_failed event
    failed_events = [e for e in events if e["type"] == "tool_failed"]
    assert len(failed_events) == 1
    assert "not found" in failed_events[0]["error"].lower()


@pytest.mark.asyncio
async def test_invalid_args():
    """Test that invalid tool arguments are rejected."""
    # Mock dependencies
    services = MagicMock()
    session_store = MagicMock()
    copilot_store = MagicMock()
    executor = MagicMock()
    context_service = MagicMock()
    ollama_client = MagicMock()
    
    # Mock copilot store
    copilot_store.load_session.return_value = {
        "schema_version": "assistant_copilot_session_v2",
        "session_id": "test-session",
        "messages": [],
        "tool_runs": [],
        "pending_actions": [],
        "active_jobs": [],
    }
    copilot_store.save_session = MagicMock()
    
    # Mock context service
    context_service.build_context = MagicMock(return_value={})
    
    # Mock ollama client - returns tool with invalid args
    mock_response = MagicMock()
    mock_response.content = "I'll check the strategy."
    mock_response.tool_calls = [
        {"name": "read_strategy_file", "arguments": {"invalid_field": "value"}}
    ]
    ollama_client.chat = AsyncMock(return_value=mock_response)
    
    # Create copilot
    copilot = WorkflowCopilot(
        services=services,
        session_store=session_store,
        copilot_store=copilot_store,
        executor=executor,
        context_service=context_service,
        ollama_client=ollama_client,
    )
    
    # Process turn
    events = []
    async for event in copilot.process_turn(
        session_id="test-session",
        user_message="Read strategy",
        model="llama3",
        mode="analysis",
        stream=False,
    ):
        events.append(event)
    
    # Should emit error event
    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) > 0
    assert "invalid" in error_events[0]["message"].lower()


@pytest.mark.asyncio
async def test_unknown_tool():
    """Test that unknown tools are rejected."""
    # Mock dependencies
    services = MagicMock()
    session_store = MagicMock()
    copilot_store = MagicMock()
    executor = MagicMock()
    context_service = MagicMock()
    ollama_client = MagicMock()
    
    # Mock copilot store
    copilot_store.load_session.return_value = {
        "schema_version": "assistant_copilot_session_v2",
        "session_id": "test-session",
        "messages": [],
        "tool_runs": [],
        "pending_actions": [],
        "active_jobs": [],
    }
    copilot_store.save_session = MagicMock()
    
    # Mock context service
    context_service.build_context = MagicMock(return_value={})
    
    # Mock ollama client - returns unknown tool
    mock_response = MagicMock()
    mock_response.content = "I'll do something unknown."
    mock_response.tool_calls = [
        {"name": "unknown_tool", "arguments": {}}
    ]
    ollama_client.chat = AsyncMock(return_value=mock_response)
    
    # Create copilot
    copilot = WorkflowCopilot(
        services=services,
        session_store=session_store,
        copilot_store=copilot_store,
        executor=executor,
        context_service=context_service,
        ollama_client=ollama_client,
    )
    
    # Process turn
    events = []
    async for event in copilot.process_turn(
        session_id="test-session",
        user_message="Do unknown action",
        model="llama3",
        mode="analysis",
        stream=False,
    ):
        events.append(event)
    
    # Should emit error event
    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) > 0
    assert "unknown" in error_events[0]["message"].lower()


@pytest.mark.asyncio
async def test_duplicate_tool_call():
    """Test that duplicate tool calls are detected and rejected."""
    # Mock dependencies
    services = MagicMock()
    session_store = MagicMock()
    copilot_store = MagicMock()
    executor = MagicMock()
    context_service = MagicMock()
    ollama_client = MagicMock()
    
    # Mock copilot store
    copilot_store.load_session.return_value = {
        "schema_version": "assistant_copilot_session_v2",
        "session_id": "test-session",
        "messages": [],
        "tool_runs": [],
        "pending_actions": [],
        "active_jobs": [],
    }
    copilot_store.save_session = MagicMock()
    
    # Mock context service
    context_service.build_context = MagicMock(return_value={})
    
    # Mock ollama client - returns same tool call twice
    mock_response = MagicMock()
    mock_response.content = "I'll check strategies."
    mock_response.tool_calls = [
        {"name": "list_strategies", "arguments": {}},
        {"name": "list_strategies", "arguments": {}},  # Duplicate
    ]
    ollama_client.chat = AsyncMock(return_value=mock_response)
    executor.execute = AsyncMock(return_value=WorkflowToolResult(
        tool_run_id="call_duplicate",
        tool_call_id="call_duplicate",
        tool_name="list_strategies",
        status=ToolRunStatus.COMPLETED,
        result_summary={"strategies": []},
    ))
    
    # Create copilot
    copilot = WorkflowCopilot(
        services=services,
        session_store=session_store,
        copilot_store=copilot_store,
        executor=executor,
        context_service=context_service,
        ollama_client=ollama_client,
    )
    
    # Process turn
    events = []
    async for event in copilot.process_turn(
        session_id="test-session",
        user_message="List strategies twice",
        model="llama3",
        mode="analysis",
        stream=False,
    ):
        events.append(event)
    
    # Should emit error for duplicate
    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) > 0
    assert "duplicate" in error_events[0]["message"].lower()


@pytest.mark.asyncio
async def test_max_loop_guard():
    """Test that max steps guard prevents infinite loops."""
    # Mock dependencies
    services = MagicMock()
    session_store = MagicMock()
    copilot_store = MagicMock()
    executor = MagicMock()
    context_service = MagicMock()
    ollama_client = MagicMock()
    
    # Mock copilot store
    copilot_store.load_session.return_value = {
        "schema_version": "assistant_copilot_session_v2",
        "session_id": "test-session",
        "messages": [],
        "tool_runs": [],
        "pending_actions": [],
        "active_jobs": [],
    }
    copilot_store.save_session = MagicMock()
    
    # Mock context service
    context_service.build_context = MagicMock(return_value={})
    
    # Mock ollama client - always returns tool call
    mock_response = MagicMock()
    mock_response.content = "I'll keep calling tools."
    mock_response.tool_calls = [
        {"name": "list_strategies", "arguments": {}}
    ]
    ollama_client.chat = AsyncMock(return_value=mock_response)
    
    # Mock executor - returns success
    mock_result = WorkflowToolResult(
        tool_run_id="call_loop",
        tool_call_id="call_loop",
        tool_name="list_strategies",
        status=ToolRunStatus.COMPLETED,
        result_summary={"strategies": []},
    )
    executor.execute = AsyncMock(return_value=mock_result)
    
    # Create copilot
    copilot = WorkflowCopilot(
        services=services,
        session_store=session_store,
        copilot_store=copilot_store,
        executor=executor,
        context_service=context_service,
        ollama_client=ollama_client,
    )
    
    # Process turn
    events = []
    async for event in copilot.process_turn(
        session_id="test-session",
        user_message="Infinite loop",
        model="llama3",
        mode="analysis",
        stream=False,
    ):
        events.append(event)
    
    # Should hit max steps and stop
    # Verify model was called MAX_ORCHESTRATION_STEPS times
    from backend.services.ai.workflow_copilot import MAX_ORCHESTRATION_STEPS
    assert ollama_client.chat.call_count <= MAX_ORCHESTRATION_STEPS


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
