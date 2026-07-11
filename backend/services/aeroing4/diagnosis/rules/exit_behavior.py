"""Exit behavior diagnosis rules.

Rules for evaluating exit patterns and loss concentration.
"""

from __future__ import annotations

from typing import Optional

from ..models import (
    DiagnosisCategory,
    DiagnosisCode,
    DiagnosisFinding,
    Severity,
)
from ..resolver import CanonicalExitCategory
from ..thresholds import STOPLOSS_DOMINANCE_THRESHOLD
from .base import BaseRule, RuleEvaluationContext


class StoplossDominanceRule(BaseRule):
    """Rule: STOPLOSS_DOMINANCE

    Triggers when stop loss exits dominate exit reasons.
    """

    rule_id = "stoploss_dominance"
    category = DiagnosisCategory.EXIT_BEHAVIOR
    diagnosis_code = DiagnosisCode.STOPLOSS_DOMINANCE
    required_evidence = ["exit_reason_distribution", "total_trades"]
    priority = 130

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        if not self.check_required_evidence(context):
            return None

        resolver = context.resolver
        stoploss_share = resolver.get_stoploss_exit_share()

        if stoploss_share is None or stoploss_share < STOPLOSS_DOMINANCE_THRESHOLD:
            return None

        # Severity based on dominance level
        if stoploss_share >= 0.80:
            severity = Severity.HIGH
            confidence = 0.90
        else:
            severity = Severity.MEDIUM
            confidence = 0.85

        explanation = (
            f"Stop loss exits dominate: {stoploss_share:.1%} of trades "
            f"exit via stop loss. This suggests risk management may be too "
            f"tight or entries are poorly timed."
        )

        return self.create_finding(
            severity=severity,
            confidence=confidence,
            explanation=explanation,
            evidence_refs=["exit_reason_distribution"],
            evidence_values={
                "stoploss_exit_share": stoploss_share,
            },
            suggested_research_area="exit_behavior",
            limitations=[
                "Does not distinguish between tight and appropriate stop losses",
                "May be acceptable if stop losses are protecting against larger losses",
            ],
        )


class ExitLossConcentrationRule(BaseRule):
    """Rule: EXIT_LOSS_CONCENTRATION

    Triggers when losses are concentrated in specific exit reasons.
    """

    rule_id = "exit_loss_concentration"
    category = DiagnosisCategory.EXIT_BEHAVIOR
    diagnosis_code = DiagnosisCode.EXIT_LOSS_CONCENTRATION
    required_evidence = ["exit_reason_distribution"]
    priority = 125

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        if not self.check_required_evidence(context):
            return None

        resolver = context.resolver
        exit_dist = resolver.get_exit_reason_distribution()

        if not exit_dist:
            return None

        # Calculate loss concentration
        total_loss_profit = sum(
            e.total_profit_contribution for e in exit_dist if e.total_profit_contribution and e.total_profit_contribution < 0
        )
        total_profit = sum(
            e.total_profit_contribution for e in exit_dist if e.total_profit_contribution
        )

        if total_loss_profit == 0 or total_profit == 0:
            return None

        loss_concentration = abs(total_loss_profit) / total_profit

        # Trigger if losses are > 50% of total profit
        if loss_concentration < 0.50:
            return None

        confidence = 0.80
        severity = Severity.MEDIUM

        explanation = (
            f"Losses are concentrated in specific exit reasons: "
            f"{loss_concentration:.1%} of total profit comes from losing exits. "
            f"This suggests specific exit patterns need investigation."
        )

        return self.create_finding(
            severity=severity,
            confidence=confidence,
            explanation=explanation,
            evidence_refs=["exit_reason_distribution"],
            evidence_values={
                "loss_concentration": loss_concentration,
                "total_loss_profit": total_loss_profit,
                "total_profit": total_profit,
            },
            suggested_research_area="exit_behavior",
            limitations=[
                "Requires reliable exit reason distribution data",
                "May be influenced by sample size",
            ],
        )


class ExitBehaviorRules:
    """Container for all exit behavior rules."""

    @staticmethod
    def get_all_rules() -> list[BaseRule]:
        """Return all exit behavior rules."""
        return [
            StoplossDominanceRule(),
            ExitLossConcentrationRule(),
        ]
