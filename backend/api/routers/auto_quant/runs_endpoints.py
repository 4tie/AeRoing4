"""Runs listing and options endpoints for Auto-Quant."""

from fastapi import APIRouter, Request

from ....services.auto_quant.api_service import (
    get_pipeline_status,
    list_pipeline_runs,
    load_options_data,
    request_pipeline_cancel,
    save_options_data,
)

from .schemas import AutoQuantOptions


def register_runs_endpoints(router: APIRouter) -> None:
    """Register runs listing and options endpoints on the given router."""
    
    @router.get(
        "/run/{run_id}",
        summary="Compatibility alias for getting a single Auto-Quant run",
    )
    async def get_run_singular_alias(run_id: str) -> dict:
        return get_pipeline_status(run_id)

    @router.get(
        "/runs",
        summary="List all pipeline runs",
    )
    async def list_runs() -> dict:
        return list_pipeline_runs()

    @router.get(
        "/runs/{run_id}",
        summary="Compatibility alias for getting a single Auto-Quant run",
    )
    async def get_run_alias(run_id: str) -> dict:
        return get_pipeline_status(run_id)

    @router.delete(
        "/runs/{run_id}",
        summary="Compatibility alias for cancelling a running Auto-Quant run",
    )
    async def cancel_run_alias(run_id: str) -> dict:
        result = request_pipeline_cancel(run_id)
        return {
            "success": True,
            "message": "Cancellation requested",
            **result,
        }

    @router.get(
        "/options",
        summary="Load saved Auto-Quant form options",
    )
    async def get_options(request: Request) -> AutoQuantOptions:
        """Load saved Auto-Quant form options from JSON file."""
        services = request.app.state.services
        settings = services.settings_store.load()
        return AutoQuantOptions(**load_options_data(settings.user_data_directory_path))

    @router.post(
        "/options",
        summary="Save Auto-Quant form options",
    )
    async def save_options(body: AutoQuantOptions, request: Request) -> dict:
        """Save Auto-Quant form options to JSON file."""
        services = request.app.state.services
        settings = services.settings_store.load()
        return save_options_data(settings.user_data_directory_path, body.model_dump(mode="json"))
