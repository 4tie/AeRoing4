"""AeRoing4 data models for run state and step results."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field

from .research.state import ResearchProtocolState


class AeRoing4RunStatus(str, Enum):
    """Overall run status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AeRoing4StepStatus(str, Enum):
    """Individual step status."""
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SmokeBacktestOutcome(str, Enum):
    """Smoke backtest outcome classification."""
    PASS_ACTIVITY = "pass_activity"
    NO_SIGNAL_ACTIVITY = "no_signal_activity"
    EXECUTION_FAILURE = "execution_failure"


class BiasCheckOutcome(str, Enum):
    """Bias check outcome classification."""
    PASS = "pass"
    PASS_WITH_WARNING = "pass_with_warning"
    FAIL_LOOKAHEAD = "fail_lookahead"
    FAIL_RECURSIVE_BIAS = "fail_recursive_bias"
    EXECUTION_FAILURE = "execution_failure"
    NOT_SUPPORTED = "not_supported"


class BiasCheckItemResult(BaseModel):
    """Individual bias check execution result."""
    check_type: str
    execution_status: str
    analytical_status: str
    decision_code: str
    summary: str = ""
    evidence: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    command: str = ""
    exit_code: int | None = None
    stdout_artifact: str | None = None
    stderr_artifact: str | None = None
    duration_seconds: float = 0.0


class BiasCheckResult(BaseModel):
    """Result of the bias check stage."""
    outcome: BiasCheckOutcome
    lookahead_result: BiasCheckItemResult | None = None
    recursive_result: BiasCheckItemResult | None = None
    checks_requested: list[str] = Field(default_factory=list)
    checks_executed: list[str] = Field(default_factory=list)
    checks_skipped: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    execution_errors: list[str] = Field(default_factory=list)
    command_records: list[str] = Field(default_factory=list)
    artifact_references: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float = 0.0
    policy_version: str = "1.0.0"
    input_identity: str = ""
    timerange: str = ""
    pairs: list[str] = Field(default_factory=list)


class PairCandidateStatus(str, Enum):
    """Pair discovery evaluation status."""
    DATA_UNAVAILABLE = "data_unavailable"
    EXECUTION_FAILURE = "execution_failure"
    ZERO_TRADES = "zero_trades"
    INSUFFICIENT_TRADES = "insufficient_trades"
    VALID_CANDIDATE = "valid_candidate"


class AeRoing4RunRequest(BaseModel):
    """Request model for starting an AeRoing4 run."""
    strategy_name: str
    timeframe: str = "5m"
    smoke_timerange: str = "20240101-20240131"
    smoke_pairs: list[str] | None = None

    # Milestone 2A: Pair Discovery fields
    enable_pair_discovery: bool = False
    discovery_pairs: list[str] | None = None
    discovery_timerange: str | None = None

    # Milestone 3: Research Protocol / Data Zone Guard.
    # Optional and additive — omitting both keeps the run fully backward
    # compatible (no boundaries are initialized, Pair Discovery behaves
    # exactly as before). Providing both activates the protocol: the run's
    # `discovery_timerange` (or its default) becomes the DEVELOP zone.
    confirmation_timerange: str | None = None
    final_unseen_timerange: str | None = None

    # Milestone 7.5: Portfolio Baseline execution configuration
    exchange: str = "binance"
    trading_mode: str = "spot"
    max_open_trades: int = 4
    dry_run_wallet: float = 1000.0
    config_file: str = "config.json"

    # PROMPT 8: Controlled Research Loop (strict opt-in).
    enable_research_loop: bool = False


class StepResult(BaseModel):
    """Base result for any step."""
    step_name: str
    status: AeRoing4StepStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    """Result of strict strategy validation."""
    valid: bool
    class_name: str | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    output_summary: str = ""


class DataPreparationResult(BaseModel):
    """Result of smoke data preparation."""
    pairs_ready: dict[str, bool] = Field(default_factory=dict)
    missing_pairs_downloaded: list[str] = Field(default_factory=list)
    download_errors: dict[str, str] = Field(default_factory=dict)
    coverage_check_passed: bool = False


