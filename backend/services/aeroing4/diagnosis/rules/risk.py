"""Risk quality diagnosis rules.

Rules for evaluating drawdown and risk-adjusted performance.
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
    DRAWDOWN_CRITICAL_THRESHOLD,
    DRAWDOWN_ELEVATED_MAX,
    DRAWDOWN_ELEVATED_MIN,
    DRAWDOWN_HIGH_MAX,
    DRAWDOWN_HIGH_MIN,
)
from .base import BaseRule, RuleEvaluationContext


class ExcessiveDrawdownRule(BaseRule):
    """Rule: EXCESSIVE_DRAWDOWN

    Triggers when max drawdown exceeds thresholds.
    """

    rule_id = "excessive_drawdown"
    category = DiagnosisCategory.RISK_QUALITY
    diagnosis_code = DiagnosisCode.EXCESSIVE_DRAWDOWN
    required_evidence = ["max_drawdown_pct"]
    priority = 170  # High priority - drawdown is critical risk

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        if not self.check_required_evidence(context):
            return None

        resolver = context.resolver
        dd = resolver.get_max_drawdown_pct()

        if dd is None or dd < DRAWDOWN_ELEVATED_MIN:
            return None

        # Determine severity based on drawdown level
        if dd >= DRAWDOWN_CRITICAL_THRESHOLD:
            severity = Severity.CRITICAL
            confidence = 0.95
            level = "critical"
        elif dd >= DRAWDOWN_HIGH_MIN:
            severity = Severity.HIGH
            confidence = 0.90
            level = "high"
        else:
            severity = Severity.MEDIUM
            confidence = 0.85
            level = "elevated"

        explanation = (
            f"Maximum drawdown is {level} ({dd:.1f}%). "
            f"This level of drawdown indicates significant risk exposure."
        )

        return self.create_finding(
            severity=severity,
            confidence=confidence,
            explanation=explanation,
            evidence_refs=["max_drawdown_pct"],
            evidence_values={"max_drawdown_pct": dd, "level": level},
            suggested_research_area="risk_quality",
            limitations=[
                "Drawdown alone does not indicate profitability",
                "May be acceptable if returns are proportionally high",
            ],
        )


class PoorReturnToDrawdownRule(BaseRule):
    """Rule: POOR_RETURN_TO_DRAWDOWN

    Triggers when Calmar ratio indicates poor return-to-drawdown.
    """

    rule_id = "poor_return_to_drawdown"
    category = DiagnosisCategory.RISK_QUALITY
    diagnosis_code = DiagnosisCode.POOR_RETURN_TO_DRAWDOWN
    required_evidence = ["calmar"]
    priority = 165

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        if not self.check_required_evidence(context):
            return None

        resolver = context.resolver
        calmar = resolver.get_calmar()

        if calmar is None or calmar >= 0.5:
            return None

        # Calmar < 0.5 indicates poor return-to-drawdown
        if calmar < 0.2:
            confidence = 0.90
            severity = Severity.HIGH
        else:
            confidence = 0.85
            severity = Severity.MEDIUM

        explanation = (
            f"Calmar ratio is poor ({calmar:.2f}), indicating low returns "
            f"relative to drawdown. The strategy may not compensate adequately "
            f"for risk taken."
        )

        return self.create_finding(
            severity=severity,
            confidence=confidence,
            explanation=explanation,
            evidence_refs=["calmar"],
            evidence_values={"calmar": calmar},
            suggested_research_area="risk_quality",
            limitations=[
                "Calmar requires sufficient drawdown to be meaningful",
                "May be influenced by short sample periods",
            ],
        )


class DownsideRiskDominanceRule(BaseRule):
    """Rule: DOWNSIDE_RISK_DOMINANCE

    Triggers when Sortino ratio indicates poor downside risk management.
    """

    rule_id = "downside_risk_dominance"
    category = DiagnosisCategory.RISK_QUALITY
    diagnosis_code = DiagnosisCode.DOWNSIDE_RISK_DOMINANCE
    required_evidence = ["sortino"]
    priority = 155

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        if not self.check_required_evidence(context):
            return None

        resolver = context.resolver
        sortino = resolver.get_sortino()

        if sortino is None or sortino >= 0.5:
            return None

        # Sortino < 0.5 indicates poor downside risk-adjusted returns
        if sortino < 0.2:
            confidence = 0.85
            severity = Severity.HIGH
        else:
            confidence = 0.80
            severity = Severity.MEDIUM

        explanation = (
            f"Sortino ratio is low ({sortino:.2f}), indicating poor "
            f"downside risk-adjusted performance. The strategy may have "
            f"excessive downside volatility relative to returns."
        )

        return self.create_finding(
            severity=severity,
            confidence=confidence,
            explanation=explanation,
            evidence_refs=["sortino"],
            evidence_values={"sortino": sortino},
            suggested_research_area="risk_quality",
            limitations=[
                "Sortino requires sufficient downside deviation to be meaningful",
                "May be influenced by outlier losing trades",
            ],
        )


class RiskRules:
    """Container for all risk quality rules."""

    @staticmethod
    def get_all_rules() -> list[BaseRule]:
        """Return all risk quality rules."""
        return [
            ExcessiveDrawdownRule(),
            PoorReturnToDrawdownRule(),
            DownsideRiskDominanceRule(),
        ]
