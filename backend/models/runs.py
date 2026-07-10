"""Backtest run metadata, progress, parsed summaries, and pair metrics."""

from __future__ import annotations
from datetime import datetime
from typing import Literal

from .base import (
    PairClassification,
    RunEtaState,
    RunPhase,
    RunProgressUpdateSource,
    RunStatus,
    RunType,
    StrictModel,
)

class RunMetadata(StrictModel):
    """Backend data type for `RunMetadata`."""
    run_id: str
    strategy_name: str
    strategy_version_id: str
    parent_version_id: str | None
    baseline_run_id: str | None
    run_type: RunType
    run_status: RunStatus
    created_at: datetime
    completed_at: datetime | None
    freqtrade_exit_code: int | None
    config_file: str
    timerange: str
    timeframe: str
    pairs: list[str]
    fee_rate: float | None = None  # Optional: not used by backtest runner anymore
    stake_amount: str | float | None = None  # Optional: not used by backtest runner anymore
    max_open_trades: int
    dry_run_wallet: float = 1000.0
    git_commit_sha: str | None = None


class RunProgress(StrictModel):
    """Backend data type for `RunProgress`."""
    progress_version: Literal[1] = 1
    phase: RunPhase
    progress_pct: int
    started_at: datetime
    phase_started_at: datetime
    updated_at: datetime
    elapsed_seconds: int
    eta_seconds: int | None
    eta_state: RunEtaState
    current_step_label: str
    last_update_source: RunProgressUpdateSource
    terminal: bool


class ExitReasonStat(StrictModel):
    """Backend data type for `ExitReasonStat`."""
    reason: str
    count: int
    total_profit: float


class ParsedSummary(StrictModel):
    """Backend data type for `ParsedSummary`."""
    run_id: str
    starting_balance: float | None
    final_balance: float | None
    net_profit_currency: float | None
    net_profit_pct: float | None
    profit_per_day: float | None = None
    start_date: str | None = None
    end_date: str | None = None
    total_days: int | None = None
    total_trades: int | None
    trades_per_day: float | None
    win_rate_pct: float | None
    loss_rate_pct: float | None
    max_drawdown_pct: float | None
    max_drawdown_currency: float | None
    avg_trade_duration_minutes: float | None
    profit_factor: float | None
    expectancy: float | None
    sharpe_ratio: float | None
    sortino_ratio: float | None
    calmar_ratio: float | None
    exit_reason_distribution: list[ExitReasonStat]


class SmartFlag(StrictModel):
    """A heuristic insight flag derived from backtest results."""
    type: Literal["warning", "danger", "info"]
    code: str
    message: str


class HealthCheck(StrictModel):
    """One specific risk check in the Strategy Health Report."""
    severity: Literal["green", "yellow", "red"]
    code: str
    title: str
    message: str
    suggestion: str | None = None


class HealthReport(StrictModel):
    """Aggregated strategy health analysis derived from backtest results."""
    overall_severity: Literal["green", "yellow", "red"]
    checks: list[HealthCheck]


class PairResult(StrictModel):
    """Backend data type for `PairResult`."""
    pair: str
    net_profit_currency: float | None
    net_profit_pct: float | None
    total_trades: int | None
    win_count: int | None
    loss_count: int | None
    win_rate_pct: float | None
    avg_trade_result_pct: float | None
    avg_trade_duration_minutes: float | None
    pair_classification: PairClassification | None
    classification_rationale: str | None
