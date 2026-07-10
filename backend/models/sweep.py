"""Backtest pair-sweep session and iteration models."""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from .base import StrictModel, _is_valid_timeframe, _is_valid_timerange

# ── Backtest Pair Sweep ───────────────────────────────────────────────────────

class SweepPhase(str, Enum):
    """Backend data type for `SweepPhase`."""
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


class SweepIterationStatus(str, Enum):
    """Backend data type for `SweepIterationStatus`."""
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


class SweepIterationMetrics(StrictModel):
    """Backend data type for `SweepIterationMetrics`."""
    net_profit_pct:   float | None = None
    total_trades:     int   | None = None
    win_rate_pct:     float | None = None
    max_drawdown_pct: float | None = None
    profit_factor:    float | None = None


class SweepIterationRecord(StrictModel):
    """Backend data type for `SweepIterationRecord`."""
    iteration_number: int
    status:           SweepIterationStatus
    pairs:            list[str]
    run_id:           str | None = None
    metrics:          SweepIterationMetrics | None = None
    started_at:       datetime | None = None
    completed_at:     datetime | None = None
    error:            str | None = None
    warning:          str | None = None


class SweepSessionConfig(StrictModel):
    """Backend data type for `SweepSessionConfig`."""
    strategy_name:   str
    config_file:     str
    timerange:       str
    timeframe:       str
    fee_rate:        float = 0.001
    max_open_trades: int   = 1
    dry_run_wallet:  float = 1000.0
    iteration_count: int   = 10
    pair_pool:       list[str]
    locked_pairs:    list[str] = Field(default_factory=list)


class SweepSession(StrictModel):
    """Backend data type for `SweepSession`."""
    session_id:           str
    strategy_name:        str
    config:               SweepSessionConfig
    phase:                SweepPhase
    created_at:           datetime
    started_at:           datetime | None = None
    completed_at:         datetime | None = None
    total_iterations:     int
    completed_iterations: int = 0
    failed_iterations:    int = 0
    iterations:           list[SweepIterationRecord] = Field(default_factory=list)
    stop_reason:          str | None = None
    elapsed_seconds:      float = 0.0
    eta_seconds:          float | None = None


class SweepSessionSummary(StrictModel):
    """Backend data type for `SweepSessionSummary`."""
    session_id:           str
    strategy_name:        str
    created_at:           datetime
    started_at:           datetime | None = None
    completed_at:         datetime | None = None
    phase:                SweepPhase
    total_iterations:     int
    completed_iterations: int
    best_net_profit_pct:  float | None = None


class StartPairSweepRequest(StrictModel):
    """Backend data type for `StartPairSweepRequest`."""
    strategy_name:   str
    config_file:     str
    timerange:       str
    timeframe:       str
    fee_rate:        float = 0.001
    max_open_trades: int   = 1
    dry_run_wallet:  float = 1000.0
    iteration_count: int   = 10
    download_data_first: bool = False

    @field_validator("iteration_count")
    @classmethod
    def validate_iteration_count(cls, value: int) -> int:
        """Validate or transform `validate_iteration_count` input before the model is accepted."""
        if value < 2 or value > 50:
            raise ValueError("iteration_count must be between 2 and 50.")
        return value

    @field_validator("timerange", mode="before")
    @classmethod
    def validate_timerange(cls, value: Any) -> str:
        """Validate or transform `validate_timerange` input before the model is accepted."""
        text = str(value or "").strip()
        if not text:
            raise ValueError("timerange is required.")
        if not _is_valid_timerange(text):
            raise ValueError("timerange must look like YYYYMMDD-YYYYMMDD.")
        return text

    @field_validator("timeframe", mode="before")
    @classmethod
    def validate_timeframe(cls, value: Any) -> str:
        """Validate or transform `validate_timeframe` input before the model is accepted."""
        text = str(value or "").strip()
        if not text:
            raise ValueError("timeframe is required.")
        if not _is_valid_timeframe(text):
            raise ValueError("timeframe must look like 5m, 1h, 1d.")
        return text
