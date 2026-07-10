"""Discord slash command handlers for Strategy Lab."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands

if TYPE_CHECKING:
    from .discord_service import DiscordBotService

logger = logging.getLogger(__name__)


class DiscordCommandHandlers:
    """Discord slash command handlers for Strategy Lab."""

    def __init__(self, discord_service: DiscordBotService) -> None:
        """Initialize command handlers.

        Args:
            discord_service: Discord bot service instance
        """
        self.discord_service = discord_service
        self._setup_commands()

    def _setup_commands(self) -> None:
        """Register all slash commands with the Discord bot."""
        if not self.discord_service.tree:
            return

        tree = self.discord_service.tree

        # Register commands
        tree.command(name="status", description="Get system health status")(self.cmd_status)
        tree.command(name="list_strategies", description="List available strategies")(self.cmd_list_strategies)
        tree.command(name="autoquant_status", description="Get AutoQuant pipeline status")(self.cmd_autoquant_status)
        tree.command(name="help", description="Show available commands and instructions")(self.cmd_help)

    async def cmd_status(self, interaction: discord.Interaction) -> None:
        """Handle /status command - Get system health status."""
        # Check permissions
        if not self.discord_service.get_user_permission(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            # Import here to avoid circular dependency
            from ...app_services import AppServices
            from ...runtime import create_services

            services = create_services()
            from ...services.system import api_service as system_api

            settings = services.settings_store.load()
            from pathlib import Path
            root_dir = Path(services.root_dir)
            payload = await system_api.collect_health(settings, root_dir)

            # Format response
            status_emoji = "✅" if payload["ok"] else "❌"
            embed = discord.Embed(
                title=f"{status_emoji} System Health Status",
                color=0x00FF00 if payload["ok"] else 0xFF0000,
            )

            # Add freqtrade status
            if "freqtrade" in payload:
                freqtrade_ok = payload["freqtrade"]["ok"]
                embed.add_field(
                    name="Freqtrade CLI",
                    value=f"{'✅ Available' if freqtrade_ok else '❌ Unavailable'}",
                    inline=True,
                )

            # Add directory status
            if "directories" in payload:
                dirs_ok = all(d["ok"] for d in payload["directories"])
                embed.add_field(
                    name="Critical Directories",
                    value=f"{'✅ All OK' if dirs_ok else '❌ Some failed'}",
                    inline=True,
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.exception(f"Error in /status command: {e}")
            await interaction.followup.send(
                f"❌ Error getting system status: {str(e)}",
                ephemeral=True,
            )

    async def cmd_list_strategies(self, interaction: discord.Interaction) -> None:
        """Handle /list_strategies command - List available strategies."""
        await interaction.response.defer()

        try:
            from ...app_services import AppServices
            from ...runtime import create_services

            services = create_services()
            strategies = services.registry.list_strategies()

            if not strategies:
                await interaction.followup.send("No strategies found.", ephemeral=True)
                return

            # Format strategy list
            strategy_list = "\n".join(f"• {s}" for s in strategies[:20])  # Limit to 20
            if len(strategies) > 20:
                strategy_list += f"\n... and {len(strategies) - 20} more"

            embed = discord.Embed(
                title="📋 Available Strategies",
                description=strategy_list,
                color=0x00AAFF,
            )
            embed.add_field(name="Total", value=str(len(strategies)), inline=True)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.exception(f"Error in /list_strategies command: {e}")
            await interaction.followup.send(
                f"❌ Error listing strategies: {str(e)}",
                ephemeral=True,
            )

    async def cmd_autoquant_status(self, interaction: discord.Interaction) -> None:
        """Handle /autoquant_status command - Get AutoQuant pipeline status."""
        await interaction.response.defer()

        try:
            from ...services.auto_quant import pipeline as _pl

            runs = _pl.list_runs()

            if not runs:
                await interaction.followup.send("No AutoQuant runs found.", ephemeral=True)
                return

            # Format runs list
            embed = discord.Embed(
                title="🔄 AutoQuant Pipeline Status",
                color=0x00AAFF,
            )

            for run in runs[:5]:  # Show last 5 runs
                status_emoji = {
                    "pending": "⏳",
                    "running": "🔄",
                    "completed": "✅",
                    "failed": "❌",
                    "cancelled": "⏹️",
                }.get(run["status"], "❓")

                embed.add_field(
                    name=f"{status_emoji} {run['run_id'][:8]}",
                    value=f"Strategy: {run['strategy']}\nStatus: {run['status']}",
                    inline=False,
                )

            if len(runs) > 5:
                embed.set_footer(text=f"... and {len(runs) - 5} more runs")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.exception(f"Error in /autoquant_status command: {e}")
            await interaction.followup.send(
                f"❌ Error getting AutoQuant status: {str(e)}",
                ephemeral=True,
            )

    async def cmd_help(self, interaction: discord.Interaction) -> None:
        """Handle /help command - Show available commands."""
        help_text = """🤖 **Strategy Lab Discord Bot**

**System Commands:**

`/status` - Get system health status (admin only)
  • Checks Freqtrade CLI availability
  • Verifies critical directories
  • Shows overall system health

`/list_strategies` - List all available strategies
  • Shows all registered strategies
  • Displays strategy metadata

`/autoquant_status` - Get AutoQuant pipeline status
  • Shows active pipeline runs
  • Displays run status and progress

**Quant Agent Commands:**

`/backtest <strategy> [timeframe] [timerange]` - Run a backtest
  • strategy: Strategy name (required)
  • timeframe: 1h, 4h, 1d (default: 1h)
  • timerange: 20240101-20240601 (default: 20240101-20240601)

`/download <pairs> [timeframe] [timerange]` - Download market data
  • pairs: BTC/USDT,ETH/USDT (comma-separated, required)

`/hyperopt <strategy> [timeframe] [timerange] [epochs]` - Run hyperopt
  • strategy: Strategy name (required)
  • epochs: Number of epochs (default: 100)

`/compare <strategies> [timeframe] [timerange]` - Compare strategies
  • strategies: StrategyA,StrategyB (comma-separated, required)

`/report [report_type]` - List available reports
  • report_type: backtest, comparison (default: backtest)

`/quant <step> [strategy] [timeframe] [timerange]` - Run workflow step
  • step: backtest, download, hyperopt, compare, report (required)

`/quant_help` - Show detailed Quant agent instructions

**Error Handling:**
• Admin commands require permission
• Invalid parameters show specific errors
• Failed operations display error details
• All errors are logged for debugging

**Notes:**
• Live trading is disabled for safety
• Use `/quant_help` for detailed Quant instructions
• Reports are saved to `/data/quant_reports/`
• Bot auto-starts with backend server"""

        embed = discord.Embed(
            title="🤖 Strategy Lab Discord Bot Commands",
            description="Complete guide for using the Strategy Lab Discord bot",
            color=0x00AAFF,
        )

        embed.add_field(name="Commands", value=help_text, inline=False)
        embed.set_footer(text="Strategy Lab v1.0 | Use /quant_help for detailed Quant instructions")

        await interaction.response.send_message(embed=embed, ephemeral=False)
