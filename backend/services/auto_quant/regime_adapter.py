"""Regime-aware parameter adaptation for trading strategies.

This module maps market regimes to optimal hyperopt parameters and provides
mechanisms for soft allocation (weighted blending) vs hard switching between
regime-specific configurations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .regime_detection import (
    REGIME_BULL,
    REGIME_CHOPPY,
    REGIME_CRISIS,
    REGIME_HIGH_VOL_TREND,
)

logger = logging.getLogger(__name__)


@dataclass
class RegimeConfig:
    """Configuration for a specific market regime."""
    
    regime: str
    hyperopt_loss: str
    hyperopt_spaces: list[str]
    param_overrides: dict[str, Any]
    description: str
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "regime": self.regime,
            "hyperopt_loss": self.hyperopt_loss,
            "hyperopt_spaces": self.hyperopt_spaces,
            "param_overrides": self.param_overrides,
            "description": self.description,
        }


# Default regime configurations
DEFAULT_REGIME_CONFIGS = {
    REGIME_BULL: RegimeConfig(
        regime=REGIME_BULL,
        hyperopt_loss="OnlyProfitHyperOptLoss",
        hyperopt_spaces=["buy", "roi"],
        param_overrides={
            "use_ema_cross": True,
            "use_atr": False,
            "use_adx": True,
            "use_rsi": False,
        },
        description="Bull market: Focus on profit maximization with trend-following indicators",
    ),
    REGIME_CHOPPY: RegimeConfig(
        regime=REGIME_CHOPPY,
        hyperopt_loss="SharpeHyperOptLoss",
        hyperopt_spaces=["buy", "sell", "stoploss"],
        param_overrides={
            "use_ema_cross": True,
            "use_atr": True,
            "use_adx": False,
            "use_rsi": True,
        },
        description="Choppy market: Focus on risk-adjusted returns with mean-reversion indicators",
    ),
    REGIME_HIGH_VOL_TREND: RegimeConfig(
        regime=REGIME_HIGH_VOL_TREND,
        hyperopt_loss="ProfitDrawDownHyperOptLoss",
        hyperopt_spaces=["buy", "trailing", "stoploss"],
        param_overrides={
            "use_ema_cross": True,
            "use_atr": True,
            "use_adx": True,
            "use_rsi": False,
        },
        description="High-volatility trend: Focus on drawdown control with trailing stops",
    ),
    REGIME_CRISIS: RegimeConfig(
        regime=REGIME_CRISIS,
        hyperopt_loss="CalmarHyperOptLoss",
        hyperopt_spaces=["stoploss", "trailing"],
        param_overrides={
            "use_ema_cross": False,
            "use_atr": True,
            "use_adx": False,
            "use_rsi": True,
        },
        description="Crisis market: Focus on capital preservation with defensive indicators",
    ),
}


class RegimeAdapter:
    """Adapts strategy parameters based on market regime."""
    
    def __init__(
        self,
        regime_configs: dict[str, RegimeConfig] | None = None,
        use_soft_allocation: bool = True,
    ):
        """Initialize regime adapter.
        
        Args:
            regime_configs: Dictionary of regime configurations (default: DEFAULT_REGIME_CONFIGS)
            use_soft_allocation: Whether to use soft allocation (weighted blending) vs hard switching
        """
        self.regime_configs = regime_configs or DEFAULT_REGIME_CONFIGS
        self.use_soft_allocation = use_soft_allocation
        
        logger.info(
            "RegimeAdapter initialized with %d regimes, soft_allocation=%s",
            len(self.regime_configs),
            self.use_soft_allocation,
        )
    
    def get_config(self, regime: str) -> RegimeConfig:
        """Get configuration for a specific regime.
        
        Args:
            regime: Regime identifier
            
        Returns:
            RegimeConfig for the specified regime
            
        Raises:
            KeyError: If regime is not found
        """
        if regime not in self.regime_configs:
            logger.warning("Regime %s not found, using choppy as fallback", regime)
            regime = REGIME_CHOPPY
        
        return self.regime_configs[regime]
    
    def adapt_parameters(
        self,
        regime: str,
        regime_probabilities: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Adapt hyperopt parameters based on regime.
        
        Args:
            regime: Current regime
            regime_probabilities: Optional regime probabilities for soft allocation
            
        Returns:
            Dictionary with adapted parameters:
            - hyperopt_loss: Loss function to use
            - hyperopt_spaces: Search spaces to optimize
            - param_overrides: Strategy parameter overrides
        """
        if self.use_soft_allocation and regime_probabilities:
            return self._soft_allocation(regime_probabilities)
        else:
            return self._hard_switch(regime)
    
    def _hard_switch(self, regime: str) -> dict[str, Any]:
        """Hard switch to regime-specific configuration."""
        config = self.get_config(regime)
        
        logger.info(
            "Hard switch to regime %s: loss=%s, spaces=%s",
            regime,
            config.hyperopt_loss,
            config.hyperopt_spaces,
        )
        
        return {
            "hyperopt_loss": config.hyperopt_loss,
            "hyperopt_spaces": config.hyperopt_spaces,
            "param_overrides": config.param_overrides.copy(),
            "allocation_method": "hard_switch",
        }
    
    def _soft_allocation(self, regime_probabilities: dict[str, float]) -> dict[str, Any]:
        """Soft allocation using weighted blending of regime configurations.
        
        Args:
            regime_probabilities: Dictionary mapping regimes to probabilities
            
        Returns:
            Dictionary with blended parameters
        """
        # Normalize probabilities
        total_prob = sum(regime_probabilities.values())
        if total_prob == 0:
            logger.warning("All regime probabilities are zero, using equal weights")
            regime_probabilities = {r: 0.25 for r in regime_probabilities.keys()}
            total_prob = 1.0
        
        normalized_probs = {r: p / total_prob for r, p in regime_probabilities.items()}
        
        # Weight hyperopt_loss by probability (choose highest probability)
        dominant_regime = max(normalized_probs.items(), key=lambda x: x[1])[0]
        hyperopt_loss = self.get_config(dominant_regime).hyperopt_loss
        
        # Weight hyperopt_spaces by probability (union of spaces with weights)
        space_weights = {}
        for regime, prob in normalized_probs.items():
            config = self.get_config(regime)
            for space in config.hyperopt_spaces:
                space_weights[space] = space_weights.get(space, 0) + prob
        
        # Select spaces with weight > 0.5 (majority vote)
        hyperopt_spaces = [space for space, weight in space_weights.items() if weight > 0.5]
        
        # Weight param_overrides by probability
        param_overrides = {}
        for regime, prob in normalized_probs.items():
            config = self.get_config(regime)
            for param, value in config.param_overrides.items():
                if param not in param_overrides:
                    param_overrides[param] = value
                else:
                    # For boolean params, use majority vote
                    if isinstance(value, bool):
                        if prob > 0.5:
                            param_overrides[param] = value
                    # For numeric params, use weighted average
                    elif isinstance(value, (int, float)):
                        current = param_overrides[param]
                        param_overrides[param] = current * (1 - prob) + value * prob
        
        logger.info(
            "Soft allocation: dominant=%s, loss=%s, spaces=%s",
            dominant_regime,
            hyperopt_loss,
            hyperopt_spaces,
        )
        
        return {
            "hyperopt_loss": hyperopt_loss,
            "hyperopt_spaces": hyperopt_spaces,
            "param_overrides": param_overrides,
            "allocation_method": "soft_allocation",
            "regime_weights": normalized_probs,
        }
    
    def get_regime_description(self, regime: str) -> str:
        """Get description for a regime.
        
        Args:
            regime: Regime identifier
            
        Returns:
            Description of the regime
        """
        config = self.get_config(regime)
        return config.description
    
    def update_config(self, regime: str, config: RegimeConfig) -> None:
        """Update configuration for a regime.
        
        Args:
            regime: Regime identifier
            config: New configuration
        """
        self.regime_configs[regime] = config
        logger.info("Updated configuration for regime %s", regime)
    
    def get_all_configs(self) -> dict[str, RegimeConfig]:
        """Get all regime configurations.
        
        Returns:
            Dictionary mapping regime identifiers to configurations
        """
        return self.regime_configs.copy()


