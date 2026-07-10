import pytest
from datetime import UTC, datetime
from unittest.mock import patch, MagicMock, AsyncMock

from backend.services.aeroing4.models import (
    AeRoing4Run,
    BiasCheckOutcome,
    BiasCheckItemResult,
    BiasCheckResult,
    AeRoing4StepStatus,
    SmokeBacktestOutcome
)
from backend.services.storage.bias_parser import BiasParser
from backend.services.aeroing4.steps.bias_check import BiasCheckStep
from backend.services.execution.bias_check_runner import BiasCheckCommandResult
from backend.app_services import AppServices


def test_bias_parser_lookahead_stdout_bias():
    stdout = "Lookahead bias found in indicator XYZ"
    res = BiasParser.parse_lookahead_stdout(stdout)
    assert res["status"] == "success"
    assert res["has_bias"] is True

def test_bias_parser_lookahead_stdout_clean():
    stdout = "0 pairs with lookahead bias"
    res = BiasParser.parse_lookahead_stdout(stdout)
    assert res["status"] == "success"
    assert res["has_bias"] is False

def test_bias_parser_lookahead_stdout_malformed():
    """Malformed output must not become PASS."""
    stdout = "Some random output that doesn't match expected patterns"
    res = BiasParser.parse_lookahead_stdout(stdout)
    assert res["status"] == "error"
    # Error status means we can't determine bias - parser returns error status
    # The 'has_bias' key may not be present in error case

def test_bias_parser_lookahead_stdout_empty():
    """Empty output must not become PASS."""
    stdout = ""
    res = BiasParser.parse_lookahead_stdout(stdout)
    assert res["status"] == "error"

def test_bias_parser_recursive_stdout_bias():
    stdout = "Recursive formula issue detected in RSI"
    res = BiasParser.parse_recursive_stdout(stdout)
    assert res["status"] == "success"
    assert res["has_bias"] is True

def test_bias_parser_recursive_stdout_clean():
    stdout = "All indicators are stable. No recursive formula issue."
    res = BiasParser.parse_recursive_stdout(stdout)
    assert res["status"] == "success"
    assert res["has_bias"] is False

def test_bias_parser_recursive_stdout_malformed():
    """Malformed output must not become PASS."""
    stdout = "Random output that doesn't match patterns"
    res = BiasParser.parse_recursive_stdout(stdout)
    assert res["status"] == "error"
    # Error status means we can't determine bias - parser returns error status

def test_bias_parser_recursive_stdout_empty():
    """Empty output must not become PASS."""
    stdout = ""
    res = BiasParser.parse_recursive_stdout(stdout)
    assert res["status"] == "error"


@pytest.mark.asyncio
async def test_bias_check_step_execution_failure():
    services = MagicMock(spec=AppServices)
    services.execution_services = MagicMock()
    runner_mock = MagicMock()
    
    # Mock Lookahead to fail execution
    runner_mock.run_lookahead_analysis.return_value = BiasCheckCommandResult(
        success=False, exit_code=1, stdout="", stderr="Crash", duration_seconds=1.0, command="freqtrade lookahead"
    )
    runner_mock.run_recursive_analysis.return_value = BiasCheckCommandResult(
        success=True, exit_code=0, stdout="No recursive formula", stderr="", duration_seconds=1.0, command="freqtrade recursive"
    )
    
    services.execution_services.bias_check_runner = runner_mock
    
    step = BiasCheckStep(services)
    result = await step.execute(
        strategy_name="Dummy",
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131"
    )
    
    assert result.status == AeRoing4StepStatus.FAILED
    assert result.data["outcome"] == BiasCheckOutcome.EXECUTION_FAILURE
    assert "Crash" in result.data["execution_errors"]


@pytest.mark.asyncio
async def test_bias_check_step_fatal_lookahead():
    services = MagicMock(spec=AppServices)
    services.execution_services = MagicMock()
    runner_mock = MagicMock()
    
    # Mock Lookahead to report bias
    runner_mock.run_lookahead_analysis.return_value = BiasCheckCommandResult(
        success=True, exit_code=0, stdout="Lookahead bias found", stderr="", duration_seconds=1.0, command="freqtrade lookahead"
    )
    runner_mock.run_recursive_analysis.return_value = BiasCheckCommandResult(
        success=True, exit_code=0, stdout="No recursive formula", stderr="", duration_seconds=1.0, command="freqtrade recursive"
    )
    
    services.execution_services.bias_check_runner = runner_mock
    
    step = BiasCheckStep(services)
    result = await step.execute(
        strategy_name="Dummy",
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131"
    )
    
    assert result.status == AeRoing4StepStatus.FAILED
    assert result.data["outcome"] == BiasCheckOutcome.FAIL_LOOKAHEAD


@pytest.mark.asyncio
async def test_bias_check_step_pass():
    services = MagicMock(spec=AppServices)
    services.execution_services = MagicMock()
    runner_mock = MagicMock()
    
    # Mock both cleanly
    runner_mock.run_lookahead_analysis.return_value = BiasCheckCommandResult(
        success=True, exit_code=0, stdout="0 pairs with lookahead", stderr="", duration_seconds=1.0, command="freqtrade lookahead"
    )
    runner_mock.run_recursive_analysis.return_value = BiasCheckCommandResult(
        success=True, exit_code=0, stdout="No recursive formula", stderr="", duration_seconds=1.0, command="freqtrade recursive"
    )
    
    services.execution_services.bias_check_runner = runner_mock
    
    step = BiasCheckStep(services)
    result = await step.execute(
        strategy_name="Dummy",
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131"
    )
    
    assert result.status == AeRoing4StepStatus.PASSED
    assert result.data["outcome"] == BiasCheckOutcome.PASS

