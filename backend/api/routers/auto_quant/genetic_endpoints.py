"""Genetic algorithm evolution endpoints for Auto-Quant."""

from fastapi import APIRouter, HTTPException

from ....services.auto_quant import pipeline as _pl


def register_genetic_endpoints(router: APIRouter) -> None:
    """Register genetic algorithm endpoints on the given router."""
    
    @router.get(
        "/genetic/status/{run_id}",
        summary="Get genetic evolution status for a pipeline run",
    )
    async def get_genetic_status(run_id: str) -> dict:
        """Get genetic evolution progress and best DNA for a pipeline run.
        
        Returns:
            Dictionary with genetic evolution status, best DNA, and history
        """
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        
        return {
            "run_id": run_id,
            "genetic_evolution_enabled": state.genetic_evolution_enabled,
            "best_dna": state.best_dna,
            "ga_history": state.ga_history,
            "ga_converged": state.ga_converged,
            "ga_generations": state.ga_generations,
            "ga_population_size": state.ga_population_size,
        }

    @router.post(
        "/genetic/evolve/{run_id}",
        summary="Start genetic evolution for a pipeline run",
    )
    async def start_genetic_evolution(
        run_id: str,
        body: dict,
    ) -> dict:
        """Start genetic algorithm evolution for a pipeline run.
        
        Args:
            run_id: Pipeline run identifier
            body: Dictionary with GA configuration:
                - generations: Number of generations (default 20)
                - population_size: Population size (default 50)
                - elite_size: Elite size (default 2)
                - tournament_size: Tournament size (default 3)
                - crossover_rate: Crossover rate (default 0.8)
                - mutation_rate: Mutation rate (default 0.1)
                - mutation_strength: Mutation strength (default 0.1)
                - adaptive_mutation: Enable adaptive mutation (default True)
        
        Returns:
            Dictionary with evolution status
        """
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        
        # Enable genetic evolution
        state.genetic_evolution_enabled = True
        
        # Update GA configuration
        state.ga_generations = body.get("generations", 20)
        state.ga_population_size = body.get("population_size", 50)
        
        # Save state
        from ....services.auto_quant.pipeline import _save_state_to_disk
        _save_state_to_disk(state)
        
        return {
            "success": True,
            "message": "Genetic evolution enabled for run",
            "run_id": run_id,
            "ga_generations": state.ga_generations,
            "ga_population_size": state.ga_population_size,
        }

    @router.get(
        "/genetic/history/{run_id}",
        summary="Get genetic evolution history for a pipeline run",
    )
    async def get_genetic_history(run_id: str) -> dict:
        """Get genetic evolution history across generations.
        
        Returns:
            Dictionary with generation history and statistics
        """
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        
        return {
            "run_id": run_id,
            "ga_history": state.ga_history,
            "ga_converged": state.ga_converged,
        }
