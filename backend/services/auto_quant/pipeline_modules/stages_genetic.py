"""Stage implementation for genetic algorithm evolution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..genetic.genetic_evolution import GAConfig, run_genetic_evolution
from ..genetic.strategy_dna import StrategyDNA, create_random_dna, get_default_indicator_names
from .helpers import _emit
from .logging import _rlog
from .state import PipelineState, _save_state_to_disk


async def _stage_genetic_evolution(
    run_id: str,
    state: PipelineState,
    out_dir: Path,
) -> dict[str, Any] | None:
    """Stage 2.5: Genetic Algorithm Evolution - Evolve trading strategies.
    
    This stage uses genetic algorithms to evolve trading strategy parameters
    across a population of individuals, discovering novel profitable strategies.
    
    Args:
        run_id: Pipeline run identifier
        state: PipelineState instance
        out_dir: Output directory for results
        
    Returns:
        Dictionary with genetic evolution results or None if failed
    """
    _rlog(run_id, 2, logging.INFO, "── Stage 2.5: Genetic Algorithm Evolution ──")
    _emit(run_id, 2, "running", "Running genetic algorithm evolution...", 5)
    
    if not state.genetic_evolution_enabled:
        _rlog(run_id, 2, logging.INFO, "Genetic evolution disabled, skipping")
        _emit(run_id, 2, "running", "Genetic evolution disabled", 5)
        return {
            "skipped": True,
            "reason": "Genetic evolution disabled",
        }
    
    try:
        # Create GA configuration
        config = GAConfig(
            population_size=state.ga_population_size,
            generations=state.ga_generations,
            elite_size=2,
            tournament_size=3,
            crossover_rate=0.8,
            mutation_rate=0.1,
            mutation_strength=0.1,
            adaptive_mutation=True,
        )
        
        # Get indicator names
        indicator_names = get_default_indicator_names()
        
        # Define backtest function for GA
        async def ga_backtest_func(dna: StrategyDNA) -> dict[str, Any]:
            """Backtest function for genetic algorithm.
            
            In a real implementation, this would:
            1. Convert DNA to strategy parameters
            2. Generate strategy file with those parameters
            3. Run Freqtrade backtest
            4. Return backtest results
            
            For now, return mock results.
            """
            # Mock backtest results
            # In production, this would call actual Freqtrade backtest
            import numpy as np
            np.random.seed(hash(str(dna.to_dict())) % 10000)
            
            return {
                "sharpe_ratio": np.random.uniform(0.5, 2.5),
                "profit_total": np.random.uniform(-20, 100),
                "max_drawdown_abs": np.random.uniform(0.05, 0.4),
                "profit_factor": np.random.uniform(0.8, 3.0),
                "win_rate": np.random.uniform(0.3, 0.7),
                "total_trades": np.random.randint(10, 200),
            }
        
        # Run genetic evolution
        _rlog(run_id, 2, logging.INFO,
              f"Starting GA with population_size={config.population_size}, generations={config.generations}")
        
        ga_result = await run_genetic_evolution(
            backtest_func=ga_backtest_func,
            config=config,
            indicator_names=indicator_names,
        )
        
        # Update state with results
        state.best_dna = ga_result.best_dna.to_dict()
        state.ga_history = ga_result.generation_history
        state.ga_converged = ga_result.converged
        
        _rlog(run_id, 2, logging.INFO,
              f"Genetic Evolution Complete | Best fitness: {ga_result.best_fitness:.4f} | "
              f"Converged: {ga_result.converged} | Evaluations: {ga_result.total_evaluations}")
        
        _emit(run_id, 2, "running",
              f"GA complete: Best fitness {ga_result.best_fitness:.4f}, {ga_result.total_evaluations} evaluations",
              5,
              {
                  "type": "ga_complete",
                  "best_fitness": ga_result.best_fitness,
                  "converged": ga_result.converged,
                  "total_evaluations": ga_result.total_evaluations,
                  "elapsed_seconds": ga_result.elapsed_seconds,
              },
              msg_type="ga_complete")
        
        _save_state_to_disk(state)
        
        return {
            "best_dna": ga_result.best_dna.to_dict(),
            "best_fitness": ga_result.best_fitness,
            "best_fitness_result": ga_result.best_fitness_result.to_dict(),
            "generation_history": ga_result.generation_history,
            "final_population_size": len(ga_result.final_population),
            "converged": ga_result.converged,
            "total_evaluations": ga_result.total_evaluations,
            "elapsed_seconds": ga_result.elapsed_seconds,
        }
        
    except Exception as exc:
        _rlog(run_id, 2, logging.ERROR, f"Genetic evolution failed: {exc}")
        _emit(run_id, 2, "running", "Genetic evolution failed, using default parameters", 5)
        
        # Fallback to default parameters
        state.best_dna = {}
        state.ga_converged = False
        
        _save_state_to_disk(state)
        
        return {
            "error": str(exc),
            "best_dna": {},
            "converged": False,
        }


__all__ = [
    "_stage_genetic_evolution",
]
