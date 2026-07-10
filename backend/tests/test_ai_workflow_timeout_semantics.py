from backend.services.ai.workflow_copilot import WorkflowCopilot
from backend.services.ai.workflow_tool_executor import WorkflowToolExecutor
from backend.services.ai.workflow_tool_models import ToolRunStatus, WorkflowToolResult


def test_observation_timeout_normalizes_to_observation_paused(tmp_path):
    executor = WorkflowToolExecutor(services={}, session_store=None, copilot_store=None)

    assert (
        executor._normalize_status("observation_timeout", "run_backtest")
        == ToolRunStatus.OBSERVATION_PAUSED
    )
    assert (
        executor._normalize_status("execution_timeout", "run_backtest")
        == ToolRunStatus.TIMED_OUT
    )


def test_terminal_events_keep_observation_and_execution_timeout_distinct():
    copilot = WorkflowCopilot(
        services={},
        session_store=None,
        copilot_store=None,
        executor=None,
        context_service=None,
        ollama_client=None,
    )

    observation_event = copilot._terminal_event_for_result(
        WorkflowToolResult(
            tool_run_id="run-1",
            tool_call_id="call-1",
            tool_name="run_backtest",
            status=ToolRunStatus.OBSERVATION_PAUSED,
            result_summary={"api_session_id": "api-1"},
        )
    )
    execution_event = copilot._terminal_event_for_result(
        WorkflowToolResult(
            tool_run_id="run-2",
            tool_call_id="call-2",
            tool_name="run_backtest",
            status=ToolRunStatus.TIMED_OUT,
            error="Execution timed out.",
        )
    )

    assert observation_event["type"] == "observation_timeout"
    assert observation_event["status"] == "observation_paused"
    assert execution_event["type"] == "tool_timed_out"
    assert execution_event["status"] == "timed_out"
