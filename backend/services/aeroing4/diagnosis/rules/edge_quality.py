"""Edge quality diagnosis rules.

Rules for evaluating profitability and edge evidence.
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
    EXPECTANCY_NEGATIVE_THRESHOLD,
    PF_MARGINAL_MAX,
    PF_MARGINAL_MIN,
    PF_NEGATIVE_THRESHOLD,
    PF_STRONG_THRESHOLD,
    PF_WEAK_MAX,
    PF_WEAK_MIN,
)
from .base import BaseRule, RuleEvaluationContext


class NegativeExpectancyRule(BaseRule):
    """Rule: NEGATIVE_EXPECTANCY

    Triggers when expectancy is negative (losing per-trade on average).
    """

    rule_id = "negative_expectancy"
    category = DiagnosisCategory.EDGE_QUALITY
    diagnosis_code = DiagnosisCode.NEGATIVE_EXPECTANCY
    required_evidence = ["expectancy"]
    priority = 180  # High priority - negative expectancy is serious

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        if not self.check_required_evidence(context):
            return None

        resolver = context.resolver
        expectancy = resolver.get_expectancy()
        profit_factor = resolver.get_profit_factor()

        if expectancy is None or expectancy >= EXPECTANCY_NEGATIVE_THRESHOLD:
            return None

        # Use scale-independent evidence for severity determination
        # Negative expectancy with poor profit factor is more severe
        if profit_factor is not None and profit_factor < 1.0:
            # Both expectancy negative AND profit factor below 1.0 - very serious
            confidence = 0.95
            severity = Severity.CRITICAL
        elif profit_factor is not None and profit_factor < PF_WEAK_MAX:
            # Negative expectancy with weak profit factor (1.0-1.10)
            confidence = 0.90
            severity = Severity.HIGH
        else:
            # Negative expectancy alone or with better profit factor - conservative severity
            confidence = 0.85
            severity = Severity.MEDIUM

        explanation = (
            f"Expectancy is negative ({expectancy:.4f}), meaning the strategy "
            f"loses money on average per trade. This indicates no positive edge."
        )

        return self.create_finding(
            severity=severity,
            confidence=confidence,
            explanation=explanation,
            evidence_refs=["expectancy"],
            evidence_values={"expectancy": expectancy},
            suggested_research_area="edge_quality",
            limitations=[
                "Expectancy alone does not capture risk-adjusted performance",
                "May be influenced by outlier trades",
            ],
        )


class WeakEdgeRule(BaseRule):
    """Rule: WEAK_EDGE

    Triggers when profit factor is in the weak range (1.00-1.10).
    """

    rule_id = "weak_edge"
    category = DiagnosisCategory.EDGE_QUALITY
    diagnosis_code = DiagnosisCode.WEAK_EDGE
    required_evidence = ["profit_factor"]
    priority = 160

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        if not self.check_required_evidence(context):
            return None

        resolver = context.resolver
        pf = resolver.get_profit_factor()

        if pf is None or pf < PF_WEAK_MIN or pf > PF_WEAK_MAX:
            return None

        confidence = 0.80
        severity = Severity.MEDIUM

        explanation = (
            f"Profit factor is weak ({pf:.2f}), indicating marginal edge. "
            f"This range (1.00-1.10) suggests the strategy barely covers losses."
        )

        return self.create_finding(
            severity=severity,
            confidence=confidence,
            explanation=explanation,
            evidence_refs=["profit_factor"],
            evidence_values={"profit_factor": pf},
            suggested_research_area="edge_quality",
            limitations=[
                "Weak PF may be acceptable if risk metrics are strong",
                "Does not account for drawdown or volatility",
            ],
        )


class LowProfitFactorRule(BaseRule):
    """Rule: LOW_PROFIT_FACTOR

    Triggers when profit factor is below 1.0 (negative edge).
    """

    rule_id = "low_profit_factor"
    category = DiagnosisCategory.EDGE_QUALITY
    diagnosis_code = DiagnosisCode.LOW_PROFIT_FACTOR
    required_evidence = ["profit_factor"]
    priority = 185  # Very high priority - below breakeven

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        if not self.check_required_evidence(context):
            return None

        resolver = context.resolver
        pf = resolver.get_profit_factor()

        if pf is None or pf >= PF_NEGATIVE_THRESHOLD:
            return None

        # Confidence based on severity
        if pf < 0.8:
            confidence = 0.95
            severity = Severity.CRITICAL
        else:
            confidence = 0.90
            severity = Severity.HIGH

        explanation = (
            f"Profit factor is below 1.0 ({pf:.2f}), meaning the strategy "
            f"loses more than it wins. This indicates no positive edge."
        )

        return self.create_finding(
            severity=severity,
            confidence=confidence,
            explanation=explanation,
            evidence_refs=["profit_factor"],
            evidence_values={"profit_factor": pf},
            suggested_research_area="edge_quality",
            limitations=[
                "Does not account for risk-adjusted performance",
                "May be influenced by sample size",
            ],
        )


class NoEdgeRule(BaseRule):
    """Rule: NO_EDGE

    Conservative definition: sufficient sample + PF < 1.0 + Expectancy < 0.
    Risk metrics are optional for this classification.
    """

    rule_id = "no_edge"
    category = DiagnosisCategory.EDGE_QUALITY
    diagnosis_code = DiagnosisCode.NO_EDGE
    required_evidence = ["total_trades", "profit_factor", "expectancy"]
    priority = 190  # Highest priority - no edge is fundamental

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        if not self.check_required_evidence(context):
            return None

        resolver = context.resolver
        pf = resolver.get_profit_factor()
        expectancy = resolver.get_expectancy()

        # Conservative definition: both PF < 1.0 and Expectancy < 0
        if pf is None or expectancy is None:
            return None

        if pf >= PF_NEGATIVE_THRESHOLD or expectancy >= EXPECTANCY_NEGATIVE_THRESHOLD:
            return None

        confidence = 0.95
        severity = Severity.CRITICAL

        explanation = (
            f"Strategy shows no positive edge: Profit Factor ({pf:.2f}) "
            f"is below 1.0 and Expectancy ({expectancy:.4f}) is negative. "
            f"This combination strongly indicates the strategy does not have "
            f"a profitable edge."
        )

        return self.create_finding(
            severity=severity,
            confidence=confidence,
            explanation=explanation,
            evidence_refs=["profit_factor", "expectancy"],
            evidence_values={
                "profit_factor": pf,
                "expectancy": expectancy,
            },
            suggested_research_area="edge_quality",
            limitations=[
                "Risk metrics not required for this classification",
                "May need to consider market conditions and timeframe",
            ],
        )


class EdgeQualityRules:
    """Container for all edge quality rules."""

    @staticmethod
    def get_all_rules() -> list[BaseRule]:
        """Return all edge quality rules."""
        return [
            NegativeExpectancyRule(),
            WeakEdgeRule(),
            LowProfitFactorRule(),
            NoEdgeRule(),
        ]
