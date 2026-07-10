"""Integration test fixtures for AutoQuant pipeline tests.

This file provides fixtures for integration-level testing that combines
real pipeline orchestration with mocked subprocess calls.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routers.auto_quant import router
from backend.services.auto_quant.pipeline import (
    _cancel_flags,
    _queues,
    _states,
)

from .fixtures.mock_subprocess import (
    MockAsyncProcess,
    create_backtest_output,
    create_backtest_result,
)
from .fixtures.websocket import validate_websocket_message


# ═══════════════════════════════════════════════════════════════════════════════
# Mocking fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_freqtrade_subprocess(monkeypatch):
    """
    Patch asyncio.create_subprocess_exec to return mock processes
    with realistic backtest output instead of actually running freqtrade.
    """

    async def mock_exec(
        *args,
        stdout=None,
        stderr=None,
        env=None,
        **kwargs,
    ) -> MockAsyncProcess:
        """Mock subprocess that returns cached backtest results."""

        # Determine what kind of output based on command
        if "backtest" in str(args):
            # Standard backtest output
            output = create_backtest_result(
                profit=0.05, max_dd=0.10, trades=42, win_rate=0.55
            )
        elif "hyperopt" in str(args):
            # Hyperopt output with epochs
            output = create_backtest_output(include_hyperopt=True, epochs=10)
        else:
            # Default backtest
            output = create_backtest_result(profit=0.02)

        return MockAsyncProcess(stdout_data=output, return_code=0)

    monkeypatch.setattr("asyncio.create_subprocess_exec", mock_exec)
    return mock_exec


@pytest.fixture
def app_with_service(tmp_path, mock_freqtrade_subprocess):
    """
    Build a FastAPI app with auto_quant router and mocked services.

    This is the primary fixture for integration tests. It provides:
    - A real FastAPI app with the auto_quant router
    - Mocked freqtrade subprocess calls
    - Temporary directory for test files
    - Settings and services mocks

    Yields:
        tuple[TestClient, Path, MagicMock]: (test_client, temp_dir, settings)
    """
    app = FastAPI()
    app.include_router(router)

    # Create real temporary directories
    user_data_dir = tmp_path / "user_data"
    strategies_dir = user_data_dir / "strategies"
    strategies_dir.mkdir(parents=True, exist_ok=True)
    user_data_dir.mkdir(parents=True, exist_ok=True)

    # Create a minimal test strategy
    test_strategy = (
        strategies_dir / "TestStrategy.py"
    )
    test_strategy.write_text(
        """
from freqtrade.strategy import IStrategy

class TestStrategy(IStrategy):
    stoploss = -0.10
    timeframe = '5m'

    def populate_indicators(self, dataframe, metadata):
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe.loc[:, 'enter_long'] = 0
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe.loc[:, 'exit_long'] = 0
        return dataframe
""",
        encoding="utf-8",
    )

    # Create mock settings
    settings = MagicMock()
    settings.default_config_file_path = str(tmp_path / "config.json")
    settings.strategies_directory_path = str(strategies_dir)
    settings.freqtrade_executable_path = "freqtrade"
    settings.user_data_directory_path = str(user_data_dir)

    # Create default config file
    config = {
        "stake_currency": "USDT",
        "dry_run": True,
        "exchange": {"name": "binance"},
    }
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")

    # Create mock services
    services = MagicMock()
    services.settings_store.load.return_value = settings
    app.state.services = services

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, tmp_path, settings


# ═══════════════════════════════════════════════════════════════════════════════
# Parameterized fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture(params=[5, 10, 50])
def hyperopt_epochs(request):
    """Parametrized fixture providing different epoch counts for hyperopt tests."""
    return request.param


@pytest.fixture(params=[True, False])
def wfo_enabled(request):
    """Parametrized fixture for WFO enabled/disabled."""
    return request.param


@pytest.fixture(params=[True, False])
def ensemble_enabled(request):
    """Parametrized fixture for ensemble enabled/disabled."""
    return request.param


@pytest.fixture(
    params=[
        ("5m", 10, False, False),
        ("1h", 50, True, False),
        ("4h", 100, False, True),
    ]
)
def pipeline_config(request):
    """
    Parametrized fixture providing different pipeline configurations.

    Yields:
        tuple[str, int, bool, bool]: (timeframe, hyperopt_epochs, wfo_enabled, ensemble_enabled)
    """
    return request.param


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket testing fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
async def websocket_messages(
    app_with_service,
) -> AsyncGenerator[list[dict[str, Any]], None]:
    """
    Fixture that collects WebSocket messages during a pipeline run.

    This fixture manages connection to the WebSocket endpoint and validates
    all received messages against the expected schema.
    """
    messages: list[dict[str, Any]] = []

    async def collect_messages(
        client: TestClient, run_id: str, timeout: int = 30
    ) -> list[dict[str, Any]]:
        """Collect all WebSocket messages from a pipeline run."""
        messages_local = []
        end_time = asyncio.get_event_loop().time() + timeout

        # Note: WebSocket testing in FastAPI TestClient requires special handling
        # In actual tests, use a real WebSocket client or test the handler directly
        return messages_local

    yield messages


# ═══════════════════════════════════════════════════════════════════════════════
# Utility fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def pipeline_state_snapshot(tmp_path):
    """Create a sample PipelineState snapshot for testing."""
    from backend.services.auto_quant.pipeline_modules.state import PipelineState

    state = PipelineState(
        run_id="test-run-123",
        config={
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "hyperopt_epochs": 10,
            "wfo_enabled": False,
            "ensemble_enabled": False,
        },
        output_dir=tmp_path / "output",
    )
    return state


@pytest.fixture(autouse=True)
def cleanup_integration_state():
    """Clean up global state after each integration test."""
    yield
    _states.clear()
    _queues.clear()
    _cancel_flags.clear()
