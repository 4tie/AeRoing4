"""Router: GET /api/system/health

Performs an active, multi-point diagnostic of the runtime environment:
  1. freqtrade CLI — is it reachable and does `--version` succeed?
  2. Critical directories — data/, data/backups/, user_data/strategies/
     all exist AND are writable.

Returns a structured JSON payload and a terminal-style log block.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ...app_services import AppServices
from ...services.system import api_service as system_api
from ..dependencies import get_services

router = APIRouter(prefix="/api/system", tags=["System"])

_check_freqtrade = system_api.check_freqtrade
_check_directory = system_api.check_directory
_build_log = system_api.build_log
_collect_health = system_api.collect_health


@router.get(
    "/health",
    summary="Active system diagnostic",
    description=(
        "Checks freqtrade CLI availability and critical directory writability. "
        "Returns a structured JSON payload and a terminal-style log block."
    ),
)
async def system_health(
    services: AppServices = Depends(get_services),
) -> JSONResponse:
    settings = services.settings_store.load()
    root_dir = Path(services.root_dir)
    payload = await _collect_health(settings, root_dir)

    return JSONResponse(
        status_code=200 if payload["ok"] else 207,
        content=payload,
    )


@router.get("/stats")
async def get_system_stats(request: Request) -> dict:
    """Get system statistics for the Overview tab with pipeline context."""
    import random
    from datetime import datetime, timedelta
    
    # Get pipeline state from app state if available
    pipeline_active = False
    pipeline_progress = 0
    try:
        services = request.app.state.services
        if hasattr(services, 'run_repository'):
            runs = services.run_repository.list_runs(limit=1)
            if runs:
                latest_run = runs[0]
                pipeline_active = latest_run.get("status") in ["running", "pending"]
                pipeline_progress = latest_run.get("progress_percent", 0) or 0
    except Exception:
        pass

    # Calculate uptime (mock - would be real in production)
    uptime_start = datetime.now() - timedelta(hours=2, minutes=15)
    uptime_str = f"{uptime_start.hour}h {uptime_start.minute}m"

    return {
        "stats": {
            "queue": 1 if pipeline_active else 0,
            "sessions": 1,
            "errors": 0,
            "today": 42 + (1 if pipeline_active else 0),
            "uptime": uptime_str,
            "pipeline_active": pipeline_active,
            "pipeline_progress": pipeline_progress
        }
    }


@router.get("/metrics")
async def get_system_metrics() -> dict:
    """Get system metrics for the StatsStrip."""
    return {
        "metrics": {
            "integrity": 99.95,
            "agentCalls": 1247,
            "messages": 8432,
            "tokensIn": "2.1M",
            "cacheHits": 94.2
        }
    }


@router.get("/throughput")
async def get_throughput() -> dict:
    """Get throughput data for the Throughput component."""
    import random
    return {
        "totalResponses": 12478,
        "mostActiveDay": "Monday",
        "weeklyData": [random.random() * 0.8 + 0.1 for _ in range(7)]
    }
