"""Rich backtest result models for trades, charts, and advanced metrics."""

from __future__ import annotations

from pydantic import Field

from .base import StrictModel
from .runs import ExitReasonStat, PairResult, ParsedSummary

class BacktestOrder(StrictModel):
    """Backend data type for `BacktestOrder`."""
    amount: float | None = None
    safe_price: float | None = None
    ft_order_side: str | None = None
    order_filled_timestamp: int | None = None
    ft_is_entry: bool | None = None
    ft_order_tag: str | None = None
    cost: float | None = None


class BacktestTrade(StrictModel):
    """Backend data type for `BacktestTrade`."""
    pair: str
    open_date: str | None = None
    close_date: str | None = None
    open_timestamp: int | None = None
    close_timestamp: int | None = None

    stake_amount: float | None = None
    max_stake_amount: float | None = None
    amount: float | None = None

    open_rate: float | None = None
    close_rate: float | None = None
    fee_open: float | None = None
    fee_close: float | None = None

    trade_duration: int | None = None
    profit_ratio: float | None = None
    profit_abs: float | None = None

    exit_reason: str | None = None
    enter_tag: str | None = None

    initial_stop_loss_abs: float | None = None
    initial_stop_loss_ratio: float | None = None
    stop_loss_abs: float | None = None
    stop_loss_ratio: float | None = None

    min_rate: float | None = None
    max_rate: float | None = None

    leverage: float | None = None
    is_short: bool | None = None

    orders: list[BacktestOrder] = Field(default_factory=list)
    funding_fees: float | None = None
    weekday: int | None = None


class EquityPoint(StrictModel):
    """Backend data type for `EquityPoint`."""
    ts: int
    equity: float


class DrawdownPoint(StrictModel):
    """Backend data type for `DrawdownPoint`."""
    ts: int
    drawdown_pct: float


class HistogramBin(StrictModel):
    """Backend data type for `HistogramBin`."""
    left: float
    right: float
    count: int


class BacktestCharts(StrictModel):
    """Backend data type for `BacktestCharts`."""
    equity_curve: list[EquityPoint] = Field(default_factory=list)
    drawdown_curve: list[DrawdownPoint] = Field(default_factory=list)
    profit_ratio_histogram: list[HistogramBin] = Field(default_factory=list)
    duration_minutes_histogram: list[HistogramBin] = Field(default_factory=list)
    weekday_winrate: dict[str, float] = Field(default_factory=dict)
    exit_reason_counts: dict[str, int] = Field(default_factory=dict)


class BacktestAdvancedMetrics(StrictModel):
    """Backend data type for `BacktestAdvancedMetrics`."""
    profit_factor: float | None = None
    expectancy: float | None = None
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None

    max_drawdown_pct: float | None = None
    max_drawdown_currency: float | None = None

    avg_trade_duration_minutes: float | None = None

    win_rate_pct: float | None = None
    loss_rate_pct: float | None = None

    total_trades: int | None = None
    trades_per_day: float | None = None


class PairTradeBreakdown(StrictModel):
    """Backend data type for `PairTradeBreakdown`."""
    pair: str
    trades: list[BacktestTrade] = Field(default_factory=list)


class BacktestRichResults(StrictModel):
    """Expanded results payload for the Results screen."""

    parsed_summary: ParsedSummary
    pair_results: list[PairResult]
    exit_reason_distribution: list[ExitReasonStat]

    trades: list[BacktestTrade] = Field(default_factory=list)
    trades_by_pair: dict[str, PairTradeBreakdown] = Field(default_factory=dict)

    advanced_metrics: BacktestAdvancedMetrics | None = None
    charts: BacktestCharts | None = None
