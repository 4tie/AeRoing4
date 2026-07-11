"""Tests for diagnosis models."""

import pytest
from backend.services.aeroing4.diagnosis.models import (
    DiagnosisCategory,
    DiagnosisCode,
    DiagnosisFinding,
    DiagnosisInput,
    DiagnosisOutcome,
    DiagnosisResult,
    EvidenceQuality,
    Severity,
)


def test_diagnosis_code_enum():
    """Test DiagnosisCode enum has all expected codes."""
    # Sample Quality
    assert DiagnosisCode.INSUFFICIENT_SAMPLE
    assert DiagnosisCode.UNBALANCED_PAIR_SAMPLE

    # Edge Quality
    assert DiagnosisCode.NEGATIVE_EXPECTANCY
    assert DiagnosisCode.WEAK_EDGE
    assert DiagnosisCode.LOW_PROFIT_FACTOR
    assert DiagnosisCode.NO_EDGE

    # Risk Quality
    assert DiagnosisCode.EXCESSIVE_DRAWDOWN
    assert DiagnosisCode.POOR_RETURN_TO_DRAWDOWN
    assert DiagnosisCode.DOWNSIDE_RISK_DOMINANCE

    # Pair Structure
    assert DiagnosisCode.PAIR_CONCENTRATION
    assert DiagnosisCode.SINGLE_PAIR_DEPENDENCE
    assert DiagnosisCode.MULTIPLE_NEGATIVE_CONTRIBUTORS

    # Exit Behavior
    assert DiagnosisCode.STOPLOSS_DOMINANCE
    assert DiagnosisCode.EXIT_LOSS_CONCENTRATION

    # Entry Behavior
    assert DiagnosisCode.ENTRY_TOO_RESTRICTIVE

    # Parameter Research
    assert DiagnosisCode.PARAMETER_RESEARCH_NEEDED
    assert DiagnosisCode.EXIT_PARAMETER_RESEARCH_NEEDED
    assert DiagnosisCode.RISK_PARAMETER_RESEARCH_NEEDED
    assert DiagnosisCode.ENTRY_PARAMETER_RESEARCH_NEEDED


def test_diagnosis_finding_validation():
    """Test DiagnosisFinding validation."""
    finding = DiagnosisFinding(
        diagnosis_code=DiagnosisCode.INSUFFICIENT_SAMPLE,
        category=DiagnosisCategory.SAMPLE_QUALITY,
        severity=Severity.HIGH,
        confidence=0.85,
        evidence_refs=["total_trades"],
        evidence_values={"total_trades": 10},
        explanation="Test explanation",
        suggested_research_area="sample_quality",
        limitations=["Test limitation"],
    )

    assert finding.diagnosis_code == DiagnosisCode.INSUFFICIENT_SAMPLE
    assert finding.category == DiagnosisCategory.SAMPLE_QUALITY
    assert finding.severity == Severity.HIGH
    assert finding.confidence == 0.85
    assert 0.0 <= finding.confidence <= 1.0


def test_diagnosis_finding_confidence_bounds():
    """Test DiagnosisFinding confidence bounds."""
    with pytest.raises(ValueError):
        DiagnosisFinding(
            diagnosis_code=DiagnosisCode.INSUFFICIENT_SAMPLE,
            category=DiagnosisCategory.SAMPLE_QUALITY,
            severity=Severity.HIGH,
            confidence=1.5,  # Invalid: > 1.0
            evidence_refs=[],
            evidence_values={},
            explanation="Test",
            suggested_research_area="test",
        )

    with pytest.raises(ValueError):
        DiagnosisFinding(
            diagnosis_code=DiagnosisCode.INSUFFICIENT_SAMPLE,
            category=DiagnosisCategory.SAMPLE_QUALITY,
            severity=Severity.HIGH,
            confidence=-0.1,  # Invalid: < 0.0
            evidence_refs=[],
            evidence_values={},
            explanation="Test",
            suggested_research_area="test",
        )


def test_diagnosis_result_validation():
    """Test DiagnosisResult validation."""
    result = DiagnosisResult(
        run_id="test-run",
        champion_id="test-champion",
        diagnosis_id="test-diagnosis",
        outcome=DiagnosisOutcome.DIAGNOSIS_COMPLETE,
        primary_diagnosis=None,
        secondary_findings=[],
        informational_findings=[],
        evidence_quality=EvidenceQuality.HIGH,
        unavailable_evidence=[],
        evaluated_rules=[],
        skipped_rules=[],
        skipped_reasons={},
    )

    assert result.run_id == "test-run"
    assert result.champion_id == "test-champion"
    assert result.outcome == DiagnosisOutcome.DIAGNOSIS_COMPLETE
    assert result.evidence_quality == EvidenceQuality.HIGH


def test_evidence_quality_enum():
    """Test EvidenceQuality enum."""
    assert EvidenceQuality.HIGH
    assert EvidenceQuality.MEDIUM
    assert EvidenceQuality.LOW
    assert EvidenceQuality.INSUFFICIENT


def test_severity_enum():
    """Test Severity enum."""
    assert Severity.INFO
    assert Severity.LOW
    assert Severity.MEDIUM
    assert Severity.HIGH
    assert Severity.CRITICAL


def test_diagnosis_category_enum():
    """Test DiagnosisCategory enum."""
    assert DiagnosisCategory.SAMPLE_QUALITY
    assert DiagnosisCategory.EDGE_QUALITY
    assert DiagnosisCategory.RISK_QUALITY
    assert DiagnosisCategory.PAIR_STRUCTURE
    assert DiagnosisCategory.EXIT_BEHAVIOR
    assert DiagnosisCategory.ENTRY_BEHAVIOR
    assert DiagnosisCategory.PARAMETER_RESEARCH


def test_diagnosis_outcome_enum():
    """Test DiagnosisOutcome enum."""
    assert DiagnosisOutcome.DIAGNOSIS_COMPLETE
    assert DiagnosisOutcome.INSUFFICIENT_EVIDENCE
    assert DiagnosisOutcome.NO_ACTIONABLE_FINDING
    assert DiagnosisOutcome.INTEGRITY_ERROR
    assert DiagnosisOutcome.SYSTEM_FAILURE
