"""Rule registry for AeRoing4 Diagnosis.

Centralized registry of all diagnosis rules with metadata.
"""

from __future__ import annotations

from typing import Dict, List

from .rules.base import BaseRule
from .rules.edge_quality import EdgeQualityRules
from .rules.entry_behavior import EntryBehaviorRules
from .rules.exit_behavior import ExitBehaviorRules
from .rules.pair_structure import PairStructureRules
from .rules.parameter_research import ParameterResearchRules
from .rules.risk import RiskRules
from .rules.sample_quality import SampleQualityRules


class RuleRegistry:
    """Centralized registry of all diagnosis rules.

    Provides authoritative access to all rules with their metadata.
    """

    def __init__(self):
        """Initialize the rule registry with all rules."""
        self._rules: Dict[str, BaseRule] = {}
        self._register_all_rules()

    def _register_all_rules(self) -> None:
        """Register all rules from each category."""
        rule_collections = [
            SampleQualityRules.get_all_rules(),
            EdgeQualityRules.get_all_rules(),
            RiskRules.get_all_rules(),
            PairStructureRules.get_all_rules(),
            ExitBehaviorRules.get_all_rules(),
            EntryBehaviorRules.get_all_rules(),
            ParameterResearchRules.get_all_rules(),
        ]

        for collection in rule_collections:
            for rule in collection:
                self._rules[rule.rule_id] = rule

    def get_rule(self, rule_id: str) -> BaseRule | None:
        """Get a rule by ID.

        Args:
            rule_id: The rule ID

        Returns:
            The rule if found, None otherwise
        """
        return self._rules.get(rule_id)

    def get_all_rules(self) -> List[BaseRule]:
        """Get all registered rules.

        Returns:
            List of all rules
        """
        return list(self._rules.values())

    def get_rules_by_category(self, category: str) -> List[BaseRule]:
        """Get all rules for a specific category.

        Args:
            category: The category name

        Returns:
            List of rules in the category
        """
        return [
            rule for rule in self._rules.values()
            if rule.category.value == category
        ]

    def get_primary_eligible_rules(self) -> List[BaseRule]:
        """Get rules that are eligible to be primary diagnosis.

        Excludes derived/routing rules (parameter research).

        Returns:
            List of rules that can be primary diagnosis
        """
        return [
            rule for rule in self._rules.values()
            if not rule.is_derived
        ]

    def get_rule_by_diagnosis_code(self, diagnosis_code: str) -> BaseRule | None:
        """Get a rule by its diagnosis code.

        Args:
            diagnosis_code: The diagnosis code value (e.g., "NEGATIVE_EXPECTANCY")

        Returns:
            The rule if found, None otherwise
        """
        for rule in self._rules.values():
            if rule.diagnosis_code.value == diagnosis_code:
                return rule
        return None
