"""Genetic algorithm evolution orchestration for trading strategies.

This module implements the main genetic algorithm loop for evolving
trading strategies, including population management, parallel backtest
evaluation, and convergence detection.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .genetic_fitness import (
    calculate_fitness,
    calculate_population_statistics,
    FitnessResult,
    rank_by_fitness,
)
from .genetic_operators import (
    calculate_diversity,
    crossover_blend,
    elitism_selection,
    mutation_gaussian,
    selection_tournament,
)
from .strategy_dna import StrategyDNA, create_random_dna, get_default_indicator_names

logger = logging.getLogger(__name__)


@dataclass
class GAConfig:
    """Configuration for genetic algorithm evolution."""
    
    population_size: int = 50
    generations: int = 20
    elite_size: int = 2
    tournament_size: int = 3
    crossover_rate: float = 0.8
    mutation_rate: float = 0.1
    mutation_strength: float = 0.1
    adaptive_mutation: bool = True
    convergence_window: int = 5
    convergence_tolerance: float = 1e-6
    parallel_workers: int = 4


@dataclass
class GAResult:
    """Result of genetic algorithm evolution."""
    
    best_dna: StrategyDNA
    best_fitness: float
    best_fitness_result: FitnessResult
    generation_history: list[dict[str, Any]]
    final_population: list[tuple[StrategyDNA, float]]
    converged: bool
    total_evaluations: int
    elapsed_seconds: float
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "best_dna": self.best_dna.to_dict(),
            "best_fitness": self.best_fitness,
            "best_fitness_result": self.best_fitness_result.to_dict(),
            "generation_history": self.generation_history,
            "final_population_size": len(self.final_population),
            "converged": self.converged,
            "total_evaluations": self.total_evaluations,
            "elapsed_seconds": self.elapsed_seconds,
        }


class GeneticEvolution:
    """Main genetic algorithm orchestrator for strategy evolution."""
    
    def __init__(
        self,
        config: GAConfig | None = None,
        indicator_names: list[str] | None = None,
    ):
        """Initialize genetic evolution orchestrator.
        
        Args:
            config: GA configuration (default: GAConfig())
            indicator_names: List of indicator names for DNA encoding
        """
        self.config = config or GAConfig()
        self.indicator_names = indicator_names or get_default_indicator_names()
        
        self.population: list[tuple[StrategyDNA, float]] = []
        self.generation_history: list[dict[str, Any]] = []
        self.total_evaluations = 0
        self.best_fitness_history: list[float] = []
        
        logger.info(
            "GeneticEvolution initialized with population_size=%d, generations=%d",
            self.config.population_size,
            self.config.generations,
        )
    
    async def run_evolution(
        self,
        backtest_func: callable,
        initial_population: list[StrategyDNA] | None = None,
    ) -> GAResult:
        """Run genetic algorithm evolution.
        
        Args:
            backtest_func: Async function that takes DNA and returns backtest result
            initial_population: Optional initial population (random if None)
            
        Returns:
            GAResult with best DNA and evolution history
        """
        start_time = datetime.now(timezone.utc)
        
        # Initialize population
        if initial_population is None:
            logger.info("Initializing random population")
            self.population = await self._initialize_population(backtest_func)
        else:
            logger.info("Using provided initial population")
            self.population = await self._evaluate_population(initial_population, backtest_func)
        
        # Evolution loop
        for generation in range(self.config.generations):
            logger.info("Starting generation %d/%d", generation + 1, self.config.generations)
            
            # Record generation statistics
            fitness_values = [f for _, f in self.population]
            stats = calculate_population_statistics(fitness_values)
            diversity = calculate_diversity([dna for dna, _ in self.population], self.indicator_names)
            
            gen_record = {
                "generation": generation,
                "population_size": len(self.population),
                "statistics": stats,
                "diversity": diversity,
                "best_fitness": max(fitness_values),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self.generation_history.append(gen_record)
            
            # Track best fitness for convergence detection
            best_fitness = max(fitness_values)
            self.best_fitness_history.append(best_fitness)
            
            # Check convergence
            if self._check_convergence():
                logger.info("Converged at generation %d", generation + 1)
                gen_record["converged"] = True
                break
            
            # Selection
            selected = self._selection()
            
            # Crossover
            offspring = self._crossover(selected)
            
            # Mutation
            mutated = self._mutation(offspring, generation)
            
            # Evaluate offspring
            evaluated_offspring = await self._evaluate_population(mutated, backtest_func)
            
            # Elitism: keep best individuals
            elites = elitism_selection(self.population, self.config.elite_size)
            
            # Create new population (elites + offspring)
            new_population = [(elite, 0.0) for elite in elites]  # Fitness will be recalculated
            new_population.extend(evaluated_offspring)
            
            # Trim to population size
            if len(new_population) > self.config.population_size:
                # Sort by fitness and keep best
                new_population = rank_by_fitness(new_population, descending=True)
                new_population = new_population[:self.config.population_size]
            
            # Re-evaluate elites with current backtest function
            if elites:
                elite_dnas = [dna for dna, _ in new_population[:self.config.elite_size]]
                elite_evaluated = await self._evaluate_population(elite_dnas, backtest_func)
                new_population[:self.config.elite_size] = elite_evaluated
            
            self.population = new_population
            
            logger.info(
                "Generation %d complete | Best fitness: %.4f | Avg fitness: %.4f | Diversity: %.4f",
                generation + 1,
                best_fitness,
                stats["mean"],
                diversity,
            )
        
        # Get best individual
        best_dna, best_fitness = max(self.population, key=lambda x: x[1])
        
        # Get detailed fitness result for best individual
        best_backtest = await backtest_func(best_dna)
        best_fitness_result = calculate_fitness(best_backtest)
        
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        result = GAResult(
            best_dna=best_dna,
            best_fitness=best_fitness,
            best_fitness_result=best_fitness_result,
            generation_history=self.generation_history,
            final_population=self.population,
            converged=self._check_convergence(),
            total_evaluations=self.total_evaluations,
            elapsed_seconds=elapsed,
        )
        
        logger.info(
            "Genetic evolution complete | Best fitness: %.4f | Evaluations: %d | Elapsed: %.2fs",
            best_fitness,
            self.total_evaluations,
            elapsed,
        )
        
        return result
    
    async def _initialize_population(
        self,
        backtest_func: callable,
    ) -> list[tuple[StrategyDNA, float]]:
        """Initialize random population and evaluate fitness.
        
        Args:
            backtest_func: Async function for backtesting
            
        Returns:
            List of (DNA, fitness) tuples
        """
        population = []
        
        for i in range(self.config.population_size):
            dna = create_random_dna(self.indicator_names)
            population.append(dna)
        
        return await self._evaluate_population(population, backtest_func)
    
    async def _evaluate_population(
        self,
        population: list[StrategyDNA],
        backtest_func: callable,
    ) -> list[tuple[StrategyDNA, float]]:
        """Evaluate fitness for entire population.
        
        Args:
            population: List of StrategyDNA instances
            backtest_func: Async function for backtesting
            
        Returns:
            List of (DNA, fitness) tuples
        """
        evaluated = []
        
        # Parallel evaluation
        tasks = [backtest_func(dna) for dna in population]
        backtest_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for dna, result in zip(population, backtest_results):
            if isinstance(result, Exception):
                logger.error(f"Backtest failed for DNA: {result}")
                fitness = 0.0
            else:
                fitness_result = calculate_fitness(result)
                fitness = fitness_result.fitness
            
            evaluated.append((dna, fitness))
            self.total_evaluations += 1
        
        return evaluated
    
    def _selection(self) -> list[StrategyDNA]:
        """Select individuals for reproduction using tournament selection.
        
        Returns:
            List of selected StrategyDNA instances
        """
        selected = []
        
        for _ in range(self.config.population_size):
            selected.append(selection_tournament(self.population, self.config.tournament_size))
        
        return selected
    
    def _crossover(self, selected: list[StrategyDNA]) -> list[StrategyDNA]:
        """Apply crossover to selected individuals.
        
        Args:
            selected: List of selected StrategyDNA instances
            
        Returns:
            List of offspring StrategyDNA instances
        """
        offspring = []
        
        for i in range(0, len(selected), 2):
            if i + 1 < len(selected):
                parent1 = selected[i]
                parent2 = selected[i + 1]
                
                if np.random.random() < self.config.crossover_rate:
                    child = crossover_blend(parent1, parent2)
                    offspring.append(child)
                else:
                    # No crossover, add parents as-is
                    offspring.append(parent1)
                    offspring.append(parent2)
            else:
                # Odd number, add last individual as-is
                offspring.append(selected[i])
        
        return offspring
    
    def _mutation(
        self,
        population: list[StrategyDNA],
        generation: int,
    ) -> list[StrategyDNA]:
        """Apply mutation to population.
        
        Args:
            population: List of StrategyDNA instances
            generation: Current generation number
            
        Returns:
            List of mutated StrategyDNA instances
        """
        mutated = []
        
        for dna in population:
            if self.config.adaptive_mutation:
                mutated_dna = mutation_gaussian(
                    dna,
                    mutation_rate=self.config.mutation_rate,
                    mutation_strength=self.config.mutation_strength,
                    adaptive=True,
                    generation=generation,
                    max_generations=self.config.generations,
                )
            else:
                mutated_dna = mutation_gaussian(
                    dna,
                    mutation_rate=self.config.mutation_rate,
                    mutation_strength=self.config.mutation_strength,
                )
            
            mutated.append(mutated_dna)
        
        return mutated
    
    def _check_convergence(self) -> bool:
        """Check if population has converged.
        
        Convergence is detected if best fitness hasn't improved
        significantly over the last convergence_window generations.
        
        Returns:
            True if converged, False otherwise
        """
        if len(self.best_fitness_history) < self.config.convergence_window:
            return False
        
        recent = self.best_fitness_history[-self.config.convergence_window:]
        
        # Check if improvement is below tolerance
        improvement = max(recent) - min(recent)
        
        return improvement < self.config.convergence_tolerance


async def run_genetic_evolution(
    backtest_func: callable,
    config: GAConfig | None = None,
    indicator_names: list[str] | None = None,
    initial_population: list[StrategyDNA] | None = None,
) -> GAResult:
    """Convenience function to run genetic algorithm evolution.
    
    Args:
        backtest_func: Async function that takes DNA and returns backtest result
        config: GA configuration (default: GAConfig())
        indicator_names: List of indicator names for DNA encoding
        initial_population: Optional initial population (random if None)
        
    Returns:
        GAResult with best DNA and evolution history
    """
    evolution = GeneticEvolution(config, indicator_names)
    return await evolution.run_evolution(backtest_func, initial_population)


__all__ = [
    "GAConfig",
    "GAResult",
    "GeneticEvolution",
    "run_genetic_evolution",
]