def create_regime_adapter(
    regime_configs: dict[str, RegimeConfig] | None = None,
    use_soft_allocation: bool = True,
) -> RegimeAdapter:
    """Factory function to create a RegimeAdapter instance.
    
    Args:
        regime_configs: Dictionary of regime configurations
        use_soft_allocation: Whether to use soft allocation
        
    Returns:
        Configured RegimeAdapter instance
    """
    return RegimeAdapter(
        regime_configs=regime_configs,
        use_soft_allocation=use_soft_allocation,
    )


def get_regime_specific_ai_prompt(
    regime: str,
    regime_probabilities: dict[str, float] | None = None,
    current_state: Any = None,
) -> str:
    """Generate regime-specific AI prompt for Ollama.
    
    Args:
        regime: Current regime
        regime_probabilities: Optional regime probabilities
        current_state: Current pipeline state (for context)
        
    Returns:
        AI prompt with regime-specific guidance
    """
    adapter = create_regime_adapter()
    config = adapter.get_config(regime)
    
    prompt = f"""CURRENT MARKET REGIME: {regime.upper()}

Regime Description: {config.description}

Recommended Hyperopt Configuration:
- Loss Function: {config.hyperopt_loss}
- Search Spaces: {', '.join(config.hyperopt_spaces)}
- Parameter Overrides: {config.param_overrides}

"""
    
    if regime_probabilities:
        prompt += f"Regime Probabilities: {regime_probabilities}\n\n"
    
    prompt += """When suggesting parameter adjustments, consider:
1. The current regime characteristics
2. The recommended hyperopt configuration for this regime
3. Whether to use hard switching or soft allocation based on regime probabilities
4. Risk management appropriate for this regime (e.g., tighter stops in crisis)
"""
    
    return prompt


__all__ = [
    "RegimeConfig",
    "DEFAULT_REGIME_CONFIGS",
    "RegimeAdapter",
    "create_regime_adapter",
    "get_regime_specific_ai_prompt",
]
