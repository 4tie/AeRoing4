"""RL training orchestration for trading agents.

This module implements the training orchestration for RL agents,
including curriculum learning, checkpointing, and early stopping.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np

from .rl_agents import AgentConfig, create_agent, create_ensemble
from .rl_environment import TradingConfig, create_trading_env, create_vectorized_env

logger = logging.getLogger(__name__)


@dataclass
class TrainingConfig:
    """Configuration for RL training."""
    
    total_timesteps: int = 1000000
    checkpoint_interval: int = 100000
    early_stopping_patience: int = 5
    early_stopping_threshold: float = 0.01
    use_ensemble: bool = True
    ensemble_algorithms: list[str] = field(default_factory=lambda: ["ppo", "sac", "a2c"])
    use_vectorized_env: bool = True
    n_envs: int = 4
    curriculum_learning: bool = True
    curriculum_phases: int = 3
    output_dir: str = "rl_checkpoints"


@dataclass
class TrainingResult:
    """Result of RL training."""
    
    model_path: str
    algorithm: str
    total_timesteps: int
    final_reward: float
    best_reward: float
    training_history: list[dict[str, Any]]
    converged: bool
    elapsed_seconds: float
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "model_path": self.model_path,
            "algorithm": self.algorithm,
            "total_timesteps": self.total_timesteps,
            "final_reward": self.final_reward,
            "best_reward": self.best_reward,
            "training_history": self.training_history,
            "converged": self.converged,
            "elapsed_seconds": self.elapsed_seconds,
        }


class RLTrainer:
    """Orchestrator for RL agent training."""
    
    def __init__(
        self,
        config: TrainingConfig | None = None,
        agent_config: AgentConfig | None = None,
    ):
        """Initialize RL trainer.
        
        Args:
            config: Training configuration
            agent_config: Agent configuration
        """
        self.config = config or TrainingConfig()
        self.agent_config = agent_config or AgentConfig()
        
        self.training_history: list[dict[str, Any]] = []
        self.best_reward = -np.inf
        self.patience_counter = 0
        
        logger.info(
            "RLTrainer initialized with total_timesteps=%d, use_ensemble=%s",
            self.config.total_timesteps,
            self.config.use_ensemble,
        )
    
    def train(
        self,
        data: Any,
        output_dir: str | None = None,
        progress_callback: callable | None = None,
    ) -> TrainingResult:
        """Train RL agent(s) on provided data.
        
        Args:
            data: OHLCV data (DataFrame or similar)
            output_dir: Output directory for checkpoints
            progress_callback: Optional callback for progress updates
            
        Returns:
            TrainingResult with training metrics
        """
        start_time = datetime.now(timezone.utc)
        
        output_dir = Path(output_dir or self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create environment
        trading_config = TradingConfig()
        
        if self.config.use_vectorized_env:
            env = create_vectorized_env(data, self.config.n_envs, trading_config)
        else:
            env = create_trading_env(data, trading_config)
        
        # Curriculum learning
        if self.config.curriculum_learning:
            logger.info("Using curriculum learning with %d phases", self.config.curriculum_phases)
            return self._train_with_curriculum(env, output_dir, progress_callback)
        else:
            logger.info("Training without curriculum learning")
            return self._train_single_phase(env, output_dir, progress_callback)
    
    def _train_single_phase(
        self,
        env: gym.Env,
        output_dir: Path,
        progress_callback: callable | None = None,
    ) -> TrainingResult:
        """Train agent in single phase (no curriculum).
        
        Args:
            env: Training environment
            output_dir: Output directory
            progress_callback: Progress callback
            
        Returns:
            TrainingResult
        """
        if self.config.use_ensemble:
            ensemble = create_ensemble(
                env,
                self.config.ensemble_algorithms,
                self.agent_config,
            )
            
            # Train ensemble
            ensemble.train_all(
                self.config.total_timesteps,
                progress_callback,
            )
            
            # Save ensemble
            ensemble_path = output_dir / "ensemble"
            ensemble.save_all(ensemble_path)
            
            # Evaluate final performance
            final_reward = self._evaluate_agent(ensemble, env)
            
            return TrainingResult(
                model_path=str(ensemble_path),
                algorithm="ensemble",
                total_timesteps=self.config.total_timesteps,
                final_reward=final_reward,
                best_reward=self.best_reward,
                training_history=self.training_history,
                converged=self.patience_counter >= self.config.early_stopping_patience,
                elapsed_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
            )
        else:
            # Train single agent
            agent = create_agent(
                self.agent_config.algorithm,
                env,
                self.agent_config,
            )
            
            # Custom callback for checkpointing and early stopping
            class TrainingCallback:
                def __init__(self, trainer, output_dir, progress_callback):
                    self.trainer = trainer
                    self.output_dir = output_dir
                    self.progress_callback = progress_callback
                    self.checkpoint_count = 0
                
                def __call__(self, locals_, globals_):
                    if "num_timesteps" in locals_:
                        timesteps = locals_["num_timesteps"]
                        
                        # Progress callback
                        if self.progress_callback:
                            self.progress_callback(timesteps, self.trainer.config.total_timesteps)
                        
                        # Checkpointing
                        if timesteps % self.trainer.config.checkpoint_interval == 0:
                            checkpoint_path = self.output_dir / f"checkpoint_{self.checkpoint_count}"
                            agent.save(checkpoint_path)
                            self.checkpoint_count += 1
                            logger.info(f"Saved checkpoint at {timesteps} timesteps")
                        
                        # Early stopping
                        if "episode_reward" in locals_:
                            reward = locals_["episode_reward"]
                            self.trainer.training_history.append({
                                "timesteps": timesteps,
                                "reward": reward,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
                            
                            if reward > self.trainer.best_reward:
                                self.trainer.best_reward = reward
                                self.trainer.patience_counter = 0
                            else:
                                self.trainer.patience_counter += 1
                            
                            if self.trainer.patience_counter >= self.trainer.config.early_stopping_patience:
                                logger.info("Early stopping triggered")
                                return False  # Stop training
            
            callback = TrainingCallback(self, output_dir, progress_callback)
            
            # Train agent
            agent.learn(
                self.config.total_timesteps,
                callback=callback,
                progress_bar=self.agent_config.verbose > 0,
            )
            
            # Save final model
            model_path = output_dir / "final_model"
            agent.save(model_path)
            
            # Evaluate final performance
            final_reward = self._evaluate_agent(agent, env)
            
            return TrainingResult(
                model_path=str(model_path),
                algorithm=self.agent_config.algorithm,
                total_timesteps=self.config.total_timesteps,
                final_reward=final_reward,
                best_reward=self.best_reward,
                training_history=self.training_history,
                converged=self.patience_counter >= self.config.early_stopping_patience,
                elapsed_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
            )
    
    def _train_with_curriculum(
        self,
        env: gym.Env,
        output_dir: Path,
        progress_callback: callable | None = None,
    ) -> TrainingResult:
        """Train agent with curriculum learning.
        
        Curriculum phases:
        Phase 1: Simple 2-indicator strategy
        Phase 2: Add more indicators
        Phase 3: Full feature set with regime awareness
        
        Args:
            env: Training environment
            output_dir: Output directory
            progress_callback: Progress callback
            
        Returns:
            TrainingResult
        """
        timesteps_per_phase = self.config.total_timesteps // self.config.curriculum_phases
        
        for phase in range(self.config.curriculum_phases):
            logger.info(f"Starting curriculum phase {phase + 1}/{self.config.curriculum_phases}")
            
            # Adjust complexity based on phase
            if phase == 0:
                # Phase 1: Simple
                self.agent_config.policy_kwargs = {"net_arch": [64, 64]}
                timesteps = timesteps_per_phase // 2
            elif phase == 1:
                # Phase 2: Medium
                self.agent_config.policy_kwargs = {"net_arch": [128, 128]}
                timesteps = timesteps_per_phase
            else:
                # Phase 3: Full
                self.agent_config.policy_kwargs = {"net_arch": [256, 256]}
                timesteps = timesteps_per_phase
            
            # Train this phase
            phase_output_dir = output_dir / f"phase_{phase + 1}"
            phase_output_dir.mkdir(parents=True, exist_ok=True)
            
            if self.config.use_ensemble:
                ensemble = create_ensemble(
                    env,
                    self.config.ensemble_algorithms,
                    self.agent_config,
                )
                ensemble.train_all(timesteps, progress_callback)
                ensemble.save_all(phase_output_dir)
            else:
                agent = create_agent(self.agent_config.algorithm, env, self.agent_config)
                agent.learn(timesteps, progress_bar=self.agent_config.verbose > 0)
                model_path = phase_output_dir / "model"
                agent.save(model_path)
            
            logger.info(f"Completed curriculum phase {phase + 1}")
        
        # Final evaluation
        if self.config.use_ensemble:
            ensemble = create_ensemble(env, self.config.ensemble_algorithms, self.agent_config)
            ensemble.load_all(output_dir / "phase_3")
            final_reward = self._evaluate_agent(ensemble, env)
            model_path = output_dir / "phase_3"
        else:
            agent = create_agent(self.agent_config.algorithm, env, self.agent_config)
            agent.load(output_dir / "phase_3" / "model")
            final_reward = self._evaluate_agent(agent, env)
            model_path = output_dir / "phase_3" / "model"
        
        return TrainingResult(
            model_path=str(model_path),
            algorithm="ensemble" if self.config.use_ensemble else self.agent_config.algorithm,
            total_timesteps=self.config.total_timesteps,
            final_reward=final_reward,
            best_reward=self.best_reward,
            training_history=self.training_history,
            converged=False,
            elapsed_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
        )
    
    def _evaluate_agent(self, agent: Any, env: gym.Env, n_episodes: int = 10) -> float:
        """Evaluate agent performance.
        
        Args:
            agent: Trained agent or ensemble
            env: Evaluation environment
            n_episodes: Number of evaluation episodes
            
        Returns:
            Average reward over episodes
        """
        rewards = []
        
        for _ in range(n_episodes):
            obs, _ = env.reset()
            episode_reward = 0
            done = False
            truncated = False
            
            while not (done or truncated):
                if hasattr(agent, 'predict_with_confidence'):
                    action, _ = agent.predict_with_confidence(obs, deterministic=True)
                else:
                    action, _ = agent.predict(obs, deterministic=True)
                
                obs, reward, done, truncated, _ = env.step(action)
                episode_reward += reward
            
            rewards.append(episode_reward)
        
        return np.mean(rewards)


async def train_rl_agent(
    data: Any,
    config: TrainingConfig | None = None,
    agent_config: AgentConfig | None = None,
    output_dir: str | None = None,
    progress_callback: callable | None = None,
) -> TrainingResult:
    """Convenience function to train RL agent.
    
    Args:
        data: OHLCV data
        config: Training configuration
        agent_config: Agent configuration
        output_dir: Output directory
        progress_callback: Progress callback
        
    Returns:
        TrainingResult
    """
    trainer = RLTrainer(config, agent_config)
    return trainer.train(data, output_dir, progress_callback)


__all__ = [
    "TrainingConfig",
    "TrainingResult",
    "RLTrainer",
    "train_rl_agent",
]
