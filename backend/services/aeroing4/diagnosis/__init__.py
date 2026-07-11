"""Deterministic Diagnosis Engine for AeRoing4.

This package provides a deterministic diagnosis engine that analyzes the Initial
Champion using measured evidence to identify weaknesses without using AI or
executing new backtests.

Diagnosis Policy Version: 1.0.0
"""

from .engine import DiagnosisEngine
from .models import (
    DIAGNOSIS_POLICY_VERSION,
    DiagnosisCategory,
    DiagnosisCode,
    DiagnosisFinding,
    DiagnosisInput,
    DiagnosisOutcome,
    DiagnosisResult,
    Severity,
)
from .persistence import DiagnosisStore
from .registry import RuleRegistry

__all__ = [
    "DiagnosisEngine",
    "DiagnosisCategory",
    "DiagnosisCode",
    "DiagnosisFinding",
    "DiagnosisInput",
    "DiagnosisOutcome",
    "DiagnosisResult",
    "Severity",
    "DiagnosisStore",
    "RuleRegistry",
    "DIAGNOSIS_POLICY_VERSION",
]
