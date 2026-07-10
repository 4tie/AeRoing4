"""Reinforcement learning endpoints for Auto-Quant."""

from fastapi import APIRouter, HTTPException

from ....services.auto_quant import pipeline as _pl


def register_rl_endpoints(router: APIRouter) -> None:
    """Register reinforcement learning endpoints on the given router."""
    
    @router.get(
        "/rl/status/{run_id}",
        summary="Get RL training and deployment status for a pipeline run",
    )
    async def get_rl_status(run_id: str) -> dict:
        """Get RL training and deployment status for a pipeline run.
        
        Returns:
            Dictionary with RL status, model path, and performance metrics
        """
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        
        return {
            "run_id": run_id,
            "rl_training_enabled": state.rl_training_enabled,
            "rl_deployment_enabled": state.rl_deployment_enabled,
            "rl_algorithm": state.rl_algorithm,
            "rl_total_timesteps": state.rl_total_timesteps,
            "rl_model_path": state.rl_model_path,
            "rl_performance": state.rl_performance,
            "rl_trades_count": len(state.rl_trades),
        }

    @router.post(
        "/rl/train/{run_id}",
        summary="Enable RL training for a pipeline run",
    )
    async def enable_rl_training(
        run_id: str,
        body: dict,
    ) -> dict:
        """Enable RL training for a pipeline run.
        
        Args:
            run_id: Pipeline run identifier
            body: Dictionary with RL configuration:
                - algorithm: Algorithm name (ppo, sac, a2c)
                - total_timesteps: Total training timesteps (default 1000000)
                - use_ensemble: Use ensemble of agents (default False)
        
        Returns:
            Dictionary with RL training configuration
        """
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        
        # Enable RL training
        state.rl_training_enabled = True
        
        # Update RL configuration
        state.rl_algorithm = body.get("algorithm", "ppo")
        state.rl_total_timesteps = body.get("total_timesteps", 1000000)
        
        # Save state
        from ....services.auto_quant.pipeline import _save_state_to_disk
        _save_state_to_disk(state)
        
        return {
            "success": True,
            "message": "RL training enabled for run",
            "run_id": run_id,
            "rl_algorithm": state.rl_algorithm,
            "rl_total_timesteps": state.rl_total_timesteps,
        }

    @router.post(
        "/rl/deploy/{run_id}",
        summary="Enable RL deployment for a pipeline run",
    )
    async def enable_rl_deployment(
        run_id: str,
    ) -> dict:
        """Enable RL deployment for a pipeline run.
        
        Args:
            run_id: Pipeline run identifier
        
        Returns:
            Dictionary with RL deployment status
        """
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        
        # Enable RL deployment
        state.rl_deployment_enabled = True
        
        # Save state
        from ....services.auto_quant.pipeline import _save_state_to_disk
        _save_state_to_disk(state)
        
        return {
            "success": True,
            "message": "RL deployment enabled for run",
            "run_id": run_id,
        }

    @router.get(
        "/rl/trades/{run_id}",
        summary="Get RL agent trades for a pipeline run",
    )
    async def get_rl_trades(run_id: str) -> dict:
        """Get RL agent trading signals for a pipeline run.
        
        Returns:
            Dictionary with RL agent trades
        """
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        
        return {
            "run_id": run_id,
            "rl_trades": state.rl_trades,
            "trades_count": len(state.rl_trades),
        }
