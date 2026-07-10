"""Confirmation logic for multi-indicator validation.

Implements confirmation requirements and validation for indicator combinations
to reduce false signals and improve strategy reliability.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from .library import IndicatorDefinition


class ConfirmationMode(Enum):
    """Confirmation requirement modes."""
    NONE = "none"  # No confirmation required
    SINGLE = "single"  # At least one additional indicator
    MAJORITY = "majority"  # Majority of indicators must agree
    UNANIMOUS = "unanimous"  # All indicators must agree
    WEIGHTED = "weighted"  # Weighted consensus based on indicator weights


@dataclass
class ConfirmationRule:
    """Rule for indicator confirmation."""
    mode: ConfirmationMode
    min_confirmations: int = 1
    required_categories: Optional[List[str]] = None
    exclude_categories: Optional[List[str]] = None
    custom_validator: Optional[Callable[[pd.DataFrame, Dict[str, Any]], bool]] = None


class ConfirmationEngine:
    """Validates indicator combinations and applies confirmation logic."""
    
    def __init__(self):
        self.default_rules = {
            "trending": ConfirmationRule(
                mode=ConfirmationMode.MAJORITY,
                min_confirmations=2,
                required_categories=["trend"],
            ),
            "ranging": ConfirmationRule(
                mode=ConfirmationMode.SINGLE,
                min_confirmations=1,
                required_categories=["momentum"],
            ),
            "high_volatility": ConfirmationRule(
                mode=ConfirmationMode.MAJORITY,
                min_confirmations=2,
                required_categories=["volatility"],
            ),
            "low_volatility": ConfirmationRule(
                mode=ConfirmationMode.SINGLE,
                min_confirmations=1,
                required_categories=["volume"],
            ),
        }
    
    def validate_combination(
        self,
        indicators: List[IndicatorDefinition],
        market_condition: str,
        rule: Optional[ConfirmationRule] = None,
    ) -> tuple[bool, List[str]]:
        """Validate indicator combination against confirmation rules.
        
        Args:
            indicators: List of selected indicators
            market_condition: Current market condition
            rule: Custom confirmation rule (uses default if None)
        
        Returns:
            Tuple of (is_valid, list of validation messages)
        """
        messages = []
        
        # Get rule
        if rule is None:
            rule = self.default_rules.get(market_condition, ConfirmationRule(mode=ConfirmationMode.NONE))
        
        # Check required categories
        if rule.required_categories:
            present_categories = {ind.category.value for ind in indicators}
            missing = set(rule.required_categories) - present_categories
            if missing:
                messages.append(f"Missing required categories: {missing}")
                return False, messages
        
        # Check excluded categories
        if rule.exclude_categories:
            present_categories = {ind.category.value for ind in indicators}
            excluded = present_categories & set(rule.exclude_categories)
            if excluded:
                messages.append(f"Contains excluded categories: {excluded}")
                return False, messages
        
        # Check minimum confirmations
        if len(indicators) < rule.min_confirmations:
            messages.append(
                f"Insufficient indicators: {len(indicators)} < {rule.min_confirmations}"
            )
            return False, messages
        
        # Validate with custom validator if provided
        if rule.custom_validator:
            # Custom validation would need actual data
            # For now, just check that it's callable
            if not callable(rule.custom_validator):
                messages.append("Custom validator is not callable")
                return False, messages
        
        messages.append("Combination is valid")
        return True, messages
    
    def apply_confirmation_logic(
        self,
        dataframe: pd.DataFrame,
        indicators: List[IndicatorDefinition],
        rule: ConfirmationRule,
    ) -> pd.DataFrame:
        """Apply confirmation logic to dataframe.
        
        Args:
            dataframe: DataFrame with indicator values
            indicators: List of indicator definitions
            rule: Confirmation rule to apply
        
        Returns:
            DataFrame with confirmation signals
        """
        if rule.mode == ConfirmationMode.NONE:
            return dataframe
        
        # Collect individual signals
        signals = []
        weights = []
        
        for ind in indicators:
            # Generate signal for each indicator
            signal = self._generate_indicator_signal(dataframe, ind)
            if signal is not None:
                signals.append(signal)
                weights.append(ind.confirmation_weight)
        
        if not signals:
            return dataframe
        
        # Apply confirmation mode
        if rule.mode == ConfirmationMode.SINGLE:
            # At least one signal must be True
            combined = pd.concat(signals, axis=1).any(axis=1)
        elif rule.mode == ConfirmationMode.MAJORITY:
            # Majority of signals must be True
            combined = pd.concat(signals, axis=1).sum(axis=1) >= (len(signals) / 2)
        elif rule.mode == ConfirmationMode.UNANIMOUS:
            # All signals must be True
            combined = pd.concat(signals, axis=1).all(axis=1)
        elif rule.mode == ConfirmationMode.WEIGHTED:
            # Weighted consensus
            signals_df = pd.concat(signals, axis=1)
            weighted_sum = (signals_df * weights).sum(axis=1)
            total_weight = sum(weights)
            combined = weighted_sum / total_weight >= 0.5
        else:
            combined = pd.concat(signals, axis=1).any(axis=1)
        
        dataframe["confirmed_signal"] = combined.astype(int)
        return dataframe
    
    def _generate_indicator_signal(
        self, dataframe: pd.DataFrame, indicator: IndicatorDefinition
    ) -> Optional[pd.Series]:
        """Generate buy signal for an indicator.
        
        This is a simplified implementation. In production, each indicator
        would have its own signal generation logic based on its parameters.
        """
        # Simplified signal generation based on indicator type
        if indicator.name == "rsi":
            # RSI oversold signal
            if "rsi" in dataframe.columns:
                threshold = indicator.default_params.get("oversold", 30)
                return dataframe["rsi"] < threshold
        
        elif indicator.name == "macd":
            # MACD crossover signal
            if "macd" in dataframe.columns and "macdsignal" in dataframe.columns:
                import freqtrade.vendor.qtpylib.indicators as qtpylib
                return qtpylib.crossed_above(dataframe["macd"], dataframe["macdsignal"])
        
        elif indicator.name == "bollinger_bands":
            # BB breakout signal
            if "bb_lowerband" in dataframe.columns:
                factor = indicator.default_params.get("std_dev", 2.0)
                return dataframe["close"] < dataframe["bb_lowerband"] * factor
        
        elif indicator.name == "ema_crossover":
            # EMA crossover signal
            if "ema_fast" in dataframe.columns and "ema_slow" in dataframe.columns:
                import freqtrade.vendor.qtpylib.indicators as qtpylib
                return qtpylib.crossed_above(dataframe["ema_fast"], dataframe["ema_slow"])
        
        elif indicator.name == "adx":
            # ADX trend strength signal
            if "adx" in dataframe.columns:
                threshold = indicator.default_params.get("threshold", 25)
                return dataframe["adx"] > threshold
        
        # Default: return None if no signal logic defined
        return None
    
    def generate_confirmation_code(
        self, indicators: List[IndicatorDefinition], rule: ConfirmationRule
    ) -> str:
        """Generate Python code for confirmation logic in strategy.
        
        Args:
            indicators: List of indicator definitions
            rule: Confirmation rule to implement
        
        Returns:
            Python code string for confirmation logic
        """
        code_lines = []
        
        # Generate signal collection
        code_lines.append("# Collect individual indicator signals")
        code_lines.append("conditions = []")
        
        for ind in indicators:
            signal_code = self._generate_signal_code(ind)
            if signal_code:
                code_lines.append(signal_code)
        
        # Generate confirmation logic based on mode
        code_lines.append("\n# Apply confirmation logic")
        if rule.mode == ConfirmationMode.SINGLE:
            code_lines.append("if conditions:")
            code_lines.append("    combined = reduce(operator.and_, conditions)")
            code_lines.append("else:")
            code_lines.append("    combined = False")
        elif rule.mode == ConfirmationMode.MAJORITY:
            code_lines.append("if len(conditions) >= 2:")
            code_lines.append("    combined = sum(conditions) >= (len(conditions) / 2)")
            code_lines.append("else:")
            code_lines.append("    combined = conditions[0] if conditions else False")
        elif rule.mode == ConfirmationMode.UNANIMOUS:
            code_lines.append("if conditions:")
            code_lines.append("    combined = all(conditions)")
            code_lines.append("else:")
            code_lines.append("    combined = False")
        elif rule.mode == ConfirmationMode.WEIGHTED:
            code_lines.append("# Weighted consensus")
            code_lines.append("weights = [{}]".format(
                ", ".join(str(ind.confirmation_weight) for ind in indicators)
            ))
            code_lines.append("if conditions and weights:")
            code_lines.append("    weighted_sum = sum(c * w for c, w in zip(conditions, weights))")
            code_lines.append("    total_weight = sum(weights)")
            code_lines.append("    combined = weighted_sum / total_weight >= 0.5")
            code_lines.append("else:")
            code_lines.append("    combined = False")
        else:
            code_lines.append("combined = any(conditions) if conditions else False")
        
        code_lines.append("\ndataframe.loc[combined & (dataframe['volume'] > 0), 'enter_long'] = 1")
        
        return "\n".join(code_lines)
    
    def _generate_signal_code(self, indicator: IndicatorDefinition) -> str:
        """Generate Python code for indicator signal generation."""
        
        if indicator.name == "rsi":
            threshold = indicator.default_params.get("oversold", 30)
            return f"conditions.append(dataframe['rsi'] < {threshold})"
        
        elif indicator.name == "macd":
            return "conditions.append(qtpylib.crossed_above(dataframe['macd'], dataframe['macdsignal']))"
        
        elif indicator.name == "bollinger_bands":
            factor = indicator.default_params.get("std_dev", 2.0)
            return f"conditions.append(dataframe['close'] <= dataframe['bb_lowerband'] * {factor})"
        
        elif indicator.name == "ema_crossover":
            return "conditions.append(dataframe['ema_fast'] > dataframe['ema_slow'])"
        
        elif indicator.name == "adx":
            threshold = indicator.default_params.get("threshold", 25)
            return f"conditions.append(dataframe['adx'] > {threshold})"
        
        elif indicator.name == "stochastic":
            threshold = indicator.default_params.get("threshold", 30)
            return f"conditions.append(dataframe['stoch_slowk'] < {threshold})"
        
        elif indicator.name == "cci":
            threshold = indicator.default_params.get("threshold", -100)
            return f"conditions.append(dataframe['cci'] < {threshold})"
        
        elif indicator.name == "williams_r":
            threshold = indicator.default_params.get("threshold", -80)
            return f"conditions.append(dataframe['willr'] < {threshold})"
        
        elif indicator.name == "atr":
            return "conditions.append(dataframe['atr'] > dataframe['atr'].median())"
        
        elif indicator.name == "obv":
            return "conditions.append(dataframe['obv'] > dataframe['obv'].rolling(20).mean())"
        
        elif indicator.name == "mfi":
            threshold = indicator.default_params.get("threshold", 30)
            return f"conditions.append(dataframe['mfi'] < {threshold})"
        
        elif indicator.name == "parabolic_sar":
            return "conditions.append(dataframe['close'] > dataframe['sar'])"
        
        # Default: return empty string
        return ""


# Global instance
_engine = ConfirmationEngine()


def require_confirmation(
    indicators: List[IndicatorDefinition],
    market_condition: str,
    rule: Optional[ConfirmationRule] = None,
) -> tuple[bool, List[str]]:
    """Validate indicator combination against confirmation rules."""
    return _engine.validate_combination(indicators, market_condition, rule)


def validate_indicator_combination(
    indicators: List[IndicatorDefinition],
    market_condition: str,
    rule: Optional[ConfirmationRule] = None,
) -> tuple[bool, List[str]]:
    """Validate indicator combination against confirmation rules."""
    return _engine.validate_combination(indicators, market_condition, rule)
