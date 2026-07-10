"""Dynamic indicator selection based on market conditions.

Implements market condition detection and intelligent indicator selection
for AutoQuant strategy generation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd
import talib.abstract as ta

from .library import (
    IndicatorDefinition,
    IndicatorLibrary,
    MarketCondition,
    get_indicators_by_market_condition,
)


class MarketCondition(Enum):
    """Market condition categories for indicator selection."""
    TRENDING = "trending"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"


@dataclass
class MarketConditionResult:
    """Result of market condition detection."""
    condition: MarketCondition
    confidence: float
    metrics: Dict[str, float]
    
    def __str__(self) -> str:
        return f"{self.condition.value} (confidence: {self.confidence:.2f})"


class MarketConditionDetector:
    """Detects current market conditions from price data."""
    
    def __init__(self, atr_period: int = 14, adx_period: int = 14, lookback: int = 50):
        self.atr_period = atr_period
        self.adx_period = adx_period
        self.lookback = lookback
    
    def detect(self, dataframe: pd.DataFrame) -> MarketConditionResult:
        """Detect market condition from dataframe."""
        if len(dataframe) < self.lookback:
            return MarketConditionResult(
                condition=MarketCondition.RANGING,
                confidence=0.5,
                metrics={"reason": "insufficient_data"}
            )
        
        # Calculate indicators
        atr = ta.ATR(dataframe, timeperiod=self.atr_period)
        adx = ta.ADX(dataframe, timeperiod=self.adx_period)
        
        # Use recent data for detection
        recent_atr = atr.tail(self.lookback)
        recent_adx = adx.tail(self.lookback)
        
        # Volatility detection
        atr_median = recent_atr.median()
        atr_current = recent_atr.iloc[-1]
        atr_pct_change = (atr_current - atr_median) / atr_median if atr_median > 0 else 0
        
        # Trend strength detection
        adx_mean = recent_adx.mean()
        adx_current = recent_adx.iloc[-1]
        
        # Price range detection (trending vs ranging)
        recent_high = dataframe["high"].tail(self.lookback).max()
        recent_low = dataframe["low"].tail(self.lookback).min()
        price_range = (recent_high - recent_low) / dataframe["close"].iloc[-1]
        
        metrics = {
            "atr_current": float(atr_current),
            "atr_median": float(atr_median),
            "atr_pct_change": float(atr_pct_change),
            "adx_current": float(adx_current),
            "adx_mean": float(adx_mean),
            "price_range": float(price_range),
        }
        
        # Determine condition
        condition, confidence = self._classify_condition(
            atr_pct_change, adx_current, price_range, metrics
        )
        
        return MarketConditionResult(
            condition=condition,
            confidence=confidence,
            metrics=metrics,
        )
    
    def _classify_condition(
        self, atr_pct_change: float, adx: float, price_range: float, metrics: Dict[str, float]
    ) -> tuple[MarketCondition, float]:
        """Classify market condition from metrics."""
        
        # High volatility detection
        if atr_pct_change > 0.3:
            if adx > 25:
                return MarketCondition.HIGH_VOLATILITY, 0.8
            else:
                return MarketCondition.HIGH_VOLATILITY, 0.6
        
        # Low volatility detection
        if atr_pct_change < -0.2:
            return MarketCondition.LOW_VOLATILITY, 0.7
        
        # Trend detection
        if adx > 25:
            if price_range > 0.05:
                return MarketCondition.TRENDING, 0.8
            else:
                return MarketCondition.TRENDING, 0.6
        
        # Ranging detection
        if adx < 20 and price_range < 0.03:
            return MarketCondition.RANGING, 0.8
        elif adx < 25:
            return MarketCondition.RANGING, 0.6
        
        # Default to trending with moderate confidence
        return MarketCondition.TRENDING, 0.5


class IndicatorSelector:
    """Selects indicators based on market conditions and strategy requirements."""
    
    def __init__(self, library: Optional[IndicatorLibrary] = None):
        self.library = library or IndicatorLibrary()
    
    def select(
        self,
        condition: MarketCondition,
        max_indicators: int = 5,
        require_confirmation: bool = True,
        exclude_categories: Optional[List[str]] = None,
    ) -> List[IndicatorDefinition]:
        """Select indicators for given market condition.
        
        Args:
            condition: Market condition to optimize for
            max_indicators: Maximum number of indicators to select
            require_confirmation: Whether to require confirmation indicators
            exclude_categories: Categories to exclude from selection
        
        Returns:
            List of selected indicator definitions
        """
        # Get indicators suitable for condition
        suitable = get_indicators_by_market_condition(condition)
        
        # Filter by excluded categories
        if exclude_categories:
            suitable = [ind for ind in suitable if ind.category.value not in exclude_categories]
        
        # Sort by confirmation weight (higher = more reliable)
        suitable.sort(key=lambda x: x.confirmation_weight, reverse=True)
        
        # Select top indicators
        selected = suitable[:max_indicators]
        
        # Add confirmation indicators if required
        if require_confirmation and len(selected) < max_indicators:
            confirmation_indicators = self._get_confirmation_indicators(
                condition, selected, max_indicators - len(selected)
            )
            selected.extend(confirmation_indicators)
        
        return selected
    
    def _get_confirmation_indicators(
        self, condition: MarketCondition, current: List[IndicatorDefinition], needed: int
    ) -> List[IndicatorDefinition]:
        """Get additional indicators for confirmation."""
        
        # Get indicators not already selected
        suitable = get_indicators_by_market_condition(condition)
        current_names = {ind.name for ind in current}
        available = [ind for ind in suitable if ind.name not in current_names]
        
        # Prioritize different categories for diversification
        current_categories = {ind.category for ind in current}
        diversified = [ind for ind in available if ind.category not in current_categories]
        others = [ind for ind in available if ind.category in current_categories]
        
        # Select from diversified first, then others
        confirmation = diversified[:needed] + others[:needed - len(diversified)]
        return confirmation[:needed]
    
    def generate_strategy_indicators(
        self,
        dataframe: pd.DataFrame,
        strategy_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generate indicator configuration for strategy.
        
        Args:
            dataframe: Price data for market condition detection
            strategy_config: Strategy configuration with preferences
        
        Returns:
            Dictionary with selected indicators and their parameters
        """
        # Detect market condition
        detector = MarketConditionDetector()
        condition_result = detector.detect(dataframe)
        
        # Select indicators
        max_indicators = strategy_config.get("max_indicators", 5)
        require_confirmation = strategy_config.get("require_confirmation", True)
        exclude_categories = strategy_config.get("exclude_categories", [])
        
        selected = self.select(
            condition_result.condition,
            max_indicators=max_indicators,
            require_confirmation=require_confirmation,
            exclude_categories=exclude_categories,
        )
        
        # Generate indicator configuration
        indicators_config = {
            "market_condition": condition_result.condition.value,
            "condition_confidence": condition_result.confidence,
            "indicators": [],
        }
        
        for ind in selected:
            indicators_config["indicators"].append({
                "name": ind.name,
                "category": ind.category.value,
                "params": ind.default_params,
                "param_ranges": ind.param_ranges,
                "confirmation_weight": ind.confirmation_weight,
            })
        
        return indicators_config


# Global instances
_detector = MarketConditionDetector()
_selector = IndicatorSelector()


def detect_market_condition(dataframe: pd.DataFrame) -> MarketConditionResult:
    """Detect market condition from price data."""
    return _detector.detect(dataframe)


def select_indicators_for_condition(
    condition: MarketCondition,
    max_indicators: int = 5,
    require_confirmation: bool = True,
    exclude_categories: Optional[List[str]] = None,
) -> List[IndicatorDefinition]:
    """Select indicators for given market condition."""
    return _selector.select(
        condition,
        max_indicators=max_indicators,
        require_confirmation=require_confirmation,
        exclude_categories=exclude_categories,
    )
