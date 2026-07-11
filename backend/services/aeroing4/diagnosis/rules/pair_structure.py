"""Pair structure diagnosis rules.

Rules for evaluating pair concentration and dependence.
"""

from __future__ import annotations

from typing import Optional

from ..models import (
    DiagnosisCategory,
    DiagnosisCode,
    DiagnosisFinding,
    Severity,
)
from ..thresholds import (
    CONCENTRATION_TOP_PAIR_THRESHOLD,
    SINGLE_PAIR_DEPENDENCE_THRESHOLD,
)
from .base import BaseRule, RuleEvaluationContext


class PairConcentrationRule(BaseRule):
    """Rule: PAIR_CONCENTRATION

    Triggers when one pair dominates portfolio performance.
    """

    rule_id = "pair_concentration"
    category = DiagnosisCategory.PAIR_STRUCTURE
    diagnosis_code = DiagnosisCode.PAIR_CONCENTRATION
    required_evidence = ["concentration_summary"]
    priority = 140

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        if not self.check_required_evidence(context):
            return None

        resolver = context.resolver
        concentration = resolver.get_concentration_summary()

        if concentration is None:
            return None

        top_pair_share = concentration.top_pair_profit_contribution_share

        if top_pair_share is None or top_pair_share < CONCENTRATION_TOP_PAIR_THRESHOLD:
            return None

        # Severity based on concentration level
        if top_pair_share >= 0.80:
            severity = Severity.HIGH
            confidence = 0.90
        else:
            severity = Severity.MEDIUM
            confidence = 0.85

        explanation = (
            f"Portfolio is highly concentrated: top pair accounts for "
            f"{top_pair_share:.1%} of total profit. This creates single-pair "
            f"dependence and increases risk."
        )

        return self.create_finding(
            severity=severity,
            confidence=confidence,
            explanation=explanation,
            evidence_refs=["concentration_summary"],
            evidence_values={
                "top_pair_profit_share": top_pair_share,
                "total_contributing_pairs": concentration.total_contributing_pairs,
            },
            suggested_research_area="pair_structure",
            limitations=[
                "Concentration may be justified if top pair has exceptional quality",
                "Does not assess correlation between pairs",
            ],
        )


class SinglePairDependenceRule(BaseRule):
    """Rule: SINGLE_PAIR_DEPENDENCE

    Triggers when only one pair contributes to performance.
    """

    rule_id = "single_pair_dependence"
    category = DiagnosisCategory.PAIR_STRUCTURE
    diagnosis_code = DiagnosisCode.SINGLE_PAIR_DEPENDENCE
    required_evidence = ["concentration_summary"]
    priority = 145  # Higher than general concentration

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        if not self.check_required_evidence(context):
            return None

        resolver = context.resolver
        concentration = resolver.get_concentration_summary()

        if concentration is None:
            return None

        total_pairs = concentration.total_contributing_pairs

        if total_pairs is None or total_pairs > SINGLE_PAIR_DEPENDENCE_THRESHOLD:
            return None

        confidence = 0.95
        severity = Severity.CRITICAL

        explanation = (
            f"Portfolio depends on a single contributing pair. "
            f"This creates extreme concentration risk and is not robust."
        )

        return self.create_finding(
            severity=severity,
            confidence=confidence,
            explanation=explanation,
            evidence_refs=["concentration_summary"],
            evidence_values={
                "total_contributing_pairs": total_pairs,
            },
            suggested_research_area="pair_structure",
            limitations=[
                "May be acceptable for single-pair strategies",
                "Does not account for intentional single-pair focus",
            ],
        )


class MultipleNegativeContributorsRule(BaseRule):
    """Rule: MULTIPLE_NEGATIVE_CONTRIBUTORS

    Triggers when multiple pairs have negative contribution.
    """

    rule_id = "multiple_negative_contributors"
    category = DiagnosisCategory.PAIR_STRUCTURE
    diagnosis_code = DiagnosisCode.MULTIPLE_NEGATIVE_CONTRIBUTORS
    required_evidence = ["per_pair_contribution", "selected_pairs"]
    priority = 135

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        if not self.check_required_evidence(context):
            return None

        resolver = context.resolver
        contributions = resolver.get_per_pair_contributions()
        selected_pairs = resolver.get_selected_pairs()

        if not contributions or len(selected_pairs) < 2:
            return None

        negative_count = resolver.get_negative_contributing_pairs()
        total_pairs = len(selected_pairs)

        # Trigger if > 50% of pairs are negative contributors
        if negative_count <= total_pairs / 2:
            return None

        ratio = negative_count / total_pairs

        if ratio >= 0.75:
            severity = Severity.HIGH
            confidence = 0.90
        else:
            severity = Severity.MEDIUM
            confidence = 0.85

        explanation = (
            f"Multiple pairs have negative contribution: {negative_count}/{total_pairs} "
            f"({ratio:.1%}) of selected pairs are losing. This suggests poor "
            f"pair selection or strategy fit."
        )

        return self.create_finding(
            severity=severity,
            confidence=confidence,
            explanation=explanation,
            evidence_refs=["per_pair_contribution", "selected_pairs"],
            evidence_values={
                "negative_contributing_pairs": negative_count,
                "total_selected_pairs": total_pairs,
                "negative_ratio": ratio,
            },
            suggested_research_area="pair_structure",
            limitations=[
                "Does not assess magnitude of negative contributions",
                "May be acceptable if positive pairs compensate strongly",
            ],
        )


class PairStructureRules:
    """Container for all pair structure rules."""

    @staticmethod
    def get_all_rules() -> list[BaseRule]:
        """Return all pair structure rules."""
        return [
            PairConcentrationRule(),
            SinglePairDependenceRule(),
            MultipleNegativeContributorsRule(),
        ]
