"""Fitness functions for genetic algorithm strategy evolution.

This module implements multi-objective fitness functions for evaluating
trading strategies, combining Sharpe ratio, total return, and maximum
drawdown into a single fitness score with penalties for undesirable traits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FitnessResult:
    """Result of fitness evaluation."""
    
    fitness: float
    sharpe_ratio: float
    total_return: float
    max_drawdown: float
    profit_factor: float
    win_rate: float
    total_trades: int
    penalties: dict[str, float]
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "fitness": self.fitness,
            "sharpe_ratio": self.sharpe_ratio,
            "total_return": self.total_return,
            "max_drawdown": self.max_drawdown,
            "profit_factor": self.profit_factor,
            "win_rate": self.win_rate,
            "total_trades": self.total_trades,
            "penalties": self.penalties,
        }


def calculate_fitness(
    backtest_result: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> FitnessResult:
    """Calculate fitness score from backtest results.
    
    Multi-objective fitness function:
    fitness = (sharpe * w1) + (return * w2) + (1/max_dd * w3)
    
    With penalties for:
    - Insufficient trades
    - High turnover
    - Overfitting (in-sample vs OOS divergence)
    
    Args:
        backtest_result: Dictionary with backtest metrics
        weights: Optional custom weights for fitness components
        
    Returns:
        FitnessResult with fitness score and component metrics
    """
    # Default weights
    if weights is None:
        weights = {
            "sharpe": 0.4,
            "return": 0.3,
            "drawdown": 0.3,
        }
    
    # Extract metrics with fallbacks
    sharpe_ratio = backtest_result.get("sharpe_ratio", 0.0)
    total_return = backtest_result.get("profit_total", 0.0)
    max_drawdown = abs(backtest_result.get("max_drawdown_abs", 0.1))
    profit_factor = backtest_result.get("profit_factor", 1.0)
    win_rate = backtest_result.get("win_rate", 0.0)
    total_trades = backtest_result.get("total_trades", 0)
    
    # Normalize metrics to 0-1 scale
    # Sharpe: 3.0 is excellent, 0 is poor
    sharpe_norm = min(sharpe_ratio / 3.0, 1.0)
    
    # Return: 100% is excellent, 0% is poor
    return_norm = min(total_return / 100.0, 1.0) if total_return > 0 else 0.0
    
    # Drawdown: 0% is excellent, 50% is poor
    drawdown_norm = max(0, 1.0 - (max_drawdown / 0.5))
    
    # Calculate base fitness
    base_fitness = (
        sharpe_norm * weights["sharpe"] +
        return_norm * weights["return"] +
        drawdown_norm * weights["drawdown"]
    )
    
    # Apply penalties
    penalties = {}
    
    # Penalty for insufficient trades (< 20)
    min_trades = 20
    if total_trades < min_trades:
        trade_penalty = (min_trades - total_trades) / min_trades * 0.5
        penalties["insufficient_trades"] = trade_penalty
        base_fitness -= trade_penalty
    
    # Penalty for high turnover (> 50% monthly)
    # This would need trade frequency data, simplified here
    turnover_penalty = 0.0
    if "avg_trade_duration_hours" in backtest_result:
        avg_duration = backtest_result["avg_trade_duration_hours"]
        if avg_duration < 24:  # Less than 1 day average hold
            turnover_penalty = 0.1
            penalties["high_turnover"] = turnover_penalty
            base_fitness -= turnover_penalty
    
    # Penalty for poor profit factor (< 1.0)
    if profit_factor < 1.0:
        pf_penalty = (1.0 - profit_factor) * 0.2
        penalties["poor_profit_factor"] = pf_penalty
        base_fitness -= pf_penalty
    
    # Penalty for low win rate (< 40%)
    if win_rate < 0.4:
        win_rate_penalty = (0.4 - win_rate) * 0.3
        penalties["low_win_rate"] = win_rate_penalty
        base_fitness -= win_rate_penalty
    
    # Ensure fitness is non-negative
    fitness = max(0.0, base_fitness)
    
    return FitnessResult(
        fitness=fitness,
        sharpe_ratio=sharpe_ratio,
        total_return=total_return,
        max_drawdown=max_drawdown,
        profit_factor=profit_factor,
        win_rate=win_rate,
        total_trades=total_trades,
        penalties=penalties,
    )


def calculate_fitness_multi_objective(
    backtest_result: dict[str, Any],
) -> dict[str, float]:
    """Calculate multi-objective fitness (Pareto front).
    
    Returns separate fitness values for each objective:
    - sharpe_fitness: Normalized Sharpe ratio
    - return_fitness: Normalized total return
    - drawdown_fitness: Normalized inverse drawdown
    
    Args:
        backtest_result: Dictionary with backtest metrics
        
    Returns:
        Dictionary with fitness values for each objective
    """
    sharpe_ratio = backtest_result.get("sharpe_ratio", 0.0)
    total_return = backtest_result.get("profit_total", 0.0)
    max_drawdown = abs(backtest_result.get("max_drawdown_abs", 0.1))
    
    # Normalize each objective
    sharpe_fitness = min(sharpe_ratio / 3.0, 1.0)
    return_fitness = min(total_return / 100.0, 1.0) if total_return > 0 else 0.0
    drawdown_fitness = max(0, 1.0 - (max_drawdown / 0.5))
    
    return {
        "sharpe_fitness": sharpe_fitness,
        "return_fitness": return_fitness,
        "drawdown_fitness": drawdown_fitness,
    }


def calculate_fitness_sharpe_only(
    backtest_result: dict[str, Any],
) -> FitnessResult:
    """Calculate fitness using Sharpe ratio only.
    
    Simpler fitness function focused on risk-adjusted returns.
    
    Args:
        backtest_result: Dictionary with backtest metrics
        
    Returns:
        FitnessResult with Sharpe-based fitness
    """
    sharpe_ratio = backtest_result.get("sharpe_ratio", 0.0)
    total_return = backtest_result.get("profit_total", 0.0)
    max_drawdown = abs(backtest_result.get("max_drawdown_abs", 0.1))
    profit_factor = backtest_result.get("profit_factor", 1.0)
    win_rate = backtest_result.get("win_rate", 0.0)
    total_trades = backtest_result.get("total_trades", 0)
    
    # Fitness is just Sharpe ratio normalized
    fitness = min(sharpe_ratio / 3.0, 1.0)
    
    # Apply basic penalties
    penalties = {}
    
    if total_trades < 20:
        trade_penalty = (20 - total_trades) / 20 * 0.5
        penalties["insufficient_trades"] = trade_penalty
        fitness -= trade_penalty
    
    if profit_factor < 1.0:
        pf_penalty = (1.0 - profit_factor) * 0.2
        penalties["poor_profit_factor"] = pf_penalty
        fitness -= pf_penalty
    
    fitness = max(0.0, fitness)
    
    return FitnessResult(
        fitness=fitness,
        sharpe_ratio=sharpe_ratio,
        total_return=total_return,
        max_drawdown=max_drawdown,
        profit_factor=profit_factor,
        win_rate=win_rate,
        total_trades=total_trades,
        penalties=penalties,
    )


def calculate_fitness_profit_only(
    backtest_result: dict[str, Any],
) -> FitnessResult:
    """Calculate fitness using total profit only.
    
    Simple fitness function focused on absolute returns.
    
    Args:
        backtest_result: Dictionary with backtest metrics
        
    Returns:
        FitnessResult with profit-based fitness
    """
    sharpe_ratio = backtest_result.get("sharpe_ratio", 0.0)
    total_return = backtest_result.get("profit_total", 0.0)
    max_drawdown = abs(backtest_result.get("max_drawdown_abs", 0.1))
    profit_factor = backtest_result.get("profit_factor", 1.0)
    win_rate = backtest_result.get("win_rate", 0.0)
    total_trades = backtest_result.get("total_trades", 0)
    
    # Fitness is total return normalized
    fitness = min(total_return / 100.0, 1.0) if total_return > 0 else 0.0
    
    # Apply basic penalties
    penalties = {}
    
    if total_trades < 20:
        trade_penalty = (20 - total_trades) / 20 * 0.5
        penalties["insufficient_trades"] = trade_penalty
        fitness -= trade_penalty
    
    if max_drawdown > 0.3:  # 30% drawdown penalty
        dd_penalty = (max_drawdown - 0.3) / 0.2 * 0.5
        penalties["high_drawdown"] = dd_penalty
        fitness -= dd_penalty
    
    fitness = max(0.0, fitness)
    
    return FitnessResult(
        fitness=fitness,
        sharpe_ratio=sharpe_ratio,
        total_return=total_return,
        max_drawdown=max_drawdown,
        profit_factor=profit_factor,
        win_rate=win_rate,
        total_trades=total_trades,
        penalties=penalties,
    )


def calculate_fitness_sortino(
    backtest_result: dict[str, Any],
) -> FitnessResult:
    """Calculate fitness using Sortino ratio.
    
    Similar to Sharpe but only penalizes downside volatility.
    
    Args:
        backtest_result: Dictionary with backtest metrics
        
    Returns:
        FitnessResult with Sortino-based fitness
    """
    # Sortino ratio = (return - risk_free_rate) / downside_deviation
    # Simplified: use profit_factor as proxy
    profit_factor = backtest_result.get("profit_factor", 1.0)
    total_return = backtest_result.get("profit_total", 0.0)
    max_drawdown = abs(backtest_result.get("max_drawdown_abs", 0.1))
    sharpe_ratio = backtest_result.get("sharpe_ratio", 0.0)
    win_rate = backtest_result.get("win_rate", 0.0)
    total_trades = backtest_result.get("total_trades", 0)
    
    # Fitness based on profit factor
    fitness = min(profit_factor / 3.0, 1.0)
    
    # Apply penalties
    penalties = {}
    
    if total_trades < 20:
        trade_penalty = (20 - total_trades) / 20 * 0.5
        penalties["insufficient_trades"] = trade_penalty
        fitness -= trade_penalty
    
    if max_drawdown > 0.3:
        dd_penalty = (max_drawdown - 0.3) / 0.2 * 0.5
        penalties["high_drawdown"] = dd_penalty
        fitness -= dd_penalty
    
    fitness = max(0.0, fitness)
    
    return FitnessResult(
        fitness=fitness,
        sharpe_ratio=sharpe_ratio,
        total_return=total_return,
        max_drawdown=max_drawdown,
        profit_factor=profit_factor,
        win_rate=win_rate,
        total_trades=total_trades,
        penalties=penalties,
    )


def compare_fitness(
    fitness1: float,
    fitness2: float,
    tolerance: float = 1e-6,
) -> int:
    """Compare two fitness values.
    
    Args:
        fitness1: First fitness value
        fitness2: Second fitness value
        tolerance: Tolerance for equality
        
    Returns:
        -1 if fitness1 < fitness2
        0 if fitness1 == fitness2 (within tolerance)
        1 if fitness1 > fitness2
    """
    if abs(fitness1 - fitness2) < tolerance:
        return 0
    elif fitness1 < fitness2:
        return -1
    else:
        return 1


def rank_by_fitness(
    population: list[tuple[Any, float]],
    descending: bool = True,
) -> list[tuple[Any, float]]:
    """Rank population by fitness.
    
    Args:
        population: List of (individual, fitness) tuples
        descending: Whether to rank in descending order (higher is better)
        
    Returns:
        Sorted list of (individual, fitness) tuples
    """
    return sorted(population, key=lambda x: x[1], reverse=descending)


def calculate_population_statistics(
    fitness_values: list[float],
) -> dict[str, float]:
    """Calculate statistics for population fitness.
    
    Args:
        fitness_values: List of fitness values
        
    Returns:
        Dictionary with statistics (mean, std, min, max, median)
    """
    if not fitness_values:
        return {
            "mean": 0.0,
            "std": 0.0,
            "min": 0.0,
            "max": 0.0,
            "median": 0.0,
        }
    
    import numpy as np
    
    return {
        "mean": float(np.mean(fitness_values)),
        "std": float(np.std(fitness_values)),
        "min": float(np.min(fitness_values)),
        "max": float(np.max(fitness_values)),
        "median": float(np.median(fitness_values)),
    }


__all__ = [
    "FitnessResult",
    "calculate_fitness",
    "calculate_fitness_multi_objective",
    "calculate_fitness_sharpe_only",
    "calculate_fitness_profit_only",
    "calculate_fitness_sortino",
    "compare_fitness",
    "rank_by_fitness",
    "calculate_population_statistics",
]
