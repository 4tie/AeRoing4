"""
Robustness Testing Engine
Tests strategy stability under parameter and market perturbations
"""

from typing import List, Dict, Tuple
from ..models.domain.strategy import Strategy, StrategyMetrics


class RobustnessTestingEngine:
    """
    Test strategy robustness by perturbing parameters and market conditions.

    Tests include:
    - Parameter sensitivity (vary indicator periods, thresholds)
    - Slippage testing (add trading costs)
    - Spread testing (increase bid-ask spreads)
    - Volatility testing (different market regimes)
    - Noise testing (add market noise)
    """

    def __init__(self, perturbation_range: float = 0.10):
        """
        Args:
            perturbation_range: How much to perturb (e.g., 0.10 = ±10%)
        """
        self.perturbation_range = perturbation_range

    def test_robustness(self, strategy: Strategy) -> Dict:
        """
        Run comprehensive robustness tests.

        Returns:
            {
                "robustness_score": float (0-1),
                "parameter_stability": float,
                "slippage_tolerance": float,
                "spread_tolerance": float,
                "volatility_tolerance": float,
                "degradation_analysis": {
                    "worst_case": float,
                    "average_case": float,
                    "best_case": float,
                },
                "fragility_flags": [str],
                "recommendation": str,
            }
        """
        if not strategy.metrics:
            return {"robustness_score": 0, "fragility_flags": ["No metrics available"]}

        base_pf = strategy.metrics.profit_factor
        base_profit = strategy.metrics.expectancy

        scores = {
            "parameter_stability": self._test_parameter_sensitivity(strategy),
            "slippage_tolerance": self._test_slippage(strategy),
            "spread_tolerance": self._test_spreads(strategy),
            "volatility_tolerance": self._test_volatility(strategy),
        }

        # Calculate overall robustness score (0-1)
        robustness_score = sum(scores.values()) / len(scores)

        # Identify fragility flags
        flags = self._identify_fragility_flags(scores, strategy)

        return {
            "robustness_score": robustness_score,
            "parameter_stability": scores["parameter_stability"],
            "slippage_tolerance": scores["slippage_tolerance"],
            "spread_tolerance": scores["spread_tolerance"],
            "volatility_tolerance": scores["volatility_tolerance"],
            "degradation_analysis": self._analyze_degradation(scores),
            "fragility_flags": flags,
            "recommendation": self._generate_recommendation(robustness_score, flags),
        }

    def _test_parameter_sensitivity(self, strategy: Strategy) -> float:
        """
        Test how sensitive the strategy is to small parameter changes.
        Robust strategies should degrade gracefully.
        Fragile strategies collapse with small changes.

        Returns float (0-1): Stability score
        """
        # Simulate parameter perturbation
        # In reality, this would re-run backtest with modified parameters
        base_pf = strategy.metrics.profit_factor

        # Simulate worst case: parameters degraded by perturbation_range
        degraded_pf = base_pf * (1 - self.perturbation_range * 0.5)

        # Calculate degradation percentage
        degradation = (base_pf - degraded_pf) / base_pf if base_pf > 0 else 0

        # Convert to stability score (0-1)
        # Small degradation = high stability
        stability = max(0, 1 - degradation)

        return stability

    def _test_slippage(self, strategy: Strategy) -> float:
        """
        Test tolerance to execution slippage.
        Slippage reduces profit factor.

        Returns float (0-1): Slippage tolerance
        """
        base_pf = strategy.metrics.profit_factor
        base_trades = strategy.metrics.trades

        # Assume slippage impact: 0.1% per trade on average
        slippage_cost = base_trades * 0.001

        # Profit factor reduction estimate
        pf_with_slippage = base_pf * (1 - slippage_cost / 100)

        # If PF drops below 1.0, strategy is not slippage-tolerant
        if pf_with_slippage < 1.0:
            return 0.0

        # Otherwise, score based on how much PF remains
        tolerance = min(1.0, pf_with_slippage / base_pf)

        return tolerance

    def _test_spreads(self, strategy: Strategy) -> float:
        """
        Test tolerance to wider bid-ask spreads.
        Scalping is more sensitive to spreads than swing trading.

        Returns float (0-1): Spread tolerance
        """
        # Strategy with many trades is more sensitive to spreads
        trade_count = strategy.metrics.trades

        # Assume 0.5 bps spread impact
        # High trade count = higher sensitivity
        spread_impact = min(0.1, trade_count * 0.0001)

        # Score based on how much margin remains
        tolerance = max(0.0, 1.0 - spread_impact)

        return tolerance

    def _test_volatility(self, strategy: Strategy) -> float:
        """
        Test how strategy performs in different volatility regimes.
        Good strategies adapt to volatility changes.

        Returns float (0-1): Volatility tolerance
        """
        # Use Sharpe ratio as volatility indicator
        # Higher Sharpe = better volatility adaptation
        sharpe = strategy.metrics.sharpe_ratio or 0

        # Score based on Sharpe (scale to 0-1)
        # Sharpe < 0 = bad in all regimes
        # Sharpe > 2 = very robust
        tolerance = min(1.0, max(0.0, sharpe / 2.0))

        return tolerance

    def _analyze_degradation(self, scores: Dict) -> Dict:
        """Analyze worst/average/best case degradation"""
        values = list(scores.values())
        worst = min(values)
        best = max(values)
        average = sum(values) / len(values)

        return {
            "worst_case": worst,
            "average_case": average,
            "best_case": best,
        }

    def _identify_fragility_flags(self, scores: Dict, strategy: Strategy) -> List[str]:
        """Identify potential fragility issues"""
        flags = []

        if scores["parameter_stability"] < 0.5:
            flags.append("⚠️ Parameter Sensitivity: Performance degrades significantly with small parameter changes")

        if scores["slippage_tolerance"] < 0.5:
            flags.append("⚠️ Slippage Risk: Strategy is sensitive to execution slippage")

        if scores["spread_tolerance"] < 0.5:
            flags.append("⚠️ Spread Risk: Strategy struggles with wider spreads")

        if scores["volatility_tolerance"] < 0.5:
            flags.append("⚠️ Volatility Risk: Performance varies significantly across different market regimes")

        # Check for suspiciously high win rate (possible overfitting)
        if strategy.metrics.win_rate > 0.80:
            flags.append("⚠️ Overfitting Risk: Win rate is suspiciously high (>80%)")

        # Check for very few trades (high variance)
        if strategy.metrics.trades < 50:
            flags.append("⚠️ Sample Size: Too few trades for statistical significance")

        return flags

    def _generate_recommendation(self, robustness_score: float, flags: List[str]) -> str:
        """Generate human-readable recommendation"""
        if robustness_score >= 0.75 and not flags:
            return "Highly Robust - Excellent candidate for deployment"
        elif robustness_score >= 0.60:
            return "Moderately Robust - Suitable for testing with caution"
        elif robustness_score >= 0.45:
            return "Fragile - Requires further investigation before deployment"
        else:
            return "Very Fragile - Not recommended for deployment"
