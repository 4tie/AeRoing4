"""Core backend model helpers, enums, strategy records, and version records."""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

def _normalize_csv_or_list(value: Any) -> list[str] | None:
    """Normalize user-provided CSV/list values into a clean list of strings."""
    if value is None:
        return None
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, list):
        items = value
    else:
        raise ValueError("Value must be a list or comma-separated string.")
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    return cleaned or None


def _is_valid_timerange(value: str) -> bool:
    """Check whether a timerange string follows allowed `start-end` formats."""
    if "-" not in value:
        return False
    start, end = value.split("-", maxsplit=1)
    for part in (start, end):
        if not part:
            continue
        if not part.isdigit() or len(part) not in {8, 14}:
            return False
    return True


def _is_valid_timeframe(value: str) -> bool:
    """Check whether a timeframe string looks like `5m`, `1h`, or similar."""
    if len(value) < 2:
        return False
    unit = value[-1]
    amount = value[:-1]
    return amount.isdigit() and unit in {"m", "h", "d", "w", "M"}


class StrictModel(BaseModel):
    """Backend data type for `StrictModel`."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True, use_enum_values=True)


class ManagedStatus(str, Enum):
    """Backend data type for `ManagedStatus`."""
    UNMANAGED = "unmanaged"
    MANAGED = "managed"
    EXTERNAL = "external"
    AVAILABLE = "available"


class RunStatus(str, Enum):
    """Backend data type for `RunStatus`."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunPhase(str, Enum):
    """Backend data type for `RunPhase`."""
    QUEUED = "queued"
    INITIALIZING = "initializing"
    DATA_LOADING = "data_loading"
    INDICATOR_CALCULATION = "indicator_calculation"
    BACKTESTING = "backtesting"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunType(str, Enum):
    """Backend data type for `RunType`."""
    BASELINE = "baseline"
    CANDIDATE_PARAMETER = "candidate_parameter"
    CANDIDATE_CODE = "candidate_code"


class VersionChangeType(str, Enum):
    """Backend data type for `VersionChangeType`."""
    PARAMETER = "parameter"
    CODE = "code"
    INITIAL = "initial"
    OPTIMIZATION = "optimization"


class VersionCreationSource(str, Enum):
    """Backend data type for `VersionCreationSource`."""
    AI_PROPOSAL = "ai_proposal"
    MANUAL = "manual"
    BOOTSTRAP = "bootstrap"
    OPTIMIZATION = "optimization"
    OPTIMIZER_TRIAL = "optimizer_trial"


class AcceptanceStatus(str, Enum):
    """Backend data type for `AcceptanceStatus`."""
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ProposalType(str, Enum):
    """Backend data type for `ProposalType`."""
    PARAMETER = "parameter"
    CODE = "code"


class OptimizationLoopMode(str, Enum):
    """Backend data type for `OptimizationLoopMode`."""
    AUTO = "auto"
    OFF = "off"


class ImprovementStyle(str, Enum):
    """Backend data type for `ImprovementStyle`."""
    CONSERVATIVE = "conservative"


class ImprovementSuccessProfile(str, Enum):
    """Backend data type for `ImprovementSuccessProfile`."""
    BALANCED = "balanced"


class OptimizationSessionStatus(str, Enum):
    """Backend data type for `OptimizationSessionStatus`."""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESSFUL = "successful"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OptimizationConfirmationStatus(str, Enum):
    """Backend data type for `OptimizationConfirmationStatus`."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    UNCONFIRMED_SHORT_WINDOW = "unconfirmed_short_window"
    NOT_REQUIRED = "not_required"


class OptimizationCandidateState(str, Enum):
    """Backend data type for `OptimizationCandidateState`."""
    GENERATED = "generated"
    READY = "ready"
    BACKTESTING = "backtesting"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    SKIPPED = "skipped"


class ConfidenceLevel(str, Enum):
    """Backend data type for `ConfidenceLevel`."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PairClassification(str, Enum):
    """Backend data type for `PairClassification`."""
    KEEP = "keep"
    WATCH = "watch"
    EXCLUDE = "exclude"


class MetricLabel(str, Enum):
    """Backend data type for `MetricLabel`."""
    IMPROVED = "improved"
    REGRESSED = "regressed"
    UNCHANGED = "unchanged"
    SUSPICIOUS = "suspicious"


class RunEtaState(str, Enum):
    """Backend data type for `RunEtaState`."""
    ESTIMATING = "estimating"
    AVAILABLE = "available"
    NOT_APPLICABLE = "not_applicable"


