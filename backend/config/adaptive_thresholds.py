"""Deprecated compatibility wrapper for AutoQuant threshold policy.

Threshold values are loaded from ``backend/config/thresholds/*.json`` through
``backend.services.auto_quant.policy``.  This module keeps the legacy class API
available without maintaining a second set of threshold constants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.services.auto_quant.policy import load_policy, thresholds_for


@dataclass
class ValidationThresholds:
    """Thresholds for a validation tier."""

    min_profit_factor: float
    max_drawdown: float
    min_expectancy: float
    min_trades: int
    min_win_rate: float = 0.0
    min_oos_profit: float = 0.0
    min_robustness_score: float = 0.0
    min_walk_forward_score: float = 0.0


class AdaptiveThresholdConfig:
    """Compatibility facade over the JSON-backed policy threshold system."""

    def __init__(self, style: str = "swing"):
        policy = load_policy()
        if style not in policy.thresholds:
            raise ValueError(f"Unknown style: {style}. Choose from {list(policy.thresholds.keys())}")
        self.style = style

    def get_thresholds(
        self,
        tier: Literal["discovery", "validation", "elite"],
        timeframe: str = "1h",
        *,
        timerange: str | None = None,
        timerange_days: int | None = None,
    ) -> ValidationThresholds:
        """Return thresholds for the requested tier.

        ``timeframe`` is accepted for legacy callers but no longer changes the
        threshold values. Trade-count requirements are duration-adjusted by the
        policy layer when ``timerange`` or ``timerange_days`` is provided.
        """
        del timeframe
        if tier not in ("discovery", "validation", "elite"):
            raise ValueError(f"Unknown tier: {tier}")

        policy_tier = "elite_validation" if tier == "elite" else tier
        gates = thresholds_for(
            self.style,
            "balanced",
            policy_tier,
            timerange=timerange,
            timerange_days=timerange_days,
        )
        return ValidationThresholds(
            min_profit_factor=float(gates.get("min_profit_factor", 1.0) or 1.0),
            max_drawdown=float(gates.get("max_drawdown", 1.0) or 1.0),
            min_expectancy=float(gates.get("min_expectancy", 0.0) or 0.0),
            min_trades=int(gates.get("min_trades", 1) or 1),
            min_win_rate=float(gates.get("min_win_rate", 0.0) or 0.0),
            min_oos_profit=float(gates.get("min_oos_profit", 0.0) or 0.0),
            min_robustness_score=float(gates.get("min_robustness_score", 0.0) or 0.0),
            min_walk_forward_score=float(
                gates.get("min_walk_forward_score", gates.get("min_walk_forward_pass_rate", 0.0))
                or 0.0
            ),
        )

    def get_all_tiers(self, timeframe: str = "1h") -> dict[str, ValidationThresholds]:
        """Return thresholds for all legacy tiers."""
        return {
            "discovery": self.get_thresholds("discovery", timeframe),
            "validation": self.get_thresholds("validation", timeframe),
            "elite": self.get_thresholds("elite", timeframe),
        }
