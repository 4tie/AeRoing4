"""
Elite Validation Engine - Find deployment-quality strategies
Strict criteria for production-ready strategies
"""

from typing import List, Tuple
from ..models.domain.strategy import Strategy


class EliteValidationEngine:
    """
    Elite validation stage: Find deployment-quality strategies.
    Apply strictest criteria - only elite-quality strategies pass.
    """

    def __init__(self, thresholds: dict = None):
        self.thresholds = thresholds or {
            "min_profit_factor": 1.5,
            "max_drawdown": 0.25,
            "min_walk_forward_score": 0.70,
            "min_robustness_score": 0.70,
        }

    def validate(
        self, promising: List[Strategy]
    ) -> Tuple[List[Strategy], List[str]]:
        """
        Filter by elite criteria.

        Args:
            promising: Promising strategies from validation stage

        Returns:
            Tuple of (validated_strategies, error_messages)
        """
        validated = []
        errors = []

        for strategy in promising:
            reasons = self._check_strategy(strategy)
            if not reasons:
                # Mark as validated/elite
                strategy.tier = "validated"
                strategy.status = "validated"
                validated.append(strategy)
            else:
                errors.append(f"{strategy.name}: {'; '.join(reasons)}")

        return validated, errors

    def _check_strategy(self, strategy: Strategy) -> List[str]:
        """Check strategy against elite thresholds."""
        m = strategy.metrics
        reasons = []

        if m.profit_factor < self.thresholds["min_profit_factor"]:
            reasons.append("Profit factor too low for deployment")

        if m.drawdown > self.thresholds["max_drawdown"]:
            reasons.append("Drawdown too high for deployment")

        if (
            not m.walk_forward_score
            or m.walk_forward_score < self.thresholds["min_walk_forward_score"]
        ):
            reasons.append("Walk-forward score insufficient")

        if (
            not m.robustness_score
            or m.robustness_score < self.thresholds["min_robustness_score"]
        ):
            reasons.append("Robustness score insufficient")

        return reasons
