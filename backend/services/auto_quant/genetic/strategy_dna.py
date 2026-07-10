"""Strategy DNA encoding for genetic algorithm evolution.

This module defines the DNA structure for trading strategies, encoding
indicator weights, thresholds, risk parameters, and other strategy parameters
into a format suitable for genetic algorithm operations (crossover, mutation).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class StrategyDNA:
    """DNA encoding for a trading strategy.
    
    The DNA encodes all evolvable parameters of a strategy:
    - indicator_weights: Weights for 484+ technical indicators (0.0-1.0)
    - buy_thresholds: Thresholds for buy signals
    - sell_thresholds: Thresholds for sell signals
    - risk_parameters: Risk management parameters (stoploss, trailing, position sizing)
    - hold_days: Maximum holding period
    - regime_sensitivity: Sensitivity to market regime changes
    """
    
    # Indicator weights (484+ factors, normalized to 0-1)
    indicator_weights: dict[str, float] = field(default_factory=dict)
    
    # Buy signal thresholds
    buy_thresholds: dict[str, float] = field(default_factory=lambda: {
        "rsi_buy": 30.0,
        "macd_signal_buy": 0.0,
        "ema_cross_buy": 0.0,
        "atr_breakout_buy": 0.0,
    })
    
    # Sell signal thresholds
    sell_thresholds: dict[str, float] = field(default_factory=lambda: {
        "rsi_sell": 70.0,
        "macd_signal_sell": 0.0,
        "ema_cross_sell": 0.0,
        "atr_breakout_sell": 0.0,
    })
    
    # Risk parameters
    risk_parameters: dict[str, float] = field(default_factory=lambda: {
        "stoploss": -0.05,  # -5% stop loss
        "trailing_stop": 0.02,  # 2% trailing stop
        "trailing_only": False,
        "position_sizing": 0.1,  # 10% of capital per trade
        "max_open_trades": 5,
    })
    
    # Strategy parameters
    hold_days: int = 30
    regime_sensitivity: float = 0.5  # 0-1, higher = more sensitive to regime changes
    
    # Boolean indicator switches
    indicator_switches: dict[str, bool] = field(default_factory=lambda: {
        "use_ema_cross": True,
        "use_atr": True,
        "use_rsi": True,
        "use_macd": True,
        "use_bollinger": False,
        "use_adx": False,
    })
    
    def to_array(self) -> np.ndarray:
        """Convert DNA to numpy array for genetic algorithm operations.
        
        Returns:
            Flattened array of all DNA parameters
        """
        # Flatten indicator weights
        weight_values = list(self.indicator_weights.values())
        
        # Flatten buy thresholds
        buy_values = list(self.buy_thresholds.values())
        
        # Flatten sell thresholds
        sell_values = list(self.sell_thresholds.values())
        
        # Flatten risk parameters
        risk_values = [
            self.risk_parameters["stoploss"],
            self.risk_parameters["trailing_stop"],
            self.risk_parameters["position_sizing"],
            self.risk_parameters["max_open_trades"],
        ]
        
        # Strategy parameters
        strategy_values = [
            self.hold_days,
            self.regime_sensitivity,
        ]
        
        # Boolean switches (convert to 0/1)
        switch_values = [1 if v else 0 for v in self.indicator_switches.values()]
        
        # Concatenate all values
        all_values = weight_values + buy_values + sell_values + risk_values + strategy_values + switch_values
        
        return np.array(all_values, dtype=np.float64)
    
    @classmethod
    def from_array(cls, arr: np.ndarray, indicator_names: list[str]) -> "StrategyDNA":
        """Create DNA from numpy array.
        
        Args:
            arr: Flattened array of DNA parameters
            indicator_names: List of indicator names for weight reconstruction
            
        Returns:
            StrategyDNA instance
        """
        idx = 0
        
        # Reconstruct indicator weights
        n_weights = len(indicator_names)
        indicator_weights = {name: float(arr[idx:idx+n_weights][i]) for i, name in enumerate(indicator_names)}
        idx += n_weights
        
        # Reconstruct buy thresholds
        buy_thresholds = {
            "rsi_buy": float(arr[idx]),
            "macd_signal_buy": float(arr[idx+1]),
            "ema_cross_buy": float(arr[idx+2]),
            "atr_breakout_buy": float(arr[idx+3]),
        }
        idx += 4
        
        # Reconstruct sell thresholds
        sell_thresholds = {
            "rsi_sell": float(arr[idx]),
            "macd_signal_sell": float(arr[idx+1]),
            "ema_cross_sell": float(arr[idx+2]),
            "atr_breakout_sell": float(arr[idx+3]),
        }
        idx += 4
        
        # Reconstruct risk parameters
        risk_parameters = {
            "stoploss": float(arr[idx]),
            "trailing_stop": float(arr[idx+1]),
            "position_sizing": float(arr[idx+2]),
            "max_open_trades": int(arr[idx+3]),
        }
        idx += 4
        
        # Reconstruct strategy parameters
        hold_days = int(arr[idx])
        regime_sensitivity = float(arr[idx+1])
        idx += 2
        
        # Reconstruct boolean switches
        switch_names = ["use_ema_cross", "use_atr", "use_rsi", "use_macd", "use_bollinger", "use_adx"]
        indicator_switches = {name: bool(arr[idx+i]) for i, name in enumerate(switch_names)}
        
        return cls(
            indicator_weights=indicator_weights,
            buy_thresholds=buy_thresholds,
            sell_thresholds=sell_thresholds,
            risk_parameters=risk_parameters,
            hold_days=hold_days,
            regime_sensitivity=regime_sensitivity,
            indicator_switches=indicator_switches,
        )
    
    def validate(self) -> tuple[bool, str]:
        """Validate DNA parameters against safe ranges.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Validate indicator weights (0-1)
        for name, weight in self.indicator_weights.items():
            if not 0 <= weight <= 1:
                return False, f"Indicator weight {name} out of range: {weight}"
        
        # Validate buy thresholds
        if not 0 <= self.buy_thresholds["rsi_buy"] <= 100:
            return False, f"RSI buy threshold out of range: {self.buy_thresholds['rsi_buy']}"
        
        # Validate sell thresholds
        if not 0 <= self.sell_thresholds["rsi_sell"] <= 100:
            return False, f"RSI sell threshold out of range: {self.sell_thresholds['rsi_sell']}"
        
        # Validate risk parameters
        if not -0.5 <= self.risk_parameters["stoploss"] <= 0:
            return False, f"Stoploss out of range: {self.risk_parameters['stoploss']}"
        
        if not 0 <= self.risk_parameters["trailing_stop"] <= 0.5:
            return False, f"Trailing stop out of range: {self.risk_parameters['trailing_stop']}"
        
        if not 0.01 <= self.risk_parameters["position_sizing"] <= 1.0:
            return False, f"Position sizing out of range: {self.risk_parameters['position_sizing']}"
        
        if not 1 <= self.risk_parameters["max_open_trades"] <= 20:
            return False, f"Max open trades out of range: {self.risk_parameters['max_open_trades']}"
        
        # Validate strategy parameters
        if not 1 <= self.hold_days <= 365:
            return False, f"Hold days out of range: {self.hold_days}"
        
        if not 0 <= self.regime_sensitivity <= 1:
            return False, f"Regime sensitivity out of range: {self.regime_sensitivity}"
        
        return True, ""
    
    def clamp(self) -> "StrategyDNA":
        """Clamp DNA parameters to safe ranges.
        
        Returns:
            New StrategyDNA with clamped parameters
        """
        # Clamp indicator weights
        clamped_weights = {
            name: max(0.0, min(1.0, weight))
            for name, weight in self.indicator_weights.items()
        }
        
        # Clamp buy thresholds
        clamped_buy = {
            "rsi_buy": max(0.0, min(100.0, self.buy_thresholds["rsi_buy"])),
            "macd_signal_buy": self.buy_thresholds["macd_signal_buy"],
            "ema_cross_buy": self.buy_thresholds["ema_cross_buy"],
            "atr_breakout_buy": self.buy_thresholds["atr_breakout_buy"],
        }
        
        # Clamp sell thresholds
        clamped_sell = {
            "rsi_sell": max(0.0, min(100.0, self.sell_thresholds["rsi_sell"])),
            "macd_signal_sell": self.sell_thresholds["macd_signal_sell"],
            "ema_cross_sell": self.sell_thresholds["ema_cross_sell"],
            "atr_breakout_sell": self.sell_thresholds["atr_breakout_sell"],
        }
        
        # Clamp risk parameters
        clamped_risk = {
            "stoploss": max(-0.5, min(0.0, self.risk_parameters["stoploss"])),
            "trailing_stop": max(0.0, min(0.5, self.risk_parameters["trailing_stop"])),
            "position_sizing": max(0.01, min(1.0, self.risk_parameters["position_sizing"])),
            "max_open_trades": max(1, min(20, int(self.risk_parameters["max_open_trades"]))),
            "trailing_only": self.risk_parameters.get("trailing_only", False),
        }
        
        # Clamp strategy parameters
        clamped_hold_days = max(1, min(365, int(self.hold_days)))
        clamped_regime_sensitivity = max(0.0, min(1.0, self.regime_sensitivity))
        
        return StrategyDNA(
            indicator_weights=clamped_weights,
            buy_thresholds=clamped_buy,
            sell_thresholds=clamped_sell,
            risk_parameters=clamped_risk,
            hold_days=clamped_hold_days,
            regime_sensitivity=clamped_regime_sensitivity,
            indicator_switches=self.indicator_switches.copy(),
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert DNA to dictionary for JSON serialization."""
        return {
            "indicator_weights": self.indicator_weights,
            "buy_thresholds": self.buy_thresholds,
            "sell_thresholds": self.sell_thresholds,
            "risk_parameters": self.risk_parameters,
            "hold_days": self.hold_days,
            "regime_sensitivity": self.regime_sensitivity,
            "indicator_switches": self.indicator_switches,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StrategyDNA":
        """Create DNA from dictionary.
        
        Args:
            data: Dictionary with DNA parameters
            
        Returns:
            StrategyDNA instance
        """
        return cls(
            indicator_weights=data.get("indicator_weights", {}),
            buy_thresholds=data.get("buy_thresholds", {}),
            sell_thresholds=data.get("sell_thresholds", {}),
            risk_parameters=data.get("risk_parameters", {}),
            hold_days=data.get("hold_days", 30),
            regime_sensitivity=data.get("regime_sensitivity", 0.5),
            indicator_switches=data.get("indicator_switches", {}),
        )
    
    def mutate(self, mutation_rate: float = 0.1, mutation_strength: float = 0.1) -> "StrategyDNA":
        """Apply random mutations to DNA.
        
        Args:
            mutation_rate: Probability of mutating each parameter
            mutation_strength: Magnitude of mutation (relative to parameter range)
            
        Returns:
            New StrategyDNA with mutations applied
        """
        # Mutate indicator weights
        mutated_weights = {}
        for name, weight in self.indicator_weights.items():
            if np.random.random() < mutation_rate:
                # Add Gaussian noise
                noise = np.random.normal(0, mutation_strength)
                mutated_weights[name] = max(0.0, min(1.0, weight + noise))
            else:
                mutated_weights[name] = weight
        
        # Mutate buy thresholds
        mutated_buy = {}
        for key, value in self.buy_thresholds.items():
            if np.random.random() < mutation_rate:
                noise = np.random.normal(0, mutation_strength * 10)
                if key == "rsi_buy":
                    mutated_buy[key] = max(0.0, min(100.0, value + noise))
                else:
                    mutated_buy[key] = value + noise
            else:
                mutated_buy[key] = value
        
        # Mutate sell thresholds
        mutated_sell = {}
        for key, value in self.sell_thresholds.items():
            if np.random.random() < mutation_rate:
                noise = np.random.normal(0, mutation_strength * 10)
                if key == "rsi_sell":
                    mutated_sell[key] = max(0.0, min(100.0, value + noise))
                else:
                    mutated_sell[key] = value + noise
            else:
                mutated_sell[key] = value
        
        # Mutate risk parameters
        mutated_risk = {}
        for key, value in self.risk_parameters.items():
            if np.random.random() < mutation_rate:
                if isinstance(value, bool):
                    # Flip boolean
                    mutated_risk[key] = not value
                elif isinstance(value, (int, float)):
                    noise = np.random.normal(0, mutation_strength)
                    if key == "stoploss":
                        mutated_risk[key] = max(-0.5, min(0.0, value + noise))
                    elif key == "trailing_stop":
                        mutated_risk[key] = max(0.0, min(0.5, value + noise))
                    elif key == "position_sizing":
                        mutated_risk[key] = max(0.01, min(1.0, value + noise))
                    elif key == "max_open_trades":
                        mutated_risk[key] = max(1, min(20, int(value + noise * 5)))
                    else:
                        mutated_risk[key] = value + noise
                else:
                    mutated_risk[key] = value
            else:
                mutated_risk[key] = value
        
        # Mutate strategy parameters
        if np.random.random() < mutation_rate:
            mutated_hold_days = max(1, min(365, int(self.hold_days + np.random.normal(0, mutation_strength * 10))))
        else:
            mutated_hold_days = self.hold_days
        
        if np.random.random() < mutation_rate:
            mutated_regime_sensitivity = max(0.0, min(1.0, self.regime_sensitivity + np.random.normal(0, mutation_strength)))
        else:
            mutated_regime_sensitivity = self.regime_sensitivity
        
        # Mutate boolean switches
        mutated_switches = {}
        for key, value in self.indicator_switches.items():
            if np.random.random() < mutation_rate:
                mutated_switches[key] = not value
            else:
                mutated_switches[key] = value
        
        return StrategyDNA(
            indicator_weights=mutated_weights,
            buy_thresholds=mutated_buy,
            sell_thresholds=mutated_sell,
            risk_parameters=mutated_risk,
            hold_days=mutated_hold_days,
            regime_sensitivity=mutated_regime_sensitivity,
            indicator_switches=mutated_switches,
        )


def create_random_dna(indicator_names: list[str]) -> StrategyDNA:
    """Create a random DNA for initialization.
    
    Args:
        indicator_names: List of indicator names for weight initialization
        
    Returns:
        Random StrategyDNA instance
    """
    # Random indicator weights (0-1)
    indicator_weights = {
        name: np.random.random()
        for name in indicator_names
    }
    
    # Random buy thresholds
    buy_thresholds = {
        "rsi_buy": np.random.uniform(20, 40),
        "macd_signal_buy": np.random.uniform(-0.1, 0.1),
        "ema_cross_buy": np.random.uniform(-0.05, 0.05),
        "atr_breakout_buy": np.random.uniform(0.0, 0.1),
    }
    
    # Random sell thresholds
    sell_thresholds = {
        "rsi_sell": np.random.uniform(60, 80),
        "macd_signal_sell": np.random.uniform(-0.1, 0.1),
        "ema_cross_sell": np.random.uniform(-0.05, 0.05),
        "atr_breakout_sell": np.random.uniform(0.0, 0.1),
    }
    
    # Random risk parameters
    risk_parameters = {
        "stoploss": np.random.uniform(-0.15, -0.02),
        "trailing_stop": np.random.uniform(0.01, 0.05),
        "trailing_only": np.random.choice([True, False]),
        "position_sizing": np.random.uniform(0.05, 0.2),
        "max_open_trades": np.random.randint(3, 10),
    }
    
    # Random strategy parameters
    hold_days = np.random.randint(7, 60)
    regime_sensitivity = np.random.uniform(0.3, 0.8)
    
    # Random boolean switches
    indicator_switches = {
        "use_ema_cross": np.random.choice([True, False]),
        "use_atr": np.random.choice([True, False]),
        "use_rsi": np.random.choice([True, False]),
        "use_macd": np.random.choice([True, False]),
        "use_bollinger": np.random.choice([True, False]),
        "use_adx": np.random.choice([True, False]),
    }
    
    dna = StrategyDNA(
        indicator_weights=indicator_weights,
        buy_thresholds=buy_thresholds,
        sell_thresholds=sell_thresholds,
        risk_parameters=risk_parameters,
        hold_days=hold_days,
        regime_sensitivity=regime_sensitivity,
        indicator_switches=indicator_switches,
    )
    
    # Clamp to ensure valid ranges
    return dna.clamp()


def get_default_indicator_names() -> list[str]:
    """Get default list of indicator names for DNA encoding.
    
    Returns:
        List of 484+ indicator names
    """
    # This is a simplified list - in production, this would be generated
    # from the actual indicator library
    base_indicators = [
        "sma_short", "sma_long", "ema_short", "ema_long",
        "macd", "macd_signal", "macd_hist",
        "adx", "plus_di", "minus_di",
        "rsi", "stochastic_k", "stochastic_d",
        "atr", "atr_percent",
        "bollinger_upper", "bollinger_middle", "bollinger_lower",
        "bollinger_width", "bollinger_position",
        "obv", "vwap", "mfi",
        "skewness", "kurtosis", "hurst",
    ]
    
    # Generate variations for 484+ indicators
    indicator_names = []
    for indicator in base_indicators:
        for period in [5, 10, 20, 50, 100]:
            indicator_names.append(f"{indicator}_{period}")
    
    # Add some additional indicators
    indicator_names.extend([
        "momentum_10", "momentum_20", "momentum_50",
        "roc_5", "roc_10", "roc_20",
        "williams_r_14", "williams_r_20",
        "cci_20", "cci_50",
    ])
    
    # Ensure we have at least 484 indicators
    while len(indicator_names) < 484:
        indicator_names.append(f"indicator_{len(indicator_names)}")
    
    return indicator_names[:484]


__all__ = [
    "StrategyDNA",
    "create_random_dna",
    "get_default_indicator_names",
]
