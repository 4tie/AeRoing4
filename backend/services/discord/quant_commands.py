"""Discord slash commands for Quant agent."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands

if TYPE_CHECKING:
    from .discord_service import DiscordBotService

logger = logging.getLogger(__name__)


class QuantCommandHandlers:
    """Discord slash command handlers for Quant agent."""

    def __init__(self, discord_service: DiscordBotService) -> None:
        """Initialize Quant command handlers.

        Args:
            discord_service: Discord bot service instance
        """
        self.discord_service = discord_service
        self._setup_commands()

    def _setup_commands(self) -> None:
        """Register all Quant slash commands with the Discord bot."""
        if not self.discord_service.tree:
            return

        tree = self.discord_service.tree

        # Register Quant commands
        tree.command(name="backtest", description="Run a backtest for a strategy")(self.cmd_backtest)
        tree.command(name="download", description="Download market data")(self.cmd_download)
        tree.command(name="hyperopt", description="Run hyperopt optimization")(self.cmd_hyperopt)
        tree.command(name="compare", description="Compare multiple strategies")(self.cmd_compare)
        tree.command(name="report", description="Generate a report")(self.cmd_report)
        tree.command(name="quant", description="Run Quant workflow step")(self.cmd_quant)
        tree.command(name="quant_help", description="Show Quant agent instructions")(self.cmd_quant_help)

    async def cmd_backtest(
        self,
        interaction: discord.Interaction,
        strategy: str,
        timeframe: str = "1h",
        timerange: str = "20240101-20240601",
    ) -> None:
        """Handle /backtest command - Run a backtest."""
        # Check permissions
        if not self.discord_service.get_user_permission(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            from pathlib import Path
            from ...services.quant import QuantService
            from ...settings_store import SettingsStore

            settings_store = SettingsStore(Path(self.discord_service.settings_store.root_dir))
            quant_service = QuantService(settings_store, Path(self.discord_service.settings_store.root_dir))

            # Run backtest
            results = await quant_service.run_backtest(strategy, timeframe, timerange)

            # Generate report
            report_path = await quant_service.generate_report(results, "backtest")

            # Send results
            embed = discord.Embed(
                title=f"📊 Backtest Results: {strategy}",
                description=f"Backtest completed successfully",
                color=0x00FF00,
            )
            embed.add_field(name="Profit", value=f"${results['profit']:.2f}", inline=True)
            embed.add_field(name="Profit Factor", value=f"{results['profit_factor']:.2f}", inline=True)
            embed.add_field(name="Sharpe", value=f"{results['sharpe']:.2f}", inline=True)
            embed.add_field(name="Max Drawdown", value=f"{results['max_drawdown']:.2%}", inline=True)
            embed.add_field(name="Win Rate", value=f"{results['win_rate']:.2%}", inline=True)
            embed.add_field(name="Total Trades", value=str(results['total_trades']), inline=True)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.exception(f"Error in /backtest command: {e}")
            await interaction.followup.send(
                f"❌ Error running backtest: {str(e)}",
                ephemeral=True,
            )

    async def cmd_download(
        self,
        interaction: discord.Interaction,
        pairs: str,
        timeframe: str = "1h",
        timerange: str = "20240101-20240601",
    ) -> None:
        """Handle /download command - Download market data."""
        # Check permissions
        if not self.discord_service.get_user_permission(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            from pathlib import Path
            from ...services.quant import QuantService
            from ...settings_store import SettingsStore

            settings_store = SettingsStore(Path(self.discord_service.settings_store.root_dir))
            quant_service = QuantService(settings_store, Path(self.discord_service.settings_store.root_dir))

            # Parse pairs (comma-separated)
            pair_list = [p.strip() for p in pairs.split(",")]

            # Download data
            results = await quant_service.download_data(pair_list, timeframe, timerange)

            # Send results
            embed = discord.Embed(
                title="📥 Data Download",
                description=f"Downloaded data for {results['downloaded']} pairs",
                color=0x00AAFF,
            )
            embed.add_field(name="Pairs", value=", ".join(results['pairs']), inline=False)
            embed.add_field(name="Timeframe", value=results['timeframe'], inline=True)
            embed.add_field(name="Time Range", value=results['timerange'], inline=True)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.exception(f"Error in /download command: {e}")
            await interaction.followup.send(
                f"❌ Error downloading data: {str(e)}",
                ephemeral=True,
            )

    async def cmd_hyperopt(
        self,
        interaction: discord.Interaction,
        strategy: str,
        timeframe: str = "1h",
        timerange: str = "20240101-20240601",
        epochs: int = 100,
    ) -> None:
        """Handle /hyperopt command - Run hyperopt optimization."""
        # Check permissions
        if not self.discord_service.get_user_permission(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            from pathlib import Path
            from ...services.quant import QuantService
            from ...settings_store import SettingsStore

            settings_store = SettingsStore(Path(self.discord_service.settings_store.root_dir))
            quant_service = QuantService(settings_store, Path(self.discord_service.settings_store.root_dir))

            # Run hyperopt
            results = await quant_service.run_hyperopt(strategy, timeframe, timerange, epochs=epochs)

            # Send results
            embed = discord.Embed(
                title=f"🔧 Hyperopt Results: {strategy}",
                description=f"Hyperopt optimization completed",
                color=0x00FF00,
            )
            embed.add_field(name="Best Profit", value=f"${results['best_profit']:.2f}", inline=True)
            embed.add_field(name="Best Profit Factor", value=f"{results['best_profit_factor']:.2f}", inline=True)
            embed.add_field(name="Best Sharpe", value=f"{results['best_sharpe']:.2f}", inline=True)
            embed.add_field(name="Epochs", value=str(results['epochs']), inline=True)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.exception(f"Error in /hyperopt command: {e}")
            await interaction.followup.send(
                f"❌ Error running hyperopt: {str(e)}",
                ephemeral=True,
            )

    async def cmd_compare(
        self,
        interaction: discord.Interaction,
        strategies: str,
        timeframe: str = "1h",
        timerange: str = "20240101-20240601",
    ) -> None:
        """Handle /compare command - Compare strategies."""
        # Check permissions
        if not self.discord_service.get_user_permission(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            from pathlib import Path
            from ...services.quant import QuantService
            from ...settings_store import SettingsStore

            settings_store = SettingsStore(Path(self.discord_service.settings_store.root_dir))
            quant_service = QuantService(settings_store, Path(self.discord_service.settings_store.root_dir))

            # Parse strategies (comma-separated)
            strategy_list = [s.strip() for s in strategies.split(",")]

            # Compare strategies
            results = await quant_service.compare_strategies(strategy_list, timeframe, timerange)

            # Generate report
            report_path = await quant_service.generate_report(results, "comparison")

            # Send results
            embed = discord.Embed(
                title="📊 Strategy Comparison",
                description=f"Compared {len(strategy_list)} strategies",
                color=0x00FF00,
            )

            # Add top 3 results
            for i, result in enumerate(results['comparison'][:3], 1):
                embed.add_field(
                    name=f"#{i} {result['strategy']}",
                    value=f"Profit: ${result['profit']:.2f} | Sharpe: {result['sharpe']:.2f}",
                    inline=False,
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.exception(f"Error in /compare command: {e}")
            await interaction.followup.send(
                f"❌ Error comparing strategies: {str(e)}",
                ephemeral=True,
            )

    async def cmd_report(
        self,
        interaction: discord.Interaction,
        report_type: str = "backtest",
    ) -> None:
        """Handle /report command - Generate a report."""
        # Check permissions
        if not self.discord_service.get_user_permission(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            from pathlib import Path
            from ...services.quant import QuantService
            from ...settings_store import SettingsStore

            settings_store = SettingsStore(Path(self.discord_service.settings_store.root_dir))
            quant_service = QuantService(settings_store, Path(self.discord_service.settings_store.root_dir))

            # List available reports
            reports = quant_service.list_reports()

            if not reports:
                await interaction.followup.send("No reports available.", ephemeral=True)
                return

            # Send report list
            embed = discord.Embed(
                title="📄 Available Reports",
                description=f"Found {len(reports)} reports",
                color=0x00AAFF,
            )

            for report in reports[:10]:  # Show first 10
                embed.add_field(name=report, value="", inline=False)

            if len(reports) > 10:
                embed.set_footer(text=f"... and {len(reports) - 10} more reports")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.exception(f"Error in /report command: {e}")
            await interaction.followup.send(
                f"❌ Error listing reports: {str(e)}",
                ephemeral=True,
            )

    async def cmd_quant(
        self,
        interaction: discord.Interaction,
        step: str,
        strategy: str | None = None,
        timeframe: str = "1h",
        timerange: str = "20240101-20240601",
    ) -> None:
        """Handle /quant command - Run a specific workflow step."""
        # Check permissions
        if not self.discord_service.get_user_permission(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            from pathlib import Path
            from ...services.quant import QuantService
            from ...settings_store import SettingsStore

            settings_store = SettingsStore(Path(self.discord_service.settings_store.root_dir))
            quant_service = QuantService(settings_store, Path(self.discord_service.settings_store.root_dir))

            # Execute step
            if step == "backtest":
                if not strategy:
                    await interaction.followup.send("❌ Strategy required for backtest", ephemeral=True)
                    return
                results = await quant_service.run_backtest(strategy, timeframe, timerange)
                await quant_service.generate_report(results, "backtest")
                await interaction.followup.send(f"✅ Backtest completed for {strategy}")
            elif step == "download":
                results = await quant_service.download_data(["BTC/USDT"], timeframe, timerange)
                await interaction.followup.send(f"✅ Data download completed")
            elif step == "hyperopt":
                if not strategy:
                    await interaction.followup.send("❌ Strategy required for hyperopt", ephemeral=True)
                    return
                results = await quant_service.run_hyperopt(strategy, timeframe, timerange)
                await interaction.followup.send(f"✅ Hyperopt completed for {strategy}")
            elif step == "compare":
                if not strategy:
                    await interaction.followup.send("❌ Strategies required for comparison", ephemeral=True)
                    return
                strategies = [s.strip() for s in strategy.split(",")]
                results = await quant_service.compare_strategies(strategies, timeframe, timerange)
                await quant_service.generate_report(results, "comparison")
                await interaction.followup.send(f"✅ Comparison completed for {len(strategies)} strategies")
            elif step == "report":
                reports = quant_service.list_reports()
                await interaction.followup.send(f"📄 Found {len(reports)} reports")
            else:
                await interaction.followup.send(f"❌ Unknown step: {step}", ephemeral=True)

        except Exception as e:
            logger.exception(f"Error in /quant command: {e}")
            await interaction.followup.send(
                f"❌ Error running step {step}: {str(e)}",
                ephemeral=True,
            )

    async def cmd_quant_help(self, interaction: discord.Interaction) -> None:
        """Handle /quant_help command - Show complete instructions."""
        help_text = """📊 **Quant Agent Help**

