"""
Elite Ranking Engine - Rank elite strategies by weighted score
Scores strategies on multiple dimensions: expectancy, profit factor, drawdown, etc.
"""

from typing import List, Tuple
from ..models.domain.strategy import Strategy, EliteScore


class EliteRankingEngine:
    """
    Rank elite strategies by weighted score (0-100).
    Higher score = better strategy for deployment.
    """

    WEIGHTS = {
        "expectancy": 0.20,
        "profit_factor": 0.20,
        "drawdown": 0.20,
        "walk_forward": 0.15,
        "robustness": 0.15,
        "pair_consistency": 0.05,
        "trade_quality": 0.05,
    }

    def rank(self, validated: List[Strategy]) -> Tuple[List[Strategy], List[EliteScore]]:
        """
        Rank and score elite strategies.

        Args:
            validated: Validated strategies

        Returns:
            Tuple of (ranked_strategies, scores)
        """
        scores = []

        for strategy in validated:
            score = self._calculate_score(strategy)
            scores.append(score)
            strategy.score = score.overall
            strategy.tier = "elite"
            strategy.status = "elite"

        # Sort by overall score (highest first)
        ranked = sorted(validated, key=lambda s: s.score, reverse=True)
        ranked_scores = sorted(scores, key=lambda s: s.overall, reverse=True)

        return ranked, ranked_scores

    def _calculate_score(self, strategy: Strategy) -> EliteScore:
        """Calculate weighted elite score for strategy."""
        m = strategy.metrics

        # Normalize metrics to 0-100 scale
        expectancy_score = min(100, m.expectancy * 1000)  # Higher is better
        pf_score = min(100, (m.profit_factor - 1.0) * 50)   # Higher is better
        dd_score = max(0, 100 - m.drawdown * 100)          # Lower is better (inverted)
        wf_score = (m.walk_forward_score or 0) * 100
        robustness_score = (m.robustness_score or 0) * 100
        pair_consistency_score = (m.pair_consistency or 0) * 100
        trade_quality_score = min(100, m.trades / 100)     # More trades = better

        # Apply weights
        overall = (
            expectancy_score * self.WEIGHTS["expectancy"]
            + pf_score * self.WEIGHTS["profit_factor"]
            + dd_score * self.WEIGHTS["drawdown"]
            + wf_score * self.WEIGHTS["walk_forward"]
            + robustness_score * self.WEIGHTS["robustness"]
            + pair_consistency_score * self.WEIGHTS["pair_consistency"]
            + trade_quality_score * self.WEIGHTS["trade_quality"]
        )

        return EliteScore(
            strategy_id=strategy.id,
            overall=min(100, max(0, overall)),
            expectancy=expectancy_score,
            profit_factor=pf_score,
            drawdown=dd_score,
            walk_forward=wf_score,
            robustness=robustness_score,
            pair_consistency=pair_consistency_score,
            trade_quality=trade_quality_score,
        )
