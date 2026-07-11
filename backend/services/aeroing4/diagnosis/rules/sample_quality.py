"""Sample quality diagnosis rules.

Rules for evaluating trade sample sufficiency and balance.
"""

from __future__ import annotations

from typing import Optional

from ..models import (
    DiagnosisCategory,
    DiagnosisCode,
    DiagnosisFinding,
    Severity,
)
from ...policies import get_min_trades
from ..thresholds import EvidenceQuality
from .base import BaseRule, RuleEvaluationContext


class InsufficientSampleRule(BaseRule):
    """Rule: INSUFFICIENT_SAMPLE

    Triggers when total trades are below the timeframe minimum threshold.
    """

    rule_id = "insufficient_sample"
    category = DiagnosisCategory.SAMPLE_QUALITY
    diagnosis_code = DiagnosisCode.INSUFFICIENT_SAMPLE
    required_evidence = ["total_trades"]
    priority = 200  # High priority - sample quality is foundational

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        if not self.check_required_evidence(context):
            return None

        resolver = context.resolver
        total_trades = resolver.get_total_trades()
        min_trades = get_min_trades(context.timeframe)

        if total_trades is None or total_trades >= min_trades:
            return None

        # Calculate confidence based on how far below threshold
        ratio = total_trades / min_trades if min_trades > 0 else 0
        if ratio < 0.5:
            confidence = 0.95
            severity = Severity.CRITICAL
        elif ratio < 0.75:
            confidence = 0.85
            severity = Severity.HIGH
        else:
            confidence = 0.75
            severity = Severity.MEDIUM

        explanation = (
            f"Total trades ({total_trades}) are below the minimum required "
            f"for timeframe {context.timeframe} ({min_trades} trades). "
            f"This is {ratio:.1%} of the required sample size."
        )

        return self.create_finding(
            severity=severity,
            confidence=confidence,
            explanation=explanation,
            evidence_refs=["total_trades", "timeframe"],
            evidence_values={
                "total_trades": total_trades,
                "min_trades": min_trades,
                "timeframe": context.timeframe,
                "ratio": ratio,
            },
            suggested_research_area="sample_quality",
            limitations=[
                "Minimum trade thresholds are heuristic estimates",
                "Quality of individual trades not assessed",
            ],
        )


class UnbalancedPairSampleRule(BaseRule):
    """Rule: UNBALANCED_PAIR_SAMPLE

    Triggers when trade distribution across pairs is highly uneven.
    """

    rule_id = "unbalanced_pair_sample"
    category = DiagnosisCategory.SAMPLE_QUALITY
    diagnosis_code = DiagnosisCode.UNBALANCED_PAIR_SAMPLE
    required_evidence = ["per_pair_contribution", "selected_pairs"]
    priority = 150

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        if not self.check_required_evidence(context):
            return None

        resolver = context.resolver
        contributions = resolver.get_per_pair_contributions()
        selected_pairs = resolver.get_selected_pairs()

        if not contributions or len(selected_pairs) < 2:
            return None

        # Calculate trade distribution
        trade_counts = [c.trade_count for c in contributions if c.trade_count]
        if not trade_counts:
            return None

        total_trades = sum(trade_counts)
        max_trades = max(trade_counts)
        max_share = max_trades / total_trades if total_trades > 0 else 0

        # Trigger if one pair has > 70% of trades
        if max_share < 0.70:
            return None

        confidence = 0.80
        severity = Severity.MEDIUM

        explanation = (
            f"Trade distribution is unbalanced: one pair accounts for "
            f"{max_share:.1%} of total trades ({max_trades}/{total_trades}). "
            f"This may reduce the robustness of the strategy."
        )

        return self.create_finding(
            severity=severity,
            confidence=confidence,
            explanation=explanation,
            evidence_refs=["per_pair_contribution", "selected_pairs"],
            evidence_values={
                "max_pair_trades": max_trades,
                "total_trades": total_trades,
                "max_share": max_share,
                "pair_count": len(selected_pairs),
            },
            suggested_research_area="sample_quality",
            limitations=[
                "Does not assess whether imbalance is justified by pair quality",
                "May be acceptable if top pair has exceptional performance",
            ],
        )


class SampleQualityRules:
    """Container for all sample quality rules."""

    @staticmethod
    def get_all_rules() -> list[BaseRule]:
        """Return all sample quality rules."""
        return [
            InsufficientSampleRule(),
            UnbalancedPairSampleRule(),
        ]