class RunProgressUpdateSource(str, Enum):
    """Backend data type for `RunProgressUpdateSource`."""
    LOG_MARKER = "log_marker"
    INTERPOLATION = "interpolation"
    TERMINAL_UPDATE = "terminal_update"


class WeaknessCategory(str, Enum):
    """Backend data type for `WeaknessCategory`."""
    ENTRY_QUALITY = "entry quality"
    EXIT_TIMING = "exit timing"
    STOPLOSS_CONFIGURATION = "stoploss configuration"
    PROFIT_TARGET_REALISM = "profit target realism"
    PAIR_BASKET_QUALITY = "pair basket quality"
    OVERTRADING_AND_FEE_DRAG = "overtrading and fee drag"
    WIN_RATE_VS_EXPECTANCY_MISMATCH = "win rate vs expectancy mismatch"
    DRAWDOWN_VS_RETURN_RATIO = "drawdown vs return ratio"
    SIGNAL_REACTIVITY = "signal reactivity"
    TREND_FILTER_ABSENCE = "trend filter absence"
    MARKET_REGIME_UNAWARENESS = "market regime unawareness"
    PROTECTION_GAPS = "protection gaps"
    PARAMETER_INCONSISTENCY = "parameter inconsistency"
    CANDIDATE_OVERFITTING = "candidate overfitting"


class DiagnosisSeverity(str, Enum):
    """Backend data type for `DiagnosisSeverity`."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DiagnosisEvidenceType(str, Enum):
    """Backend data type for `DiagnosisEvidenceType`."""
    METRIC = "metric"
    DATA = "data"


class DiagnosisEvidenceSource(str, Enum):
    """Backend data type for `DiagnosisEvidenceSource`."""
    PARSED_SUMMARY = "parsed_summary"
    PAIR_RESULTS = "pair_results"
    EXIT_REASONS = "exit_reasons"
    STRATEGY_SOURCE = "strategy_source"


class StrategyParameterDefinition(StrictModel):
    """Backend data type for `StrategyParameterDefinition`."""
    name: str
    parameter_type: str
    space: str | None = None
    default: Any = None
    min_value: float | None = None
    max_value: float | None = None
    choices: list[Any] | None = None
    decimals: int | None = None
    optimizable: bool = True


class StrategyProtectionDefinition(StrictModel):
    """Backend data type for `StrategyProtectionDefinition`."""
    source: str
    detail: str


class StrategyRecord(StrictModel):
    """Backend data type for `StrategyRecord`."""
    strategy_name: str
    strategy_id: str
    class_name: str
    file_path: str
    timeframe: str | None
    parameter_count: int
    protection_count: int
    managed_status: ManagedStatus
    last_modified_timestamp: datetime
    indicator_method_names: list[str]
    parameters: list[StrategyParameterDefinition]
    protections: list[StrategyProtectionDefinition]
    parse_error: str | None = None


class RegistryDiff(StrictModel):
    """Backend data type for `RegistryDiff`."""
    added: list[str]
    removed: list[str]
    modified: list[str]
    parse_errors: list[dict[str, str]]


class ParamsSchema(StrictModel):
    """Backend data type for `ParamsSchema`."""
    strategy_name: str
    version_id: str
    extracted_at: datetime
    pair_list: list[str] | None
    buy_params: dict[str, Any]
    sell_params: dict[str, Any]
    protection_params: dict[str, Any]
    roi_table: dict[str, float]
    stoploss: float
    trailing_stop: bool
    trailing_stop_positive: float | None
    trailing_stop_positive_offset: float | None
    trailing_only_offset_is_reached: bool | None
    custom_params: dict[str, Any]


class QualityGateCheck(StrictModel):
    """Backend data type for `QualityGateCheck`."""
    check_name: str
    status: Literal["pass", "fail"]
    error_detail: str | None = None


class VersionMetadata(StrictModel):
    """Backend data type for `VersionMetadata`."""
    version_id: str
    strategy_name: str
    parent_version_id: str | None
    created_at: datetime
    change_type: VersionChangeType
    creation_source: VersionCreationSource
    proposal_id: str | None
    source_run_id: str | None
    acceptance_status: AcceptanceStatus
    accepted_at: datetime | None
    rejected_at: datetime | None
    result_summary_run_id: str | None
    quality_gate_results: list[QualityGateCheck]


class CurrentAcceptedPointer(StrictModel):
    """Backend data type for `CurrentAcceptedPointer`."""
    strategy_name: str
    accepted_version_id: str
    accepted_at: datetime
    accepted_run_id: str | None
