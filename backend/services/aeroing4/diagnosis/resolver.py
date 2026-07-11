"""Evidence resolver and exit reason mapper for AeRoing4 Diagnosis.

Provides typed accessors for evidence (no fragile dict access) and
canonical mapping of exit reasons.
"""

from __future__ import annotations

from typing import Optional

from ..metrics.models import CanonicalMetricsSnapshot, MetricAvailability, MetricValue
from ..portfolio_baseline.models import (
    ConcentrationSummary,
    ExitReasonDistribution,
    PerPairContribution,
    PortfolioBaselineResult,
)
from .models import DiagnosisCategory


# ── Exit Reason Canonical Categories ────────────────────────────────────────────


class CanonicalExitCategory(str):
    """Canonical exit reason categories for diagnosis."""

    STOP_RISK_EXIT = "STOP_RISK_EXIT"
    PROFIT_TARGET_EXIT = "PROFIT_TARGET_EXIT"
    STRATEGY_EXIT = "STRATEGY_EXIT"
    OPERATIONAL_EXIT = "OPERATIONAL_EXIT"
    OTHER = "OTHER"


# Mapping from raw Freqtrade exit reasons to canonical categories
_EXIT_REASON_MAPPING: dict[str, CanonicalExitCategory] = {
    # Stop-loss related
    "stop_loss": CanonicalExitCategory.STOP_RISK_EXIT,
    "stop_loss_on_exchange": CanonicalExitCategory.STOP_RISK_EXIT,
    "trailing_stop_loss": CanonicalExitCategory.STOP_RISK_EXIT,
    "stoploss": CanonicalExitCategory.STOP_RISK_EXIT,
    "stoploss_on_exchange": CanonicalExitCategory.STOP_RISK_EXIT,
    "trailing_stoploss": CanonicalExitCategory.STOP_RISK_EXIT,

    # Profit-target/ROI related
    "roi": CanonicalExitCategory.PROFIT_TARGET_EXIT,
    "take_profit": CanonicalExitCategory.PROFIT_TARGET_EXIT,
    "take_profit_multi": CanonicalExitCategory.PROFIT_TARGET_EXIT,
    "tp": CanonicalExitCategory.PROFIT_TARGET_EXIT,
    "tp_multi": CanonicalExitCategory.PROFIT_TARGET_EXIT,

    # Strategy-driven exits
    "exit_signal": CanonicalExitCategory.STRATEGY_EXIT,
    "exit_tag": CanonicalExitCategory.STRATEGY_EXIT,
    "custom_exit": CanonicalExitCategory.STRATEGY_EXIT,
    "exit": CanonicalExitCategory.STRATEGY_EXIT,

    # Operational/manual/emergency exits
    "force_exit": CanonicalExitCategory.OPERATIONAL_EXIT,
    "emergency_exit": CanonicalExitCategory.OPERATIONAL_EXIT,
    "force_sell": CanonicalExitCategory.OPERATIONAL_EXIT,
    "force_buy": CanonicalExitCategory.OPERATIONAL_EXIT,
}


def map_exit_reason(raw_reason: str) -> tuple[str, CanonicalExitCategory]:
    """Map a raw Freqtrade exit reason to a canonical category.

    Preserves the original raw reason and provides a normalized category.
    Unknown values are mapped to OTHER.

    Args:
        raw_reason: The raw exit reason string from Freqtrade

    Returns:
        Tuple of (raw_reason, canonical_category)
    """
    canonical = _EXIT_REASON_MAPPING.get(raw_reason.lower(), CanonicalExitCategory.OTHER)
    return raw_reason, canonical


# ── Evidence Resolver ────────────────────────────────────────────────────────────


