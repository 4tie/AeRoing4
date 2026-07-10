"""AI agent router package."""

from fastapi import APIRouter

# Create the main router
router = APIRouter(prefix="/api/ai-agent", tags=["AI Agent"])

# Import and register all endpoint modules
from . import (
    discovery_endpoints,
    strategy_tool_endpoints,
    app_structure_endpoint,
    execution_tool_endpoints,
    report_endpoint,
    chat_endpoint,
)
from .session_manager import SessionManager

# Register endpoints from each module
discovery_endpoints.register_discovery_endpoints(router)
strategy_tool_endpoints.register_strategy_tool_endpoints(router)
app_structure_endpoint.register_app_structure_endpoint(router)
execution_tool_endpoints.register_execution_tool_endpoints(router)
report_endpoint.register_report_endpoint(router)
chat_endpoint.register_chat_endpoint(router)

__all__ = ["router", "SessionManager"]