class SmokeBacktestResult(BaseModel):
    """Result of smoke backtest."""
    outcome: SmokeBacktestOutcome
    backtest_run_id: str | None = None
    total_trades: int = 0
    trades_per_pair: dict[str, int] = Field(default_factory=dict)
    net_profit: float | None = None
    profit_factor: float | None = None
    max_drawdown: float | None = None
    execution_error: str | None = None


class PairEvaluationRecord(BaseModel):
    """Per-pair evidence record from discovery.

    Null metrics are never substituted with zero.  The ``metrics_available``
    dict records which metrics were actually present in the backtest output.
    """
    pair: str
    status: PairCandidateStatus
    rejection_reasons: list[str] = Field(default_factory=list)

    # Trade evidence
    total_trades: int = 0
    net_profit_pct: Optional[float] = None
    profit_factor: Optional[float] = None
    expectancy: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    win_rate: Optional[float] = None
    avg_trade_duration: Optional[float] = None

    # Ranking
    rank: Optional[int] = None
    rank_score: Optional[float] = None
    score_components: dict[str, float] = Field(default_factory=dict)

    # Traceability
    backtest_run_id: Optional[str] = None
    explorer_session_id: Optional[str] = None
    metrics_available: dict[str, bool] = Field(default_factory=dict)


class PairDiscoveryResult(BaseModel):
    """Complete result of the pair discovery step."""
    universe_size: int
    usable_pairs_count: int
    evaluated_pairs_count: int
    valid_candidates_count: int
    rejected_pairs_count: int

    ranked_pairs: list[PairEvaluationRecord] = Field(default_factory=list)
    all_evaluations: list[PairEvaluationRecord] = Field(default_factory=list)

    # Reproducibility state
    discovery_pairs_requested: list[str] = Field(default_factory=list)
    discovery_timerange: str = ""
    timeframe: str = ""
    strategy_name: str = ""
    explorer_session_id: Optional[str] = None
    ranking_policy_version: str = ""


class AeRoing4Run(BaseModel):
    """Complete AeRoing4 run state."""
    run_id: str
    strategy_name: str
    timeframe: str = "5m"
    smoke_pairs: list[str] = Field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "BNB/USDT"])
    smoke_timerange: str = "20240101-20240131"
    status: AeRoing4RunStatus = AeRoing4RunStatus.PENDING
    current_step: str = "validation"
    steps: dict[str, StepResult] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    # Milestone 2A: Pair Discovery configuration (persisted for reproducibility)
    enable_pair_discovery: bool = False
    discovery_pairs: list[str] | None = None
    discovery_timerange: str | None = None

    # Milestone 3: Research Protocol / Data Zone Guard (additive; defaults
    # to None/absent for runs created before this milestone existed, so
    # existing round-trip serialization tests are unaffected).
    confirmation_timerange: str | None = None
    final_unseen_timerange: str | None = None
    research_protocol: ResearchProtocolState | None = None

    # Milestone 4: Pair Selection configuration
    pair_selection_mode: str | None = None  # "auto_best_n" or "manual"
    target_pair_count: int = 4
    manually_selected_pairs: list[str] | None = None

    # Milestone 7.5: Portfolio Baseline execution configuration
    exchange: str = "binance"
    trading_mode: str = "spot"
    max_open_trades: int = 4
    dry_run_wallet: float = 1000.0
    config_file: str = "config.json"

    # PROMPT 8: Controlled Research Loop (strict opt-in).
    enable_research_loop: bool = False

    def update_step(self, step_name: str, result: StepResult) -> None:
        """Update a step result and mark as current step."""
        self.steps[step_name] = result
        self.current_step = step_name
        self.updated_at = datetime.now(UTC)

    def mark_running(self) -> None:
        """Mark run as running."""
        self.status = AeRoing4RunStatus.RUNNING
        self.updated_at = datetime.now(UTC)

    def mark_completed(self) -> None:
        """Mark run as completed."""
        self.status = AeRoing4RunStatus.COMPLETED
        self.completed_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)

    def mark_failed(self, error: str) -> None:
        """Mark run as failed."""
        self.status = AeRoing4RunStatus.FAILED
        self.error = error
        self.completed_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)

    def mark_cancelled(self) -> None:
        """Mark run as cancelled."""
        self.status = AeRoing4RunStatus.CANCELLED
        self.completed_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)
