"""Router: GET /api/settings  &  POST /api/settings

Read and update the application configuration stored in
``data/strategy_lab_settings.json``.

GET  — returns the current effective settings as a validated JSON object.
POST — validates the full payload (path existence, allowlists), persists it,
       reloads the service graph so the change is live immediately, and
       re-wires log callbacks so the SSE stream is not interrupted.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...app_services import AppServices
from ...models import SaveSettingsRequest
from ..dependencies import get_log_broadcaster, get_services
from ..log_broadcaster import wire_service_callbacks

router = APIRouter(prefix="/api/settings", tags=["Settings"])


class SettingsResponse(BaseModel):
    """Current application settings as a plain JSON-serialisable dict."""

    settings: dict[str, Any]


@router.get(
    "",
    response_model=SettingsResponse,
    summary="Get current settings",
    description="Returns the active application configuration from the local settings file.",
)
async def get_settings(
    services: AppServices = Depends(get_services),
) -> SettingsResponse:
    settings = services.settings_store.load()
    return SettingsResponse(settings=settings.model_dump(mode="json"))


@router.post(
    "",
    response_model=SettingsResponse,
    summary="Update settings",
    description=(
        "Validates and persists a full settings payload. "
        "All path fields are verified to exist on disk. "
        "The internal service graph is reloaded so changes take effect "
        "immediately — no server restart required."
    ),
)
async def update_settings(
    body: SaveSettingsRequest,
    services: AppServices = Depends(get_services),
    log_broadcaster=Depends(get_log_broadcaster),
) -> SettingsResponse:
    updated = services.settings_store.save(body)

    services.reload()

    wire_service_callbacks(services, log_broadcaster)

    return SettingsResponse(settings=updated.model_dump(mode="json"))
