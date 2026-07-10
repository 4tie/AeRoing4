"""backend/tests/conftest.py — Shared fixtures for Auto-Quant tests.

This file contains pytest fixtures used across all test files.
Helper functions are in test_helpers.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Make project root importable ─────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

import backend.services.auto_quant.pipeline as pl
from backend.services.auto_quant.pipeline import (
    _cancel_flags,
    _queues,
    _states,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Pytest fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_path(tmp_path):
    """Provide a temporary path for test files."""
    return tmp_path


@pytest.fixture
def app_client(tmp_path):
    """
    Build a minimal FastAPI app with only the auto_quant router mounted,
    backed by a mock services/settings layer.
    """
    from backend.api.routers.auto_quant import router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router)

    # Mock the settings object the router reads from request.app.state.services
    settings = MagicMock()
    settings.default_config_file_path = str(tmp_path / "config.json")
    settings.strategies_directory_path = str(tmp_path / "strategies")
    settings.freqtrade_executable_path = "freqtrade"
    settings.user_data_directory_path = str(tmp_path / "user_data")

    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "strategies").mkdir(parents=True, exist_ok=True)
    (tmp_path / "user_data").mkdir(parents=True, exist_ok=True)

    services = MagicMock()
    services.settings_store.load.return_value = settings
    app.state.services = services

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, tmp_path, settings


@pytest.fixture(autouse=True)
def cleanup_state():
    """Clean up global state after each test to prevent cross-test contamination."""
    yield
    _states.clear()
    _queues.clear()
    _cancel_flags.clear()
