"""Portfolio Baseline analysis logic for AeRoing4.

This module implements concentration analysis, per-pair contribution extraction,
and exit reason distribution for portfolio baseline results.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import (
    ConcentrationFlag,
    ConcentrationSummary,
    ExitReasonDistribution,
    PerPairContribution,
    PORTFOLIO_CONCENTRATION_POLICY_VERSION,
)

if TYPE_CHECKING:
    from ....models import ParsedSummary, PairResult


class PortfolioAnalyzer:
    """Analyzes portfolio baseline results."""

    def __init__(self):
        self.concentration_policy_version = PORTFOLIO_CONCENTRATION_POLICY_VERSION

    def extract_per_pair_contributions(
        self,
        pair_results: list[PairResult],
        total_profit_abs: float | None,
        total_trades: int,
    ) -> list[PerPairContribution]:
        """Extract per-pair contribution from portfolio baseline results.

        Args:
            pair_results: Pair results from backtest
            total_profit_abs: Total portfolio profit in absolute currency
            total_trades: Total number of trades in portfolio

        Returns:
            List of per-pair contributions
        """
        contributions: list[PerPairContribution] = []

        for pair_result in pair_results:
            contribution = PerPairContribution(
                pair=pair_result.pair,
                trade_count=pair_result.total_trades,
                net_profit_abs=pair_result.net_profit_currency,
                net_profit_pct=pair_result.net_profit_pct,
                win_rate=pair_result.win_rate_pct,
            )

            # Calculate contribution shares if totals are available
            if total_profit_abs is not None and total_profit_abs != 0:
                if pair_result.net_profit_currency is not None:
                    contribution.contribution_to_total_profit_pct = (
                        pair_result.net_profit_currency / total_profit_abs * 100
                    )

            if total_trades > 0:
                contribution.contribution_to_total_trades_pct = (
                    pair_result.total_trades / total_trades * 100
                )

            contributions.append(contribution)

        return contributions

    def analyze_concentration(
        self,
        per_pair_contributions: list[PerPairContribution],
    ) -> ConcentrationSummary:
        """Analyze portfolio concentration.

        Policy thresholds (v1.0.0):
        - BALANCED_CONTRIBUTION: top pair < 40% of profit, top pair < 40% of trades
        - MODERATE_CONCENTRATION: top pair 40-60% of profit OR 40-60% of trades
        - HIGH_PAIR_CONCENTRATION: top pair > 60% of profit OR > 60% of trades

        Args:
            per_pair_contributions: Per-pair contributions from portfolio baseline

        Returns:
            Concentration summary with flag and metrics
        """
        if not per_pair_contributions:
            return ConcentrationSummary(
                concentration_flag=ConcentrationFlag.BALANCED_CONTRIBUTION,
                policy_version=self.concentration_policy_version,
            )

        # Sort by profit contribution
        sorted_by_profit = sorted(
            per_pair_contributions,
            key=lambda x: x.contribution_to_total_profit_pct or 0,
            reverse=True,
        )

        # Sort by trade contribution
        sorted_by_trades = sorted(
            per_pair_contributions,
            key=lambda x: x.contribution_to_total_trades_pct or 0,
            reverse=True,
        )

        top_pair_profit = sorted_by_profit[0]
        top_pair_trades = sorted_by_trades[0]

        top_pair_profit_share = top_pair_profit.contribution_to_total_profit_pct or 0
        top_pair_trade_share = top_pair_trades.contribution_to_total_trades_pct or 0

        # Determine concentration flag
        if top_pair_profit_share > 60 or top_pair_trade_share > 60:
            flag = ConcentrationFlag.HIGH_PAIR_CONCENTRATION
        elif top_pair_profit_share >= 40 or top_pair_trade_share >= 40:
            flag = ConcentrationFlag.MODERATE_CONCENTRATION
        else:
            flag = ConcentrationFlag.BALANCED_CONTRIBUTION

        # Count profitable vs losing pairs
        profitable = sum(
            1
            for c in per_pair_contributions
            if c.net_profit_abs is not None and c.net_profit_abs > 0
        )
        losing = sum(
            1
            for c in per_pair_contributions
            if c.net_profit_abs is not None and c.net_profit_abs <= 0
        )

        # Build contribution distribution
        contribution_distribution = {
            c.pair: c.contribution_to_total_profit_pct or 0
            for c in per_pair_contributions
        }

        return ConcentrationSummary(
            concentration_flag=flag,
            policy_version=self.concentration_policy_version,
            top_pair_profit_contribution_share=top_pair_profit_share,
            top_pair_trade_share=top_pair_trade_share,
            top_pair=top_pair_profit.pair,
            profitable_contributing_pairs=profitable,
            losing_contributing_pairs=losing,
            total_contributing_pairs=len(per_pair_contributions),
            pair_contribution_distribution=contribution_distribution,
        )

    def extract_exit_reason_distribution(
        self,
        parsed_summary: ParsedSummary,
    ) -> list[ExitReasonDistribution]:
        """Extract exit reason distribution from parsed summary.

        Args:
            parsed_summary: Parsed summary from backtest result

        Returns:
            List of exit reason distributions
        """
        if not parsed_summary.exit_reason_distribution:
            return []

        total_trades = parsed_summary.total_trades or 0
        distributions: list[ExitReasonDistribution] = []

        for exit_stat in parsed_summary.exit_reason_distribution:
            percentage = (
                (exit_stat.count / total_trades * 100) if total_trades > 0 else 0.0
            )

            distribution = ExitReasonDistribution(
                reason_name=exit_stat.reason,
                count=exit_stat.count,
                percentage_of_trades=percentage,
                total_profit_contribution=exit_stat.total_profit,
                average_result=None,  # Would need trade-level data to compute
            )

            distributions.append(distribution)

        return distributions
