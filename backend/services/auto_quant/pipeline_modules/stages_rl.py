"""Stage implementation for reinforcement learning training and deployment."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..rl.rl_training import TrainingConfig, AgentConfig, train_rl_agent
from ..rl.rl_inference import load_rl_agent, predict_with_model
from .helpers import _emit
from .logging import _rlog
from .state import PipelineState, _save_state_to_disk


async def _stage_rl_training(
    run_id: str,
    state: PipelineState,
    out_dir: Path,
) -> dict[str, Any] | None:
    """Stage 3.5: RL Training - Train reinforcement learning agent.
    
    This stage trains a deep RL agent (PPO, SAC, or A2C) on historical
    market data to learn optimal trading policies.
    
    Args:
        run_id: Pipeline run identifier
        state: PipelineState instance
        out_dir: Output directory for results
        
    Returns:
        Dictionary with RL training results or None if failed
    """
    _rlog(run_id, 3, logging.INFO, "── Stage 3.5: RL Training ──")
    _emit(run_id, 3, "running", "Training reinforcement learning agent...", 5)
    
    if not state.rl_training_enabled:
        _rlog(run_id, 3, logging.INFO, "RL training disabled, skipping")
        _emit(run_id, 3, "running", "RL training disabled", 5)
        return {
            "skipped": True,
            "reason": "RL training disabled",
        }
    
    try:
        # Create training configuration
        training_config = TrainingConfig(
            total_timesteps=state.rl_total_timesteps,
            use_ensemble=False,  # Use single agent for faster training
            output_dir=str(out_dir / "rl_checkpoints"),
        )
        
        agent_config = AgentConfig(
            algorithm=state.rl_algorithm,
            learning_rate=3e-4,
            n_steps=2048,
            batch_size=64,
            n_epochs=10,
        )
        
        # Load market data (placeholder - in production, load actual OHLCV data)
        import pandas as pd
        import numpy as np
        
        # Mock data for testing
        n_points = 10000
        dates = pd.date_range(end=pd.Timestamp.now(), periods=n_points, freq='H')
        data = pd.DataFrame({
            'open': np.cumsum(np.random.randn(n_points) * 0.01) + 100,
            'high': np.cumsum(np.random.randn(n_points) * 0.01) + 100 + np.random.rand(n_points) * 0.5,
            'low': np.cumsum(np.random.randn(n_points) * 0.01) + 100 - np.random.rand(n_points) * 0.5,
            'close': np.cumsum(np.random.randn(n_points) * 0.01) + 100,
            'volume': np.random.randint(1000, 10000, n_points),
        }, index=dates)
        
        # Progress callback
        def progress_callback(current, total):
            progress = int((current / total) * 100)
            _emit(run_id, 3, "running", f"RL training progress: {progress}%", 5)
        
        # Train RL agent
        _rlog(run_id, 3, logging.INFO,
              f"Starting RL training with {state.rl_algorithm.upper()}, {state.rl_total_timesteps} timesteps")
        
        result = await train_rl_agent(
            data=data,
            config=training_config,
            agent_config=agent_config,
            output_dir=str(out_dir / "rl_checkpoints"),
            progress_callback=progress_callback,
        )
        
        # Update state with results
        state.rl_model_path = result.model_path
        state.rl_performance = {
            "algorithm": result.algorithm,
            "total_timesteps": result.total_timesteps,
            "final_reward": result.final_reward,
            "best_reward": result.best_reward,
            "converged": result.converged,
            "elapsed_seconds": result.elapsed_seconds,
        }
        
        _rlog(run_id, 3, logging.INFO,
              f"RL Training Complete | Final reward: {result.final_reward:.4f} | "
              f"Best reward: {result.best_reward:.4f} | Converged: {result.converged}")
        
        _emit(run_id, 3, "running",
              f"RL training complete: Final reward {result.final_reward:.4f}",
              5,
              {
                  "type": "rl_training_complete",
                  "final_reward": result.final_reward,
                  "best_reward": result.best_reward,
                  "converged": result.converged,
                  "elapsed_seconds": result.elapsed_seconds,
              },
              msg_type="rl_training_complete")
        
        _save_state_to_disk(state)
        
        return {
            "model_path": result.model_path,
            "algorithm": result.algorithm,
            "total_timesteps": result.total_timesteps,
            "final_reward": result.final_reward,
            "best_reward": result.best_reward,
            "converged": result.converged,
            "elapsed_seconds": result.elapsed_seconds,
        }
        
    except Exception as exc:
        _rlog(run_id, 3, logging.ERROR, f"RL training failed: {exc}")
        _emit(run_id, 3, "running", "RL training failed, using default strategy", 5)
        
        # Fallback
        state.rl_model_path = None
        state.rl_performance = {}
        
        _save_state_to_disk(state)
        
        return {
            "error": str(exc),
            "model_path": None,
        }


async def _stage_rl_deployment(
    run_id: str,
    state: PipelineState,
    out_dir: Path,
) -> dict[str, Any] | None:
    """Stage 4.5: RL Deployment - Deploy trained RL agent for live trading.
    
    This stage loads a trained RL agent and deploys it for inference,
    generating trading signals based on market observations.
    
    Args:
        run_id: Pipeline run identifier
        state: PipelineState instance
        out_dir: Output directory for results
        
    Returns:
        Dictionary with RL deployment results or None if failed
    """
    _rlog(run_id, 4, logging.INFO, "── Stage 4.5: RL Deployment ──")
    _emit(run_id, 4, "running", "Deploying reinforcement learning agent...", 5)
    
    if not state.rl_deployment_enabled:
        _rlog(run_id, 4, logging.INFO, "RL deployment disabled, skipping")
        _emit(run_id, 4, "running", "RL deployment disabled", 5)
        return {
            "skipped": True,
            "reason": "RL deployment disabled",
        }
    
    if not state.rl_model_path:
        _rlog(run_id, 4, logging.WARNING, "No trained RL model available, skipping deployment")
        _emit(run_id, 4, "running", "No trained RL model available", 5)
        return {
            "skipped": True,
            "reason": "No trained model",
        }
    
    try:
        # Load market data (placeholder)
        import pandas as pd
        import numpy as np
        
        n_points = 1000
        dates = pd.date_range(end=pd.Timestamp.now(), periods=n_points, freq='H')
        data = pd.DataFrame({
            'open': np.cumsum(np.random.randn(n_points) * 0.01) + 100,
            'high': np.cumsum(np.random.randn(n_points) * 0.01) + 100 + np.random.rand(n_points) * 0.5,
            'low': np.cumsum(np.random.randn(n_points) * 0.01) + 100 - np.random.rand(n_points) * 0.5,
            'close': np.cumsum(np.random.randn(n_points) * 0.01) + 100,
            'volume': np.random.randint(1000, 10000, n_points),
        }, index=dates)
        
        # Load RL agent
        inference = load_rl_agent(
            model_path=state.rl_model_path,
            data=data,
            algorithm=state.rl_algorithm,
            use_ensemble=False,
        )
        
        # Generate predictions
        predictions = inference.predict_from_data(data, deterministic=True)
        
        # Extract trades from predictions
        trades = []
        for i, pred in enumerate(predictions):
            if pred.entry_signal > 0.5:
                trades.append({
                    "timestamp": str(data.index[i]),
                    "action": "entry",
                    "position_size": pred.position_size,
                    "confidence": pred.confidence,
                })
            elif pred.exit_signal > 0.5:
                trades.append({
                    "timestamp": str(data.index[i]),
                    "action": "exit",
                    "position_size": pred.position_size,
                    "confidence": pred.confidence,
                })
        
        # Update state
        state.rl_trades = trades
        
        _rlog(run_id, 4, logging.INFO,
              f"RL Deployment Complete | Generated {len(trades)} trading signals")
        
        _emit(run_id, 4, "running",
              f"RL deployment complete: {len(trades)} signals generated",
              5,
              {
                  "type": "rl_deployment_complete",
                  "trades_count": len(trades),
              },
              msg_type="rl_deployment_complete")
        
        _save_state_to_disk(state)
        
        return {
            "trades_count": len(trades),
            "trades": trades[:100],  # Return first 100 trades
        }
        
    except Exception as exc:
        _rlog(run_id, 4, logging.ERROR, f"RL deployment failed: {exc}")
        _emit(run_id, 4, "running", "RL deployment failed", 5)
        
        state.rl_trades = []
        _save_state_to_disk(state)
        
        return {
            "error": str(exc),
            "trades_count": 0,
        }


__all__ = [
    "_stage_rl_training",
    "_stage_rl_deployment",
]
