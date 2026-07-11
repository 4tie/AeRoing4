"""Diagnosis data models for AeRoing4.

Defines the typed input, output, and finding models for the deterministic
diagnosis engine.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..portfolio_baseline.models import PortfolioBaselineResult
from ..research.champions import ChampionReference

# Policy version (defined here to avoid circular import)
DIAGNOSIS_POLICY_VERSION = "1.0.0"


# ── Enums ──────────────────────────────────────────────────────────────────────


class Severity(str, Enum):
    """Severity levels for diagnosis findings."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DiagnosisCategory(str, Enum):
    """Categories of diagnosis findings."""
    SAMPLE_QUALITY = "sample_quality"
    EDGE_QUALITY = "edge_quality"
    RISK_QUALITY = "risk_quality"
    PAIR_STRUCTURE = "pair_structure"
    EXIT_BEHAVIOR = "exit_behavior"
    ENTRY_BEHAVIOR = "entry_behavior"
    PARAMETER_RESEARCH = "parameter_research"


class DiagnosisOutcome(str, Enum):
    """Overall diagnosis outcome."""
    DIAGNOSIS_COMPLETE = "diagnosis_complete"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NO_ACTIONABLE_FINDING = "no_actionable_finding"
    INTEGRITY_ERROR = "integrity_error"
    SYSTEM_FAILURE = "system_failure"


class EvidenceQuality(str, Enum):
    """Quality classification for evidence."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


# ── Diagnosis Codes ───────────────────────────────────────────────────────────────


class DiagnosisCode(str, Enum):
    """All diagnosis codes supported by the engine."""

    # Sample Quality
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    UNBALANCED_PAIR_SAMPLE = "UNBALANCED_PAIR_SAMPLE"

    # Edge Quality
    NEGATIVE_EXPECTANCY = "NEGATIVE_EXPECTANCY"
    WEAK_EDGE = "WEAK_EDGE"
    LOW_PROFIT_FACTOR = "LOW_PROFIT_FACTOR"
    NO_EDGE = "NO_EDGE"

    # Risk Quality
    EXCESSIVE_DRAWDOWN = "EXCESSIVE_DRAWDOWN"
    POOR_RETURN_TO_DRAWDOWN = "POOR_RETURN_TO_DRAWDOWN"
    DOWNSIDE_RISK_DOMINANCE = "DOWNSIDE_RISK_DOMINANCE"

    # Pair Structure
    PAIR_CONCENTRATION = "PAIR_CONCENTRATION"
    SINGLE_PAIR_DEPENDENCE = "SINGLE_PAIR_DEPENDENCE"
    MULTIPLE_NEGATIVE_CONTRIBUTORS = "MULTIPLE_NEGATIVE_CONTRIBUTORS"

    # Exit Behavior
    STOPLOSS_DOMINANCE = "STOPLOSS_DOMINANCE"
    EXIT_LOSS_CONCENTRATION = "EXIT_LOSS_CONCENTRATION"

    # Entry Behavior
    ENTRY_TOO_RESTRICTIVE = "ENTRY_TOO_RESTRICTIVE"

    # Parameter Research (derived/routing only)
    PARAMETER_RESEARCH_NEEDED = "PARAMETER_RESEARCH_NEEDED"
    EXIT_PARAMETER_RESEARCH_NEEDED = "EXIT_PARAMETER_RESEARCH_NEEDED"
    RISK_PARAMETER_RESEARCH_NEEDED = "RISK_PARAMETER_RESEARCH_NEEDED"
    ENTRY_PARAMETER_RESEARCH_NEEDED = "ENTRY_PARAMETER_RESEARCH_NEEDED"


# ── Models ───────────────────────────────────────────────────────────────────────


class DiagnosisInput(BaseModel):
    """Typed input for diagnosis evaluation.

    Contains all evidence references required for deterministic diagnosis.
    """

    # Run and champion identification
    run_id: str
    champion_id: str
    champion_strategy_hash: str
    champion_parameter_hash: str

    # Portfolio baseline evidence
    baseline_result_id: str
    baseline_result: PortfolioBaselineResult

    # Pair discovery evidence (optional, for context)
    pair_discovery_result_id: str | None = None
    pair_discovery_valid_candidates_count: int | None = None

    # Timeframe information
    timeframe: str
    develop_timerange: str

    # Champion reference (for integrity verification)
    champion_reference: ChampionReference | None = None


class DiagnosisFinding(BaseModel):
    """Individual diagnosis finding.

    Every finding contains the evidence that supports it and the confidence
    in that conclusion.
    """

    diagnosis_code: DiagnosisCode
    category: DiagnosisCategory
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)

    # Evidence references
    evidence_refs: list[str] = Field(default_factory=list)
    evidence_values: dict[str, Any] = Field(default_factory=dict)

    # Explanation and research guidance
    explanation: str
    suggested_research_area: str
    limitations: list[str] = Field(default_factory=list)

    # Rule metadata
    rule_version: str = "1.0.0"


class DiagnosisResult(BaseModel):
    """Complete diagnosis result.

    Contains all findings, evidence quality assessment, and metadata.
    Persisted to diagnoses.json for future reference.
    """

    # Identification
    run_id: str
    champion_id: str
    diagnosis_id: str
    diagnosis_policy_version: str = DIAGNOSIS_POLICY_VERSION

    # Outcome
    outcome: DiagnosisOutcome

    # Findings
    primary_diagnosis: DiagnosisFinding | None = None
    secondary_findings: list[DiagnosisFinding] = Field(default_factory=list)
    informational_findings: list[DiagnosisFinding] = Field(default_factory=list)

    # Evidence assessment
    evidence_quality: EvidenceQuality
    unavailable_evidence: list[str] = Field(default_factory=list)

    # Rule evaluation
    evaluated_rules: list[str] = Field(default_factory=list)
    skipped_rules: list[str] = Field(default_factory=list)
    skipped_reasons: dict[str, str] = Field(default_factory=dict)

    # Identity and idempotency
    input_hash: str = ""

    # Timing
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_seconds: float = 0.0

    # Error information (if system failure)
    error_message: str | None = None
