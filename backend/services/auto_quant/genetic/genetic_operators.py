"""Genetic algorithm operators for strategy evolution.

This module implements crossover and mutation operators for evolving
trading strategy DNA, including blend crossover for continuous parameters
and uniform crossover for discrete parameters.
"""

from __future__ import annotations

import logging
import random
from typing import Any

import numpy as np

from .strategy_dna import StrategyDNA, get_default_indicator_names

logger = logging.getLogger(__name__)


def crossover_blend(
    parent1: StrategyDNA,
    parent2: StrategyDNA,
    alpha: float = 0.5,
) -> StrategyDNA:
    """Blend crossover for continuous parameters.
    
    Creates offspring by blending parent parameters:
    offspring = alpha * parent1 + (1 - alpha) * parent2
    
    Args:
        parent1: First parent DNA
        parent2: Second parent DNA
        alpha: Blend factor (0.5 = equal blend)
        
    Returns:
        New StrategyDNA (offspring)
    """
    # Blend indicator weights
    offspring_weights = {}
    for name in parent1.indicator_weights.keys():
        w1 = parent1.indicator_weights.get(name, 0.5)
        w2 = parent2.indicator_weights.get(name, 0.5)
        offspring_weights[name] = alpha * w1 + (1 - alpha) * w2
    
    # Blend buy thresholds
    offspring_buy = {}
    for key in parent1.buy_thresholds.keys():
        v1 = parent1.buy_thresholds.get(key, 0)
        v2 = parent2.buy_thresholds.get(key, 0)
        offspring_buy[key] = alpha * v1 + (1 - alpha) * v2
    
    # Blend sell thresholds
    offspring_sell = {}
    for key in parent1.sell_thresholds.keys():
        v1 = parent1.sell_thresholds.get(key, 0)
        v2 = parent2.sell_thresholds.get(key, 0)
        offspring_sell[key] = alpha * v1 + (1 - alpha) * v2
    
    # Blend risk parameters
    offspring_risk = {}
    for key in parent1.risk_parameters.keys():
        v1 = parent1.risk_parameters.get(key, 0)
        v2 = parent2.risk_parameters.get(key, 0)
        
        if isinstance(v1, bool) or isinstance(v2, bool):
            # For booleans, use probability based on alpha
            offspring_risk[key] = v1 if random.random() < alpha else v2
        elif isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
            offspring_risk[key] = alpha * v1 + (1 - alpha) * v2
        else:
            offspring_risk[key] = v1
    
    # Blend strategy parameters
    offspring_hold_days = int(alpha * parent1.hold_days + (1 - alpha) * parent2.hold_days)
    offspring_regime_sensitivity = alpha * parent1.regime_sensitivity + (1 - alpha) * parent2.regime_sensitivity
    
    # Uniform crossover for boolean switches
    offspring_switches = {}
    for key in parent1.indicator_switches.keys():
        v1 = parent1.indicator_switches.get(key, False)
        v2 = parent2.indicator_switches.get(key, False)
        offspring_switches[key] = v1 if random.random() < alpha else v2
    
    offspring = StrategyDNA(
        indicator_weights=offspring_weights,
        buy_thresholds=offspring_buy,
        sell_thresholds=offspring_sell,
        risk_parameters=offspring_risk,
        hold_days=offspring_hold_days,
        regime_sensitivity=offspring_regime_sensitivity,
        indicator_switches=offspring_switches,
    )
    
    # Clamp to ensure valid ranges
    return offspring.clamp()


