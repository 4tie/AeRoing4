"""Request/response schemas for Auto-Quant router."""

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Any


class StartAutoQuantRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    strategy: str | None = Field(None, description="Strategy name (without .py extension)")
    timeframe: str | None = Field(None, description="Candle timeframe, e.g. '5m', '1h'")
    in_sample_range: str | None = Field(None, description="In-sample timerange, e.g. '20230101-20240101'")
    out_sample_range: str | None = Field(None, description="Out-of-sample timerange, e.g. '20240101-20240601'")
    exchange: str = Field("binance", description="Exchange name")
    config_file: str | None = Field(None, description="Path to config.json (optional, uses default)")
    max_drawdown_threshold: float = Field(30.0, description="Max allowed drawdown % (Stage 4 & 6)")
    min_win_rate: float = Field(40.0, description="Min required win rate % (Stage 6)")
    min_profit_factor: float = Field(1.0, description="Min required profit factor (Stage 6)")
    min_sharpe: float = Field(0.5, description="Min required Sharpe ratio (Stage 6)")
    min_oos_profit: float = Field(0.0, description="Min required OOS total profit fraction (Stage 4)")
    monte_carlo_threshold: float = Field(0.35, description="Max allowed Monte Carlo p95 drawdown (fraction, Stage 6)")
    hyperopt_loss: str = Field("ProfitLockinHyperOptLoss", description="Hyperopt loss function")
    hyperopt_spaces: list[str] = Field(default_factory=lambda: ["stoploss", "roi"], description="Hyperopt search spaces")
    hyperopt_epochs: int = Field(100, description="Number of hyperopt epochs")
    # Walk-Forward Optimization
    wfo_enabled: bool = Field(False, description="Enable Walk-Forward Optimization")
    wfo_is_months: int = Field(3, description="IS window size in months")
    wfo_oos_months: int = Field(1, description="OOS window size in months")
    wfo_recency_weight: float = Field(1.0, description="Recency weight multiplier (>1 favours recent windows)")
    # Alpha Ensemble Voting
    ensemble_enabled: bool = Field(False, description="Enable Alpha Consensus Voting (ensemble strategy)")
    # Optional single-pair override selected from the Pair Screener
    pair: str | None = Field(None, description="Target pair override (e.g. 'BTC/USDT'); passed as --pairs to Stage 1 & 4 backtests")
    # Dynamic Pair-list Whitelisting
    pair_universe: list[str] | None = Field(None, min_length=1, description="Custom pair universe for multi-pair backtesting (default: Top 50 by volume)")
    # Robustness-first workflow fields
    strategy_source: str | None = Field(None, description="Source mode: existing, uploaded, generated, or template")
    trading_style: str | None = Field(None, description="Trading style: scalping, intraday, swing, position")
    risk_profile: str | None = Field(None, description="Risk profile: conservative, balanced, aggressive")
    analysis_depth: str | None = Field(None, description="Analysis depth: quick, standard, deep")
    uploaded_strategy_id: str | None = Field(None, description="Uploaded/generated strategy identifier")
    generated_by: str | None = Field(None, description="AI provider that generated the strategy (e.g., 'hermes')")
    advanced_overrides: dict[str, Any] | None = Field(default_factory=dict, description="Advanced compatibility overrides")
    workflow_mode: str = Field("auto_quant", description="Workflow mode: auto_quant or validate_existing")
    max_attempts: int = Field(3, ge=1, le=10, description="User-facing full validation attempts for validate_existing mode")

    @field_validator("in_sample_range", "out_sample_range")
    @classmethod
    def _validate_timerange(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parts = value.split("-", 1)
        if len(parts) != 2 or any(len(part) != 8 for part in parts):
            raise ValueError("timerange must use YYYYMMDD-YYYYMMDD format")
        try:
            from datetime import datetime
            start = datetime.strptime(parts[0], "%Y%m%d")
            end = datetime.strptime(parts[1], "%Y%m%d")
        except ValueError as exc:
            raise ValueError("timerange must use valid YYYYMMDD dates") from exc
        if end <= start:
            raise ValueError("timerange end must be after start")
        return value

    @field_validator("hyperopt_epochs")
    @classmethod
    def _validate_hyperopt_epochs(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("hyperopt_epochs must be greater than zero")
        return value

    @field_validator("wfo_enabled", "ensemble_enabled", mode="before")
    @classmethod
    def _validate_bool(cls, value: Any) -> Any:
        if not isinstance(value, bool):
            raise ValueError("value must be a boolean")
        return value


class StartAutoQuantResponse(BaseModel):
    run_id: str
    status: str
    message: str


class ResumePipelineRequest(BaseModel):
    approved_pairs: list[str] = Field(..., description="List of approved pair names")


class AISuggestionDecisionResponse(BaseModel):
    run_id: str
    status: str
    suggestion: dict[str, Any]
    message: str


class ExplainStageRequest(BaseModel):
    stage_index: int | None = Field(None, description="Stage index to explain")
    stage_name: str | None = Field(None, description="Stage name to explain")


class ExplainFailureRequest(BaseModel):
    failure_context: dict[str, Any] | None = Field(default_factory=dict)


class GenerateTemplateRequest(BaseModel):
    strategy_name: str = Field("CatFactory", description="Class name for the generated strategy")
    adaptive: bool = Field(False, description="Generate adaptive regime-switching template")
    ensemble: bool = Field(False, description="Generate Alpha Consensus Voting (ensemble) template")
    momentum: bool = Field(False, description="Generate Momentum / EMA Crossover + ATR filter template")
    omni: bool = Field(False, description="Generate Omni-Strategy with Boolean indicator switches")
    timeframe: str = Field("5m", description="Target timeframe — used by Omni template to calibrate ROI/stoploss defaults")


class GenerateTemplateResponse(BaseModel):
    strategy_name: str
    file_path: str


class ScreenPairsRequest(BaseModel):
    strategy: str = Field(..., description="Strategy name (without .py extension)")
    timeframe: str = Field("5m", description="Candle timeframe, e.g. '5m', '1h'")
    date_range: str = Field(..., description="Timerange to backtest, e.g. '20230101-20240101'")
    pairs: list[str] = Field(..., min_length=1, description="List of pairs to screen")
    exchange: str = Field("binance", description="Exchange name")
    config_file: str | None = Field(None, description="Path to config.json (optional)")


class GenerateStrategySpecRequest(BaseModel):
    """Request model for generating a StrategySpec via Hermes AI."""
    trading_style: str = Field(..., description="Trading style: scalping, intraday, swing, position")
    direction: str = Field(..., description="Direction: long, short, both")
    risk_profile: str = Field(..., description="Risk profile: conservative, balanced, aggressive")
    timeframe_preference: str = Field(..., description="Preferred timeframe, e.g. '5m', '1h'")
    user_notes: str | None = Field(None, description="Optional user notes for the AI")


class GenerateStrategySpecResponse(BaseModel):
    """Response model for generating a StrategySpec via Hermes AI."""
    spec: dict[str, Any] | None = Field(None, description="Generated StrategySpec JSON")
    errors: list[str] = Field(default_factory=list, description="Validation errors if any")
    raw_response: str = Field("", description="Raw AI response for debugging")


class AutoQuantOptions(BaseModel):
    """Model for Auto-Quant form options persistence."""
    model_config = ConfigDict(extra="ignore")

    strategy: str = Field("", description="Strategy name")
    strategy_source: str = Field("existing", description="Strategy source mode")
    trading_style: str = Field("swing", description="Trading style")
    risk_profile: str = Field("balanced", description="Risk profile")
    analysis_depth: str = Field("deep", description="Analysis depth")
    uploaded_strategy_id: str | None = Field(None, description="Uploaded strategy id")
    advanced_overrides: dict[str, Any] = Field(default_factory=dict, description="Advanced overrides")
    workflow_mode: str = Field("auto_quant", description="Workflow mode")
    max_attempts: int = Field(3, description="User-facing full validation attempts for validate_existing mode")
    timeframe: str = Field("5m", description="Candle timeframe")
    in_sample_range: str = Field("20230101-20240101", description="In-sample timerange")
    out_sample_range: str = Field("20240101-20241201", description="Out-of-sample timerange")
    exchange: str = Field("binance", description="Exchange name")
    pair: str = Field("", description="Target pair override")
    pair_universe: str = Field("", description="Custom pair list for multi-pair backtesting")
    max_drawdown_threshold: float = Field(30, description="Max allowed drawdown %")
    min_win_rate: float = Field(40, description="Min required win rate %")
    min_profit_factor: float = Field(1.0, description="Min required profit factor")
    min_sharpe: float = Field(0.5, description="Min required Sharpe ratio")
    min_oos_profit: float = Field(0.0, description="Min required OOS total profit fraction")
    monte_carlo_threshold: float = Field(0.35, description="Max allowed Monte Carlo p95 drawdown")
    hyperopt_loss: str = Field("ProfitLockinHyperOptLoss", description="Hyperopt loss function")
    hyperopt_spaces: list[str] = Field(default_factory=lambda: ["buy", "stoploss", "roi"], description="Hyperopt search spaces")
    hyperopt_epochs: int = Field(100, description="Number of hyperopt epochs")
    wfo_enabled: bool = Field(False, description="Enable Walk-Forward Optimization")
    wfo_is_months: int = Field(3, description="IS window size in months")
    wfo_oos_months: int = Field(1, description="OOS window size in months")
    wfo_recency_weight: float = Field(1.0, description="Recency weight multiplier")
    ensemble_enabled: bool = Field(False, description="Enable Alpha Consensus Voting")
