"""RL agent management for trading strategies.

This module provides a factory pattern for creating different RL agents
(A2C, PPO, SAC) and supports multi-agent ensemble training.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Configuration for RL agent training."""
    
    algorithm: str = "ppo"  # a2c, ppo, sac
    learning_rate: float = 3e-4
    n_steps: int = 2048
    batch_size: int = 64
    n_epochs: int = 10
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_range: float = 0.2
    ent_coef: float = 0.01
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    buffer_size: int = 100000
    learning_starts: int = 1000
    train_freq: int = 4
    gradient_steps: int = 1
    tau: float = 0.005
    policy_kwargs: dict | None = None
    tensorboard_log: str | None = None
    verbose: int = 1


class AgentFactory:
    """Factory for creating RL agents."""
    
    @staticmethod
    def create_agent(
        algorithm: str,
        env: gym.Env,
        config: AgentConfig | None = None,
    ) -> Any:
        """Create an RL agent based on algorithm type.
        
        Args:
            algorithm: Algorithm name (a2c, ppo, sac)
            env: Gymnasium environment
            config: Agent configuration
            
        Returns:
            Configured RL agent
        """
        config = config or AgentConfig(algorithm=algorithm)
        
        # Import stable-baselines3
        try:
            from stable_baselines3 import A2C, PPO, SAC
        except ImportError:
            raise ImportError("stable-baselines3 is required. Install with: pip install stable-baselines3")
        
        # Default policy kwargs
        default_policy_kwargs = {
            "net_arch": [256, 256],
            "activation_fn": "relu",
        }
        
        if config.policy_kwargs:
            default_policy_kwargs.update(config.policy_kwargs)
        
        # Create agent based on algorithm
        if algorithm.lower() == "a2c":
            agent = A2C(
                "MlpPolicy",
                env,
                learning_rate=config.learning_rate,
                n_steps=config.n_steps,
                gamma=config.gamma,
                gae_lambda=config.gae_lambda,
                ent_coef=config.ent_coef,
                vf_coef=config.vf_coef,
                max_grad_norm=config.max_grad_norm,
                policy_kwargs=default_policy_kwargs,
                tensorboard_log=config.tensorboard_log,
                verbose=config.verbose,
            )
        elif algorithm.lower() == "ppo":
            agent = PPO(
                "MlpPolicy",
                env,
                learning_rate=config.learning_rate,
                n_steps=config.n_steps,
                batch_size=config.batch_size,
                n_epochs=config.n_epochs,
                gamma=config.gamma,
                gae_lambda=config.gae_lambda,
                clip_range=config.clip_range,
                ent_coef=config.ent_coef,
                vf_coef=config.vf_coef,
                max_grad_norm=config.max_grad_norm,
                policy_kwargs=default_policy_kwargs,
                tensorboard_log=config.tensorboard_log,
                verbose=config.verbose,
            )
        elif algorithm.lower() == "sac":
            agent = SAC(
                "MlpPolicy",
                env,
                learning_rate=config.learning_rate,
                buffer_size=config.buffer_size,
                learning_starts=config.learning_starts,
                batch_size=config.batch_size,
                tau=config.tau,
                gamma=config.gamma,
                gradient_steps=config.gradient_steps,
                train_freq=config.train_freq,
                policy_kwargs=default_policy_kwargs,
                tensorboard_log=config.tensorboard_log,
                verbose=config.verbose,
            )
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}. Supported: a2c, ppo, sac")
        
        logger.info(f"Created {algorithm.upper()} agent with config: {config}")
        return agent