def crossover_uniform(
    parent1: StrategyDNA,
    parent2: StrategyDNA,
    crossover_rate: float = 0.5,
) -> StrategyDNA:
    """Uniform crossover for all parameters.
    
    Each parameter is independently selected from either parent
    with probability crossover_rate.
    
    Args:
        parent1: First parent DNA
        parent2: Second parent DNA
        crossover_rate: Probability of selecting from parent1
        
    Returns:
        New StrategyDNA (offspring)
    """
    # Uniform crossover for indicator weights
    offspring_weights = {}
    for name in parent1.indicator_weights.keys():
        if random.random() < crossover_rate:
            offspring_weights[name] = parent1.indicator_weights[name]
        else:
            offspring_weights[name] = parent2.indicator_weights.get(name, 0.5)
    
    # Uniform crossover for buy thresholds
    offspring_buy = {}
    for key in parent1.buy_thresholds.keys():
        if random.random() < crossover_rate:
            offspring_buy[key] = parent1.buy_thresholds[key]
        else:
            offspring_buy[key] = parent2.buy_thresholds.get(key, 0)
    
    # Uniform crossover for sell thresholds
    offspring_sell = {}
    for key in parent1.sell_thresholds.keys():
        if random.random() < crossover_rate:
            offspring_sell[key] = parent1.sell_thresholds[key]
        else:
            offspring_sell[key] = parent2.sell_thresholds.get(key, 0)
    
    # Uniform crossover for risk parameters
    offspring_risk = {}
    for key in parent1.risk_parameters.keys():
        if random.random() < crossover_rate:
            offspring_risk[key] = parent1.risk_parameters[key]
        else:
            offspring_risk[key] = parent2.risk_parameters.get(key, 0)
    
    # Uniform crossover for strategy parameters
    if random.random() < crossover_rate:
        offspring_hold_days = parent1.hold_days
        offspring_regime_sensitivity = parent1.regime_sensitivity
    else:
        offspring_hold_days = parent2.hold_days
        offspring_regime_sensitivity = parent2.regime_sensitivity
    
    # Uniform crossover for boolean switches
    offspring_switches = {}
    for key in parent1.indicator_switches.keys():
        if random.random() < crossover_rate:
            offspring_switches[key] = parent1.indicator_switches[key]
        else:
            offspring_switches[key] = parent2.indicator_switches.get(key, False)
    
    offspring = StrategyDNA(
        indicator_weights=offspring_weights,
        buy_thresholds=offspring_buy,
        sell_thresholds=offspring_sell,
        risk_parameters=offspring_risk,
        hold_days=offspring_hold_days,
        regime_sensitivity=offspring_regime_sensitivity,
        indicator_switches=offspring_switches,
    )
    
    # Clamp to ensure valid ranges
    return offspring.clamp()


def mutation_gaussian(
    dna: StrategyDNA,
    mutation_rate: float = 0.1,
    mutation_strength: float = 0.1,
    adaptive: bool = False,
    generation: int = 0,
    max_generations: int = 100,
) -> StrategyDNA:
    """Gaussian mutation for continuous parameters.
    
    Adds Gaussian noise to parameters with probability mutation_rate.
    Can adapt mutation strength based on generation (adaptive GA).
    
    Args:
        dna: StrategyDNA to mutate
        mutation_rate: Probability of mutating each parameter
        mutation_strength: Standard deviation of Gaussian noise
        adaptive: Whether to adapt mutation strength over generations
        generation: Current generation number
        max_generations: Maximum number of generations
        
    Returns:
        Mutated StrategyDNA
    """
    # Adapt mutation strength (decrease over time)
    if adaptive:
        # Linear decay from 1.0 to 0.1
        adaptive_strength = mutation_strength * (1 - 0.9 * generation / max_generations)
        adaptive_strength = max(0.01, adaptive_strength)
    else:
        adaptive_strength = mutation_strength
    
    # Mutate indicator weights
    mutated_weights = {}
    for name, weight in dna.indicator_weights.items():
        if random.random() < mutation_rate:
            noise = np.random.normal(0, adaptive_strength)
            mutated_weights[name] = max(0.0, min(1.0, weight + noise))
        else:
            mutated_weights[name] = weight
    
    # Mutate buy thresholds
    mutated_buy = {}
    for key, value in dna.buy_thresholds.items():
        if random.random() < mutation_rate:
            noise = np.random.normal(0, adaptive_strength * 10)
            if key == "rsi_buy":
                mutated_buy[key] = max(0.0, min(100.0, value + noise))
            else:
                mutated_buy[key] = value + noise
        else:
            mutated_buy[key] = value
    
    # Mutate sell thresholds
    mutated_sell = {}
    for key, value in dna.sell_thresholds.items():
        if random.random() < mutation_rate:
            noise = np.random.normal(0, adaptive_strength * 10)
            if key == "rsi_sell":
                mutated_sell[key] = max(0.0, min(100.0, value + noise))
            else:
                mutated_sell[key] = value + noise
        else:
            mutated_sell[key] = value
    
    # Mutate risk parameters
    mutated_risk = {}
    for key, value in dna.risk_parameters.items():
        if random.random() < mutation_rate:
            if isinstance(value, bool):
                # Flip boolean
                mutated_risk[key] = not value
            elif isinstance(value, (int, float)):
                noise = np.random.normal(0, adaptive_strength)
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
    if random.random() < mutation_rate:
        mutated_hold_days = max(1, min(365, int(dna.hold_days + np.random.normal(0, adaptive_strength * 10))))
    else:
        mutated_hold_days = dna.hold_days
    
    if random.random() < mutation_rate:
        mutated_regime_sensitivity = max(0.0, min(1.0, dna.regime_sensitivity + np.random.normal(0, adaptive_strength)))
    else:
        mutated_regime_sensitivity = dna.regime_sensitivity
    
    # Mutate boolean switches
    mutated_switches = {}
    for key, value in dna.indicator_switches.items():
        if random.random() < mutation_rate:
            mutated_switches[key] = not value
        else:
            mutated_switches[key] = value
    
    mutated = StrategyDNA(
        indicator_weights=mutated_weights,
        buy_thresholds=mutated_buy,
        sell_thresholds=mutated_sell,
        risk_parameters=mutated_risk,
        hold_days=mutated_hold_days,
        regime_sensitivity=mutated_regime_sensitivity,
        indicator_switches=mutated_switches,
    )
    
    # Clamp to ensure valid ranges
    return mutated.clamp()


