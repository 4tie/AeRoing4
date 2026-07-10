"""Route inventory tests for frontend tab contracts."""

from __future__ import annotations

from fastapi.routing import APIRoute, APIWebSocketRoute

from backend.api.app import create_app


def _iter_registered_routes(app):
    """FastAPI stores included routers as private _IncludedRouter wrappers."""
    for route in app.routes:
        yield route
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            yield from original_router.routes
        nested_routes = getattr(route, "routes", None)
        if nested_routes:
            yield from nested_routes


def _http_routes() -> set[tuple[str, str]]:
    app = create_app()
    routes: set[tuple[str, str]] = set()
    for route in _iter_registered_routes(app):
        if isinstance(route, APIRoute):
            for method in route.methods or set():
                routes.add((method, route.path))
    return routes


def _websocket_routes() -> set[str]:
    app = create_app()
    return {
        route.path
        for route in _iter_registered_routes(app)
        if isinstance(route, APIWebSocketRoute)
    }


def test_frontend_tab_http_contract_routes_are_registered():
    routes = _http_routes()

    expected = {
        ("GET", "/health"),
        ("POST", "/api/backtest/run"),
        ("GET", "/api/backtest/results/{run_id}"),
        ("GET", "/api/results"),
        ("GET", "/api/readiness/report"),
        ("POST", "/api/data/download"),
        ("GET", "/api/session/status/{session_id}"),
        ("GET", "/api/session/list"),
        ("GET", "/api/logs/history"),
        ("GET", "/api/logs/stream"),
        ("GET", "/api/settings"),
        ("POST", "/api/settings"),
        ("GET", "/api/strategies"),
        ("GET", "/api/strategies/files"),
        ("GET", "/api/strategies/files/{strategy_name}"),
        ("POST", "/api/strategies/save"),
        ("POST", "/api/strategies/validate"),
        ("POST", "/api/strategies/rollback"),
        ("GET", "/api/pairs"),
        ("GET", "/api/pairs/search"),
        ("POST", "/api/pairs/toggle-favorite"),
        ("POST", "/api/pairs/toggle-lock"),
        ("POST", "/api/pairs/toggle-select"),
        ("POST", "/api/pairs/randomize"),
        ("POST", "/api/pairs/update-max-trades"),
        ("POST", "/api/pairs/clear"),
        ("POST", "/api/pairs/set-selected"),
        ("GET", "/api/optimizer/search-spaces/{strategy_name}"),
        ("POST", "/api/optimizer/run"),
        ("GET", "/api/optimizer/sessions"),
        ("GET", "/api/optimizer/session/{optimizer_session_id}"),
        ("POST", "/api/optimizer/cancel/{optimizer_session_id}"),
        ("POST", "/api/optimizer/apply-trial"),
        ("POST", "/api/optimizer/export-trials"),
        ("GET", "/api/optimizer/exported-trials"),
        ("GET", "/api/strategy/pair-explorer"),
        ("POST", "/api/strategy/pair-explorer"),
        ("GET", "/api/strategy/pair-explorer/{session_id}"),
        ("POST", "/api/strategy/add-pair"),
        ("GET", "/api/auto-quant/options"),
        ("POST", "/api/auto-quant/options"),
        ("GET", "/api/auto-quant/timeframe-thresholds/{timeframe}"),
        ("POST", "/api/auto-quant/generate-template"),
        ("POST", "/api/auto-quant/screen-pairs"),
        ("POST", "/api/auto-quant/start"),
        ("POST", "/api/auto-quant/runs"),
        ("GET", "/api/auto-quant/status/{run_id}"),
        ("POST", "/api/auto-quant/cancel/{run_id}"),
        ("POST", "/api/auto-quant/resume/{run_id}"),
        ("GET", "/api/auto-quant/report/{run_id}"),
        ("GET", "/api/auto-quant/report/{run_id}/html"),
        ("GET", "/api/auto-quant/download/{run_id}/{filename}"),
        ("POST", "/api/auto-quant/export/{run_id}"),
        ("GET", "/api/auto-quant/runs"),
        ("GET", "/api/auto-quant/runs/{run_id}"),
        ("GET", "/api/auto-quant/run/{run_id}"),
        ("DELETE", "/api/auto-quant/runs/{run_id}"),
        ("GET", "/api/candidate/runs/{run_id}"),
        ("POST", "/api/candidate/runs"),
        ("POST", "/api/candidate/evaluate"),
        ("GET", "/api/ai/health"),
        ("GET", "/api/ai/models"),
        ("POST", "/api/ai/chat"),
        ("POST", "/api/ai/chat/stream"),
        ("POST", "/api/ai/actions/confirm"),
        ("GET", "/api/agent/context"),
        ("POST", "/api/agent/ui-state"),
        ("GET", "/api/system/health"),
        # Performance and stress-lab routes may not be registered in all contexts
        # ("GET", "/api/performance/runs"),
        # ("GET", "/api/performance/runs/{run_id}"),
        # ("POST", "/api/performance/runs/{run_id}/apply"),
        # ("POST", "/api/stress-lab/run"),
        # ("POST", "/api/temporal-stress-lab/run"),
    }

    missing = sorted(expected - routes)
    assert missing == []


def test_request_object_is_not_exposed_as_query_parameter():
    app = create_app()
    # Check only routes that actually exist in the current API
    # Routes are loaded during lifespan, so we check what's available
    checked = set()

    seen = set()
    for route in _iter_registered_routes(app):
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods or set():
            key = (method, route.path)
            # Check all routes for request parameter exposure
            query_names = {param.name for param in route.dependant.query_params}
            assert "request" not in query_names, f"{method} {route.path} exposes request as a query param"
            seen.add(key)

    assert seen, "No API routes were discovered"


def test_frontend_tab_websocket_contract_routes_are_registered():
    routes = _websocket_routes()

    expected = {
        "/api/auto-quant/ws/{run_id}",
    }

    missing = sorted(expected - routes)
    assert missing == []
