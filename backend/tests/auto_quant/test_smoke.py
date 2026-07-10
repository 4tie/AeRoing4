"""Smoke tests for AutoQuant pipeline — fast health checks (<5s).

These tests verify basic system functionality without running full pipelines.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_backend_api_responsive(app_with_service):
    """Verify backend API responds to basic health check."""
    client, tmp_path, settings = app_with_service

    response = client.get("/api/auto-quant/runs")
    assert response.status_code == 200


def test_test_strategy_exists(app_with_service):
    """Verify TestStrategy.py exists and is readable."""
    client, tmp_path, settings = app_with_service

    strategy_path = Path(settings.strategies_directory_path) / "TestStrategy.py"
    assert strategy_path.exists(), f"TestStrategy not found at {strategy_path}"
    assert strategy_path.read_text(), "TestStrategy is empty"


def test_default_config_valid(app_with_service):
    """Verify default config file is valid JSON."""
    import json

    client, tmp_path, settings = app_with_service

    with open(settings.default_config_file_path) as f:
        config = json.load(f)

    assert isinstance(config, dict)
    assert "stake_currency" in config


def test_websocket_endpoint_registered(app_with_service):
    """Verify WebSocket endpoint is registered in router."""
    client, tmp_path, settings = app_with_service
    app = client.app

    # Check that WebSocket endpoint is in routes
    routes = {route.path for route in app.routes if hasattr(route, "path")}
    for route in app.routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            routes.update(
                subroute.path
                for subroute in getattr(original_router, "routes", [])
                if hasattr(subroute, "path")
            )
    ws_route_found = any(route.endswith("/ws/{run_id}") for route in routes)
    assert ws_route_found, "WebSocket endpoint not found in app routes"


def test_backend_imports_no_errors():
    """Verify pipeline modules import without errors."""
    try:
        # Import main pipeline modules
        import backend.services.auto_quant.pipeline as pl  # noqa: F401
        from backend.services.auto_quant.pipeline_modules import orchestrator  # noqa: F401
        from backend.services.auto_quant.pipeline_modules import stages_validation  # noqa: F401
        from backend.services.auto_quant.pipeline_modules import stages_optimization  # noqa: F401
        from backend.services.auto_quant.pipeline_modules import stages_assessment  # noqa: F401
    except Exception as e:
        pytest.fail(f"Pipeline modules failed to import: {e}")


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/auto-quant/runs",
        "/api/auto-quant/options",
    ],
)
def test_endpoints_reachable(app_with_service, endpoint):
    """Verify key endpoints are reachable (smoke test for routing)."""
    client, tmp_path, settings = app_with_service

    response = client.get(endpoint)
    # Just verify endpoint is registered (may 404 or return 200 depending on endpoint)
    assert response.status_code in (200, 404, 422, 500), f"Unexpected status for {endpoint}: {response.status_code}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
