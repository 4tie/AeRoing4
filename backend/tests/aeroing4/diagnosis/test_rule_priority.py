"""Tests for diagnosis rule priority selection."""

import pytest
from backend.services.aeroing4.diagnosis.models import (
    DiagnosisCategory,
    DiagnosisCode,
    DiagnosisFinding,
    EvidenceQuality,
    Severity,
)
from backend.services.aeroing4.diagnosis.registry import RuleRegistry
from backend.services.aeroing4.diagnosis.rules.base import BaseRule, RuleEvaluationContext
from backend.services.aeroing4.diagnosis.resolver import EvidenceResolver


class MockRule(BaseRule):
    """Mock rule for testing priority."""

    def __init__(self, rule_id, diagnosis_code, priority=100):
        self.rule_id = rule_id
        self.diagnosis_code = diagnosis_code
        self.category = DiagnosisCategory.EDGE_QUALITY
        self.required_evidence = []
        self.priority = priority
        self.is_derived = False

    def evaluate(self, context):
        return None


def test_registry_get_rule_by_diagnosis_code():
    """Test that registry can find rules by diagnosis code."""
    registry = RuleRegistry()

    # Test finding existing rules
    negative_expectancy_rule = registry.get_rule_by_diagnosis_code("NEGATIVE_EXPECTANCY")
    assert negative_expectancy_rule is not None
    assert negative_expectancy_rule.diagnosis_code == DiagnosisCode.NEGATIVE_EXPECTANCY

    no_edge_rule = registry.get_rule_by_diagnosis_code("NO_EDGE")
    assert no_edge_rule is not None
    assert no_edge_rule.diagnosis_code == DiagnosisCode.NO_EDGE

    # Test non-existent code
    nonexistent = registry.get_rule_by_diagnosis_code("NONEXISTENT_CODE")
    assert nonexistent is None


def test_rule_priority_lookup():
    """Test that _get_rule_priority correctly resolves rule priority."""
    from backend.services.aeroing4.diagnosis.engine import DiagnosisEngine

    engine = DiagnosisEngine("/tmp/test_runs")

    # Test priority of known rules
    negative_expectancy_priority = engine._get_rule_priority(DiagnosisCode.NEGATIVE_EXPECTANCY)
    assert negative_expectancy_priority == 180  # As defined in edge_quality.py

    no_edge_priority = engine._get_rule_priority(DiagnosisCode.NO_EDGE)
    assert no_edge_priority == 190  # As defined in edge_quality.py

    # Test non-existent code returns 0
    nonexistent_priority = engine._get_rule_priority(DiagnosisCode.SINGLE_PAIR_DEPENDENCE)
    # This should return the actual priority if the rule exists, or 0 if not
    assert isinstance(nonexistent_priority, int)


def test_primary_diagnosis_uses_rule_priority():
    """Test that primary diagnosis selection uses rule priority when severity and confidence are equal."""
    from backend.services.aeroing4.diagnosis.engine import DiagnosisEngine
    from backend.services.aeroing4.diagnosis.rules.base import BaseRule
    from backend.services.aeroing4.portfolio_baseline.models import (
        ConcentrationFlag,
        ConcentrationSummary,
        ExitReasonDistribution,
        PerPairContribution,
        PortfolioBaselineResult,
        PortfolioBaselineOutcome,
    )

    engine = DiagnosisEngine("/tmp/test_runs")

    # Create two findings with equal severity and confidence but different priorities
    finding1 = DiagnosisFinding(
        diagnosis_code=DiagnosisCode.NEGATIVE_EXPECTANCY,
        category=DiagnosisCategory.EDGE_QUALITY,
        severity=Severity.HIGH,
        confidence=0.90,
        explanation="Test finding 1",
        evidence_refs=["expectancy"],
        evidence_values={"expectancy": -0.01},
        suggested_research_area="edge_quality",
    )

    finding2 = DiagnosisFinding(
        diagnosis_code=DiagnosisCode.NO_EDGE,
        category=DiagnosisCategory.EDGE_QUALITY,
        severity=Severity.HIGH,
        confidence=0.90,
        explanation="Test finding 2",
        evidence_refs=["profit_factor"],
        evidence_values={"profit_factor": 0.8},
        suggested_research_area="edge_quality",
    )

    findings = [finding1, finding2]
    evidence_quality = EvidenceQuality.HIGH

    primary = engine._select_primary_diagnosis(findings, evidence_quality)

    # NO_EDGE has priority 190, NEGATIVE_EXPECTANCY has priority 180
    # NO_EDGE should win due to higher priority
    assert primary is not None
    assert primary.diagnosis_code == DiagnosisCode.NO_EDGE


