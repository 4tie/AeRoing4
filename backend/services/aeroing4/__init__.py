"""AeRoing4 - Clean orchestration layer for strategy validation and testing.

This package provides a minimal workflow for proving the core engine:
Strategy Selection → Strict Validation → Data Preparation → Smoke Backtest
→ (Milestone 2A) Pair Discovery → Ranked Candidate List
"""

from .models import (
    AeRoing4Run,
    AeRoing4RunStatus,
    AeRoing4StepStatus,
    StepResult,
    ValidationResult,
    DataPreparationResult,
    SmokeBacktestResult,
    SmokeBacktestOutcome,
    AeRoing4RunRequest,
    PairCandidateStatus,
    PairEvaluationRecord,
    PairDiscoveryResult,
)
from .state_store import AeRoing4StateStore

# Note: AeRoing4Orchestrator is not imported at package level to avoid circular imports
# Import it directly from backend.services.aeroing4.orchestrator when needed

__all__ = [
    "AeRoing4Run",
    "AeRoing4RunStatus",
    "AeRoing4StepStatus",
    "StepResult",
    "ValidationResult",
    "DataPreparationResult",
    "SmokeBacktestResult",
    "SmokeBacktestOutcome",
    "AeRoing4RunRequest",
    "PairCandidateStatus",
    "PairEvaluationRecord",
    "PairDiscoveryResult",
    "AeRoing4StateStore",
]
