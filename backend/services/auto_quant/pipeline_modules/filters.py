"""Pair filtering and trading window analysis for the Auto-Quant pipeline."""

from __future__ import annotations

from datetime import datetime

from .config import get_timeframe_thresholds


def _filter_winning_pairs(per_pair_results: list[dict], timeframe: str) -> list[dict]:
    """Filter pairs based on timeframe-specific profitability and drawdown thresholds.

    Args:
        per_pair_results: List of per-pair result dictionaries from backtest
        timeframe: Current timeframe string (e.g., "15m", "1h")

    Returns:
        List of winning pairs with their metrics (profit, drawdown, ATR, etc.)
    """
    thresholds = get_timeframe_thresholds(timeframe)
    min_profit = thresholds["min_oos_profit"]
    max_dd = thresholds["max_drawdown_threshold"]

    winning_pairs = []
    for pair_result in per_pair_results:
        profit = pair_result.get("profit_total", 0)
        drawdown = pair_result.get("max_drawdown_pct", 100)

        if profit >= min_profit and drawdown < max_dd:
            winning_pairs.append(pair_result)

    return winning_pairs


def _analyze_trading_windows(per_pair_results: list[dict]) -> dict:
    """Analyze trading performance by hour and day to identify losing time blocks.

    Args:
        per_pair_results: List of per-pair result dictionaries from backtest

    Returns:
        Dictionary with excluded hours and days based on profitability criteria
    """
    # Initialize time bucket counters
    hour_stats = {h: {"profit": 0.0, "wins": 0, "total": 0} for h in range(24)}
    day_stats = {d: {"profit": 0.0, "wins": 0, "total": 0} for d in range(7)}

    # Aggregate stats across all pairs
    for pair_result in per_pair_results:
        trades = pair_result.get("trades", [])
        for trade in trades:
            try:
                # Parse trade timestamp
                trade_time = trade.get("close_date")
                if not trade_time:
                    continue

                # Convert to datetime if it's a string
                if isinstance(trade_time, str):
                    trade_time = datetime.fromisoformat(trade_time.replace("Z", "+00:00"))

                hour = trade_time.hour
                day = trade_time.weekday()

                profit = trade.get("profit_abs", 0)
                is_win = profit > 0

                hour_stats[hour]["profit"] += profit
                hour_stats[hour]["total"] += 1
                if is_win:
                    hour_stats[hour]["wins"] += 1

                day_stats[day]["profit"] += profit
                day_stats[day]["total"] += 1
                if is_win:
                    day_stats[day]["wins"] += 1
            except Exception:
                continue

    # Apply exclusion rule: exclude IF (profit < 0 OR win_rate < 40%) AND trade_count >= 15
    excluded_hours = []
    for hour, stats in hour_stats.items():
        if stats["total"] >= 15:
            win_rate = (stats["wins"] / stats["total"]) * 100 if stats["total"] > 0 else 0
            if stats["profit"] < 0 or win_rate < 40:
                excluded_hours.append(hour)

    excluded_days = []
    for day, stats in day_stats.items():
        if stats["total"] >= 15:
            win_rate = (stats["wins"] / stats["total"]) * 100 if stats["total"] > 0 else 0
            if stats["profit"] < 0 or win_rate < 40:
                excluded_days.append(day)

    return {
        "excluded_hours": excluded_hours,
        "excluded_days": excluded_days,
        "hour_stats": hour_stats,
        "day_stats": day_stats,
    }
