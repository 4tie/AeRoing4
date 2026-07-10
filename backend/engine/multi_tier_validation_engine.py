"""
Enhanced Multi-Tier Validation Engine
Candidate → Promising → Validated → Elite
"""

from typing import List, Tuple
from ..models.domain.strategy import Strategy
from .discovery_engine import DiscoveryEngine
from .validation_engine import ValidationEngine
from .elite_validation_engine import EliteValidationEngine
from .elite_ranking_engine import EliteRankingEngine


class MultiTierValidationEngine:
    """
    Complete validation pipeline with multiple tiers.

    Tier 1 (Discovery/Candidate):
    - Minimal requirements
    - Finds potential edges
    - High pass rate

    Tier 2 (Promising):
    - Moderate requirements
    - Filters obvious failures
    - ~20-30% pass rate

    Tier 3 (Validated):
    - Strict requirements
    - Requires OOS + Robustness
    - ~5-10% pass rate

    Tier 4 (Elite):
    - Most strict requirements
    - Requires Walk Forward + all tests
    - ~1-5% pass rate
    """

    def __init__(self, strategy_type: str = "swing"):
        self.strategy_type = strategy_type
        self.discovery_engine = DiscoveryEngine()
        self.validation_engine = ValidationEngine()
        self.elite_validation_engine = EliteValidationEngine()
        self.ranking_engine = EliteRankingEngine()

    def validate_all_tiers(
        self, strategies: List[Strategy]
    ) -> dict:
        """
        Run complete multi-tier validation.

        Returns:
            {
                "candidates": [Strategy],      # Tier 1 - Discovery pass
                "promising": [Strategy],       # Tier 2 - Validation pass
                "validated": [Strategy],       # Tier 3 - Elite Validation pass
                "elite": [Strategy],           # Tier 4 - Ranked and elite
                "elite_scores": [EliteScore],
                "summary": {
                    "total_input": int,
                    "candidates_count": int,
                    "promising_count": int,
                    "validated_count": int,
                    "elite_count": int,
                    "survival_rate": float,  # % that made it to elite
                }
            }
        """
        # Tier 1: Discovery - Find candidates
        candidates, discovery_errors = self.discovery_engine.discover(strategies)

        # Tier 2: Validation - Filter to promising
        promising, validation_errors = self.validation_engine.validate(candidates)

        # Tier 3: Elite Validation - Strict filtering
        validated, elite_validation_errors = self.elite_validation_engine.validate(promising)

        # Tier 4: Ranking - Score and rank elite
        elite, elite_scores = self.ranking_engine.rank(validated)

        # Calculate survival rate
        total = len(strategies)
        elite_count = len(elite)
        survival_rate = (elite_count / total * 100) if total > 0 else 0

        return {
            "candidates": candidates,
            "promising": promising,
            "validated": validated,
            "elite": elite,
            "elite_scores": elite_scores,
            "errors": {
                "discovery": discovery_errors,
                "validation": validation_errors,
                "elite_validation": elite_validation_errors,
            },
            "summary": {
                "total_input": total,
                "candidates_count": len(candidates),
                "promising_count": len(promising),
                "validated_count": len(validated),
                "elite_count": elite_count,
                "survival_rate": survival_rate,
                "discovery_pass_rate": (len(candidates) / total * 100) if total > 0 else 0,
                "promising_pass_rate": (len(promising) / len(candidates) * 100) if candidates else 0,
                "validated_pass_rate": (len(validated) / len(promising) * 100) if promising else 0,
                "elite_pass_rate": (len(elite) / len(validated) * 100) if validated else 0,
            },
        }

    def get_tier_explanation(self, tier: str) -> str:
        """Get human-readable explanation of each tier"""
        explanations = {
            "candidates": (
                "Candidate strategies passed initial screening. "
                "These strategies show potential but require further validation. "
                "Many will be filtered in subsequent stages."
            ),
            "promising": (
                "Promising strategies passed moderate validation. "
                "These strategies showed consistent performance across basic tests. "
                "They are worth deeper investigation."
            ),
            "validated": (
                "Validated strategies passed strict validation including robustness testing. "
                "These strategies demonstrated stability under various conditions. "
                "They are ready for real-world deployment consideration."
            ),
            "elite": (
                "Elite strategies represent the best discoveries. "
                "They passed all validation stages including walk-forward and robustness testing. "
                "They are recommended for dry-run or paper trading."
            ),
        }
        return explanations.get(tier, "Unknown tier")
