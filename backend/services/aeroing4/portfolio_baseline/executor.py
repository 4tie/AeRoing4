"""Portfolio Baseline execution logic for AeRoing4.

This module implements the execution of portfolio baseline backtests
using the existing BacktestRunner infrastructure.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ....models import RunRequest
from ....utils import utc_now
from .models import (
    PortfolioBaselineOutcome,
    PortfolioBaselineResult,
    PORTFOLIO_BASELINE_POLICY_VERSION,
)

if TYPE_CHECKING:
    from ...app_services import AppServices
    from ..pair_selection import PairSelectionResult

logger = logging.getLogger(__name__)


class PortfolioBaselineExecutor:
    """Executes portfolio baseline backtests."""

    def __init__(self, services: "AppServices"):
        """Initialize executor with services."""
        self.services = services
        self.policy_version = PORTFOLIO_BASELINE_POLICY_VERSION

    async def execute_baseline(
        self,
        strategy_name: str,
        version_id: str | None,
        selected_pairs: list[str],
        selection_result: PairSelectionResult,
        develop_timerange: str,
        timeframe: str,
        config_file: str,
        max_open_trades: int,
        dry_run_wallet: float,
        exchange: str = "binance",
        trading_mode: str = "spot",
    ) -> PortfolioBaselineResult:
        """Execute portfolio baseline backtest.

        Args:
            strategy_name: Strategy name
            version_id: Strategy version ID (None for current)
            selected_pairs: Selected pairs from Pair Selection
            selection_result: Pair Selection result for traceability
            develop_timerange: DEVELOP zone timerange
            timeframe: Candle timeframe
            config_file: Freqtrade config file path
            max_open_trades: Maximum open trades
            dry_run_wallet: Dry run wallet amount
            exchange: Exchange name
            trading_mode: Trading mode (spot, futures, etc.)

        Returns:
            PortfolioBaselineResult with execution results
        """
        started_at = utc_now()

        # Compute input hash for idempotency
        input_hash = self._compute_input_hash(
            strategy_name=strategy_name,
            version_id=version_id,
            selected_pairs=selected_pairs,
            develop_timerange=develop_timerange,
            timeframe=timeframe,
            max_open_trades=max_open_trades,
            dry_run_wallet=dry_run_wallet,
            exchange=exchange,
            trading_mode=trading_mode,
            selection_hash=selection_result.selection_hash,
        )

        # Build configuration snapshot
        config_snapshot = self._build_config_snapshot(
            config_file, max_open_trades, dry_run_wallet, exchange, trading_mode
        )

        try:
            # Resolve version if not provided
            if version_id is None:
                version = self.services.version_manager.get_current_pointer(strategy_name)
                if version:
                    version_id = version.accepted_version_id
                else:
                    # Fallback to latest version
                    versions = self.services.version_manager.list_versions(strategy_name)
                    if versions:
                        version_id = versions[0].version_id

            # Build backtest request
            request = RunRequest(
                config_file=config_file,
                timerange=develop_timerange,
                timeframe=timeframe,
                pairs=selected_pairs,
                max_open_trades=max_open_trades,
                dry_run_wallet=dry_run_wallet,
            )

            # Get strategy record
            strategy = self.services.strategy_service.get_strategy(strategy_name)
            if not strategy:
                return PortfolioBaselineResult(
                    status=PortfolioBaselineOutcome.FAIL_EXECUTION,
                    selected_pairs=selected_pairs,
                    pair_selection_reference=selection_result.selection_hash,
                    strategy_name=strategy_name,
                    timeframe=timeframe,
                    develop_timerange=develop_timerange,
                    configuration_snapshot=config_snapshot,
                    input_hash=input_hash,
                    started_at=started_at,
                    completed_at=utc_now(),
                    duration_seconds=(utc_now() - started_at).total_seconds(),
                    logs="Strategy not found",
                )

            # Execute backtest
            run_id = await self.services.backtest_runner.queue_strategy_backtest(
                strategy=strategy,
                version_id=version_id,
                request=request,
            )

            # Wait for completion and load results
            # Note: In production, this should poll for completion
            # For now, we'll assume synchronous completion or add polling logic
            metadata = self.services.run_repository.load_metadata(run_id)

            if metadata.run_status.value not in ("completed", "failed", "cancelled"):
                # Wait for completion (simplified - should use proper polling)
                import asyncio
                await asyncio.sleep(1)  # Placeholder for proper polling
                metadata = self.services.run_repository.load_metadata(run_id)

            # Load detailed results
            detail = self.services.run_repository.load_detail(run_id)

            # Determine outcome
            if metadata.run_status.value == "completed":
                if detail.parsed_summary and detail.parsed_summary.total_trades == 0:
                    outcome = PortfolioBaselineOutcome.FAIL_NO_TRADES
                else:
                    outcome = PortfolioBaselineOutcome.PASS_BASELINE_CREATED
            else:
                outcome = PortfolioBaselineOutcome.FAIL_EXECUTION

            completed_at = utc_now()
            duration_seconds = (completed_at - started_at).total_seconds()

            # Load logs
            run_dir = self.services.run_repository.find_run_dir(run_id)
            logs_path = run_dir / "logs.txt"
            logs = logs_path.read_text(encoding="utf-8") if logs_path.exists() else ""

            # Load command record
            command_path = run_dir / "freqtrade_command.txt"
            command_record = command_path.read_text(encoding="utf-8") if command_path.exists() else ""

            # Build artifacts list
            artifacts = {
                path.name: str(path.resolve())
                for path in sorted(run_dir.iterdir())
                if path.is_file()
            }

            return PortfolioBaselineResult(
                status=outcome,
                selected_pairs=selected_pairs,
                pair_selection_reference=selection_result.selection_hash,
                backtest_run_id=run_id,
                strategy_name=strategy_name,
                strategy_version=version_id,
                strategy_hash=metadata.git_commit_sha or "",
                parameter_hash="",  # Will be populated from params.json
                timeframe=timeframe,
                develop_timerange=develop_timerange,
                wallet_configuration={"dry_run_wallet": dry_run_wallet},
                stake_configuration={},  # Will be populated from config
                max_open_trades=max_open_trades,
                exchange=exchange,
                trading_mode=trading_mode,
                canonical_metrics={},  # Will be populated by Metrics SSOT adapter
                configuration_snapshot=config_snapshot,
                input_hash=input_hash,
                command_record=command_record,
                artifacts=artifacts,
                logs=logs,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=duration_seconds,
                selection_frozen_at=selection_result.frozen_at or started_at,
            )

        except Exception as exc:
            logger.exception("Portfolio baseline execution failed")
            return PortfolioBaselineResult(
                status=PortfolioBaselineOutcome.FAIL_EXECUTION,
                selected_pairs=selected_pairs,
                pair_selection_reference=selection_result.selection_hash,
                strategy_name=strategy_name,
                timeframe=timeframe,
                develop_timerange=develop_timerange,
                configuration_snapshot=config_snapshot,
                input_hash=input_hash,
                started_at=started_at,
                completed_at=utc_now(),
                duration_seconds=(utc_now() - started_at).total_seconds(),
                logs=f"Execution failed: {exc}",
            )

    def _compute_input_hash(self, **kwargs) -> str:
        """Compute deterministic hash of execution inputs for idempotency."""
        sorted_data = json.dumps(kwargs, sort_keys=True)
        return hashlib.sha256(sorted_data.encode()).hexdigest()

    def _build_config_snapshot(
        self,
        config_file: str,
        max_open_trades: int,
        dry_run_wallet: float,
        exchange: str,
        trading_mode: str,
    ) -> dict:
        """Build configuration snapshot for reproducibility."""
        return {
            "config_file": config_file,
            "max_open_trades": max_open_trades,
            "dry_run_wallet": dry_run_wallet,
            "exchange": exchange,
            "trading_mode": trading_mode,
        }