class MultiAgentEnsemble:
    """Multi-agent ensemble for robust trading decisions."""
    
    def __init__(
        self,
        env: gym.Env,
        algorithms: list[str] | None = None,
        config: AgentConfig | None = None,
    ):
        """Initialize multi-agent ensemble.
        
        Args:
            env: Gymnasium environment
            algorithms: List of algorithm names (default: ["ppo", "sac", "a2c"])
            config: Agent configuration
        """
        self.env = env
        self.algorithms = algorithms or ["ppo", "sac", "a2c"]
        self.config = config or AgentConfig()
        
        self.agents = {}
        self.agent_factory = AgentFactory()
        
        # Create agents
        for algorithm in self.algorithms:
            self.agents[algorithm] = self.agent_factory.create_agent(
                algorithm,
                env,
                self.config,
            )
        
        logger.info(f"Created multi-agent ensemble with {len(self.agents)} agents")
    
    def train_all(
        self,
        total_timesteps: int,
        progress_callback: callable | None = None,
    ) -> dict[str, Any]:
        """Train all agents in the ensemble.
        
        Args:
            total_timesteps: Total timesteps to train each agent
            progress_callback: Optional callback for progress updates
            
        Returns:
            Dictionary with training results for each agent
        """
        results = {}
        
        for algorithm, agent in self.agents.items():
            logger.info(f"Training {algorithm.upper()} agent for {total_timesteps} timesteps")
            
            # Custom callback for progress
            if progress_callback:
                class ProgressCallback:
                    def __init__(self, callback, algorithm):
                        self.callback = callback
                        self.algorithm = algorithm
                    
                    def __call__(self, locals_, globals_):
                        if "num_timesteps" in locals_:
                            self.callback(self.algorithm, locals_["num_timesteps"], total_timesteps)
                
                callback = ProgressCallback(progress_callback, algorithm)
            else:
                callback = None
            
            # Train agent
            agent.learn(
                total_timesteps,
                callback=callback,
                progress_bar=self.config.verbose > 0,
            )
            
            results[algorithm] = {
                "algorithm": algorithm,
                "timesteps": total_timesteps,
                "trained": True,
            }
        
        return results
    
    def predict_ensemble(
        self,
        observation: np.ndarray,
        deterministic: bool = True,
    ) -> np.ndarray:
        """Get ensemble prediction (average of all agents).
        
        Args:
            observation: Current observation
            deterministic: Whether to use deterministic policy
            
        Returns:
            Averaged action from all agents
        """
        actions = []
        
        for algorithm, agent in self.agents.items():
            action, _ = agent.predict(observation, deterministic=deterministic)
            actions.append(action)
        
        # Average actions
        ensemble_action = np.mean(actions, axis=0)
        
        return ensemble_action
    
    def predict_with_confidence(
        self,
        observation: np.ndarray,
        deterministic: bool = True,
    ) -> tuple[np.ndarray, float]:
        """Get ensemble prediction with confidence score.
        
        Confidence is calculated as 1 - (std / mean) of agent predictions.
        
        Args:
            observation: Current observation
            deterministic: Whether to use deterministic policy
            
        Returns:
            Tuple of (action, confidence_score)
        """
        actions = []
        
        for algorithm, agent in self.agents.items():
            action, _ = agent.predict(observation, deterministic=deterministic)
            actions.append(action)
        
        actions_array = np.array(actions)
        
        # Calculate ensemble action
        ensemble_action = np.mean(actions_array, axis=0)
        
        # Calculate confidence (inverse of variance)
        std = np.std(actions_array, axis=0)
        mean = np.mean(actions_array, axis=0)
        
        # Avoid division by zero
        confidence = 1.0 - np.mean(std / (np.abs(mean) + 1e-8))
        confidence = max(0.0, min(1.0, confidence))
        
        return ensemble_action, confidence
    
    def save_all(self, path: Path) -> None:
        """Save all agents to disk.
        
        Args:
            path: Directory to save agents
        """
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        
        for algorithm, agent in self.agents.items():
            agent_path = path / f"{algorithm}_agent"
            agent.save(agent_path)
            logger.info(f"Saved {algorithm.upper()} agent to {agent_path}")
    
    def load_all(self, path: Path) -> None:
        """Load all agents from disk.
        
        Args:
            path: Directory containing saved agents
        """
        path = Path(path)
        
        for algorithm in self.algorithms:
            agent_path = path / f"{algorithm}_agent"
            
            if agent_path.exists():
                # Load agent
                self.agents[algorithm] = self.agent_factory.create_agent(
                    algorithm,
                    self.env,
                    self.config,
                )
                self.agents[algorithm].load(agent_path)
                logger.info(f"Loaded {algorithm.upper()} agent from {agent_path}")
            else:
                logger.warning(f"Agent file not found: {agent_path}")


def create_agent(
    algorithm: str,
    env: gym.Env,
    config: AgentConfig | None = None,
) -> Any:
    """Convenience function to create a single RL agent.
    
    Args:
        algorithm: Algorithm name (a2c, ppo, sac)
        env: Gymnasium environment
        config: Agent configuration
        
    Returns:
        Configured RL agent
    """
    factory = AgentFactory()
    return factory.create_agent(algorithm, env, config)


def create_ensemble(
    env: gym.Env,
    algorithms: list[str] | None = None,
    config: AgentConfig | None = None,
) -> MultiAgentEnsemble:
    """Convenience function to create a multi-agent ensemble.
    
    Args:
        env: Gymnasium environment
        algorithms: List of algorithm names
        config: Agent configuration
        
    Returns:
        MultiAgentEnsemble instance
    """
    return MultiAgentEnsemble(env, algorithms, config)


__all__ = [
    "AgentConfig",
    "AgentFactory",
    "MultiAgentEnsemble",
    "create_agent",
    "create_ensemble",
]
