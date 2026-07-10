"""Notification hooks for Discord integration with AutoQuant pipeline."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .discord_service import DiscordBotService

logger = logging.getLogger(__name__)


class DiscordNotificationHooks:
    """Hooks for sending Discord notifications on AutoQuant events."""

    def __init__(self, discord_service: DiscordBotService) -> None:
        """Initialize notification hooks.

        Args:
            discord_service: Discord bot service instance
        """
        self.discord_service = discord_service

    async def notify_pipeline_started(
        self,
        run_id: str,
        strategy: str,
        timeframe: str,
        exchange: str,
    ) -> None:
        """Send notification when AutoQuant pipeline starts.

        Args:
            run_id: Pipeline run ID
            strategy: Strategy name
            timeframe: Timeframe
            exchange: Exchange name
        """
        if not self.discord_service.is_ready():
            return

        try:
            await self.discord_service.send_embed(
                title="🚀 AutoQuant Pipeline Started",
                description=f"Pipeline run `{run_id}` has started",
                color=0x00FF00,
                fields=[
                    ("Strategy", strategy, True),
                    ("Timeframe", timeframe, True),
                    ("Exchange", exchange, True),
                ],
            )
            logger.info(f"Sent Discord notification for pipeline start: {run_id}")
        except Exception as e:
            logger.exception(f"Failed to send pipeline start notification: {e}")

    async def notify_pipeline_completed(
        self,
        run_id: str,
        strategy: str,
        status: str,
        report: dict | None = None,
    ) -> None:
        """Send notification when AutoQuant pipeline completes.

        Args:
            run_id: Pipeline run ID
            strategy: Strategy name
            status: Pipeline status (completed, failed, cancelled)
            report: Optional pipeline report
        """
        if not self.discord_service.is_ready():
            return

        try:
            color = 0x00FF00 if status == "completed" else 0xFF0000
            emoji = "✅" if status == "completed" else "❌"

            fields = [
                ("Strategy", strategy, True),
                ("Status", status.title(), True),
            ]

            if report:
                # Add key metrics from report
                if "final_metrics" in report:
                    metrics = report["final_metrics"]
                    if "profit_factor" in metrics:
                        fields.append(("Profit Factor", f"{metrics['profit_factor']:.2f}", True))
                    if "sharpe" in metrics:
                        fields.append(("Sharpe", f"{metrics['sharpe']:.2f}", True))
                    if "max_drawdown" in metrics:
                        fields.append(("Max Drawdown", f"{metrics['max_drawdown']:.2%}", True))

            await self.discord_service.send_embed(
                title=f"{emoji} AutoQuant Pipeline {status.title()}",
                description=f"Pipeline run `{run_id}` has {status}",
                color=color,
                fields=fields,
            )
            logger.info(f"Sent Discord notification for pipeline completion: {run_id}")
        except Exception as e:
            logger.exception(f"Failed to send pipeline completion notification: {e}")

    async def notify_stage_started(
        self,
        run_id: str,
        stage_name: str,
        stage_index: int,
    ) -> None:
        """Send notification when a pipeline stage starts.

        Args:
            run_id: Pipeline run ID
            stage_name: Stage name
            stage_index: Stage index
        """
        if not self.discord_service.is_ready():
            return

        try:
            await self.discord_service.send_embed(
                title="🔄 Pipeline Stage Started",
                description=f"Stage {stage_index}: {stage_name}",
                color=0x00AAFF,
                fields=[("Run ID", run_id, True)],
            )
            logger.debug(f"Sent Discord notification for stage start: {stage_name}")
        except Exception as e:
            logger.exception(f"Failed to send stage start notification: {e}")

    async def notify_stage_completed(
        self,
        run_id: str,
        stage_name: str,
        stage_index: int,
        status: str,
        metrics: dict | None = None,
    ) -> None:
        """Send notification when a pipeline stage completes.

        Args:
            run_id: Pipeline run ID
            stage_name: Stage name
            stage_index: Stage index
            status: Stage status (passed, failed, skipped)
            metrics: Optional stage metrics
        """
        if not self.discord_service.is_ready():
            return

        try:
            color = 0x00FF00 if status == "passed" else 0xFF0000
            emoji = "✅" if status == "passed" else "❌"

            fields = [
                ("Stage", f"{stage_index}: {stage_name}", True),
                ("Status", status.title(), True),
            ]

            if metrics:
                # Add key metrics
                if "profit" in metrics:
                    fields.append(("Profit", f"{metrics['profit']:.2f}", True))
                if "trades" in metrics:
                    fields.append(("Trades", str(metrics['trades']), True))

            await self.discord_service.send_embed(
                title=f"{emoji} Stage {status.title()}",
                description=f"Pipeline run `{run_id}`",
                color=color,
                fields=fields,
            )
            logger.debug(f"Sent Discord notification for stage completion: {stage_name}")
        except Exception as e:
            logger.exception(f"Failed to send stage completion notification: {e}")

    async def notify_error(
        self,
        run_id: str,
        error: str,
        context: str = "",
    ) -> None:
        """Send notification on pipeline error.

        Args:
            run_id: Pipeline run ID
            error: Error message
            context: Additional context
        """
        if not self.discord_service.is_ready():
            return

        try:
            description = f"Pipeline run `{run_id}` encountered an error"
            if context:
                description += f"\n\nContext: {context}"

            await self.discord_service.send_embed(
                title="⚠️ Pipeline Error",
                description=description,
                color=0xFF0000,
                fields=[
                    ("Error", error[:1000], False),  # Truncate long errors
                ],
            )
            logger.warning(f"Sent Discord error notification for run: {run_id}")
        except Exception as e:
            logger.exception(f"Failed to send error notification: {e}")

    async def notify_strategy_result(
        self,
        strategy: str,
        profit: float,
        profit_factor: float,
        sharpe: float,
        max_drawdown: float,
        win_rate: float,
    ) -> None:
        """Send notification for strategy backtest results.

        Args:
            strategy: Strategy name
            profit: Total profit
            profit_factor: Profit factor
            sharpe: Sharpe ratio
            max_drawdown: Maximum drawdown
            win_rate: Win rate
        """
        if not self.discord_service.is_ready():
            return

        try:
            # Determine color based on performance
            color = 0x00FF00 if profit > 0 and max_drawdown < 0.3 else 0xFFAA00

            await self.discord_service.send_embed(
                title="📊 Strategy Backtest Results",
                description=f"Results for `{strategy}`",
                color=color,
                fields=[
                    ("Profit", f"{profit:.2f}", True),
                    ("Profit Factor", f"{profit_factor:.2f}", True),
                    ("Sharpe", f"{sharpe:.2f}", True),
                    ("Max Drawdown", f"{max_drawdown:.2%}", True),
                    ("Win Rate", f"{win_rate:.2%}", True),
                ],
            )
            logger.info(f"Sent Discord notification for strategy result: {strategy}")
        except Exception as e:
            logger.exception(f"Failed to send strategy result notification: {e}")
