"""Portfolio Baseline models for AeRoing4.

This module defines the data models for portfolio baseline execution,
including per-pair contributions, concentration analysis, and exit reason distribution.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# Policy versions
PORTFOLIO_BASELINE_POLICY_VERSION = "1.0.0"
PORTFOLIO_CONCENTRATION_POLICY_VERSION = "1.0.0"


class PortfolioBaselineOutcome(str, Enum):
    """Outcome of portfolio baseline execution."""
    PASS_BASELINE_CREATED = "pass_baseline_created"
    FAIL_EXECUTION = "fail_execution"
    FAIL_NO_TRADES = "fail_no_trades"
    FAIL_INVALID_SELECTION = "fail_invalid_selection"
    FAIL_DATA = "fail_data"
    PROTOCOL_DENIED = "protocol_denied"


class ConcentrationFlag(str, Enum):
    """Portfolio concentration classification."""
    BALANCED_CONTRIBUTION = "balanced_contribution"
    MODERATE_CONCENTRATION = "moderate_concentration"
    HIGH_PAIR_CONCENTRATION = "high_pair_concentration"


class PerPairContribution(BaseModel):
    """Per-pair contribution from portfolio baseline."""

    pair: str
    trade_count: int = 0
    net_profit_abs: float | None = None
    net_profit_pct: float | None = None
    win_rate: float | None = None
    contribution_to_total_profit_pct: float | None = None
    contribution_to_total_trades_pct: float | None = None


class ConcentrationSummary(BaseModel):
    """Portfolio concentration analysis."""

    concentration_flag: ConcentrationFlag
    policy_version: str = PORTFOLIO_CONCENTRATION_POLICY_VERSION

    # Top pair metrics
    top_pair_profit_contribution_share: float | None = None
    top_pair_trade_share: float | None = None
    top_pair: str | None = None

    # Distribution metrics
    profitable_contributing_pairs: int = 0
    losing_contributing_pairs: int = 0
    total_contributing_pairs: int = 0

    # Pair contribution distribution (pair -> contribution share)
    pair_contribution_distribution: dict[str, float] = Field(default_factory=dict)


class ExitReasonDistribution(BaseModel):
    """Exit reason distribution for portfolio baseline."""

    reason_name: str
    count: int = 0
    percentage_of_trades: float = 0.0
    total_profit_contribution: float | None = None
    average_result: float | None = None


class PortfolioBaselineResult(BaseModel):
    """Result of the portfolio baseline step."""

    status: PortfolioBaselineOutcome

    # Selection reference
    selected_pairs: list[str] = Field(default_factory=list)
    pair_selection_reference: str | None = None  # selection_hash or reference ID

    # Backtest execution
    backtest_run_id: str | None = None
    strategy_name: str = ""
    strategy_version: str | None = None
    strategy_hash: str = ""
    parameter_hash: str = ""
    timeframe: str = ""
    develop_timerange: str = ""

    # Configuration
    wallet_configuration: dict = Field(default_factory=dict)
    stake_configuration: dict = Field(default_factory=dict)
    max_open_trades: int = 0
    exchange: str = ""
    trading_mode: str = ""

    # Metrics SSOT
    canonical_metrics: dict = Field(default_factory=dict)  # CanonicalMetricsSnapshot

    # Evidence
    per_pair_contribution: list[PerPairContribution] = Field(default_factory=list)
    concentration_summary: ConcentrationSummary | None = None
    exit_reason_distribution: list[ExitReasonDistribution] = Field(default_factory=list)

    # Protocol integration
    protocol_access_entry_id: str | None = None

    # Reproducibility
    configuration_snapshot: dict = Field(default_factory=dict)
    input_hash: str = ""
    command_record: str = ""
    artifacts: dict[str, str] = Field(default_factory=dict)
    logs: str = ""

    # Timing
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float = 0.0

    # Freeze tracking
    selection_frozen_at: datetime | None = None
