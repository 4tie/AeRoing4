"""Data models for the candidate evaluation workflow."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from typing import Any

from pydantic import BaseModel, Field


CANDIDATE_GATE_NAMES: tuple[str, ...] = (
    "render_strategy",
    "save_working_copy",
    "data_quality",
    "data_download",
    "backtest_gate",
    "failure_analyzer",
    "repair_plan",
    "repair_attempts",
    "individual_pair_sweep",
    "portfolio_backtest",
    "final_pair_decision",
)


class CandidateRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


CandidateGateStatus = Literal["pending", "running", "passed", "failed", "skipped"]


class CandidateConfig(BaseModel):
    timerange: str
    timeframe: str
    pairs: list[str]
    user_data_dir: str
    config_file: str = "config.json"
    exchange: str = "binance"
    max_repair_iterations: int = 3
    auto_download_data: bool = True
    max_data_download_attempts: int = 1
    risk_profile: str = "balanced"


class CandidateGateResult(BaseModel):
    gate_name: str
    passed: bool
    details: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None


class CandidateGateProgress(BaseModel):
    run_id: str
    gate_name: str
    status: CandidateGateStatus = "pending"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)


class RepairAttempt(BaseModel):
    iteration: int
    scope: str | None = None
    change_applied: dict[str, Any] | None = None
    outcome: str = "unknown"


class CandidateVerdict(BaseModel):
    passed: bool
    gate_results: list[CandidateGateResult] = Field(default_factory=list)
    repair_attempts: list[RepairAttempt] = Field(default_factory=list)
    final_pair_set: list[str] = Field(default_factory=list)
    portfolio_metrics: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None


class CandidateRunState(BaseModel):
    run_id: str
    status: CandidateRunStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    current_gate: str | None = None
    gates: list[CandidateGateProgress] = Field(default_factory=list)
    verdict: CandidateVerdict | None = None
    error: str | None = None