**Available Commands:**

`/backtest <strategy> [timeframe] [timerange]` - Run a backtest for a strategy
  • strategy: Strategy name (required)
  • timeframe: Timeframe like 1h, 4h, 1d (default: 1h)
  • timerange: Date range like 20240101-20240601 (default: 20240101-20240601)

`/download <pairs> [timeframe] [timerange]` - Download market data
  • pairs: Comma-separated pairs like BTC/USDT,ETH/USDT (required)
  • timeframe: Timeframe (default: 1h)
  • timerange: Date range (default: 20240101-20240601)

`/hyperopt <strategy> [timeframe] [timerange] [epochs]` - Run hyperopt optimization
  • strategy: Strategy name (required)
  • timeframe: Timeframe (default: 1h)
  • timerange: Date range (default: 20240101-20240601)
  • epochs: Number of optimization epochs (default: 100)

`/compare <strategies> [timeframe] [timerange]` - Compare multiple strategies
  • strategies: Comma-separated strategy names (required)
  • timeframe: Timeframe (default: 1h)
  • timerange: Date range (default: 20240101-20240601)

`/report [report_type]` - List available reports
  • report_type: Type of report to filter (default: backtest)

`/quant <step> [strategy] [timeframe] [timerange]` - Run a specific workflow step
  • step: One of: backtest, download, hyperopt, compare, report (required)
  • strategy: Strategy name (required for backtest/hyperopt/compare)
  • timeframe: Timeframe (default: 1h)
  • timerange: Date range (default: 20240101-20240601)

**Examples:**
• `/backtest MyStrategy 4h 20240101-20240601`
• `/download BTC/USDT,ETH/USDT 1h 20240101-20240601`
• `/hyperopt MyStrategy 1h 20240101-20240601 200`
• `/compare StrategyA,StrategyB,StrategyC`
• `/quant run --step backtest --strategy MyStrategy`

**Error Handling:**
• All commands require admin permission
• Invalid parameters will show specific error messages
• Failed operations will display error details
• Reports are saved to `/data/quant_reports/`

**Notes:**
• Live trading is disabled for safety
• All operations are logged
• Reports are generated in Markdown format
• Use the Quant tab in the dashboard to view reports"""

        embed = discord.Embed(
            title="📊 Quant Agent Instructions",
            description="Complete guide for using the Quant agent",
            color=0x00AAFF,
        )
        embed.add_field(name="Commands", value=help_text, inline=False)
        embed.set_footer(text="Strategy Lab Quant Agent v1.0")

        await interaction.response.send_message(embed=embed, ephemeral=False)
