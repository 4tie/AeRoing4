"""Tests for workflow tool executor behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models import (
    OptimizerScoreMetric,
    OptimizerSession,
    OptimizerSessionConfig,
    OptimizerSessionPhase,
    OptimizerTrial,
    OptimizerTrialMetrics,
    OptimizerTrialStatus,
)
from backend.services.ai.workflow_tool_executor import WorkflowToolExecutor
from backend.services.ai.workflow_tool_models import (
    ToolRunStatus,
    ToolSafety,
    WorkflowToolCall,
)


def _services(tmp_path):
    strategies = tmp_path / "strategies"
    strategies.mkdir()
    settings = SimpleNamespace(
        strategies_directory_path=str(strategies),
        user_data_directory_path=str(tmp_path / "user_data"),
        freqtrade_executable_path="freqtrade",
        default_config_file_path="config.json",
        ollama_model="llama3",
    )
    services = MagicMock()
    services.settings_store.load.return_value = settings
    services.optimizer_store = MagicMock()
    return services


def _executor(tmp_path) -> WorkflowToolExecutor:
    return WorkflowToolExecutor(
        services=_services(tmp_path),
        session_store=MagicMock(),
        copilot_store=MagicMock(),
        root_dir=tmp_path,
    )


@pytest.mark.asyncio
async def test_read_only_tool_executes_immediately(tmp_path):
    executor = _executor(tmp_path)
    result = await executor.execute(
        tool_call=WorkflowToolCall(
            tool_name="inspect_app_structure",
            arguments={},
            safety=ToolSafety.READ_ONLY,
        ),
        copilot_session_id="test-session",
        confirmed=False,
    )

    assert result.status == ToolRunStatus.COMPLETED
    assert result.result_summary["default_config"] == "config.json"


@pytest.mark.asyncio
async def test_guarded_tool_does_not_execute_before_confirmation(tmp_path):
    executor = _executor(tmp_path)
    result = await executor.execute(
        tool_call=WorkflowToolCall(
            tool_name="run_backtest",
            arguments={"strategy_name": "DemoStrategy", "timerange": "20240101-20240131"},
            safety=ToolSafety.CONFIRMATION_REQUIRED,
        ),
        copilot_session_id="test-session",
        confirmed=False,
    )

    assert result.status == ToolRunStatus.AWAITING_CONFIRMATION
    assert "confirmation required" in result.error.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("backend_status", "expected_status"),
    [
        ("completed", ToolRunStatus.COMPLETED),
        ("failed", ToolRunStatus.FAILED),
        ("cancelled", ToolRunStatus.CANCELLED),
        ("timed_out", ToolRunStatus.TIMED_OUT),
        ("running", ToolRunStatus.RUNNING),
        ("queued", ToolRunStatus.RUNNING),
    ],
)
async def test_long_running_backend_status_mapping(tmp_path, backend_status, expected_status):
    executor = _executor(tmp_path)
    executor._dispatch_handler = AsyncMock(
        return_value={
            "summary": {
                "api_session_id": "api-1",
                "status": backend_status,
                "error": "backend failed" if backend_status == "failed" else None,
            },
            "context_patch": {},
        }
    )

    result = await executor.execute(
        tool_call=WorkflowToolCall(
            tool_name="run_backtest",
            arguments={"strategy_name": "DemoStrategy", "timerange": "20240101-20240131"},
            safety=ToolSafety.CONFIRMATION_REQUIRED,
        ),
        copilot_session_id="test-session",
        confirmed=True,
    )

    assert result.status == expected_status
    if expected_status == ToolRunStatus.RUNNING:
        assert result.completed_at is None
    if expected_status == ToolRunStatus.FAILED:
        assert result.error == "backend failed"


@pytest.mark.asyncio
async def test_observation_timeout_is_never_completed(tmp_path):
    executor = _executor(tmp_path)
    executor._dispatch_handler = AsyncMock(
        return_value={
            "summary": {
                "api_session_id": "api-timeout",
                "status": "timed_out",
                "timed_out": True,
            },
            "context_patch": {},
        }
    )

    result = await executor.execute(
        tool_call=WorkflowToolCall(
            tool_name="run_optimizer",
            arguments={"strategy_name": "DemoStrategy", "timerange": "20240101-20240131"},
            safety=ToolSafety.CONFIRMATION_REQUIRED,
        ),
        copilot_session_id="test-session",
        confirmed=True,
    )

    assert result.status == ToolRunStatus.TIMED_OUT
    assert result.status != ToolRunStatus.COMPLETED


def _optimizer_session() -> OptimizerSession:
    return OptimizerSession(
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
        total_trials=2,
        completed_trials=2,
        best_trial_number=2,
        best_metrics=OptimizerTrialMetrics(score=1.7, profit_factor=2.1),
        trials=[
            OptimizerTrial(
                trial_number=1,
                status=OptimizerTrialStatus.COMPLETED,
                parameters={"buy": {"window": 12}},
                metrics=OptimizerTrialMetrics(score=0.9, profit_factor=1.4),
            ),
            OptimizerTrial(
                trial_number=2,
                status=OptimizerTrialStatus.COMPLETED,
                parameters={"buy": {"window": 21}},
                metrics=OptimizerTrialMetrics(score=1.7, profit_factor=2.1),
            ),
        ],
    )


@pytest.mark.asyncio
async def test_view_best_params_uses_real_optimizer_model_fields(tmp_path):
    executor = _executor(tmp_path)
    executor.services.optimizer_store.load_session.return_value = _optimizer_session()

    result = await executor.execute(
        tool_call=WorkflowToolCall(
            tool_name="view_best_params",
            arguments={"optimizer_session_id": "opt-1"},
            safety=ToolSafety.READ_ONLY,
        ),
        copilot_session_id="test-session",
    )

    assert result.status == ToolRunStatus.COMPLETED
    assert result.result_summary["best_trial_number"] == 2
    assert result.result_summary["parameters"] == {"buy": {"window": 21}}
    assert result.result_summary["metrics"]["score"] == 1.7


@pytest.mark.asyncio
async def test_view_trial_params_uses_real_optimizer_model_fields(tmp_path):
    executor = _executor(tmp_path)
    executor.services.optimizer_store.load_session.return_value = _optimizer_session()

    result = await executor.execute(
        tool_call=WorkflowToolCall(
            tool_name="view_trial_params",
            arguments={"optimizer_session_id": "opt-1", "trial_number": 1},
            safety=ToolSafety.READ_ONLY,
        ),
        copilot_session_id="test-session",
    )

    assert result.status == ToolRunStatus.COMPLETED
    assert result.result_summary["trial_number"] == 1
    assert result.result_summary["parameters"] == {"buy": {"window": 12}}
    assert result.result_summary["metrics"]["profit_factor"] == 1.4


@pytest.mark.asyncio
async def test_read_strategy_file_uses_resolver(tmp_path):
    executor = _executor(tmp_path)
    
    # Create the strategy file with case mismatch
    strat_dir = Path(executor.services.settings_store.load().strategies_directory_path)
    (strat_dir / "AIStrategy.py").write_text("class AIStrategy:\n    pass")
    
    # Execute with lowercase stem
    result = await executor.execute(
        tool_call=WorkflowToolCall(
            tool_name="read_strategy_file",
            arguments={"strategy_name": "aistrategy"},
            safety=ToolSafety.READ_ONLY,
        ),
        copilot_session_id="test-session",
    )
    
    assert result.status == ToolRunStatus.COMPLETED
    assert result.result_summary["strategy_name"] == "AIStrategy"
    assert "class AIStrategy" in result.result_summary["python_content"]


@pytest.mark.asyncio
async def test_get_pair_universe_returns_available_pairs(tmp_path):
    executor = _executor(tmp_path)
    
    # Mock pair_selector
    mock_state = MagicMock()
    mock_state.available_pairs = {"BTC/USDT", "ETH/USDT", "JTO/USDT", "SOL/BTC"}
    mock_state.extended_pairs = ["ADA/USDT"]
    
    mock_pair_selector = MagicMock()
    mock_pair_selector.get_state.return_value = mock_state
    
    executor.services.pair_selector = mock_pair_selector
    
    # Test with quote_currency and max_candidates filters
    result = await executor.execute(
        tool_call=WorkflowToolCall(
            tool_name="get_pair_universe",
            arguments={
                "quote_currency": "USDT",
                "exclude_pairs": ["ETH/USDT"],
                "max_candidates": 2,
            },
            safety=ToolSafety.READ_ONLY,
        ),
        copilot_session_id="test-session",
    )
    
    assert result.status == ToolRunStatus.COMPLETED
    summary = result.result_summary
    assert summary["total"] == 2
    assert len(summary["pairs"]) == 2
    assert "ETH/USDT" not in summary["pairs"]
    assert "SOL/BTC" not in summary["pairs"]
    assert "BTC/USDT" in summary["pairs"] or "JTO/USDT" in summary["pairs"] or "ADA/USDT" in summary["pairs"]

