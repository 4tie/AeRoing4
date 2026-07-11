"""Parameter research need diagnosis rules.

Derived/routing findings that suggest research areas based on primary findings.
These rules must NOT become the primary diagnosis.
"""

from __future__ import annotations

from typing import Optional

from ..models import (
    DiagnosisCategory,
    DiagnosisCode,
    DiagnosisFinding,
    Severity,
)
from .base import BaseRule, RuleEvaluationContext


class ParameterResearchNeededRule(BaseRule):
    """Rule: PARAMETER_RESEARCH_NEEDED

    Derived finding suggesting general parameter research.
    Triggered by other primary findings.
    """

    rule_id = "parameter_research_needed"
    category = DiagnosisCategory.PARAMETER_RESEARCH
    diagnosis_code = DiagnosisCode.PARAMETER_RESEARCH_NEEDED
    required_evidence = []  # Derived from other findings
    priority = 10  # Lowest priority - should never be primary
    is_derived = True

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        # This is a derived rule - should be triggered by engine based on
        # other findings, not evaluated independently
        return None


class ExitParameterResearchNeededRule(BaseRule):
    """Rule: EXIT_PARAMETER_RESEARCH_NEEDED

    Derived finding suggesting exit parameter research.
    Triggered by exit behavior findings.
    """

    rule_id = "exit_parameter_research_needed"
    category = DiagnosisCategory.PARAMETER_RESEARCH
    diagnosis_code = DiagnosisCode.EXIT_PARAMETER_RESEARCH_NEEDED
    required_evidence = []
    priority = 10
    is_derived = True

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        # Derived rule - triggered by engine
        return None


class RiskParameterResearchNeededRule(BaseRule):
    """Rule: RISK_PARAMETER_RESEARCH_NEEDED

    Derived finding suggesting risk parameter research.
    Triggered by risk quality findings.
    """

    rule_id = "risk_parameter_research_needed"
    category = DiagnosisCategory.PARAMETER_RESEARCH
    diagnosis_code = DiagnosisCode.RISK_PARAMETER_RESEARCH_NEEDED
    required_evidence = []
    priority = 10
    is_derived = True

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        # Derived rule - triggered by engine
        return None


class EntryParameterResearchNeededRule(BaseRule):
    """Rule: ENTRY_PARAMETER_RESEARCH_NEEDED

    Derived finding suggesting entry parameter research.
    Triggered by entry behavior findings.
    """

    rule_id = "entry_parameter_research_needed"
    category = DiagnosisCategory.PARAMETER_RESEARCH
    diagnosis_code = DiagnosisCode.ENTRY_PARAMETER_RESEARCH_NEEDED
    required_evidence = []
    priority = 10
    is_derived = True

    def evaluate(self, context: RuleEvaluationContext) -> Optional[DiagnosisFinding]:
        # Derived rule - triggered by engine
        return None


class ParameterResearchRules:
    """Container for all parameter research rules."""

    @staticmethod
    def get_all_rules() -> list[BaseRule]:
        """Return all parameter research rules."""
        return [
            ParameterResearchNeededRule(),
            ExitParameterResearchNeededRule(),
            RiskParameterResearchNeededRule(),
            EntryParameterResearchNeededRule(),
        ]
