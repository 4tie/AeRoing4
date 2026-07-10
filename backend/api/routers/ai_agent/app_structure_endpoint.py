"""App structure endpoint for AI agent router."""

from fastapi import APIRouter, Request

from .helpers import _log_action
from .schemas import ToolExecutionRequest, ToolExecutionResponse


def register_app_structure_endpoint(router: APIRouter) -> None:
    """Register app structure endpoint on the given router."""
    
    @router.post(
        "/tools/inspect_app_structure",
        summary="Inspect app structure",
        description="Inspect the app structure to understand available tools and configuration.",
    )
    async def inspect_app_structure(body: ToolExecutionRequest, request: Request) -> ToolExecutionResponse:
        """Inspect the app structure."""
        try:
            services = request.app.state.services
            settings = services.settings_store.load()
            
            result = {
                "strategies_directory": settings.strategies_directory_path,
                "user_data_directory": settings.user_data_directory_path,
                "freqtrade_executable": settings.freqtrade_executable_path,
                "default_config": settings.default_config_file_path,
                "available_endpoints": [
                    "/api/pair-explorer/run",
                    "/api/backtest/run",
                    "/api/optimizer/run",
                    "/api/stress-lab/run",
                    "/api/temporal-stress-lab/run",
                    "/api/strategies/save",
                    "/api/strategies/validate"
                ],
                "ollama_configured": bool(settings.ollama_model),
                "ollama_model": settings.ollama_model or "Not configured"
            }
            
            _log_action(body.session_id, "inspect_app_structure", result, request)
            
            return ToolExecutionResponse(
                success=True,
                result=result,
                logs=[{"message": "Successfully inspected app structure"}]
            )
            
        except Exception as e:
            return ToolExecutionResponse(
                success=False,
                error=f"Failed to inspect app structure: {str(e)}"
            )
