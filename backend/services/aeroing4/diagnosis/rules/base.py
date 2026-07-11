"""Base rule interface for diagnosis rules.

All diagnosis rules must inherit from BaseRule and implement the evaluate method.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ..models import DiagnosisCategory, DiagnosisCode, DiagnosisFinding, Severity
from ..resolver import EvidenceResolver
from ..thresholds import EvidenceQuality


@dataclass
class RuleEvaluationContext:
    """Context provided to rule evaluation."""

    resolver: EvidenceResolver
    evidence_quality: EvidenceQuality
    timeframe: str
    run_id: str
    champion_id: str


class BaseRule(ABC):
    """Base interface for diagnosis rules.

    All diagnosis rules must:
    - Declare their ID, version, category
    - Declare required and optional evidence
    - Implement the evaluate method
    - Provide severity and confidence logic
    - Provide suggested research area
    """

    # Rule metadata (must be set by subclasses)
    rule_id: str
    rule_version: str = "1.0.0"
    category: DiagnosisCategory
    diagnosis_code: DiagnosisCode

    # Evidence dependencies
    required_evidence: list[str]
    optional_evidence: list[str] = []

    # Priority for primary diagnosis selection (higher = more important)
    # Parameter research rules should have lowest priority
    priority: int = 100

    # Whether this is a derived/routing finding (should not be primary diagnosis)
    is_derived: bool = False

    @abstractmethod
    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        """Evaluate the rule and return a finding if triggered.

        Args:
            context: Evaluation context with evidence and metadata

        Returns:
            DiagnosisFinding if rule triggers, None otherwise
        """
        pass

    def check_required_evidence(self, context: RuleEvaluationContext) -> bool:
        """Check if all required evidence is available.

        Args:
            context: Evaluation context

        Returns:
            True if all required evidence is available, False otherwise
        """
        for evidence in self.required_evidence:
            if not self._is_evidence_available(evidence, context):
                return False
        return True

    def _is_evidence_available(self, evidence: str, context: RuleEvaluationContext) -> bool:
        """Check if a specific evidence item is available.

        Args:
            evidence: Evidence identifier
            context: Evaluation context

        Returns:
            True if evidence is available, False otherwise
        """
        resolver = context.resolver

        # Map evidence identifiers to resolver methods
        evidence_map = {
            "total_trades": lambda: resolver.get_total_trades() is not None,
            "profit_factor": lambda: resolver.is_metric_available("profit_factor"),
            "expectancy": lambda: resolver.is_metric_available("expectancy"),
            "max_drawdown_pct": lambda: resolver.is_metric_available("max_drawdown_pct"),
            "calmar": lambda: resolver.is_metric_available("calmar"),
            "sortino": lambda: resolver.is_metric_available("sortino"),
            "per_pair_contribution": lambda: len(resolver.get_per_pair_contributions()) > 0,
            "concentration_summary": lambda: resolver.get_concentration_summary() is not None,
            "exit_reason_distribution": lambda: len(resolver.get_exit_reason_distribution()) > 0,
            "selected_pairs": lambda: len(resolver.get_selected_pairs()) > 0,
        }

        checker = evidence_map.get(evidence)
        if checker is None:
            # Unknown evidence - assume unavailable
            return False

        return checker()

    def create_finding(
        self,
        severity: Severity,
        confidence: float,
        explanation: str,
        evidence_refs: list[str],
        evidence_values: dict,
        suggested_research_area: str,
        limitations: list[str] | None = None,
    ) -> DiagnosisFinding:
        """Create a DiagnosisFinding with rule metadata.

        Args:
            severity: Severity level
            confidence: Confidence score (0-1)
            explanation: Human-readable explanation
            evidence_refs: List of evidence references
            evidence_values: Dict of evidence values used
            suggested_research_area: Suggested research area
            limitations: Optional list of limitations

        Returns:
            DiagnosisFinding with rule metadata populated
        """
        return DiagnosisFinding(
            diagnosis_code=self.diagnosis_code,
            category=self.category,
            severity=severity,
            confidence=confidence,
            evidence_refs=evidence_refs,
            evidence_values=evidence_values,
            explanation=explanation,
            suggested_research_area=suggested_research_area,
            limitations=limitations or [],
            rule_version=self.rule_version,
        )
