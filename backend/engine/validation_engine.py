"""
Validation Engine - Remove weak candidates
Stricter criteria than discovery
"""

from typing import List, Tuple
from ..models.domain.strategy import Strategy


class ValidationEngine:
    """
    Validation stage: Remove weak candidates.
    Apply stricter criteria than discovery.
    """

    def __init__(self, thresholds: dict = None):
        self.thresholds = thresholds or {
            "min_profit_factor": 1.3,
            "max_drawdown": 0.30,
            "min_win_rate": 0.40,
        }

    def validate(
        self, candidates: List[Strategy]
    ) -> Tuple[List[Strategy], List[str]]:
        """
        Filter candidates by stricter criteria.

        Args:
            candidates: Candidate strategies from discovery

        Returns:
            Tuple of (promising_strategies, error_messages)
        """
        promising = []
        errors = []

        for strategy in candidates:
            reasons = self._check_strategy(strategy)
            if not reasons:
                # Mark as promising
                strategy.tier = "promising"
                strategy.status = "promising"
                promising.append(strategy)
            else:
                errors.append(f"{strategy.name}: {'; '.join(reasons)}")

        return promising, errors

    def _check_strategy(self, strategy: Strategy) -> List[str]:
        """Check strategy against validation thresholds."""
        m = strategy.metrics
        reasons = []

        if m.profit_factor < self.thresholds["min_profit_factor"]:
            reasons.append(
                f"PF {m.profit_factor:.2f} < {self.thresholds['min_profit_factor']}"
            )

        if m.drawdown > self.thresholds["max_drawdown"]:
            reasons.append(
                f"DD {m.drawdown:.2f} > {self.thresholds['max_drawdown']}"
            )

        if m.win_rate < self.thresholds["min_win_rate"]:
            reasons.append(
                f"WR {m.win_rate:.2f} < {self.thresholds['min_win_rate']}"
            )

        return reasons
