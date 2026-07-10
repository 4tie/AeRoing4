"""Ollama health monitoring service for proactive reliability management."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from .ollama_client import OllamaClient
from .ollama_config import config_from_user_data_dir, resolve_user_data_dir

logger = logging.getLogger(__name__)


class OllamaHealthMonitor:
    """Background health checker for Ollama service."""

    def __init__(
        self,
        user_data_dir: Any,
        check_interval: int = 60,
        enabled: bool = True,
    ) -> None:
        """Initialize health monitor.

        Args:
            user_data_dir: Path to user_data directory
            check_interval: Seconds between health checks
            enabled: Whether health monitoring is enabled
        """
        self.user_data_dir = resolve_user_data_dir(user_data_dir)
        self.check_interval = check_interval
        self.enabled = enabled
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

        # Health state
        self._healthy = True
        self._last_check_time: datetime | None = None
        self._last_check_result: dict[str, Any] | None = None
        self._consecutive_failures = 0
        self._consecutive_successes = 0

    async def start(self) -> None:
        """Start background health monitoring."""
        if not self.enabled:
            logger.info("Health monitoring is disabled")
            return

        async with self._lock:
            if self._running:
                logger.warning("Health monitor is already running")
                return

            self._running = True
            self._task = asyncio.create_task(self._monitor_loop())
            logger.info("Started Ollama health monitor (interval=%ds)", self.check_interval)

    async def stop(self) -> None:
        """Stop background health monitoring."""
        async with self._lock:
            if not self._running:
                return

            self._running = False
            if self._task:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None

            logger.info("Stopped Ollama health monitor")

    async def _monitor_loop(self) -> None:
        """Background health check loop."""
        while self._running:
            try:
                await self._check_health()
            except Exception as exc:
                logger.error("Health check failed: %s", exc)

            # Wait for next check interval
            try:
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break

    async def _check_health(self) -> None:
        """Perform a single health check."""
        config = config_from_user_data_dir(self.user_data_dir, require_model=False)
        if config is None:
            logger.warning("Cannot check health: no Ollama config")
            self._update_health_state(False, {"error": "No Ollama config"})
            return

        client = OllamaClient(config=config)
        try:
            result = await client.health()
            self._update_health_state(result.get("healthy", False), result)
        except Exception as exc:
            logger.warning("Health check exception: %s", exc)
            self._update_health_state(False, {"error": str(exc)})
        finally:
            await client.close()

    def _update_health_state(self, healthy: bool, result: dict[str, Any]) -> None:
        """Update health state based on check result."""
        self._last_check_time = datetime.now(UTC)
        self._last_check_result = result

        if healthy:
            self._consecutive_successes += 1
            self._consecutive_failures = 0
            if not self._healthy:
                logger.info("Ollama health changed: unhealthy -> healthy")
            self._healthy = True
        else:
            self._consecutive_failures += 1
            self._consecutive_successes = 0
            if self._healthy:
                logger.warning("Ollama health changed: healthy -> unhealthy")
            self._healthy = False

    def reset_failure_count(self) -> None:
        """Reset consecutive failure count to allow recovery."""
        if self._consecutive_failures > 0:
            logger.info("Health monitor reset: clearing %d consecutive failures", self._consecutive_failures)
            self._consecutive_failures = 0
            self._consecutive_successes = 0
            self._healthy = True

    def get_health_state(self) -> dict[str, Any]:
        """Get current health state for monitoring."""
        return {
            "healthy": self._healthy,
            "last_check_time": self._last_check_time.isoformat() if self._last_check_time else None,
            "last_check_result": self._last_check_result,
            "consecutive_failures": self._consecutive_failures,
            "consecutive_successes": self._consecutive_successes,
            "monitor_enabled": self.enabled,
            "monitor_running": self._running,
        }

    def is_healthy(self) -> bool:
        """Check if Ollama is currently healthy."""
        return self._healthy

    async def force_check(self) -> dict[str, Any]:
        """Force an immediate health check."""
        await self._check_health()
        return self.get_health_state()


# Singleton instance management
_health_monitor: OllamaHealthMonitor | None = None
_health_monitor_lock = asyncio.Lock()


async def get_health_monitor(
    user_data_dir: Any,
    check_interval: int = 60,
    enabled: bool = True,
) -> OllamaHealthMonitor:
    """Get or create the singleton health monitor instance.

    Args:
        user_data_dir: Path to user_data directory
        check_interval: Seconds between health checks
        enabled: Whether health monitoring is enabled

    Returns:
        OllamaHealthMonitor singleton instance
    """
    global _health_monitor

    resolved_user_data_dir = resolve_user_data_dir(user_data_dir)

    async with _health_monitor_lock:
        if _health_monitor is None or _health_monitor.user_data_dir != resolved_user_data_dir:
            if _health_monitor is not None:
                await _health_monitor.stop()
            _health_monitor = OllamaHealthMonitor(
                resolved_user_data_dir,
                check_interval=check_interval,
                enabled=enabled,
            )
            logger.info("Created health monitor instance for %s", resolved_user_data_dir)
        return _health_monitor


async def cleanup_health_monitor() -> None:
    """Cleanup the singleton health monitor instance.

    Should be called during application shutdown.
    """
    global _health_monitor

    async with _health_monitor_lock:
        if _health_monitor is not None:
            await _health_monitor.stop()
            _health_monitor = None
            logger.info("Cleaned up health monitor instance")
