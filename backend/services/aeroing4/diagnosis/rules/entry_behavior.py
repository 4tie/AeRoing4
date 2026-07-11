"""Entry behavior diagnosis rules.

Rules for evaluating entry restrictiveness and activity levels.
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
from .base import BaseRule, RuleEvaluationContext


class EntryTooRestrictiveRule(BaseRule):
    """Rule: ENTRY_TOO_RESTRICTIVE

    Triggers when trade count is very low relative to timeframe minimum,
    suggesting entries are too restrictive.
    """

    rule_id = "entry_too_restrictive"
    category = DiagnosisCategory.ENTRY_BEHAVIOR
    diagnosis_code = DiagnosisCode.ENTRY_TOO_RESTRICTIVE
    required_evidence = ["total_trades"]
    priority = 120

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        if not self.check_required_evidence(context):
            return None

        resolver = context.resolver
        total_trades = resolver.get_total_trades()
        min_trades = get_min_trades(context.timeframe)

        if total_trades is None:
            return None

        # Trigger if trades are below 50% of minimum
        if total_trades >= min_trades * 0.5:
            return None

        ratio = total_trades / min_trades if min_trades > 0 else 0

        if ratio < 0.25:
            confidence = 0.90
            severity = Severity.HIGH
        else:
            confidence = 0.85
            severity = Severity.MEDIUM

        explanation = (
            f"Trade count is very low ({total_trades} trades), only "
            f"{ratio:.1%} of the minimum required ({min_trades}) for "
            f"timeframe {context.timeframe}. This suggests entry conditions "
            f"may be too restrictive."
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
            suggested_research_area="entry_behavior",
            limitations=[
                "Low trade count may be due to market conditions, not entry rules",
                "Does not assess whether low activity is intentional",
            ],
        )


class EntryBehaviorRules:
    """Container for all entry behavior rules."""

    @staticmethod
    def get_all_rules() -> list[BaseRule]:
        """Return all entry behavior rules."""
        return [
            EntryTooRestrictiveRule(),
        ]
