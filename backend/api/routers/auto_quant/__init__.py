"""Auto-Quant router package."""

from fastapi import APIRouter

# Create the main router
router = APIRouter(prefix="/api/auto-quant", tags=["Auto-Quant Factory"])

# Export StartAutoQuantRequest for tests
from .schemas import StartAutoQuantRequest

# Import and register all endpoint modules
from . import (
    pipeline_start,
    pipeline_control,
    pair_screening,
    ai_suggestions_endpoints,
    reports_endpoints,
    download_endpoints,
    runs_endpoints,
    regime_endpoints,
    genetic_endpoints,
    rl_endpoints,
    websocket_endpoint,
)

# Register endpoints from each module
pipeline_start.register_pipeline_start_endpoints(router)
pipeline_control.register_pipeline_control_endpoints(router)
pair_screening.register_pair_screening_endpoints(router)
ai_suggestions_endpoints.register_ai_suggestions_endpoints(router)
reports_endpoints.register_reports_endpoints(router)
download_endpoints.register_download_endpoints(router)
runs_endpoints.register_runs_endpoints(router)
regime_endpoints.register_regime_endpoints(router)
genetic_endpoints.register_genetic_endpoints(router)
rl_endpoints.register_rl_endpoints(router)
websocket_endpoint.register_websocket_endpoint(router)

__all__ = ["router", "StartAutoQuantRequest"]
