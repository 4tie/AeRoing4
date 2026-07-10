from __future__ import annotations

from typing import Any

from freqtrade.optimize.hyperopt import IHyperOptLoss


TIER1_TRIGGER = 0.03
LARGE_GIVEBACK_THRESHOLD = 0.03


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalise_trades(trades: Any) -> list[dict[str, Any]]:
    if trades is None:
        return []
    if hasattr(trades, "to_dict"):
        try:
            return list(trades.to_dict("records"))
        except Exception:
            return []
    if isinstance(trades, dict):
        return [trades]
    try:
        return [t for t in trades if isinstance(t, dict)]
    except TypeError:
        return []


def _trade_profit_ratio(trade: dict[str, Any]) -> float:
    if "profit_ratio" in trade:
        return _as_float(trade.get("profit_ratio"))
    if "profit_pct" in trade:
        return _as_float(trade.get("profit_pct")) / 100.0
    open_rate = _as_float(trade.get("open_rate"))
    close_rate = _as_float(trade.get("close_rate"))
    if open_rate > 0 and close_rate > 0:
        if trade.get("is_short"):
            return (open_rate - close_rate) / open_rate
        return (close_rate - open_rate) / open_rate
    return 0.0


def _trade_peak_profit_ratio(trade: dict[str, Any]) -> float:
    if "peak_profit_ratio" in trade:
        return max(0.0, _as_float(trade.get("peak_profit_ratio")))
    open_rate = _as_float(trade.get("open_rate"))
    if open_rate <= 0:
        return max(0.0, _trade_profit_ratio(trade))
    if trade.get("is_short"):
        min_rate = _as_float(trade.get("min_rate"), default=open_rate)
        return max(0.0, (open_rate - min_rate) / open_rate)
    max_rate = _as_float(trade.get("max_rate"), default=open_rate)
    return max(0.0, (max_rate - open_rate) / open_rate)


def compute_profit_giveback_metrics(trades: Any) -> dict[str, Any]:
    rows = _normalise_trades(trades)
    if not rows:
        return {
            "peak_profit_ratio": 0.0,
            "giveback_ratio": 0.0,
            "peak_to_loss_count": 0,
            "large_giveback_count": 0,
            "max_giveback_ratio": 0.0,
            "trade_count": 0,
        }

    peak_to_loss_count = 0
    large_giveback_count = 0
    max_peak = 0.0
    max_giveback = 0.0
    total_giveback = 0.0

    for trade in rows:
        profit = _trade_profit_ratio(trade)
        peak = _trade_peak_profit_ratio(trade)
        giveback = max(0.0, peak - profit)
        max_peak = max(max_peak, peak)
        max_giveback = max(max_giveback, giveback)
        total_giveback += giveback
        if peak >= TIER1_TRIGGER and profit < 0:
            peak_to_loss_count += 1
        if peak >= TIER1_TRIGGER and giveback >= LARGE_GIVEBACK_THRESHOLD:
            large_giveback_count += 1

    return {
        "peak_profit_ratio": round(max_peak, 10),
        "giveback_ratio": round(total_giveback / len(rows), 10),
        "peak_to_loss_count": peak_to_loss_count,
        "large_giveback_count": large_giveback_count,
        "max_giveback_ratio": round(max_giveback, 10),
        "trade_count": len(rows),
    }


def profit_lockin_loss_from_trades(trades: Any) -> float:
    rows = _normalise_trades(trades)
    total_profit = sum(_trade_profit_ratio(trade) for trade in rows)
    metrics = compute_profit_giveback_metrics(rows)
    loss = -total_profit
    loss += metrics["peak_to_loss_count"] * 2.0
    loss += metrics["large_giveback_count"] * 0.75
    loss += metrics["max_giveback_ratio"] * 2.0
    loss += metrics["giveback_ratio"]
    return float(loss)


class ProfitLockinHyperOptLoss(IHyperOptLoss):
    """Freqtrade-compatible Hyperopt loss for stepped stoploss strategies."""

    @staticmethod
    def hyperopt_loss_function(
        *,
        results,
        trade_count: int,
        min_date,
        max_date,
        config: dict,
        processed: dict,
        backtest_stats: dict,
        starting_balance: float = 0.0,
        **kwargs,
    ) -> float:
        trades = _normalise_trades(results)
        if not trades and isinstance(backtest_stats, dict):
            strategy_stats = backtest_stats.get("strategy", {})
            if strategy_stats:
                first_strategy = next(iter(strategy_stats.values()))
                trades = _normalise_trades(first_strategy.get("trades"))
        loss = profit_lockin_loss_from_trades(trades)
        if trade_count <= 0:
            loss += 100.0
        return loss
