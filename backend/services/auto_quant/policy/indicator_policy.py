"""Indicator policy configuration for AutoQuant.

Defines default indicator sets per trading style, risk profile preferences,
timeframe-appropriate indicators, and market condition trigger thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from ..indicators.library import IndicatorCategory, MarketCondition


@dataclass
class IndicatorPolicy:
    """Policy configuration for indicator selection."""
    
    trading_style: str
    risk_profile: str
    default_indicators: List[str]
    max_indicators: int
    require_confirmation: bool
    exclude_categories: Optional[List[str]] = None
    market_condition_thresholds: Optional[Dict[str, float]] = None


class IndicatorPolicyManager:
    """Manages indicator policies for different trading scenarios."""
    
    def __init__(self):
        self.policies: Dict[str, IndicatorPolicy] = {}
        self._register_default_policies()
    
    def _register_default_policies(self) -> None:
        """Register default indicator policies."""
        
        # Scalping policies (high frequency, low risk)
        self.policies["scalping_conservative"] = IndicatorPolicy(
            trading_style="scalping",
            risk_profile="conservative",
            default_indicators=["rsi", "macd", "bollinger_bands"],
            max_indicators=3,
            require_confirmation=True,
            exclude_categories=["pattern"],
            market_condition_thresholds={
                "atr_volatility_threshold": 0.2,
                "adx_trend_threshold": 20,
            },
        )
        
        self.policies["scalping_aggressive"] = IndicatorPolicy(
            trading_style="scalping",
            risk_profile="aggressive",
            default_indicators=["rsi", "macd", "ema_crossover", "atr"],
            max_indicators=4,
            require_confirmation=True,
            exclude_categories=["pattern"],
            market_condition_thresholds={
                "atr_volatility_threshold": 0.3,
                "adx_trend_threshold": 25,
            },
        )
        
        # Intraday policies (medium frequency)
        self.policies["intraday_conservative"] = IndicatorPolicy(
            trading_style="intraday",
            risk_profile="conservative",
            default_indicators=["rsi", "macd", "bollinger_bands", "adx"],
            max_indicators=4,
            require_confirmation=True,
            exclude_categories=["pattern"],
            market_condition_thresholds={
                "atr_volatility_threshold": 0.25,
                "adx_trend_threshold": 25,
            },
        )
        
        self.policies["intraday_aggressive"] = IndicatorPolicy(
            trading_style="intraday",
            risk_profile="aggressive",
            default_indicators=["rsi", "macd", "ema_crossover", "adx", "atr"],
            max_indicators=5,
            require_confirmation=True,
            exclude_categories=[],
            market_condition_thresholds={
                "atr_volatility_threshold": 0.35,
                "adx_trend_threshold": 30,
            },
        )
        
        # Swing trading policies (lower frequency)
        self.policies["swing_conservative"] = IndicatorPolicy(
            trading_style="swing",
            risk_profile="conservative",
            default_indicators=["rsi", "macd", "bollinger_bands", "adx", "ema_crossover"],
            max_indicators=5,
            require_confirmation=True,
            exclude_categories=[],
            market_condition_thresholds={
                "atr_volatility_threshold": 0.2,
                "adx_trend_threshold": 20,
            },
        )
        
        self.policies["swing_aggressive"] = IndicatorPolicy(
            trading_style="swing",
            risk_profile="aggressive",
            default_indicators=[
                "rsi", "macd", "bollinger_bands", "adx", "ema_crossover", 
                "stochastic", "atr"
            ],
            max_indicators=6,
            require_confirmation=True,
            exclude_categories=[],
            market_condition_thresholds={
                "atr_volatility_threshold": 0.3,
                "adx_trend_threshold": 25,
            },
        )
        
        # Position trading policies (long-term)
        self.policies["position_conservative"] = IndicatorPolicy(
            trading_style="position",
            risk_profile="conservative",
            default_indicators=["rsi", "macd", "ema_crossover", "adx", "atr"],
            max_indicators=5,
            require_confirmation=True,
            exclude_categories=["pattern"],
            market_condition_thresholds={
                "atr_volatility_threshold": 0.15,
                "adx_trend_threshold": 25,
            },
        )
        
        self.policies["position_aggressive"] = IndicatorPolicy(
            trading_style="position",
            risk_profile="aggressive",
            default_indicators=[
                "rsi", "macd", "ema_crossover", "adx", "atr", "parabolic_sar"
            ],
            max_indicators=6,
            require_confirmation=True,
            exclude_categories=[],
            market_condition_thresholds={
                "atr_volatility_threshold": 0.25,
                "adx_trend_threshold": 30,
            },
        )
    
    def get_policy(self, trading_style: str, risk_profile: str) -> IndicatorPolicy:
        """Get policy for trading style and risk profile.
        
        Args:
            trading_style: Trading style (scalping, intraday, swing, position)
            risk_profile: Risk profile (conservative, aggressive)
        
        Returns:
            IndicatorPolicy configuration
        """
        policy_key = f"{trading_style}_{risk_profile}"
        return self.policies.get(policy_key, self.policies["intraday_conservative"])
    
    def get_indicators_for_market_condition(
        self, condition: MarketCondition, trading_style: str, risk_profile: str
    ) -> List[str]:
        """Get recommended indicators for market condition.
        
        Args:
            condition: Market condition
            trading_style: Trading style
            risk_profile: Risk profile
        
        Returns:
            List of recommended indicator names
        """
        policy = self.get_policy(trading_style, risk_profile)
        
        # Market condition specific adjustments
        if condition == MarketCondition.TRENDING:
            # Prioritize trend indicators
            trending_indicators = ["ema_crossover", "adx", "parabolic_sar", "macd"]
            return [ind for ind in trending_indicators if ind in policy.default_indicators][:3]
        
        elif condition == MarketCondition.RANGING:
            # Prioritize momentum indicators
            ranging_indicators = ["rsi", "stochastic", "cci", "williams_r", "bollinger_bands"]
            return [ind for ind in ranging_indicators if ind in policy.default_indicators][:3]
        
        elif condition == MarketCondition.HIGH_VOLATILITY:
            # Prioritize volatility indicators
            volatility_indicators = ["atr", "bollinger_bands", "keltner_channels"]
            return [ind for ind in volatility_indicators if ind in policy.default_indicators][:3]
        
        elif condition == MarketCondition.LOW_VOLATILITY:
            # Prioritize volume indicators
            volume_indicators = ["obv", "mfi", "rsi"]
            return [ind for ind in volume_indicators if ind in policy.default_indicators][:3]
        
        return policy.default_indicators[:policy.max_indicators]
    
    def get_timeframe_appropriate_indicators(self, timeframe: str) -> List[str]:
        """Get indicators appropriate for timeframe.
        
        Args:
            timeframe: Candle timeframe (1m, 5m, 15m, 1h, 4h, 1d)
        
        Returns:
            List of appropriate indicator names
        """
        scalping_tfs = ["1m", "3m", "5m", "15m"]
        intraday_tfs = ["30m", "1h"]
        swing_tfs = ["4h"]
        position_tfs = ["1d"]
        
        if timeframe in scalping_tfs:
            return ["rsi", "macd", "bollinger_bands"]
        elif timeframe in intraday_tfs:
            return ["rsi", "macd", "bollinger_bands", "adx", "ema_crossover"]
        elif timeframe in swing_tfs:
            return ["rsi", "macd", "bollinger_bands", "adx", "ema_crossover", "stochastic"]
        elif timeframe in position_tfs:
            return ["rsi", "macd", "ema_crossover", "adx", "atr", "parabolic_sar"]
        else:
            return ["rsi", "macd", "bollinger_bands"]


# Global policy manager instance
_policy_manager = IndicatorPolicyManager()


def get_indicator_policy(trading_style: str, risk_profile: str) -> IndicatorPolicy:
    """Get indicator policy for trading style and risk profile."""
    return _policy_manager.get_policy(trading_style, risk_profile)


def get_indicators_for_condition(
    condition: MarketCondition, trading_style: str, risk_profile: str
) -> List[str]:
    """Get recommended indicators for market condition."""
    return _policy_manager.get_indicators_for_market_condition(
        condition, trading_style, risk_profile
    )


def get_timeframe_indicators(timeframe: str) -> List[str]:
    """Get indicators appropriate for timeframe."""
    return _policy_manager.get_timeframe_appropriate_indicators(timeframe)
