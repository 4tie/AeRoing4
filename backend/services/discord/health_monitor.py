"""Health monitoring service for Discord integration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .discord_service import DiscordBotService

logger = logging.getLogger(__name__)


class DiscordHealthMonitor:
    """Periodic health monitoring with Discord alerts."""

    def __init__(
        self,
        discord_service: DiscordBotService,
        check_interval: int = 300,  # 5 minutes default
    ) -> None:
        """Initialize health monitor.

        Args:
            discord_service: Discord bot service instance
            check_interval: Check interval in seconds
        """
        self.discord_service = discord_service
        self.check_interval = check_interval
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start health monitoring background task."""
        if self._running:
            logger.warning("Health monitor already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Started Discord health monitor (interval: {self.check_interval}s)")

    async def stop(self) -> None:
        """Stop health monitoring background task."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("Stopped Discord health monitor")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check_health()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error in health monitor loop: {e}")
                await asyncio.sleep(self.check_interval)

    async def _check_health(self) -> None:
        """Perform health check and send alerts if needed."""
        if not self.discord_service.is_ready():
            logger.debug("Discord bot not ready, skipping health check")
            return

        try:
            # Import here to avoid circular dependency
            from ...app_services import AppServices
            from ...runtime import create_services
            from ...services.system import api_service as system_api
            from pathlib import Path

            services = create_services()
            settings = services.settings_store.load()
            root_dir = Path(services.root_dir)
            payload = await system_api.collect_health(settings, root_dir)

            # Check for issues
            issues = []

            # Check Freqtrade
            if not payload.get("freqtrade", {}).get("ok", True):
                issues.append("Freqtrade CLI is unavailable")

            # Check directories
            for dir_check in payload.get("directories", []):
                if not dir_check.get("ok", True):
                    issues.append(f"Directory issue: {dir_check['path']}")

            # Send alert if there are issues
            if issues and not payload.get("ok", True):
                await self._send_health_alert(payload, issues)
                logger.warning(f"Health check failed: {issues}")

        except Exception as e:
            logger.exception(f"Error performing health check: {e}")
            # Send alert about monitoring failure
            try:
                await self.discord_service.send_embed(
                    title="⚠️ Health Monitor Error",
                    description=f"Health monitoring encountered an error: {str(e)}",
                    color=0xFF0000,
                )
            except Exception:
                pass

    async def _send_health_alert(
        self,
        payload: dict,
        issues: list[str],
    ) -> None:
        """Send health alert to Discord.

        Args:
            payload: Health check payload
            issues: List of issues found
        """
        try:
            status_emoji = "❌"
            embed = discord.Embed(
                title=f"{status_emoji} System Health Alert",
                description="System health check detected issues",
                color=0xFF0000,
            )

            # Add issues
            for issue in issues:
                embed.add_field(name="Issue", value=issue, inline=False)

            # Add details if available
            if "freqtrade" in payload:
                freqtrade = payload["freqtrade"]
                if not freqtrade.get("ok", True):
                    embed.add_field(
                        name="Freqtrade Details",
                        value=freqtrade.get("message", "Unknown error"),
                        inline=False,
                    )

            await self.discord_service.send_message(embed=embed)
            logger.info("Sent health alert to Discord")

        except Exception as e:
            logger.exception(f"Failed to send health alert: {e}")

    async def manual_check(self) -> dict:
        """Perform manual health check and return results.

        Returns:
            Health check payload
        """
        try:
            from ...app_services import AppServices
            from ...runtime import create_services
            from ...services.system import api_service as system_api
            from pathlib import Path

            services = create_services()
            settings = services.settings_store.load()
            root_dir = Path(services.root_dir)
            payload = await system_api.collect_health(settings, root_dir)

            return payload

        except Exception as e:
            logger.exception(f"Error in manual health check: {e}")
            return {"ok": False, "error": str(e)}
