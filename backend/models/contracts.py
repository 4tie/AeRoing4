"""Backend request/response contracts and runtime path models."""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field, field_validator

from .base import (
    CurrentAcceptedPointer,
    ParamsSchema,
    StrictModel,
    StrategyRecord,
    VersionMetadata,
    _is_valid_timeframe,
    _is_valid_timerange,
    _normalize_csv_or_list,
)
from .results import BacktestAdvancedMetrics, BacktestCharts, BacktestTrade, PairTradeBreakdown
from .runs import PairResult, ParsedSummary, RunMetadata, RunProgress, RunStatus


class SettingsModel(StrictModel):
    """Backend data type for `SettingsModel`.

    Uses extra="ignore" so that existing settings JSON files containing
    legacy keys are loaded without validation errors.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True, use_enum_values=True)

    freqtrade_executable_path: str
    strategies_directory_path: str
    user_data_directory_path: str
    default_config_file_path: str

    ollama_api_url: str = "http://localhost:11434"
    ollama_model: str = ""
    ollama_provider: str = "local"  # "local" | "ollama_cloud"
    ollama_api_key: str = ""
    network_mode: str = "local"
    hyperopt_workers: int = 2
    ollama_self_healing_enabled: bool = False
    ollama_timeout: int = 30

    # Reliability settings
    ollama_retry_delays: list[int] = [2, 5, 10, 15]
    ollama_circuit_breaker_threshold: int = 5
    ollama_circuit_breaker_cooldown: int = 300
    ollama_enable_health_check: bool = True
    ollama_health_check_interval: int = 60
    ollama_timeout_chat: int = 30
    ollama_timeout_generate: int = 60
    ollama_timeout_autoquant: int = 120
    ollama_connection_pool_size: int = 10
    ollama_connection_keepalive: int = 30

    # Workflow-specific model overrides
    ollama_model_chat: str = ""
    ollama_model_autoquant: str = ""
    ollama_model_strategylab: str = ""
    ollama_model_optimizer: str = ""

    # AI Assistant sandbox mode
    ai_assistant_sandbox_enabled: bool = False

    # Ollama generation temperature
    ollama_temperature: float = 0.1

    # Research data zones (document: Development / Confirmation / Final Unseen)
    research_development_start: str = "20240601"
    research_development_end: str = "20250930"
    research_confirmation_start: str = "20251001"
    research_confirmation_end: str = "20251231"
    research_unseen_start: str = "20260101"

    # Research pipeline defaults
    research_max_open_trades: int = 3
    research_pair_universe_size: int = 50
    research_smoke_pairs: list[str] = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"]

    # Discord integration
    discord_enabled: bool = False
    discord_bot_token: str = ""
    discord_server_id: str = ""
    discord_user_id: str = ""
    discord_notification_channel_id: str | None = None


class RunRequest(StrictModel):
    """Backend data type for `RunRequest`."""
    strategy_name: str
    version_id: str | None = None
    config_file: str
    timerange: str
    timeframe: str | None = None
    pairs: list[str] | None = None
    fee_rate: float | None = None
    stake_amount: str | float | None = None
    max_open_trades: int = 1
    dry_run_wallet: float = 1000.0

    @field_validator("strategy_name", mode="before")
    @classmethod
    def validate_strategy_name(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("strategy_name is required.")
        return text

    @field_validator("version_id", mode="before")
    @classmethod
    def validate_version_id(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("config_file", mode="before")
    @classmethod
    def validate_backtest_config_file(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("config_file is required.")
        return text

    @field_validator("timerange", mode="before")
    @classmethod
    def validate_backtest_timerange(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("timerange is required.")
        if not _is_valid_timerange(text):
            raise ValueError(
                "timerange must look like YYYYMMDD-YYYYMMDD, YYYYMMDD-, or -YYYYMMDD."
            )
        return text

    @field_validator("timeframe", mode="before")
    @classmethod
    def validate_backtest_timeframe(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if not _is_valid_timeframe(text):
            raise ValueError("timeframe must look like 5m, 1h, 1d, and so on.")
        return text

    @field_validator("pairs", mode="before")
    @classmethod
    def validate_backtest_pairs(cls, value: Any) -> list[str] | None:
        cleaned = _normalize_csv_or_list(value)
        if cleaned is None:
            return None
        invalid = [item for item in cleaned if "/" not in item]
        if invalid:
            raise ValueError(
                f"Invalid pair values: {', '.join(invalid)}. Use values like BTC/USDT."
            )
        return cleaned

    @field_validator("fee_rate")
    @classmethod
    def validate_fee_rate(cls, value: float) -> float:
        if value < 0:
            raise ValueError("fee_rate must be zero or greater.")
        return value

    @field_validator("stake_amount", mode="before")
    @classmethod
    def validate_stake_amount(cls, value: Any) -> str | float | None:
        if value is None:
            return None
        if isinstance(value, str):
            if value.strip().lower() == "unlimited":
                return "unlimited"
            try:
                numeric = float(value)
            except ValueError:
                raise ValueError("stake_amount must be 'unlimited' or a positive number.")
            if numeric <= 0:
                raise ValueError("stake_amount must be greater than zero.")
            return numeric
        if isinstance(value, (int, float)):
            if value <= 0:
                raise ValueError("stake_amount must be greater than zero.")
            return float(value)
        raise ValueError("stake_amount must be 'unlimited' or a positive number.")

    @field_validator("max_open_trades")
    @classmethod
    def validate_max_open_trades(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_open_trades must be at least 1.")
        return value

    @field_validator("dry_run_wallet")
    @classmethod
    def validate_dry_run_wallet(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("dry_run_wallet must be greater than zero.")
        return value


class DownloadDataRequest(StrictModel):
    """Backend data type for `DownloadDataRequest`."""
    config_file: str
    timerange: str | None = None
    timeframes: list[str] | None = None
    pairs: list[str] | None = None
    prepend: bool = False

    @field_validator("config_file", mode="before")
    @classmethod
    def validate_config_file(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("config_file is required.")
        return text

    @field_validator("timerange", mode="before")
    @classmethod
    def validate_timerange(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if not _is_valid_timerange(text):
            raise ValueError(
                "timerange must look like YYYYMMDD-YYYYMMDD, YYYYMMDD-, or -YYYYMMDD."
            )
        return text

    @field_validator("timeframes", mode="before")
    @classmethod
    def validate_timeframes(cls, value: Any) -> list[str] | None:
        cleaned = _normalize_csv_or_list(value)
        if cleaned is None:
            return None
        invalid = [item for item in cleaned if not _is_valid_timeframe(item)]
        if invalid:
            raise ValueError(
                f"Invalid timeframe values: {', '.join(invalid)}. Use values like 5m, 1h, 1d."
            )
        return cleaned

    @field_validator("pairs", mode="before")
    @classmethod
    def validate_pairs(cls, value: Any) -> list[str] | None:
        cleaned = _normalize_csv_or_list(value)
        if cleaned is None:
            return None
        invalid = [item for item in cleaned if "/" not in item]
        if invalid:
            raise ValueError(
                f"Invalid pair values: {', '.join(invalid)}. Use values like BTC/USDT."
            )
        return cleaned


class VersionBacktestRequest(StrictModel):
    """Backend data type for `VersionBacktestRequest`."""
    config_file: str
    timerange: str
    timeframe: str | None = None
    pairs: list[str] | None = None
    fee_rate: float = 0.001
    max_open_trades: int = 1
    dry_run_wallet: float = 1000.0
    baseline_run_id: str

    @field_validator("config_file", mode="before")
    @classmethod
    def validate_config_file(cls, value: Any) -> str:
        return RunRequest.validate_backtest_config_file(value)

    @field_validator("timerange", mode="before")
    @classmethod
    def validate_timerange(cls, value: Any) -> str:
        return RunRequest.validate_backtest_timerange(value)

    @field_validator("timeframe", mode="before")
    @classmethod
    def validate_timeframe(cls, value: Any) -> str | None:
        return RunRequest.validate_backtest_timeframe(value)

    @field_validator("pairs", mode="before")
    @classmethod
    def validate_pairs(cls, value: Any) -> list[str] | None:
        return RunRequest.validate_backtest_pairs(value)

    @field_validator("fee_rate")
    @classmethod
    def validate_fee_rate(cls, value: float) -> float:
        return RunRequest.validate_fee_rate(value)

    @field_validator("max_open_trades")
    @classmethod
    def validate_max_open_trades(cls, value: int) -> int:
        return RunRequest.validate_max_open_trades(value)

    @field_validator("dry_run_wallet")
    @classmethod
    def validate_dry_run_wallet(cls, value: float) -> float:
        return RunRequest.validate_dry_run_wallet(value)

    @field_validator("baseline_run_id", mode="before")
    @classmethod
    def validate_baseline_run_id(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("baseline_run_id is required.")
        return text


class AcceptVersionRequest(StrictModel):
    """Backend data type for `AcceptVersionRequest`."""
    confirmation_token: str
    output_strategy_name: str | None = None
    strategy_name: str | None = None


class RejectVersionRequest(StrictModel):
    """Backend data type for `RejectVersionRequest`."""
    reason: str | None = None
    strategy_name: str | None = None


class RollbackVersionRequest(StrictModel):
    """Backend data type for `RollbackVersionRequest`."""
    confirmation_token: str
    strategy_name: str | None = None


class SaveSettingsRequest(SettingsModel):
    """Backend data type for `SaveSettingsRequest`."""
    pass


class StrategyDetail(StrictModel):
    """Backend data type for `StrategyDetail`."""
    strategy: StrategyRecord
    versions: list[VersionMetadata]
    current_accepted: CurrentAcceptedPointer | None


class StrategyFiles(StrictModel):
    """Read-only source files for a registered strategy."""
    strategy_name: str
    python_path: str
    python_content: str
    json_exists: bool
    json_path: str | None = None
    json_content: str | None = None


class RunListItem(RunMetadata):
    """Backend data type for `RunListItem`."""
    progress: RunProgress


class RunStatusPayload(StrictModel):
    """Backend data type for `RunStatusPayload`."""
    run_id: str
    run_status: RunStatus
    progress: RunProgress


class RunDetail(StrictModel):
    """Backend data type for `RunDetail`."""
    metadata: RunMetadata
    progress: RunProgress | None = None
    parsed_summary: ParsedSummary | None
    pair_results: list[PairResult]

    trades: list[BacktestTrade] = Field(default_factory=list)
    trades_by_pair: dict[str, PairTradeBreakdown] = Field(default_factory=dict)
    advanced_metrics: BacktestAdvancedMetrics | None = None
    charts: BacktestCharts | None = None

    freqtrade_command: str | None
    artifacts: dict[str, str]


class LocalPaths(StrictModel):
    """Backend data type for `LocalPaths`."""
    root_dir: Path
    settings_file: Path
    app_log_file: Path
    data_downloads_root: Path
    strategies_dir: Path
    versions_root: Path
    backtest_results_root: Path
    default_config_file: Path
    pair_selector_data_dir: Path
    optimizer_root: Path
    sweep_root: Path
    backups_root: Path


class GitLogEntry(StrictModel):
    """Backend data type for `GitLogEntry`."""
    sha: str
    message: str
    timestamp: datetime
    run_id: str | None


class StrategyGitCommitRow(StrictModel):
    """Backend data type for `StrategyGitCommitRow`."""
    sha: str
    message: str
    timestamp: datetime
    run_id: str | None
    source_snippet: str
    net_profit_pct: float | None = None
    total_trades: int | None = None
    win_rate_pct: float | None = None
    max_drawdown_pct: float | None = None
    profit_factor: float | None = None
    status: str | None = None


class StrategyGitHistory(StrictModel):
    """Backend data type for `StrategyGitHistory`."""
    strategy_name: str
    commits: list[StrategyGitCommitRow]
    message: str | None = None


class ComparisonMetric(StrictModel):
    """A single metric compared between two backtest runs."""
    metric_name: str
    baseline_value: float | None
    candidate_value: float | None
    absolute_delta: float | None
    relative_delta: float | None
    threshold_value: float
    favorable_direction: str
    label: str


class PairComparison(StrictModel):
    """Per-pair profit comparison between two runs."""
    pair: str
    baseline_net_profit: float | None
    candidate_net_profit: float | None
    label: str


class ComparisonResult(StrictModel):
    """Full comparison result between a baseline and a candidate run."""
    baseline_run_id: str
    candidate_run_id: str
    candidate_run_type: str | None = None
    metrics: list[ComparisonMetric]
    pair_differences: list[PairComparison]
    suspicious_reasons: list[str]
    thresholds: dict[str, float]
    pair_list_changes: dict[str, list[str]]


# Chart data models for mplfinance integration


class CandlestickData(StrictModel):
    """OHLC candlestick data for professional charting."""
    timestamps: list[str]
    open: list[float]
    high: list[float]
    low: list[float]
    close: list[float]
    volume: list[float]


class IndicatorData(StrictModel):
    """Technical indicator data."""
    sma: dict[str, list[float]] = Field(default_factory=dict)
    ema: dict[str, list[float]] = Field(default_factory=dict)
    rsi: list[float] = Field(default_factory=list)
    macd: dict[str, list[float]] = Field(default_factory=dict)
    bollinger: dict[str, list[float]] = Field(default_factory=dict)


class ChartDataResponse(StrictModel):
    """Complete chart data response including candlestick and indicators."""
    candlestick: CandlestickData
    indicators: IndicatorData


class ChartRequest(StrictModel):
    """Request parameters for chart data generation."""
    include_sma: bool = True
    include_ema: bool = True
    include_rsi: bool = True
    include_macd: bool = True
    include_bollinger: bool = True