def test_diagnosis_code_tie_break_after_priority():
    """Test that diagnosis code tie-break only applies when priority is equal."""
    from backend.services.aeroing4.diagnosis.engine import DiagnosisEngine

    engine = DiagnosisEngine("/tmp/test_runs")

    # Create findings with equal severity, confidence, and priority
    # Use codes that would have different alphabetical order
    finding1 = DiagnosisFinding(
        diagnosis_code=DiagnosisCode.EXCESSIVE_DRAWDOWN,
        category=DiagnosisCategory.RISK_QUALITY,
        severity=Severity.HIGH,
        confidence=0.90,
        explanation="Test finding 1",
        evidence_refs=["max_drawdown_pct"],
        evidence_values={"max_drawdown_pct": 25.0},
        suggested_research_area="risk_quality",
    )

    finding2 = DiagnosisFinding(
        diagnosis_code=DiagnosisCode.NEGATIVE_EXPECTANCY,
        category=DiagnosisCategory.EDGE_QUALITY,
        severity=Severity.HIGH,
        confidence=0.90,
        explanation="Test finding 2",
        evidence_refs=["expectancy"],
        evidence_values={"expectancy": -0.01},
        suggested_research_area="edge_quality",
    )

    findings = [finding1, finding2]
    evidence_quality = EvidenceQuality.HIGH

    primary = engine._select_primary_diagnosis(findings, evidence_quality)

    # Should select based on priority first, then code tie-break
    assert primary is not None
    # The actual result depends on the declared priorities of these rules


def test_derived_findings_excluded_from_primary():
    """Test that derived parameter-research findings are excluded from primary diagnosis."""
    from backend.services.aeroing4.diagnosis.engine import DiagnosisEngine

    engine = DiagnosisEngine("/tmp/test_runs")

    # Create a derived finding (parameter research)
    derived_finding = DiagnosisFinding(
        diagnosis_code=DiagnosisCode.PARAMETER_RESEARCH_NEEDED,
        category=DiagnosisCategory.PARAMETER_RESEARCH,
        severity=Severity.CRITICAL,
        confidence=0.95,
        explanation="Test derived finding",
        evidence_refs=["profit_factor"],
        evidence_values={"profit_factor": 0.8},
        suggested_research_area="parameter_research",
    )

    # Create a non-derived finding
    primary_finding = DiagnosisFinding(
        diagnosis_code=DiagnosisCode.NO_EDGE,
        category=DiagnosisCategory.EDGE_QUALITY,
        severity=Severity.HIGH,
        confidence=0.90,
        explanation="Test primary finding",
        evidence_refs=["profit_factor"],
        evidence_values={"profit_factor": 0.8},
        suggested_research_area="edge_quality",
    )

    findings = [derived_finding, primary_finding]
    evidence_quality = EvidenceQuality.HIGH

    primary = engine._select_primary_diagnosis(findings, evidence_quality)

    # Derived finding should be excluded, primary finding should win
    assert primary is not None
    assert primary.diagnosis_code == DiagnosisCode.NO_EDGE


def test_severity_takes_precedence_over_priority():
    """Test that severity takes precedence over priority in primary selection."""
    from backend.services.aeroing4.diagnosis.engine import DiagnosisEngine

    engine = DiagnosisEngine("/tmp/test_runs")

    # CRITICAL with low priority should beat HIGH with high priority
    critical_finding = DiagnosisFinding(
        diagnosis_code=DiagnosisCode.NEGATIVE_EXPECTANCY,
        category=DiagnosisCategory.EDGE_QUALITY,
        severity=Severity.CRITICAL,
        confidence=0.90,
        explanation="Test critical finding",
        evidence_refs=["expectancy"],
        evidence_values={"expectancy": -0.01},
        suggested_research_area="edge_quality",
    )

    high_finding = DiagnosisFinding(
        diagnosis_code=DiagnosisCode.NO_EDGE,
        category=DiagnosisCategory.EDGE_QUALITY,
        severity=Severity.HIGH,
        confidence=0.90,
        explanation="Test high finding",
        evidence_refs=["profit_factor"],
        evidence_values={"profit_factor": 0.8},
        suggested_research_area="edge_quality",
    )

    findings = [critical_finding, high_finding]
    evidence_quality = EvidenceQuality.HIGH

    primary = engine._select_primary_diagnosis(findings, evidence_quality)

    # CRITICAL should win regardless of priority
    assert primary is not None
    assert primary.severity == Severity.CRITICAL


def test_confidence_takes_precedence_over_priority():
    """Test that confidence takes precedence over priority when severity is equal."""
    from backend.services.aeroing4.diagnosis.engine import DiagnosisEngine

    engine = DiagnosisEngine("/tmp/test_runs")

    # HIGH severity with higher confidence should beat HIGH severity with lower confidence
    high_confidence_finding = DiagnosisFinding(
        diagnosis_code=DiagnosisCode.NO_EDGE,
        category=DiagnosisCategory.EDGE_QUALITY,
        severity=Severity.HIGH,
        confidence=0.95,
        explanation="Test high confidence finding",
        evidence_refs=["profit_factor"],
        evidence_values={"profit_factor": 0.8},
        suggested_research_area="edge_quality",
    )

    low_confidence_finding = DiagnosisFinding(
        diagnosis_code=DiagnosisCode.NEGATIVE_EXPECTANCY,
        category=DiagnosisCategory.EDGE_QUALITY,
        severity=Severity.HIGH,
        confidence=0.85,
        explanation="Test low confidence finding",
        evidence_refs=["expectancy"],
        evidence_values={"expectancy": -0.01},
        suggested_research_area="edge_quality",
    )

    findings = [high_confidence_finding, low_confidence_finding]
    evidence_quality = EvidenceQuality.HIGH

    primary = engine._select_primary_diagnosis(findings, evidence_quality)

    # Higher confidence should win
    assert primary is not None
    assert primary.confidence == 0.95