def mutation_bit_flip(
    dna: StrategyDNA,
    mutation_rate: float = 0.1,
) -> StrategyDNA:
    """Bit-flip mutation for boolean parameters.
    
    Randomly flips boolean switches with probability mutation_rate.
    
    Args:
        dna: StrategyDNA to mutate
        mutation_rate: Probability of flipping each boolean
        
    Returns:
        Mutated StrategyDNA
    """
    # Mutate boolean switches
    mutated_switches = {}
    for key, value in dna.indicator_switches.items():
        if random.random() < mutation_rate:
            mutated_switches[key] = not value
        else:
            mutated_switches[key] = value
    
    # Also flip trailing_only boolean in risk parameters
    mutated_risk = dna.risk_parameters.copy()
    if random.random() < mutation_rate:
        mutated_risk["trailing_only"] = not mutated_risk.get("trailing_only", False)
    
    return StrategyDNA(
        indicator_weights=dna.indicator_weights.copy(),
        buy_thresholds=dna.buy_thresholds.copy(),
        sell_thresholds=dna.sell_thresholds.copy(),
        risk_parameters=mutated_risk,
        hold_days=dna.hold_days,
        regime_sensitivity=dna.regime_sensitivity,
        indicator_switches=mutated_switches,
    )


def selection_tournament(
    population: list[tuple[StrategyDNA, float]],
    tournament_size: int = 3,
) -> StrategyDNA:
    """Tournament selection.
    
    Randomly selects tournament_size individuals and returns the fittest.
    
    Args:
        population: List of (DNA, fitness) tuples
        tournament_size: Number of individuals in each tournament
        
    Returns:
        Selected StrategyDNA (fittest from tournament)
    """
    if len(population) == 0:
        raise ValueError("Population is empty")
    
    if tournament_size > len(population):
        tournament_size = len(population)
    
    # Randomly select tournament participants
    tournament = random.sample(population, tournament_size)
    
    # Return fittest
    fittest = max(tournament, key=lambda x: x[1])
    return fittest[0]


