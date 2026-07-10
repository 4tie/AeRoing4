"""Tests for workflow tool registry."""

import pytest

from backend.services.ai.workflow_tool_registry import (
    calculate_arguments_hash,
    get_handler_name,
    get_model_tools,
    get_tool_safety,
    get_tool_spec,
    is_long_running,
    list_all_tools,
    validate_tool_arguments,
)
from backend.services.ai.workflow_tool_models import ToolSafety


def test_all_expected_tools_registered():
    """Test that all expected tools are registered."""
    expected_tools = {
        "inspect_app_structure",
        "list_strategies",
        "read_strategy_file",
        "validate_strategy_syntax",
        "view_best_params",
        "view_trial_params",
        "run_pair_explorer",
        "run_backtest",
        "run_optimizer",
        "run_pair_stress_lab",
        "run_temporal_stress_test",
        "edit_strategy_section",
    }
    registered = set(list_all_tools())
    assert expected_tools.issubset(registered), f"Missing tools: {expected_tools - registered}"


def test_unknown_tool_rejected():
    """Test that unknown tool returns None."""
    spec = get_tool_spec("unknown_tool")
    assert spec is None


def test_invalid_arguments_rejected():
    """Test that invalid arguments are rejected."""
    is_valid, error_msg, validated = validate_tool_arguments(
        "read_strategy_file",
        {"invalid_field": "value"}
    )
    assert not is_valid
    assert error_msg is not None
    assert validated is None


def test_valid_arguments_accepted():
    """Test that valid arguments are accepted."""
    is_valid, error_msg, validated = validate_tool_arguments(
        "read_strategy_file",
        {"strategy_name": "DemoStrategy"}
    )
    assert is_valid
    assert error_msg is None
    assert validated is not None
    assert validated.strategy_name == "DemoStrategy"


def test_policy_classification_correct():
    """Test that safety classification is correct."""
    assert get_tool_safety("read_strategy_file") == ToolSafety.READ_ONLY
    assert get_tool_safety("run_backtest") == ToolSafety.CONFIRMATION_REQUIRED
    assert get_tool_safety("unknown_tool") == ToolSafety.FORBIDDEN


def test_model_tool_schemas_generated_from_registry():
    """Test that model tool schemas are generated from registry."""
    tools = get_model_tools()
    assert isinstance(tools, list)
    assert len(tools) > 0
    
    # Check schema structure
    for tool in tools:
        assert "name" in tool
        assert "description" in tool
        assert "parameters" in tool
        assert "type" in tool["parameters"]
        assert "properties" in tool["parameters"]


def test_no_duplicate_hand_maintained_tool_policy_lists():
    """Test that there's no duplicate hand-maintained tool policy lists."""
    # This test verifies that the registry is the single source of truth
    # by checking that all tools come from the same registry
    tools = list_all_tools()
    for tool_name in tools:
        spec = get_tool_spec(tool_name)
        assert spec is not None
        assert spec.name == tool_name


def test_is_long_running():
    """Test that long-running tools are correctly identified."""
    assert is_long_running("run_backtest") is True
    assert is_long_running("run_optimizer") is True
    assert is_long_running("read_strategy_file") is False


def test_calculate_arguments_hash():
    """Test that argument hash is consistent."""
    hash1 = calculate_arguments_hash("run_backtest", {"strategy": "A", "pairs": ["BTC"]})
    hash2 = calculate_arguments_hash("run_backtest", {"strategy": "A", "pairs": ["BTC"]})
    hash3 = calculate_arguments_hash("run_backtest", {"strategy": "B", "pairs": ["BTC"]})
    
    assert hash1 == hash2
    assert hash1 != hash3


def test_get_handler_name():
    """Test that handler names are correctly resolved."""
    assert get_handler_name("run_backtest") == "run_backtest"
    assert get_handler_name("unknown_tool") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
