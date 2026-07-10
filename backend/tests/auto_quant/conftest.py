"""Pytest configuration for auto_quant tests.

This file makes fixtures available to all tests in this directory.
"""

from __future__ import annotations

# Import all fixtures from integration conftest
from .conftest_integration import (  # noqa: F401
    app_with_service,
    cleanup_integration_state,
    ensemble_enabled,
    hyperopt_epochs,
    mock_freqtrade_subprocess,
    pipeline_config,
    pipeline_state_snapshot,
    wfo_enabled,
    websocket_messages,
)
