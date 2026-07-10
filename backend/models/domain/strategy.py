from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional, Literal

class StrategyMetrics(BaseModel):
    """Performance metrics for a strategy"""
    profit_factor: float = 0
    drawdown: float = 0
    expectancy: float = 0
    trades: int = 0
    win_rate: float = 0
    sharpe_ratio: float = 0
    sortino_ratio: float = 0
    calmar_ratio: float = 0
    monthly_returns: List[float] = []
    monthly_win_rate: List[float] = []
    max_consecutive_losses: int = 0
    pair_consistency: float = 0
    oos_stability: float = 0
    walk_forward_score: float = 0
    robustness_score: float = 0


class Strategy(BaseModel):
    """A trading strategy with metrics and status"""
    id: str
    name: str
    code: str
    timeframe: str = "4h"
    pairs: List[str] = []
    status: Literal["draft", "candidate", "promising", "validated", "elite"] = "draft"
    metrics: StrategyMetrics = StrategyMetrics()
    tier: Literal["candidate", "promising", "validated", "elite"] = "candidate"
    score: float = 0
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()


class ValidationResult(BaseModel):
    """Result of a validation stage"""
    stage: str
    passed: bool
    errors: List[str] = []
    warnings: List[str] = []
    metrics: StrategyMetrics = StrategyMetrics()
    timestamp: datetime = datetime.now()


class EliteScore(BaseModel):
    """Weighted score for elite strategies (0-100)"""
    strategy_id: str
    overall: float = 0  # 0-100
    expectancy: float = 0
    profit_factor: float = 0
    drawdown: float = 0
    walk_forward: float = 0
    robustness: float = 0
    pair_consistency: float = 0
    trade_quality: float = 0
    timestamp: datetime = datetime.now()


class PipelineRun(BaseModel):
    """State of an AutoQuant pipeline execution"""
    run_id: str
    strategy_id: str
    strategy_name: str
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    current_stage: str = "discovery"
    progress: int = 0
    candidates: List[Strategy] = []
    promising: List[Strategy] = []
    validated: List[Strategy] = []
    elite: List[Strategy] = []
    errors: List[str] = []
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    elapsed_seconds: int = 0
    eta_seconds: int = 0

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def promising_count(self) -> int:
        return len(self.promising)

    @property
    def validated_count(self) -> int:
        return len(self.validated)

    @property
    def elite_count(self) -> int:
        return len(self.elite)

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    @property
    def is_completed(self) -> bool:
        return self.status == "completed"

    @property
    def has_failed(self) -> bool:
        return self.status == "failed"
