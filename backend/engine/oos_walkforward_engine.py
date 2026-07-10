"""
Out-of-Sample (OOS) and Walk-Forward Testing Engine
Tests strategy generalization to unseen data
"""

from typing import List, Dict, Optional
from ..models.domain.strategy import Strategy, StrategyMetrics


class OOSAndWalkForwardEngine:
    """
    Test strategy performance on out-of-sample (unseen) data.

    Out-of-Sample Test:
    - Train on Period A (e.g., 2022-2024)
    - Test on Period B (e.g., 2025)
    - Optimization only on Period A
    - Period B must remain completely unseen

    Walk-Forward Test:
    - Train 2022, Test 2023
    - Train 2023, Test 2024
    - Train 2024, Test 2025
    - Measure consistency across windows

    Key Principle:
    Many strategies collapse during OOS/WF testing.
    This is GOOD - it filters out overfit strategies.
    """

    def test_oos_performance(
        self,
        strategy: Strategy,
        is_backtest_profit: float,
        oos_profit: float,
    ) -> Dict:
        """
        Test out-of-sample performance.

        Args:
            strategy: Strategy being tested
            is_backtest_profit: In-sample (backtest) profit
            oos_profit: Out-of-sample profit

        Returns:
            {
                "oos_passed": bool,
                "oos_score": float (0-1),
                "profit_degradation": float (%), # How much profit dropped
                "consistency": str,  # "Excellent", "Good", "Poor", "Collapsed"
                "explanation": str,
            }
        """
        if is_backtest_profit <= 0:
            return {
                "oos_passed": False,
                "oos_score": 0.0,
                "profit_degradation": float('inf'),
                "consistency": "No baseline",
                "explanation": "In-sample profit is zero or negative",
            }

        # Calculate profit degradation
        degradation = (is_backtest_profit - oos_profit) / is_backtest_profit

        # Determine if strategy passed OOS
        passed = oos_profit > 0 and degradation < 0.50

        # Score consistency
        if degradation < 0.10:
            consistency = "Excellent"
        elif degradation < 0.30:
            consistency = "Good"
        elif degradation < 0.60:
            consistency = "Poor"
        else:
            consistency = "Collapsed"

        # Generate score (0-1)
        # Perfect score: OOS = IS (degradation = 0)
        # Acceptable: OOS = 50% of IS (degradation = 0.50)
        # Unacceptable: OOS < 0 (strategy reversed)
        oos_score = max(0.0, 1.0 - degradation)

        explanation = self._generate_oos_explanation(
            is_backtest_profit, oos_profit, degradation, consistency
        )

        return {
            "oos_passed": passed,
            "oos_score": oos_score,
            "is_profit": is_backtest_profit,
            "oos_profit": oos_profit,
            "profit_degradation_pct": degradation * 100,
            "consistency": consistency,
            "explanation": explanation,
        }

    def test_walk_forward(
        self,
        strategy: Strategy,
        windows: List[Dict],  # [{"is_profit": x, "oos_profit": y, "period": "2022"}, ...]
        latest_window_must_not_fail: bool = True,
    ) -> Dict:
        """
        Test walk-forward consistency across multiple periods.

        Args:
            strategy: Strategy being tested
            windows: List of WF test results for each period
            latest_window_must_not_fail: If True, latest window collapse blocks validation

        Returns:
            {
                "wf_passed": bool,
                "wf_score": float (0-1),
                "window_count": int,
                "passing_windows": int,
                "avg_degradation": float (%),
                "consistency_std": float,  # Lower = more consistent
                "latest_window_passed": bool,
                "recommendation": str,
            }
        """
        if not windows:
            return {
                "wf_passed": False,
                "wf_score": 0.0,
                "window_count": 0,
                "passing_windows": 0,
                "latest_window_passed": None,
                "explanation": "No walk-forward data available",
            }

        degradations = []
        passing = 0
        latest_window_passed = True

        for i, window in enumerate(windows):
            is_profit = window.get("is_profit", 0)
            oos_profit = window.get("oos_profit", 0)

            if is_profit <= 0:
                continue

            degradation = (is_profit - oos_profit) / is_profit
            degradations.append(degradation)

            window_passed = oos_profit > 0 and degradation < 0.50
            if window_passed:
                passing += 1

            # Check if this is the latest window (last in list)
            if i == len(windows) - 1:
                latest_window_passed = window_passed

        if not degradations:
            return {
                "wf_passed": False,
                "wf_score": 0.0,
                "window_count": len(windows),
                "passing_windows": 0,
                "latest_window_passed": None,
                "explanation": "No valid windows for analysis",
            }

        # Calculate metrics
        avg_degradation = sum(degradations) / len(degradations)
        wf_score = max(0.0, 1.0 - avg_degradation)

        # Calculate consistency (std dev of degradations)
        variance = sum((d - avg_degradation) ** 2 for d in degradations) / len(degradations)
        consistency_std = variance ** 0.5

        # Determine if walk-forward passed
        # Needs: >60% windows passing AND avg degradation < 40%
        base_passed = (passing / len(degradations) >= 0.60) and (avg_degradation < 0.40)

        # Additional check: latest window must not fail catastrophically
        if latest_window_must_not_fail and not latest_window_passed:
            wf_passed = False
        else:
            wf_passed = base_passed

        explanation = self._generate_wf_explanation(
            wf_passed, base_passed, latest_window_passed, latest_window_must_not_fail,
            passing, len(degradations), avg_degradation, consistency_std
        )

        return {
            "wf_passed": wf_passed,
            "wf_score": wf_score,
            "window_count": len(windows),
            "passing_windows": passing,
            "window_pass_rate": (passing / len(degradations) * 100) if degradations else 0,
            "avg_degradation_pct": avg_degradation * 100,
            "consistency_std": consistency_std,
            "latest_window_passed": latest_window_passed,
            "latest_window_required": latest_window_must_not_fail,
            "explanation": explanation,
        }

    def _generate_oos_explanation(
        self,
        is_profit: float,
        oos_profit: float,
        degradation: float,
        consistency: str,
    ) -> str:
        """Generate human-readable OOS explanation"""
        if oos_profit <= 0:
            return (
                f"Strategy collapsed during OOS testing. "
                f"In-sample: +{is_profit:.2f}, Out-of-Sample: {oos_profit:.2f}. "
                f"This indicates severe overfitting to historical data."
            )

        if degradation < 0.10:
            return (
                f"Excellent OOS performance! Strategy maintained {100-degradation*100:.0f}% of profit. "
                f"In-sample: {is_profit:.2f}, Out-of-Sample: {oos_profit:.2f}. "
                f"Strategy shows strong generalization."
            )

        if degradation < 0.30:
            return (
                f"Good OOS performance. Strategy maintained {100-degradation*100:.0f}% of profit. "
                f"In-sample: {is_profit:.2f}, Out-of-Sample: {oos_profit:.2f}. "
                f"Some degradation is expected, but overall robust."
            )

        return (
            f"Poor OOS performance. Strategy degraded {degradation*100:.0f}%. "
            f"In-sample: {is_profit:.2f}, Out-of-Sample: {oos_profit:.2f}. "
            f"High risk of overfitting. Caution recommended."
        )

    def _generate_wf_explanation(
        self,
        passed: bool,
        base_passed: bool,
        latest_window_passed: bool,
        latest_window_required: bool,
        passing_windows: int,
        total_windows: int,
        avg_degradation: float,
        consistency_std: float,
    ) -> str:
        """Generate human-readable walk-forward explanation"""
        if not latest_window_required:
            # Legacy behavior when latest window check is disabled
            if base_passed:
                return (
                    f"Strong walk-forward consistency. "
                    f"Strategy passed {passing_windows}/{total_windows} validation windows. "
                    f"Average degradation: {avg_degradation*100:.1f}%. "
                    f"Consistency score: {100-consistency_std*100:.0f}%. "
                    f"Ready for deployment."
                )
            if passing_windows / total_windows >= 0.50:
                return (
                    f"Moderate walk-forward results. "
                    f"Strategy passed {passing_windows}/{total_windows} windows. "
                    f"Some periods showed strong results, others weak. "
                    f"May work in certain market conditions."
                )
            return (
                f"Poor walk-forward consistency. "
                f"Strategy passed only {passing_windows}/{total_windows} windows. "
                f"Performance is highly dependent on specific periods. "
                f"Not recommended for live trading."
            )

        # New behavior with latest window check enabled
        if not latest_window_passed:
            return (
                f"Latest walk-forward window failed catastrophically. "
                f"Strategy passed {passing_windows}/{total_windows} windows overall, "
                f"but the most recent period collapsed. "
                f"This indicates the strategy may not work in current market conditions. "
                f"Not recommended for live trading."
            )

        if passed:
            return (
                f"Strong walk-forward consistency. "
                f"Strategy passed {passing_windows}/{total_windows} validation windows, "
                f"including the latest window. "
                f"Average degradation: {avg_degradation*100:.1f}%. "
                f"Consistency score: {100-consistency_std*100:.0f}%. "
                f"Ready for deployment."
            )

        if passing_windows / total_windows >= 0.50:
            return (
                f"Moderate walk-forward results. "
                f"Strategy passed {passing_windows}/{total_windows} windows. "
                f"Some periods showed strong results, others weak. "
                f"May work in certain market conditions."
            )

        return (
            f"Poor walk-forward consistency. "
            f"Strategy passed only {passing_windows}/{total_windows} windows. "
            f"Performance is highly dependent on specific periods. "
            f"Not recommended for live trading."
        )
