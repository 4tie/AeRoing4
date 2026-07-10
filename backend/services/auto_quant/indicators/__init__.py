"""Comprehensive Indicator Library for AutoQuant.

This module provides a market-condition-aware indicator library that AutoQuant
can dynamically select from, targeting different market conditions with hyperopt
optimization and confirmation logic.
"""

from .library import (
    IndicatorLibrary,
    IndicatorDefinition,
    IndicatorCategory,
    MarketCondition,
    get_indicator,
    get_indicators_by_category,
    get_indicators_by_market_condition,
)
from .selector import (
    MarketConditionDetector,
    IndicatorSelector,
    detect_market_condition,
    select_indicators_for_condition,
)
from .confirmation import (
    ConfirmationEngine,
    ConfirmationMode,
    ConfirmationRule,
    require_confirmation,
    validate_indicator_combination,
)

__all__ = [
    "IndicatorLibrary",
    "IndicatorDefinition",
    "IndicatorCategory",
    "MarketCondition",
    "get_indicator",
    "get_indicators_by_category",
    "get_indicators_by_market_condition",
    "MarketConditionDetector",
    "IndicatorSelector",
    "detect_market_condition",
    "select_indicators_for_condition",
    "ConfirmationEngine",
    "ConfirmationMode",
    "ConfirmationRule",
    "require_confirmation",
    "validate_indicator_combination",
]
