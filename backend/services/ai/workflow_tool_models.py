"""Workflow tool models for unified AI copilot.

Defines typed models for tool calls, results, safety classifications,
and argument schemas that match current application contracts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ToolSafety(str, Enum):
    """Safety classification for workflow tools."""
    READ_ONLY = "read_only"
    CONFIRMATION_REQUIRED = "confirmation_required"
    FORBIDDEN = "forbidden"


class ToolRunStatus(str, Enum):
    """Status of a tool execution."""
    PROPOSED = "proposed"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    OBSERVATION_PAUSED = "observation_paused"


class WorkflowToolCall(BaseModel):
    """A validated tool call request from the model."""
    tool_call_id: str = Field(default_factory=lambda: str(uuid4()))
    tool_name: str
    arguments: dict[str, Any]
    safety: ToolSafety
    created_at: str = Field(default_factory=lambda: datetime.now(tz=UTC).isoformat())


class WorkflowToolResult(BaseModel):
    """Result of a tool execution."""
    tool_run_id: str
    tool_call_id: str
    tool_name: str
    status: ToolRunStatus
    result_summary: dict[str, Any] | None = None
    error: str | None = None
    context_patch: dict[str, Any] | None = None
    started_at: str | None = None
    completed_at: str | None = None


class PendingToolAction(BaseModel):
    """A tool action awaiting user confirmation."""
    action_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    tool_call_id: str | None = None
    tool_name: str
    arguments: dict[str, Any]
    arguments_hash: str
    safety: ToolSafety
    status: str = "awaiting_confirmation"
    created_at: str = Field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    expires_at: str | None = None


class JobReference(BaseModel):
    """Reference to a long-running backend job."""
    job_type: str  # "backtest", "optimizer", "pair_explorer", "stress", "temporal_stress"
    api_session_id: str | None = None
    workflow_session_id: str | None = None
    status: str = "running"
    created_at: str = Field(default_factory=lambda: datetime.now(tz=UTC).isoformat())


class ToolRunRecord(BaseModel):
    """Persistent record of a tool execution in the copilot session."""
    tool_run_id: str = Field(default_factory=lambda: str(uuid4()))
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    safety: ToolSafety
    status: ToolRunStatus
    created_at: str = Field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    started_at: str | None = None
    completed_at: str | None = None
    job_ref: JobReference | None = None
    result_summary: dict[str, Any] | None = None
    error: str | None = None


# ── Argument models for each tool ────────────────────────────────────────────────


class ListStrategiesArgs(BaseModel):
    """Arguments for list_strategies tool."""
    pass


class ReadStrategyFileArgs(BaseModel):
    """Arguments for read_strategy_file tool."""
    strategy_name: str = Field(
        ...,
        description=(
            "Strategy identifier — accepts filename (AIStrategy.py), stem (AIStrategy), "
            "or class name — case-insensitive."
        ),
    )


class ValidateStrategySyntaxArgs(BaseModel):
    """Arguments for validate_strategy_syntax tool."""
    strategy_name: str = Field(
        ...,
        description=(
            "Strategy identifier — accepts filename (AIStrategy.py), stem (AIStrategy), "
            "or class name — case-insensitive."
        ),
    )


class InspectAppStructureArgs(BaseModel):
    """Arguments for inspect_app_structure tool."""
    pass


class ViewBestParamsArgs(BaseModel):
    """Arguments for view_best_params tool."""
    optimizer_session_id: str = Field(..., description="Optimizer session ID")


class ViewTrialParamsArgs(BaseModel):
    """Arguments for view_trial_params tool."""
    optimizer_session_id: str = Field(..., description="Optimizer session ID")
    trial_number: int = Field(..., description="Trial number to view")


# ── Workflow tools with current application contracts ───────────────────────────


class RunBacktestArgs(BaseModel):
    """Arguments for run_backtest tool - matches current BacktestApiRequest."""
    strategy_name: str = Field(..., description="Strategy name")
    version_id: str | None = Field(None, description="Specific version ID to run")
    timerange: str = Field(..., description="Date range (e.g., '20230101-20240101')")
    timeframe: str | None = Field(None, description="Candle timeframe")
    pairs: list[str] | None = Field(None, description="List of pairs to backtest")
    max_open_trades: int = Field(default=1, ge=1, description="Maximum open trades")
    dry_run_wallet: float = Field(default=1000.0, gt=0, description="Dry run wallet amount")
    config_file: str | None = Field(None, description="Optional config file override")


class RunOptimizerArgs(BaseModel):
    """Arguments for run_optimizer tool - matches current OptimizerApiRequest."""
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


class RunPairExplorerArgs(BaseModel):
    """Arguments for run_pair_explorer tool - matches current PairExplorerRequest."""
    strategy_name: str = Field(..., description="Strategy name")
    pairs: list[str] = Field(..., description="List of pairs to explore")
    timeframe: str = Field(default="1h", description="Candle timeframe")
    timerange: str = Field(..., description="Date range")
    dry_run_wallet: float = Field(default=1000.0, description="Dry run wallet amount")
    max_open_trades: int = Field(default=1, description="Group size for backtesting")


class RunPairStressLabArgs(BaseModel):
    """Arguments for run_pair_stress_lab tool."""
    strategy_name: str = Field(..., description="Strategy name")
    pairs: list[str] = Field(..., description="List of pairs")
    timeframe: str = Field(default="5m", description="Candle timeframe")
    timerange: str = Field(..., description="Date range")
    max_open_trades: int = Field(default=1, description="Maximum open trades")
    fee_rate: float = Field(default=0.001, description="Trading fee rate")


class RunTemporalStressTestArgs(BaseModel):
    """Arguments for run_temporal_stress_test tool - matches TemporalStressLabApiRequest."""
    strategy_name: str = Field(..., description="Strategy name")
    pairs: list[str] = Field(..., description="List of pairs")
    timeframe: str = Field(default="5m", description="Candle timeframe")
    timerange: str = Field(..., description="Date range")
    tests: list[str] = Field(..., description="Tests to run: time_split, monte_carlo, crash_gauntlet")
    max_open_trades: int = Field(default=1, description="Maximum open trades")
    fee_rate: float = Field(default=0.001, description="Trading fee rate")


class EditStrategySectionArgs(BaseModel):
    """Arguments for edit_strategy_section tool."""
    strategy_name: str = Field(..., description="Strategy name without .py extension")
    section: str = Field(..., description="Section to edit")
    changes: str = Field(..., description="New content for the section")
    reason: str = Field(..., description="Reason for the edit (for audit trail)")


class GetPairUniverseArgs(BaseModel):
    """Arguments for get_pair_universe tool."""
    quote_currency: str | None = Field(
        None,
        description="Filter by quote currency, e.g. 'USDT' returns only */USDT pairs.",
    )
    exclude_pairs: list[str] | None = Field(
        None,
        description="Pairs to exclude from the returned universe.",
    )
    max_candidates: int | None = Field(
        None,
        ge=1,
        le=500,
        description="Maximum number of pairs to return.",
    )
