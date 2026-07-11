"""Adapter for converting Freqtrade native backtest results to CanonicalMetricsSnapshot.

This module provides the canonical bridge between Freqtrade 2026.6 backtest result
JSON format and AeRoing4's single source of truth metric contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from .models import (
    CanonicalMetricsSnapshot,
    MetricAvailability,
    MetricProvenance,
    MetricValue,
    SourceType,
)
from .provenance import METRICS_VERSION, build_provenance


class FreqtradeAdapterError(Exception):
    """Raised when Freqtrade result cannot be adapted to canonical snapshot."""


def _parse_holding_avg(holding_avg: str | None) -> float | None:
    """Parse Freqtrade holding_avg format (e.g., '2:25:00') to minutes.
    
    Returns None if parsing fails or input is None.
    """
    if not holding_avg:
        return None
    try:
        parts = holding_avg.split(":")
        if len(parts) == 3:
            hours, minutes, seconds = map(int, parts)
            return hours * 60 + minutes + seconds / 60
        return None
    except (ValueError, AttributeError):
        return None


def canonical_snapshot_from_freqtrade_backtest_result(
    payload: dict[str, Any],
    *,
    source_run_id: str | None = None,
    source_artifact: str | None = None,
) -> CanonicalMetricsSnapshot:
    """Convert Freqtrade native backtest result JSON to CanonicalMetricsSnapshot.
    
    Args:
        payload: Freqtrade backtest result JSON dict (from extracted .zip)
        source_run_id: Optional run ID for provenance tracking
        source_artifact: Optional artifact path for provenance tracking
    
    Returns:
        CanonicalMetricsSnapshot with metric availability states
    
    Raises:
        FreqtradeAdapterError: If critical structure is missing or invalid
    """
    # Navigate to strategy-specific results
    strategy_key = payload.get("strategy")
    if strategy_key is None:
        raise FreqtradeAdapterError("Missing 'strategy' key in payload")
    if not isinstance(strategy_key, dict):
        raise FreqtradeAdapterError("Invalid 'strategy' key: expected dict")
    
    # Get the first (and typically only) strategy name key
    strategy_names = list(strategy_key.keys())
    if not strategy_names:
        raise FreqtradeAdapterError("No strategy name found in strategy dict")
    
    strategy_name = strategy_names[0]
    strat_data = strategy_key[strategy_name]
    if not isinstance(strat_data, dict):
        raise FreqtradeAdapterError(f"Invalid strategy data for {strategy_name}")
    
    # Extract metrics with availability tracking
    def _safe_float(value: Any) -> float | None:
        """Safely convert to float, returning None on failure."""
        try:
            return float(value) if value is not None else None
        except (ValueError, TypeError):
            return None
    
    def _safe_int(value: Any) -> int | None:
        """Safely convert to int, returning None on failure."""
        try:
            return int(value) if value is not None else None
        except (ValueError, TypeError):
            return None
    
    # Activity metrics
    total_trades_raw = _safe_int(strat_data.get("total_trades"))
    winning_trades_raw = _safe_int(strat_data.get("wins"))
    losing_trades_raw = _safe_int(strat_data.get("losses"))
    
    # Profitability metrics
    profit_total_abs_raw = _safe_float(strat_data.get("profit_total_abs"))
    profit_total_raw = _safe_float(strat_data.get("profit_total"))  # May be percentage
    profit_factor_raw = _safe_float(strat_data.get("profit_factor"))
    expectancy_raw = _safe_float(strat_data.get("expectancy"))
    winrate_raw = _safe_float(strat_data.get("winrate"))
    
    # Risk-adjusted metrics
    sharpe_raw = _safe_float(strat_data.get("sharpe"))
    sortino_raw = _safe_float(strat_data.get("sortino"))
    calmar_raw = _safe_float(strat_data.get("calmar"))
    
    # Risk metrics
    max_drawdown_abs_raw = _safe_float(strat_data.get("max_drawdown_abs"))
    max_relative_drawdown_raw = _safe_float(strat_data.get("max_relative_drawdown"))
    
    # Trade behavior
    holding_avg_raw = _parse_holding_avg(strat_data.get("holding_avg"))
    
    # Bootstrap Sharpe (not available in Freqtrade native results)
    bootstrap_sharpe_p5_raw = None
    
    # Build MetricValue objects with proper availability states
    def _build_metric(value: float | int | None, critical: bool = False) -> MetricValue:
        """Build MetricValue with appropriate availability state."""
        if value is None:
            if critical:
                raise FreqtradeAdapterError(f"Critical metric unavailable: value={value}")
            return MetricValue.unavailable()
        return MetricValue.available(value)
    
    # Critical metrics that must be available
    if total_trades_raw is None:
        raise FreqtradeAdapterError("Critical metric 'total_trades' is missing")
    
    total_trades = _build_metric(total_trades_raw, critical=True)
    winning_trades = _build_metric(winning_trades_raw)
    losing_trades = _build_metric(losing_trades_raw)
    
    # Profitability
    net_profit_abs = _build_metric(profit_total_abs_raw)
    # Use profit_total if profit_total_abs is not available
    net_profit_pct = _build_metric(profit_total_raw if profit_total_abs_raw is None else profit_total_raw)
    win_rate = _build_metric(winrate_raw)
    profit_factor = _build_metric(profit_factor_raw)
    expectancy = _build_metric(expectancy_raw)
    
    # Risk-adjusted
    sharpe = _build_metric(sharpe_raw)
    sortino = _build_metric(sortino_raw)
    calmar = _build_metric(calmar_raw)
    
    # Risk
    max_drawdown_abs = _build_metric(max_drawdown_abs_raw)
    # Freqtrade reports drawdown as positive percentage, convert to negative for canonical
    if max_relative_drawdown_raw is not None and max_relative_drawdown_raw > 0:
        max_relative_drawdown_raw = -max_relative_drawdown_raw
    max_drawdown_pct = _build_metric(max_relative_drawdown_raw)
    
    # Trade behavior
    average_trade_duration_minutes = _build_metric(holding_avg_raw)
    
    # Bootstrap Sharpe (not available from Freqtrade)
    bootstrap_sharpe_p5 = MetricValue.unavailable()
    
    # Build provenance
    provenance_dict = build_provenance(
        source_type=SourceType.PARSED_SUMMARY,
        source_run_id=source_run_id,
        source_artifact=source_artifact,
        unavailable_metrics=[
            "bootstrap_sharpe_p5",  # Not available in Freqtrade native results
        ],
    )
    
    try:
        provenanceobj = MetricProvenance(**provenance_dict)
    except ValidationError as e:
        raise FreqtradeAdapterError(f"Invalid provenance: {e}")
    
    # Construct canonical snapshot
    try:
        return CanonicalMetricsSnapshot(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            net_profit_abs=net_profit_abs,
            net_profit_pct=net_profit_pct,
            win_rate=win_rate,
            profit_factor=profit_factor,
            expectancy=expectancy,
            sharpe=sharpe,
            sortino=sortino,
            calmar=calmar,
            max_drawdown_abs=max_drawdown_abs,
            max_drawdown_pct=max_drawdown_pct,
            average_trade_duration_minutes=average_trade_duration_minutes,
            bootstrap_sharpe_p5=bootstrap_sharpe_p5,
            provenance=provenanceobj,
        )
    except ValidationError as e:
        raise FreqtradeAdapterError(f"Failed to construct CanonicalMetricsSnapshot: {e}")
