"""Data structures for the Auto-Quant pipeline."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..config import (
    BROAD_UNIVERSE_PAIRS,
    MAX_DRAWDOWN_THRESHOLD,
    MIN_OOS_PROFIT,
    MIN_PROFIT_FACTOR,
    MIN_SHARPE,
    MIN_WIN_RATE,
    MONTE_CARLO_THRESHOLD,
)


@dataclass
class StageState:
    index: int          # 1-based
    name: str
    status: str = "pending"   # pending | running | passed | failed | skipped
    message: str = ""
    data: dict = field(default_factory=dict)
    started_at: str | None = None
    duration_s: float | None = None


@dataclass
class PipelineState:
    run_id: str
    strategy: str
    timeframe: str
    in_sample_range: str
    out_sample_range: str
    exchange: str
    config_file: str
    freqtrade_path: str
    user_data_dir: str
    original_strategy: str | None = None
    original_strategy_hash: str | None = None
    status: str = "pending"   # pending | running | completed | failed | cancelled | interrupted | awaiting_user_approval
    current_stage: int = 0   # 0 = not started, 1-7 = active stage
    stages: list[StageState] = field(default_factory=list)
    report: dict | None = None
    error: str | None = None
    created_at: str = ""
    completed_at: str | None = None
    # Per-run risk thresholds (fall back to module-level defaults if not set)
    max_drawdown_threshold: float = MAX_DRAWDOWN_THRESHOLD  # 0.30 = 30%
    min_win_rate: float = MIN_WIN_RATE  # 0.40 = 40%
    min_profit_factor: float = MIN_PROFIT_FACTOR
    min_sharpe: float = MIN_SHARPE
    monte_carlo_threshold: float = MONTE_CARLO_THRESHOLD
    # Per-run hyperopt settings
    hyperopt_loss: str = "OnlyProfitHyperOptLoss"
    hyperopt_spaces: list = field(default_factory=lambda: ["buy", "stoploss", "roi"])
    hyperopt_epochs: int = 200
    hyperopt_workers: int = 1
    # Per-run OOS profit gate (Stage 4)
    min_oos_profit: float = 0.0
    # Self-healing retry state
    retry_count: int = 0
    max_retries: int = 3
    retry_history: list = field(default_factory=list)
    generalization_failure: dict | None = None
    sensitivity: dict | None = None
    # Walk-Forward Optimization settings
    wfo_enabled: bool = False
    wfo_is_months: int = 3
    wfo_oos_months: int = 1
    wfo_recency_weight: float = 1.0
    planned_wfo_windows: list = field(default_factory=list)  # Planned windows from policy
    wfo_windows: list = field(default_factory=list)  # Executed window results
    wfo_skip_reason: str | None = None
    # Alpha Ensemble Voting
    ensemble_enabled: bool = False
    # Optional single-pair override (set via the Pair Screener; if provided,
    # passed as --pairs <pair> to Stage 1 and Stage 4 backtests)
    pair: str | None = None
    # Dynamic Pair-list Whitelisting
    pair_universe: list = field(default_factory=lambda: BROAD_UNIVERSE_PAIRS)
    winning_pairs: list = field(default_factory=list)  # Legacy: from Stage 5 stress test
    selected_pairs: list = field(default_factory=list)  # New: top pairs from Stage 1 pre-selection
    excluded_time_windows: dict = field(default_factory=dict)
    # Ollama AI Integration
    ai_enabled: bool = True  # Per-run AI toggle
    ai_suggestions: list = field(default_factory=list)  # Advisor-only AI suggestions for review
    pending_ai_suggestion_id: str | None = None
    ai_interactions: list = field(default_factory=list)  # Log all AI interactions
    ai_metrics: dict = field(default_factory=dict)  # Track AI performance metrics
    ollama_available: bool = False  # Cached availability check
    param_overrides: dict = field(default_factory=dict)  # Applied only through retry/patch flow
    # Data Healing Configuration
    data_healing_warmup_candles: int = 200  # Indicator warm-up period in candles
    data_healing_timeout: int = 300  # Subprocess timeout in seconds
    # Phase 1 Self-Healing Attempts
    phase1_heal_attempts: int = 0  # Counter for Stage 1 baseline backtest self-healing retries
    # Phase 3 Stability Scores (Slippage/Fee Stress Testing)
    stability_scores: dict = field(default_factory=dict)  # {pair_name: stability_score}
    # Phase 4 Portfolio Competition
    portfolio_weights: dict = field(default_factory=dict)  # {pair_name: normalized_weight}
    baseline_trade_counts: dict = field(default_factory=dict)  # {pair_name: trade_count_from_stage2}
    max_open_trades: int = 5  # Capital constraint for portfolio competition
    # Robustness-first workflow configuration
    strategy_source: str = "existing"
    trading_style: str = "swing"
    risk_profile: str = "balanced"
    analysis_depth: str = "deep"
    uploaded_strategy_id: str | None = None
    advanced_overrides: dict = field(default_factory=dict)
    auto_discovery_enabled: bool = False
    discovery_results: dict = field(default_factory=dict)
    validation_notes: list = field(default_factory=list)
    run_config_snapshot: dict = field(default_factory=dict)
    policy_versions: dict = field(default_factory=dict)
    selected_timeframe: str | None = None
    selected_pair_universe: list = field(default_factory=list)
    score: dict = field(default_factory=dict)
    validation_status: str = "Candidate"
    readiness_label: str = "Candidate"
    score_explanation: list = field(default_factory=list)
    progress_percent: int = 0
    eta_seconds: int | None = None
    progress_counters: dict = field(default_factory=lambda: {
        "strategies_generated": 0,
        "strategies_tested": 0,
        "strategies_rejected": 0,
        "strategies_surviving": 0,
    })
    strategy_runtime_dir: str | None = None
    strategy_variants: list = field(default_factory=list)
    artifact_versions: dict = field(default_factory=dict)
    # User approval workflow
    user_approved_pairs: list = field(default_factory=list)  # User-selected pairs after approval
    portfolio_baseline_result: dict = field(default_factory=dict)  # Portfolio baseline backtest results
    # Regime Detection
    regime_detection_enabled: bool = True  # Enable/disable regime detection
    current_regime: str = None  # Current market regime
    regime_probabilities: dict = field(default_factory=dict)  # Regime posterior probabilities
    regime_history: list = field(default_factory=list)  # Historical regime classifications
    regime_model_path: str = None  # Path to trained HMM model
    # Genetic Algorithm Evolution
    genetic_evolution_enabled: bool = False  # Enable/disable genetic evolution
    best_dna: dict = field(default_factory=dict)  # Best DNA from evolution
    ga_history: list = field(default_factory=list)  # Evolution history across generations
    ga_generations: int = 20  # Number of GA generations
    ga_population_size: int = 50  # GA population size
    ga_converged: bool = False  # Whether GA converged
    # Reinforcement Learning
    rl_training_enabled: bool = False  # Enable/disable RL training
    rl_deployment_enabled: bool = False  # Enable/disable RL deployment
    rl_algorithm: str = "ppo"  # RL algorithm (ppo, sac, a2c)
    rl_total_timesteps: int = 1000000  # Total RL training timesteps
    rl_model_path: str = None  # Path to trained RL model
    rl_performance: dict = field(default_factory=dict)  # RL performance metrics
    rl_trades: list = field(default_factory=list)  # RL agent trades
    # Validate Existing Strategy workflow. These fields are additive; default
    # AutoQuant runs keep their existing semantics.
    workflow_mode: str = "auto_quant"  # auto_quant | validate_existing
    max_attempts: int = 3  # User-facing full validation attempts
    validation_attempts: list = field(default_factory=list)
    oos_validation_result: dict = field(default_factory=dict)
    final_verdict: str | None = None  # validated_candidate | dry_run_candidate | rejected
    candidate_label: str | None = None  # Validated Candidate | Dry-run Candidate | Rejected
    rejection_report: dict = field(default_factory=dict)
    best_observed_result: dict = field(default_factory=dict)  # Best metrics seen across all attempts


class _Cancelled(Exception):
    """Raised when a pipeline run is cancelled by the user."""
    pass


# ── In-memory state registry ─────────────────────────────────────────────────────

_states: dict[str, PipelineState] = {}
_cancel_flags: dict[str, bool] = {}
_queues: dict[str, list[deque]] = {}
_EVENT_HISTORY_MAX = 500
_event_history: dict[str, deque[dict[str, Any]]] = {}
