"""Portfolio Baseline step for AeRoing4.

Executes portfolio baseline backtest with selected pairs and analyzes results.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..models import AeRoing4StepStatus, StepResult
from ..portfolio_baseline import (
    PortfolioAnalyzer,
    PortfolioBaselineExecutor,
    PortfolioBaselineOutcome,
    PortfolioBaselineResult,
)
from ..research import ResearchStage, ResearchZone

if TYPE_CHECKING:
    from ...app_services import AppServices
    from ..pair_selection import PairSelectionResult

logger = logging.getLogger(__name__)


class PortfolioBaselineStep:
    """Portfolio Baseline step.

    Executes portfolio baseline backtest with selected pairs and analyzes results.
    """

    def __init__(self, services: "AppServices"):
        """Initialize portfolio baseline step with services."""
        self.services = services
        self.executor = PortfolioBaselineExecutor(services)
        self.analyzer = PortfolioAnalyzer()

    async def execute(
        self,
        strategy_name: str,
        version_id: str | None,
        selection_result: PairSelectionResult,
        develop_timerange: str,
        timeframe: str,
        config_file: str,
        max_open_trades: int,
        dry_run_wallet: float,
        exchange: str,
        trading_mode: str,
        aeroing4_run_id: str | None = None,
        guard=None,
    ) -> StepResult:
        """Execute portfolio baseline.

        Args:
            strategy_name: Strategy name
            version_id: Strategy version ID (None for current)
            selection_result: Pair Selection result
            develop_timerange: DEVELOP zone timerange
            timeframe: Candle timeframe
            config_file: Freqtrade config file path
            max_open_trades: Maximum open trades
            dry_run_wallet: Dry run wallet amount
            exchange: Exchange name
            trading_mode: Trading mode
            protocol_access_entry_id: Access ledger entry ID from guard

        Returns:
            StepResult with PortfolioBaselineResult data
        """
        started_at = datetime.now(UTC)
        protocol_access_entry_id: str | None = None

        try:
            # Check if selection is valid
            if not selection_result.selected_pairs:
                return StepResult(
                    step_name="portfolio_baseline",
                    status=AeRoing4StepStatus.FAILED,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    error="No pairs selected for portfolio baseline",
                )

            # Request Research Protocol access if guard is provided
            if guard and aeroing4_run_id:
                from ..research import ResearchStage, ResearchZone
                from ..models import AeRoing4Run

                # Load the run for protocol access
                run = self.services.aeroing4_state_store.load_run(aeroing4_run_id) if hasattr(self.services, 'aeroing4_state_store') else None

                if run:
                    # Compute pair set hash for protocol
                    import hashlib
                    import json
                    pair_set_hash = hashlib.sha256(
                        json.dumps(sorted(selection_result.selected_pairs)).encode()
                    ).hexdigest()

                    # Request access to DEVELOP zone
                    decision, _ = guard.request_access(
                        run=run,
                        stage=ResearchStage.PORTFOLIO_BASELINE,
                        zone=ResearchZone.DEVELOP,
                        pair_set_hash=pair_set_hash,
                    )

                    if not decision.allowed:
                        return StepResult(
                            step_name="portfolio_baseline",
                            status=AeRoing4StepStatus.FAILED,
                            started_at=started_at,
                            completed_at=datetime.now(UTC),
                            error=f"Research Protocol denied access: {decision.reason}",
                        )

                    # Store the ledger entry ID for traceability
                    protocol_access_entry_id = str(decision.sequence) if hasattr(decision, 'sequence') else None

            # Freeze selection at baseline start
            from datetime import UTC, datetime
            selection_result.frozen_at = datetime.now(UTC)

            # Execute baseline backtest
            baseline_result = await self.executor.execute_baseline(
                strategy_name=strategy_name,
                version_id=version_id,
                selected_pairs=selection_result.selected_pairs,
                selection_result=selection_result,
                develop_timerange=develop_timerange,
                timeframe=timeframe,
                config_file=config_file,
                max_open_trades=max_open_trades,
                dry_run_wallet=dry_run_wallet,
                exchange=exchange,
                trading_mode=trading_mode,
            )

            # If execution failed, return early
            if baseline_result.status != PortfolioBaselineOutcome.PASS_BASELINE_CREATED:
                step_status = AeRoing4StepStatus.FAILED
                error_msg = f"Portfolio baseline failed: {baseline_result.status.value}"
                return StepResult(
                    step_name="portfolio_baseline",
                    status=step_status,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    data=baseline_result.model_dump(mode="json"),
                    error=error_msg,
                )

            # Load backtest results for analysis
            if baseline_result.backtest_run_id:
                detail = self.services.run_repository.load_detail(baseline_result.backtest_run_id)

                # Extract per-pair contributions
                per_pair_contributions = self.analyzer.extract_per_pair_contributions(
                    pair_results=detail.pair_results,
                    total_profit_abs=detail.parsed_summary.net_profit_currency if detail.parsed_summary else None,
                    total_trades=detail.parsed_summary.total_trades if detail.parsed_summary else 0,
                )
                baseline_result.per_pair_contribution = per_pair_contributions

                # Analyze concentration
                baseline_result.concentration_summary = self.analyzer.analyze_concentration(
                    per_pair_contributions=per_pair_contributions,
                )

                # Extract exit reason distribution
                if detail.parsed_summary:
                    baseline_result.exit_reason_distribution = self.analyzer.extract_exit_reason_distribution(
                        parsed_summary=detail.parsed_summary,
                    )

                # Integrate Metrics SSOT
                from ..metrics.adapters import from_backtest_detail
                try:
                    canonical_metrics = from_backtest_detail(detail)
                    baseline_result.canonical_metrics = canonical_metrics.model_dump(mode="json")
                except Exception as e:
                    logger.warning(f"Failed to create canonical metrics: {e}")

            # Store protocol access entry ID
            baseline_result.protocol_access_entry_id = protocol_access_entry_id

            completed_at = datetime.now(UTC)
            duration_seconds = (completed_at - started_at).total_seconds()
            baseline_result.started_at = started_at
            baseline_result.completed_at = completed_at
            baseline_result.duration_seconds = duration_seconds

            return StepResult(
                step_name="portfolio_baseline",
                status=AeRoing4StepStatus.PASSED,
                started_at=started_at,
                completed_at=completed_at,
                data=baseline_result.model_dump(mode="json"),
            )

        except Exception as exc:
            logger.exception("Portfolio baseline execution failed")
            return StepResult(
                step_name="portfolio_baseline",
                status=AeRoing4StepStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error=f"Portfolio baseline execution failed: {exc}",
            )
