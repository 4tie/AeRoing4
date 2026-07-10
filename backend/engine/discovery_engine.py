"""
Discovery Engine - Find potential edges
Permissive: Don't reject everything
"""

from typing import List, Tuple
from ..models.domain.strategy import Strategy


class DiscoveryEngine:
    """
    Discovery stage: Find potential edges.
    Permissive criteria to avoid filtering out all strategies.
    """

    def __init__(self, thresholds: dict = None):
        self.thresholds = thresholds or {
            "min_profit_factor": 1.1,
            "min_expectancy": 0,
            "min_trades": 10,
            "max_drawdown": 0.40,
        }

    def discover(
        self, strategies: List[Strategy]
    ) -> Tuple[List[Strategy], List[str]]:
        """
        Filter strategies by discovery criteria.

        Args:
            strategies: List of strategies to evaluate

        Returns:
            Tuple of (passing_strategies, error_messages)
        """
        candidates = []
        errors = []

        for strategy in strategies:
            reasons = self._check_strategy(strategy)
            if not reasons:
                # Mark as candidate
                strategy.tier = "candidate"
                strategy.status = "candidate"
                candidates.append(strategy)
            else:
                errors.append(f"{strategy.name}: {'; '.join(reasons)}")

        # If nothing passes, try relaxed criteria
        if not candidates and strategies:
            errors.append(
                f"No candidates found with strict thresholds. Trying relaxed criteria..."
            )
            return self._discover_relaxed(strategies)

        return candidates, errors

    def _check_strategy(self, strategy: Strategy) -> List[str]:
        """
        Check strategy against thresholds.
        Returns list of failure reasons (empty if passes).
        """
        reasons = []
        m = strategy.metrics

        if m.profit_factor < self.thresholds["min_profit_factor"]:
            reasons.append(
                f"PF {m.profit_factor:.2f} < {self.thresholds['min_profit_factor']}"
            )

        if m.trades < self.thresholds["min_trades"]:
            reasons.append(
                f"Trades {m.trades} < {self.thresholds['min_trades']}"
            )

        if m.drawdown > self.thresholds["max_drawdown"]:
            reasons.append(
                f"DD {m.drawdown:.2f} > {self.thresholds['max_drawdown']}"
            )

        return reasons

    def _discover_relaxed(
        self, strategies: List[Strategy]
    ) -> Tuple[List[Strategy], List[str]]:
        """
        Fallback: relax thresholds by 20%.
        """
        relaxed = {
            "min_profit_factor": self.thresholds["min_profit_factor"] * 0.8,
            "min_trades": int(self.thresholds["min_trades"] * 0.5),
            "max_drawdown": self.thresholds["max_drawdown"] * 1.2,
        }
        original = self.thresholds
        self.thresholds = relaxed
        candidates, errors = self.discover(strategies)
        self.thresholds = original
        return candidates, errors
