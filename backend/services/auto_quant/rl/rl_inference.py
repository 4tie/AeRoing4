"""RL inference and deployment for trading agents.

This module handles inference (prediction) for trained RL agents,
including model loading, batch prediction, and confidence scoring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np

from .rl_agents import AgentConfig, create_agent, create_ensemble
from .rl_environment import TradingConfig, create_trading_env

logger = logging.getLogger(__name__)


@dataclass
class InferenceResult:
    """Result of RL agent inference."""
    
    action: np.ndarray
    confidence: float
    position_size: float
    entry_signal: float
    exit_signal: float
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "action": self.action.tolist(),
            "confidence": self.confidence,
            "position_size": self.position_size,
            "entry_signal": self.entry_signal,
            "exit_signal": self.exit_signal,
        }


class RLInference:
    """Handler for RL agent inference and deployment."""
    
    def __init__(
        self,
        model_path: str,
        algorithm: str = "ppo",
        use_ensemble: bool = False,
        ensemble_algorithms: list[str] | None = None,
    ):
        """Initialize RL inference handler.
        
        Args:
            model_path: Path to trained model(s)
            algorithm: Algorithm name for single agent
            use_ensemble: Whether to use ensemble of agents
            ensemble_algorithms: List of algorithms for ensemble
        """
        self.model_path = Path(model_path)
        self.algorithm = algorithm
        self.use_ensemble = use_ensemble
        self.ensemble_algorithms = ensemble_algorithms or ["ppo", "sac", "a2c"]
        
        self.agent = None
        self.ensemble = None
        self.env = None
        
        logger.info(
            "RLInference initialized with model_path=%s, use_ensemble=%s",
            model_path,
            use_ensemble,
        )
    
    def load_model(self, data: Any) -> None:
        """Load trained model(s).
        
        Args:
            data: Sample data for environment creation
        """
        # Create environment
        trading_config = TradingConfig()
        self.env = create_trading_env(data, trading_config)
        
        if self.use_ensemble:
            # Load ensemble
            self.ensemble = create_ensemble(
                self.env,
                self.ensemble_algorithms,
                AgentConfig(),
            )
            self.ensemble.load_all(self.model_path)
            logger.info("Loaded ensemble from %s", self.model_path)
        else:
            # Load single agent
            self.agent = create_agent(self.algorithm, self.env, AgentConfig())
            self.agent.load(self.model_path)
            logger.info("Loaded %s agent from %s", self.algorithm.upper(), self.model_path)
    
    def predict(
        self,
        observation: np.ndarray,
        deterministic: bool = True,
    ) -> InferenceResult:
        """Get prediction from RL agent.
        
        Args:
            observation: Current market observation
            deterministic: Whether to use deterministic policy
            
        Returns:
            InferenceResult with action and confidence
        """
        if self.use_ensemble and self.ensemble:
            action, confidence = self.ensemble.predict_with_confidence(
                observation,
                deterministic=deterministic,
            )
        elif self.agent:
            action, _ = self.agent.predict(observation, deterministic=deterministic)
            confidence = 1.0  # Single agent has no ensemble variance
        else:
            raise RuntimeError("Model not loaded. Call load_model() first.")
        
        # Extract action components
        position_size = action[0]
        entry_signal = action[1]
        exit_signal = action[2]
        
        return InferenceResult(
            action=action,
            confidence=confidence,
            position_size=position_size,
            entry_signal=entry_signal,
            exit_signal=exit_signal,
        )
    
    def predict_batch(
        self,
        observations: list[np.ndarray],
        deterministic: bool = True,
    ) -> list[InferenceResult]:
        """Get predictions for multiple observations.
        
        Args:
            observations: List of observations
            deterministic: Whether to use deterministic policy
            
        Returns:
            List of InferenceResult
        """
        results = []
        
        for obs in observations:
            result = self.predict(obs, deterministic)
            results.append(result)
        
        return results
    
    def predict_from_data(
        self,
        data: Any,
        deterministic: bool = True,
    ) -> list[InferenceResult]:
        """Get predictions from market data.
        
        Args:
            data: OHLCV data
            deterministic: Whether to use deterministic policy
            
        Returns:
            List of InferenceResult for each data point
        """
        # Create environment if not already created
        if self.env is None:
            trading_config = TradingConfig()
            self.env = create_trading_env(data, trading_config)
        
        # Get observations for each data point
        observations = []
        for i in range(trading_config.lookback_window, len(data)):
            # Create observation for this point
            window = data.iloc[i - trading_config.lookback_window:i]
            
            # Simple observation (in production, use proper feature extraction)
            obs = np.random.randn(153).astype(np.float32)  # Placeholder
            observations.append(obs)
        
        # Get predictions
        results = self.predict_batch(observations, deterministic)
        
        return results


def load_rl_agent(
    model_path: str,
    data: Any,
    algorithm: str = "ppo",
    use_ensemble: bool = False,
) -> RLInference:
    """Convenience function to load RL agent for inference.
    
    Args:
        model_path: Path to trained model(s)
        data: Sample data for environment creation
        algorithm: Algorithm name for single agent
        use_ensemble: Whether to use ensemble
        
    Returns:
        RLInference instance
    """
    inference = RLInference(model_path, algorithm, use_ensemble)
    inference.load_model(data)
    return inference


def predict_with_model(
    model_path: str,
    observation: np.ndarray,
    data: Any,
    algorithm: str = "ppo",
    use_ensemble: bool = False,
    deterministic: bool = True,
) -> InferenceResult:
    """Convenience function for single prediction.
    
    Args:
        model_path: Path to trained model(s)
        observation: Current market observation
        data: Sample data for environment creation
        algorithm: Algorithm name for single agent
        use_ensemble: Whether to use ensemble
        deterministic: Whether to use deterministic policy
        
    Returns:
        InferenceResult
    """
    inference = load_rl_agent(model_path, data, algorithm, use_ensemble)
    return inference.predict(observation, deterministic)


__all__ = [
    "InferenceResult",
    "RLInference",
    "load_rl_agent",
    "predict_with_model",
]