class EvidenceResolver:
    """Typed accessor for diagnosis evidence.

    Provides stable, typed access to evidence without fragile dictionary access.
    """

    def __init__(self, baseline: PortfolioBaselineResult):
        """Initialize the evidence resolver with baseline result.

        Args:
            baseline: PortfolioBaselineResult containing all evidence
        """
        self.baseline = baseline
        # Handle both dict and CanonicalMetricsSnapshot for canonical_metrics
        if isinstance(baseline.canonical_metrics, dict):
            self.metrics = CanonicalMetricsSnapshot(**baseline.canonical_metrics)
        else:
            self.metrics = baseline.canonical_metrics

    # ── Canonical Metrics Accessors ─────────────────────────────────────────────

    def get_total_trades(self) -> Optional[int]:
        """Get total trades from canonical metrics."""
        return _get_metric_int(self.metrics.total_trades)

    def get_winning_trades(self) -> Optional[int]:
        """Get winning trades from canonical metrics."""
        return _get_metric_int(self.metrics.winning_trades)

    def get_losing_trades(self) -> Optional[int]:
        """Get losing trades from canonical metrics."""
        return _get_metric_int(self.metrics.losing_trades)

    def get_profit_factor(self) -> Optional[float]:
        """Get profit factor from canonical metrics."""
        return _get_metric_float(self.metrics.profit_factor)

    def get_expectancy(self) -> Optional[float]:
        """Get expectancy from canonical metrics."""
        return _get_metric_float(self.metrics.expectancy)

    def get_max_drawdown_pct(self) -> Optional[float]:
        """Get max drawdown percentage from canonical metrics."""
        return _get_metric_float(self.metrics.max_drawdown_pct)

    def get_calmar(self) -> Optional[float]:
        """Get Calmar ratio from canonical metrics."""
        return _get_metric_float(self.metrics.calmar)

    def get_sortino(self) -> Optional[float]:
        """Get Sortino ratio from canonical metrics."""
        return _get_metric_float(self.metrics.sortino)

    def get_sharpe(self) -> Optional[float]:
        """Get Sharpe ratio from canonical metrics."""
        return _get_metric_float(self.metrics.sharpe)

    def get_win_rate(self) -> Optional[float]:
        """Get win rate from canonical metrics."""
        return _get_metric_float(self.metrics.win_rate)

    def get_avg_trade_duration_minutes(self) -> Optional[float]:
        """Get average trade duration in minutes from canonical metrics."""
        return _get_metric_float(self.metrics.average_trade_duration_minutes)

    def is_metric_available(self, metric_name: str) -> bool:
        """Check if a specific metric is available.

        Args:
            metric_name: Name of the metric to check

        Returns:
            True if metric is available, False otherwise
        """
        metric_map = {
            "total_trades": self.metrics.total_trades,
            "profit_factor": self.metrics.profit_factor,
            "expectancy": self.metrics.expectancy,
            "max_drawdown_pct": self.metrics.max_drawdown_pct,
            "calmar": self.metrics.calmar,
            "sortino": self.metrics.sortino,
            "sharpe": self.metrics.sharpe,
            "win_rate": self.metrics.win_rate,
        }

        metric = metric_map.get(metric_name)
        if metric is None:
            return False
        return metric.availability == MetricAvailability.AVAILABLE

    # ── Portfolio Baseline Evidence Accessors ───────────────────────────────────

    def get_selected_pairs(self) -> list[str]:
        """Get list of selected pairs."""
        return self.baseline.selected_pairs

    def get_per_pair_contributions(self) -> list[PerPairContribution]:
        """Get per-pair contribution evidence."""
        return self.baseline.per_pair_contribution

    def get_concentration_summary(self) -> Optional[ConcentrationSummary]:
        """Get concentration summary."""
        return self.baseline.concentration_summary

    def get_exit_reason_distribution(self) -> list[ExitReasonDistribution]:
        """Get exit reason distribution."""
        return self.baseline.exit_reason_distribution

    def get_timeframe(self) -> str:
        """Get timeframe."""
        return self.baseline.timeframe

    def get_develop_timerange(self) -> str:
        """Get DEVELOP timerange."""
        return self.baseline.develop_timerange

    # ── Computed Accessors ───────────────────────────────────────────────────────

    def get_stoploss_exit_share(self) -> Optional[float]:
        """Calculate the share of exits due to stop loss.

        Returns:
            Share of trades that exited via stop loss (0-1), or None if
            exit reason distribution is unavailable
        """
        exit_dist = self.get_exit_reason_distribution()
        if not exit_dist:
            return None

        total_trades = self.get_total_trades()
        if total_trades is None or total_trades == 0:
            return None

        stoploss_count = 0
        for entry in exit_dist:
            raw_reason, canonical = map_exit_reason(entry.reason_name)
            if canonical == CanonicalExitCategory.STOP_RISK_EXIT:
                stoploss_count += entry.count

        return stoploss_count / total_trades

    def get_negative_contributing_pairs(self) -> int:
        """Count pairs with negative contribution."""
        contributions = self.get_per_pair_contributions()
        return sum(1 for c in contributions if c.net_profit_pct and c.net_profit_pct < 0)


# ── Helper Functions ────────────────────────────────────────────────────────────


def _get_metric_int(metric: MetricValue) -> Optional[int]:
    """Extract integer value from MetricValue."""
    if metric.availability != MetricAvailability.AVAILABLE:
        return None
    value = metric.value
    return int(value) if value is not None else None


def _get_metric_float(metric: MetricValue) -> Optional[float]:
    """Extract float value from MetricValue."""
    if metric.availability != MetricAvailability.AVAILABLE:
        return None
    value = metric.value
    return	float(value) if value is not None else None