def selection_roulette(
    population: list[tuple[StrategyDNA, float]],
) -> StrategyDNA:
    """Roulette wheel selection (fitness-proportionate).
    
    Selects an individual with probability proportional to its fitness.
    
    Args:
        population: List of (DNA, fitness) tuples
        
    Returns:
        Selected StrategyDNA
    """
    if len(population) == 0:
        raise ValueError("Population is empty")
    
    # Extract fitness values
    fitness_values = [f for _, f in population]
    
    # Handle negative fitness by shifting to positive
    min_fitness = min(fitness_values)
    if min_fitness < 0:
        fitness_values = [f - min_fitness + 1 for f in fitness_values]
    
    total_fitness = sum(fitness_values)
    if total_fitness == 0:
        # All fitness values are zero, select randomly
        return random.choice(population)[0]
    
    # Select based on fitness proportion
    r = random.uniform(0, total_fitness)
    cumulative = 0
    for (dna, fitness), adjusted_fitness in zip(population, fitness_values):
        cumulative += adjusted_fitness
        if r <= cumulative:
            return dna
    
    # Fallback to last individual
    return population[-1][0]


def selection_rank(
    population: list[tuple[StrategyDNA, float]],
) -> StrategyDNA:
    """Rank-based selection.
    
    Selects based on rank rather than absolute fitness values.
    Reduces selection pressure when fitness differences are large.
    
    Args:
        population: List of (DNA, fitness) tuples
        
    Returns:
        Selected StrategyDNA
    """
    if len(population) == 0:
        raise ValueError("Population is empty")
    
    # Sort by fitness (descending)
    sorted_pop = sorted(population, key=lambda x: x[1], reverse=True)
    
    # Assign ranks (higher rank = higher probability)
    n = len(sorted_pop)
    ranks = list(range(n, 0, -1))  # n, n-1, ..., 1
    total_rank = sum(ranks)
    
    # Select based on rank proportion
    r = random.uniform(0, total_rank)
    cumulative = 0
    for (dna, _), rank in zip(sorted_pop, ranks):
        cumulative += rank
        if r <= cumulative:
            return dna
    
    # Fallback to last individual
    return sorted_pop[-1][0]


def elitism_selection(
    population: list[tuple[StrategyDNA, float]],
    elite_size: int = 2,
) -> list[StrategyDNA]:
    """Select top individuals for elitism.
    
    Args:
        population: List of (DNA, fitness) tuples
        elite_size: Number of elite individuals to select
        
    Returns:
        List of elite StrategyDNA instances
    """
    if elite_size <= 0:
        return []
    
    if elite_size > len(population):
        elite_size = len(population)
    
    # Sort by fitness (descending)
    sorted_pop = sorted(population, key=lambda x: x[1], reverse=True)
    
    # Return top elite_size individuals
    return [dna for dna, _ in sorted_pop[:elite_size]]


def calculate_diversity(
    population: list[StrategyDNA],
    indicator_names: list[str],
) -> float:
    """Calculate population diversity using average pairwise distance.
    
    Args:
        population: List of StrategyDNA instances
        indicator_names: List of indicator names for array conversion
        
    Returns:
        Diversity score (higher = more diverse)
    """
    if len(population) < 2:
        return 0.0
    
    # Convert all DNA to arrays
    arrays = [dna.to_array() for dna in population]
    
    # Calculate pairwise distances
    total_distance = 0.0
    count = 0
    
    for i in range(len(arrays)):
        for j in range(i + 1, len(arrays)):
            # Euclidean distance
            distance = np.linalg.norm(arrays[i] - arrays[j])
            total_distance += distance
            count += 1
    
    if count == 0:
        return 0.0
    
    return total_distance / count


def check_convergence(
    population: list[tuple[StrategyDNA, float]],
    window_size: int = 5,
    tolerance: float = 1e-6,
) -> bool:
    """Check if population has converged.
    
    Convergence is detected if the best fitness hasn't improved
    significantly over the last window_size generations.
    
    Args:
        population: Current population (not used directly, kept for interface)
        window_size: Number of generations to check
        tolerance: Minimum improvement threshold
        
    Returns:
        True if converged, False otherwise
    """
    # This would need to track fitness history across generations
    # For now, return False (not converged)
    # In a full implementation, this would check fitness_history
    return False


__all__ = [
    "crossover_blend",
    "crossover_uniform",
    "mutation_gaussian",
    "mutation_bit_flip",
    "selection_tournament",
    "selection_roulette",
    "selection_rank",
    "elitism_selection",
    "calculate_diversity",
    "check_convergence",
]
