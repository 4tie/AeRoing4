"""Router: /api/discord/*

  POST /api/discord/test           — Send test message to Discord
  POST /api/discord/config         — Update Discord configuration
  GET  /api/discord/status         — Get Discord bot connection status
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ...app_services import AppServices
from ..dependencies import get_services

router = APIRouter(prefix="/api/discord", tags=["Discord"])


# ── Request / response models ─────────────────────────────────────────────────


class TestMessageRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str = Field(..., description="Test message to send")
    channel_id: str | None = Field(None, description="Target channel ID (optional)")


class DiscordConfigRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(..., description="Enable/disable Discord integration")
    bot_token: str = Field("", description="Discord bot token")
    server_id: str = Field("", description="Discord server ID")
    user_id: str = Field("", description="Authorized user ID for admin commands")
    notification_channel_id: str | None = Field(None, description="Default notification channel ID")


class DiscordStatusResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool
    connected: bool
    bot_username: str | None = None
    server_id: str | None = None
    notification_channel_id: str | None = None


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post(
    "/test",
    summary="Send test message to Discord",
    description="Sends a test message to the configured Discord channel to verify connectivity.",
)
async def send_test_message(
    request: TestMessageRequest,
    services: AppServices = Depends(get_services),
) -> dict:
    """Send a test message to Discord."""
    discord_service = services.discord_service

    if not discord_service.is_ready():
        raise HTTPException(
            status_code=503,
            detail="Discord bot is not connected or not enabled",
        )

    success = await discord_service.send_message(
        content=request.message,
        channel_id=request.channel_id,
    )

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to send message to Discord",
        )

    return {"status": "success", "message": "Test message sent successfully"}


@router.post(
    "/config",
    summary="Update Discord configuration",
    description="Updates Discord integration configuration. Requires settings reload.",
)
async def update_discord_config(
    request: DiscordConfigRequest,
    services: AppServices = Depends(get_services),
) -> dict:
    """Update Discord configuration."""
    from ...models import SaveSettingsRequest

    # Load current settings
    current_settings = services.settings_store.load()

    # Update Discord fields
    update_data = current_settings.model_dump()
    update_data["discord_enabled"] = request.enabled
    update_data["discord_bot_token"] = request.bot_token
    update_data["discord_server_id"] = request.server_id
    update_data["discord_user_id"] = request.user_id
    update_data["discord_notification_channel_id"] = request.notification_channel_id

    # Save settings
    save_request = SaveSettingsRequest(**update_data)
    services.save_settings(save_request)

    return {"status": "success", "message": "Discord configuration updated"}


@router.get(
    "/status",
    summary="Get Discord bot status",
    description="Returns the current connection status and configuration of the Discord bot.",
)
async def get_discord_status(
    services: AppServices = Depends(get_services),
) -> DiscordStatusResponse:
    """Get Discord bot connection status."""
    settings = services.settings_store.load()
    discord_service = services.discord_service

    bot_username = None
    if discord_service.is_ready() and discord_service.client:
        bot_username = str(discord_service.client.user)

    return DiscordStatusResponse(
        enabled=settings.discord_enabled,
        connected=discord_service.is_ready(),
        bot_username=bot_username,
        server_id=settings.discord_server_id or None,
        notification_channel_id=settings.discord_notification_channel_id,
    )
