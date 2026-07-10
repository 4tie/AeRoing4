"""Public API request / response Pydantic models.

These are the HTTP-layer contracts.  They intentionally hide internal
engine details such as absolute file paths; routers resolve those from
settings.  Internal engine models live in backend.models.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from ..models import ParsedSummary


# ── Shared response shapes ────────────────────────────────────────────────────


class AsyncJobResponse(BaseModel):
    """Returned immediately (HTTP 202) for every long-running operation."""

    session_id: str
    status: str
    message: str


class SessionStatusResponse(BaseModel):
    """Returned by GET /api/session/status/{session_id}."""

    session_id: str
    operation: str
    status: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class SessionListResponse(BaseModel):
    """Returned by GET /api/session/list."""

    sessions: list[SessionStatusResponse]


class ResultListItem(BaseModel):
    """One lightweight completed backtest row for GET /api/results."""

    run_id: str
    strategy_name: str
    timerange: str
    timeframe: str
    created_at: str
    duration_ms: float | None = None
    parsed_summary: ParsedSummary | None = None


class ResultListResponse(BaseModel):
    """Returned by GET /api/results."""

    results: list[ResultListItem]


# ── Data Download ─────────────────────────────────────────────────────────────


class DataDownloadApiRequest(BaseModel):
    """Request body for POST /api/data/download."""

    pairs: list[str] = Field(
        ...,
        min_length=1,
        description="Trading pairs to download, e.g. ['BTC/USDT', 'ETH/USDT']",
    )
    timeframes: list[str] = Field(
        default=["5m"],
        min_length=1,
        description="Candle timeframes, e.g. ['5m', '1h']",
    )
    timerange: str | None = Field(
        default=None,
        description="Date range in YYYYMMDD-YYYYMMDD format, e.g. '20240101-20241231'",
    )
    prepend: bool = Field(
        default=False,
        description="Prepend missing historical data instead of appending",
    )
    config_file: str | None = Field(
        default=None,
        description="Absolute path to Freqtrade config. Omit to use the default.",
    )

    @field_validator("pairs", mode="before")
    @classmethod
    def validate_pairs(cls, v: Any) -> list[str]:
        pairs = [str(p).strip() for p in (v if isinstance(v, list) else [v]) if str(p).strip()]
        invalid = [p for p in pairs if "/" not in p]
        if invalid:
            raise ValueError(
                f"Invalid pair format (expected BTC/USDT style): {invalid}"
            )
        return pairs

    @field_validator("timeframes", mode="before")
    @classmethod
    def validate_timeframes(cls, v: Any) -> list[str]:
        tfs = [str(t).strip() for t in (v if isinstance(v, list) else [v]) if str(t).strip()]
        if not tfs:
            raise ValueError("At least one timeframe is required.")
        return tfs


# ── Backtest ──────────────────────────────────────────────────────────────────


class BacktestApiRequest(BaseModel):
    """Request body for POST /api/backtest/run."""

    strategy_name: str = Field(
        ..., description="Exact strategy class name as registered in the strategy directory"
    )
    version_id: str | None = Field(
        default=None,
        description="Specific version ID to run. Omit to use the currently accepted version.",
    )
    timerange: str = Field(
        ..., description="Date range in YYYYMMDD-YYYYMMDD format, e.g. '20240101-20241231'"
    )
    timeframe: str | None = Field(
        default=None,
        description="Candle size, e.g. '5m'. Falls back to the strategy's declared timeframe.",
    )
    pairs: list[str] | None = Field(
        default=None,
        description="Override the pair list stored in the version params. Omit to use saved pairs.",
    )
    max_open_trades: int = Field(default=1, ge=1)
    dry_run_wallet: float = Field(default=1000.0, gt=0)
    config_file: str | None = Field(
        default=None,
        description="Absolute path to Freqtrade config. Omit to use the default.",
    )

    @field_validator("strategy_name", mode="before")
    @classmethod
    def validate_strategy_name(cls, v: Any) -> str:
        text = str(v or "").strip()
        if not text:
            raise ValueError("strategy_name is required.")
        return text

    @field_validator("pairs", mode="before")
    @classmethod
    def validate_pairs(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        pairs = [str(p).strip() for p in (v if isinstance(v, list) else [v]) if str(p).strip()]
        invalid = [p for p in pairs if "/" not in p]
        if invalid:
            raise ValueError(
                f"Invalid pair format (expected BTC/USDT style): {invalid}"
            )
        return pairs or None


# ── Stress Lab (Pair Sweep) ───────────────────────────────────────────────────


class TemporalStressLabApiRequest(BaseModel):
    """Request body for POST /api/temporal-stress-lab/run.

    Runs the strategy across multiple time-based sub-intervals to evaluate
    robustness. Three modes are supported:
      - time_split: divide the overall timerange into N equal walk-forward segments
      - monte_carlo: sample N random windows of fixed length from the timerange
      - crash_gauntlet: run against predefined historical crypto crash periods
    """

    strategy_name: str = Field(..., description="Strategy class name to stress-test")
    timerange: str = Field(..., description="Overall date range YYYYMMDD-YYYYMMDD")
    timeframe: str = Field(default="1h", description="Candle size, e.g. '1h'")
    pairs: list[str] | None = Field(default=None, description="Trading pairs to use")
    mode: str = Field(
        ...,
        description="Stress mode: time_split | monte_carlo | crash_gauntlet",
    )
    n_splits: int | None = Field(
        default=4, ge=2, le=52, description="[time_split] Number of equal segments"
    )
    n_windows: int | None = Field(
        default=5, ge=2, le=20, description="[monte_carlo] Number of random windows"
    )
    window_days: int | None = Field(
        default=14, ge=3, le=365, description="[monte_carlo] Length of each window in days"
    )
    max_open_trades: int = Field(default=1, ge=1)
    dry_run_wallet: float = Field(default=1000.0, gt=0)
    config_file: str | None = Field(
        default=None,
        description="Absolute path to Freqtrade config. Omit to use the default.",
    )
    exported_trial_id: str | None = Field(
        default=None,
        description=(
            "When set, the backend loads the exported optimizer trial with this id "
            "and overrides the strategy parameters for every segment backtest run."
        ),
    )

    @field_validator("strategy_name", mode="before")
    @classmethod
    def validate_strategy_name(cls, v: Any) -> str:
        text = str(v or "").strip()
        if not text:
            raise ValueError("strategy_name is required.")
        return text

    @field_validator("mode", mode="before")
    @classmethod
    def validate_mode(cls, v: Any) -> str:
        valid = {"time_split", "monte_carlo", "crash_gauntlet"}
        text = str(v or "").strip()
        if text not in valid:
            raise ValueError(f"mode must be one of {sorted(valid)}")
        return text

    @field_validator("pairs", mode="before")
    @classmethod
    def validate_pairs(cls, v: Any) -> list[str] | None:
        if not v:
            return None
        pairs = [str(p).strip() for p in (v if isinstance(v, list) else [v]) if str(p).strip()]
        invalid = [p for p in pairs if "/" not in p]
        if invalid:
            raise ValueError(f"Invalid pair format (expected BTC/USDT style): {invalid}")
        return pairs or None


# ── Optimizer ─────────────────────────────────────────────────────────────────


class OptimizerApiRequest(BaseModel):
    """Request body for POST /api/optimizer/run."""

    strategy_name: str = Field(..., description="Strategy class name to optimize")
    timerange: str = Field(..., description="Date range YYYYMMDD-YYYYMMDD")
    timeframe: str = Field(default="1h", description="Candle size, e.g. '1h'")
    pairs: list[str] = Field(default_factory=list, description="Trading pairs")
    config_file: str | None = Field(default=None, description="Path to Freqtrade config")
    total_trials: int = Field(default=50, ge=1, le=500, description="Number of parameter-search trials")
    search_strategy: str = Field(default="random", description="random | grid | bayesian | evolutionary")
    parameter_mode: str = Field(default="auto_safe", description="manual | auto_safe")
    score_metric: str = Field(default="composite", description="Metric used to rank trials")
    max_open_trades: int = Field(default=1, ge=1)
    dry_run_wallet: float = Field(default=1000.0, gt=0)
    fee_rate: float = Field(default=0.001, ge=0)
    enable_vectorbt_screening: bool = Field(default=True, description="Run fast VectorBT pre-screening before Freqtrade trials")
    vectorbt_candidate_count: int = Field(default=1000, ge=1, le=100000, description="Maximum VectorBT candidates to evaluate")
    vectorbt_keep_ratio: float = Field(default=0.10, gt=0, le=1, description="Fraction of VectorBT candidates to keep")
    vectorbt_timeout_seconds: int = Field(default=120, ge=1, le=3600, description="Maximum VectorBT screening time")
    search_spaces: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Parameter search spaces from the frontend parameters table",
    )

    @field_validator("strategy_name", mode="before")
    @classmethod
    def validate_strategy_name(cls, v: Any) -> str:
        text = str(v or "").strip()
        if not text:
            raise ValueError("strategy_name is required.")
        return text

    @field_validator("pairs", mode="before")
    @classmethod
    def validate_pairs(cls, v: Any) -> list[str]:
        if not v:
            return []
        pairs = [str(p).strip() for p in (v if isinstance(v, list) else [v]) if str(p).strip()]
        invalid = [p for p in pairs if "/" not in p]
        if invalid:
            raise ValueError(f"Invalid pair format (expected BTC/USDT style): {invalid}")
        return pairs


class StressLabApiRequest(BaseModel):
    """Request body for POST /api/stress-lab/run.

    Runs *iteration_count* backtests where each iteration uses a different
    randomly-sampled subset of pairs from the active pair-selector pool.
    This stress-tests strategy robustness across varying pair combinations.
    """

    strategy_name: str = Field(..., description="Strategy to stress-test")
    timerange: str = Field(..., description="Date range for every iteration backtest")
    timeframe: str = Field(..., description="Candle size, e.g. '5m'")
    iteration_count: int = Field(
        default=10,
        ge=2,
        le=50,
        description="Number of random pair-set backtests (2–50)",
    )
    max_open_trades: int = Field(default=1, ge=1)
    dry_run_wallet: float = Field(default=1000.0, gt=0)
    fee_rate: float = Field(default=0.001, ge=0)
    download_data_first: bool = Field(
        default=False,
        description="Download data for all pool pairs before starting the sweep",
    )
    config_file: str | None = Field(
        default=None,
        description="Absolute path to Freqtrade config. Omit to use the default.",
    )

    @field_validator("strategy_name", mode="before")
    @classmethod
    def validate_strategy_name(cls, v: Any) -> str:
        text = str(v or "").strip()
        if not text:
            raise ValueError("strategy_name is required.")
        return text
