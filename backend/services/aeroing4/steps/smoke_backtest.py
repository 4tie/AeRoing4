"""Smoke backtest step for AeRoing4."""

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ....core.errors import BackendError
from ....models.contracts import RunRequest
from ....models.base import RunStatus
from ....services.execution.backtest_runner import BacktestRunner
from ....services.storage.run_repository import RunRepository
from ..models import (
    StepResult,
    SmokeBacktestResult,
    SmokeBacktestOutcome,
    AeRoing4StepStatus,
)

if TYPE_CHECKING:
    from ...app_services import AppServices


class SmokeBacktestStep:
    """Smoke backtest step.

    Runs the selected strategy against smoke pairs to verify execution.
    Classifies outcome as:
    - PASS_ACTIVITY: Freqtrade completed successfully with trades
    - NO_SIGNAL_ACTIVITY: Freqtrade completed successfully with zero trades
    - EXECUTION_FAILURE: Freqtrade or strategy runtime failed
    """

    def __init__(self, services: "AppServices"):
        """Initialize smoke backtest step with services."""
        self.services = services

    async def execute(
        self,
        strategy_name: str,
        version_id: str,
        pairs: list[str],
        timeframe: str,
        timerange: str,
        max_open_trades: int = 1,
        dry_run_wallet: float = 1000.0,
        config_file: str | None = None,
    ) -> StepResult:
        """Execute smoke backtest step.

        Args:
            strategy_name: Name of the strategy
            version_id: Strategy version ID
            pairs: List of smoke pairs
            timeframe: Candle timeframe
            timerange: Date range
            max_open_trades: Maximum open trades
            dry_run_wallet: Dry run wallet amount
            config_file: Optional config file override

        Returns:
            StepResult with smoke backtest outcome
        """
        started_at = datetime.now(UTC)

        try:
            # Check for version_id first
            if version_id is None:
                pointer = self.services.version_manager.get_current_pointer(strategy_name)
                if not pointer:
                    return StepResult(
                        step_name="smoke_backtest",
                        status=AeRoing4StepStatus.FAILED,
                        started_at=started_at,
                        completed_at=datetime.now(UTC),
                        error="Strategy has no accepted version",
                        data={
                            "outcome": SmokeBacktestOutcome.EXECUTION_FAILURE.value,
                            "backtest_run_id": None,
                            "total_trades": 0,
                            "trades_per_pair": {},
                            "net_profit": None,
                            "profit_factor": None,
                            "max_drawdown": None,
                            "execution_error": "Strategy has no accepted version",
                        },
                    )
                version_id = pointer.accepted_version_id

            # Resolve config file
            settings = self.services.settings_store.load()
            config_file = config_file or settings.default_config_file_path

            # Get strategy record
            strategy = self.services.registry.get_strategy(strategy_name)

            # Create run request
            run_request = RunRequest(
                strategy_name=strategy_name,
                version_id=version_id,
                config_file=config_file,
                timerange=timerange,
                timeframe=timeframe,
                pairs=pairs,
                max_open_trades=max_open_trades,
                dry_run_wallet=dry_run_wallet,
            )

            # Run backtest (synchronous, wrap in thread)
            run_id = await asyncio.to_thread(
                self.services.backtest_runner.run_backtest,
                strategy,
                version_id,
                run_request,
            )

            # Load backtest results
            metadata = self.services.run_repository.load_metadata(run_id)

            # Classify outcome
            outcome = self._classify_outcome(metadata, run_id)

            # Extract additional metrics
            detail = self.services.run_repository.load_detail(run_id)
            total_trades = detail.parsed_summary.total_trades if detail.parsed_summary else 0
            trades_per_pair = {
                pair_result.pair: pair_result.total_trades
                for pair_result in detail.pair_results
            }
            net_profit = detail.parsed_summary.net_profit_pct if detail.parsed_summary else None
            profit_factor = detail.parsed_summary.profit_factor if detail.parsed_summary else None
            max_drawdown = detail.parsed_summary.max_drawdown_pct if detail.parsed_summary else None

            return StepResult(
                step_name="smoke_backtest",
                status=AeRoing4StepStatus.PASSED
                if outcome != SmokeBacktestOutcome.EXECUTION_FAILURE
                else AeRoing4StepStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                data={
                    "outcome": outcome.value,
                    "backtest_run_id": run_id,
                    "total_trades": total_trades,
                    "trades_per_pair": trades_per_pair,
                    "net_profit": net_profit,
                    "profit_factor": profit_factor,
                    "max_drawdown": max_drawdown,
                    "execution_error": None,
                },
            )

        except BackendError as exc:
            return StepResult(
                step_name="smoke_backtest",
                status=AeRoing4StepStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error=f"Backtest execution failed: {exc.message}",
                data={
                    "outcome": SmokeBacktestOutcome.EXECUTION_FAILURE.value,
                    "backtest_run_id": None,
                    "total_trades": 0,
                    "trades_per_pair": {},
                    "net_profit": None,
                    "profit_factor": None,
                    "max_drawdown": None,
                    "execution_error": exc.message,
                },
            )
        except Exception as exc:
            return StepResult(
                step_name="smoke_backtest",
                status=AeRoing4StepStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error=f"Smoke backtest step failed: {str(exc)}",
                data={
                    "outcome": SmokeBacktestOutcome.EXECUTION_FAILURE.value,
                    "backtest_run_id": None,
                    "total_trades": 0,
                    "trades_per_pair": {},
                    "net_profit": None,
                    "profit_factor": None,
                    "max_drawdown": None,
                    "execution_error": str(exc),
                },
            )

    def _classify_outcome(
        self, metadata, run_id: str
    ) -> SmokeBacktestOutcome:
        """Classify backtest outcome based on results.

        Args:
            metadata: Backtest run metadata
            run_id: Backtest run ID

        Returns:
            SmokeBacktestOutcome classification
        """
        # Check for execution failure
        if metadata.run_status == RunStatus.FAILED:
            return SmokeBacktestOutcome.EXECUTION_FAILURE

        if metadata.run_status == RunStatus.CANCELLED:
            return SmokeBacktestOutcome.EXECUTION_FAILURE

        # Load detail to check trade count
        try:
            detail = self.services.run_repository.load_detail(run_id)
            total_trades = detail.parsed_summary.total_trades if detail.parsed_summary else 0

            if total_trades > 0:
                return SmokeBacktestOutcome.PASS_ACTIVITY
            else:
                return SmokeBacktestOutcome.NO_SIGNAL_ACTIVITY

        except Exception:
            # If we can't load details, assume execution failure
            return SmokeBacktestOutcome.EXECUTION_FAILURE
