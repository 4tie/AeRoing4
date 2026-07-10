"""Tests for genetic algorithm evolution modules."""

import pytest
import numpy as np
import asyncio
from pathlib import Path

from backend.services.auto_quant.genetic.strategy_dna import (
    StrategyDNA,
    create_random_dna,
    get_default_indicator_names,
)
from backend.services.auto_quant.genetic.genetic_operators import (
    crossover_blend,
    crossover_uniform,
    mutation_gaussian,
    mutation_bit_flip,
    selection_tournament,
    selection_roulette,
    selection_rank,
    elitism_selection,
    calculate_diversity,
)
from backend.services.auto_quant.genetic.genetic_fitness import (
    calculate_fitness,
    calculate_fitness_multi_objective,
    calculate_fitness_sharpe_only,
    calculate_fitness_profit_only,
    calculate_fitness_sortino,
    FitnessResult,
    rank_by_fitness,
    calculate_population_statistics,
)
from backend.services.auto_quant.genetic.genetic_evolution import (
    GAConfig,
    GAResult,
    GeneticEvolution,
    run_genetic_evolution,
)


@pytest.fixture
def indicator_names():
    """Get indicator names for testing."""
    return get_default_indicator_names()[:10]  # Use smaller set for testing


@pytest.fixture
def sample_dna(indicator_names):
    """Create a sample DNA for testing."""
    return create_random_dna(indicator_names)


class TestStrategyDNA:
    """Tests for StrategyDNA encoding and operations."""
    
    def test_create_random_dna(self, indicator_names):
        """Test creation of random DNA."""
        dna = create_random_dna(indicator_names)
        
        assert isinstance(dna, StrategyDNA)
        assert len(dna.indicator_weights) == len(indicator_names)
        assert len(dna.buy_thresholds) > 0
        assert len(dna.sell_thresholds) > 0
        assert len(dna.risk_parameters) > 0
        assert dna.hold_days > 0
        assert 0 <= dna.regime_sensitivity <= 1
    
    def test_dna_to_array(self, sample_dna):
        """Test DNA to array conversion."""
        arr = sample_dna.to_array()
        
        assert isinstance(arr, np.ndarray)
        assert len(arr) > 0
        assert arr.dtype == np.float64
    
    def test_dna_from_array(self, indicator_names, sample_dna):
        """Test DNA from array conversion."""
        arr = sample_dna.to_array()
        dna2 = StrategyDNA.from_array(arr, indicator_names)
        
        assert isinstance(dna2, StrategyDNA)
        assert len(dna2.indicator_weights) == len(indicator_names)
    
    def test_dna_validate(self, sample_dna):
        """Test DNA validation."""
        is_valid, error = sample_dna.validate()
        
        assert is_valid
        assert error == ""
    
    def test_dna_validate_invalid(self, indicator_names):
        """Test DNA validation with invalid parameters."""
        dna = create_random_dna(indicator_names)
        dna.risk_parameters["stoploss"] = -1.0  # Invalid
        
        is_valid, error = dna.validate()
        
        assert not is_valid
        assert "out of range" in error.lower()
    
    def test_dna_clamp(self, indicator_names):
        """Test DNA clamping to valid ranges."""
        dna = create_random_dna(indicator_names)
        dna.risk_parameters["stoploss"] = -1.0  # Invalid
        dna.buy_thresholds["rsi_buy"] = 150.0  # Invalid
        
        clamped = dna.clamp()
        
        is_valid, _ = clamped.validate()
        assert is_valid
        assert -0.5 <= clamped.risk_parameters["stoploss"] <= 0
        assert 0 <= clamped.buy_thresholds["rsi_buy"] <= 100
    
    def test_dna_to_dict(self, sample_dna):
        """Test DNA to dictionary conversion."""
        d = sample_dna.to_dict()
        
        assert isinstance(d, dict)
        assert "indicator_weights" in d
        assert "buy_thresholds" in d
        assert "sell_thresholds" in d
        assert "risk_parameters" in d
    
    def test_dna_from_dict(self, indicator_names):
        """Test DNA from dictionary conversion."""
        dna1 = create_random_dna(indicator_names)
        d = dna1.to_dict()
        
        dna2 = StrategyDNA.from_dict(d)
        
        assert dna2.indicator_weights == dna1.indicator_weights
        assert dna2.hold_days == dna1.hold_days
    
    def test_dna_mutate(self, sample_dna):
        """Test DNA mutation."""
        mutated = sample_dna.mutate(mutation_rate=0.5, mutation_strength=0.1)
        
        assert isinstance(mutated, StrategyDNA)
        # Some parameters should be different
        assert mutated.indicator_weights != sample_dna.indicator_weights or \
               mutated.buy_thresholds != sample_dna.buy_thresholds


class TestGeneticOperators:
    """Tests for genetic algorithm operators."""
    
    def test_crossover_blend(self, indicator_names):
        """Test blend crossover."""
        parent1 = create_random_dna(indicator_names)
        parent2 = create_random_dna(indicator_names)
        
        offspring = crossover_blend(parent1, parent2, alpha=0.5)
        
        assert isinstance(offspring, StrategyDNA)
        # Offspring should be a blend of parents
        is_valid, _ = offspring.validate()
        assert is_valid
    
    def test_crossover_uniform(self, indicator_names):
        """Test uniform crossover."""
        parent1 = create_random_dna(indicator_names)
        parent2 = create_random_dna(indicator_names)
        
        offspring = crossover_uniform(parent1, parent2, crossover_rate=0.5)
        
        assert isinstance(offspring, StrategyDNA)
        is_valid, _ = offspring.validate()
        assert is_valid
    
    def test_mutation_gaussian(self, indicator_names):
        """Test Gaussian mutation."""
        dna = create_random_dna(indicator_names)
        
        mutated = mutation_gaussian(dna, mutation_rate=0.5, mutation_strength=0.1)
        
        assert isinstance(mutated, StrategyDNA)
        is_valid, _ = mutated.validate()
        assert is_valid
    
    def test_mutation_gaussian_adaptive(self, indicator_names):
        """Test adaptive Gaussian mutation."""
        dna = create_random_dna(indicator_names)
        
        mutated = mutation_gaussian(
            dna,
            mutation_rate=0.5,
            mutation_strength=0.1,
            adaptive=True,
            generation=5,
            max_generations=10,
        )
        
        assert isinstance(mutated, StrategyDNA)
        is_valid, _ = mutated.validate()
        assert is_valid
    
    def test_mutation_bit_flip(self, indicator_names):
        """Test bit-flip mutation."""
        dna = create_random_dna(indicator_names)
        
        mutated = mutation_bit_flip(dna, mutation_rate=0.5)
        
        assert isinstance(mutated, StrategyDNA)
        # Boolean switches may have changed
    
    def test_selection_tournament(self, indicator_names):
        """Test tournament selection."""
        population = []
        for _ in range(10):
            dna = create_random_dna(indicator_names)
            population.append((dna, np.random.random()))
        
        selected = selection_tournament(population, tournament_size=3)
        
        assert isinstance(selected, StrategyDNA)
        assert selected in [dna for dna, _ in population]
    
    def test_selection_roulette(self, indicator_names):
        """Test roulette wheel selection."""
        population = []
        for _ in range(10):
            dna = create_random_dna(indicator_names)
            population.append((dna, np.random.random()))
        
        selected = selection_roulette(population)
        
        assert isinstance(selected, StrategyDNA)
        assert selected in [dna for dna, _ in population]
    
    def test_selection_rank(self, indicator_names):
        """Test rank-based selection."""
        population = []
        for _ in range(10):
            dna = create_random_dna(indicator_names)
            population.append((dna, np.random.random()))
        
        selected = selection_rank(population)
        
        assert isinstance(selected, StrategyDNA)
        assert selected in [dna for dna, _ in population]
    
    def test_elitism_selection(self, indicator_names):
        """Test elitism selection."""
        population = []
        for _ in range(10):
            dna = create_random_dna(indicator_names)
            population.append((dna, np.random.random()))
        
        elites = elitism_selection(population, elite_size=2)
        
        assert len(elites) == 2
        assert all(isinstance(e, StrategyDNA) for e in elites)
    
    def test_calculate_diversity(self, indicator_names):
        """Test population diversity calculation."""
        population = []
        for _ in range(10):
            dna = create_random_dna(indicator_names)
            population.append(dna)
        
        diversity = calculate_diversity(population, indicator_names)
        
        assert isinstance(diversity, float)
        assert diversity >= 0


class TestGeneticFitness:
    """Tests for fitness function calculations."""
    
    def test_calculate_fitness(self):
        """Test standard fitness calculation."""
        backtest_result = {
            "sharpe_ratio": 1.5,
            "profit_total": 50.0,
            "max_drawdown_abs": 0.15,
            "profit_factor": 1.5,
            "win_rate": 0.55,
            "total_trades": 100,
        }
        
        result = calculate_fitness(backtest_result)
        
        assert isinstance(result, FitnessResult)
        assert result.fitness >= 0
        assert result.sharpe_ratio == 1.5
        assert result.total_return == 50.0
    
    def test_calculate_fitness_insufficient_trades(self):
        """Test fitness penalty for insufficient trades."""
        backtest_result = {
            "sharpe_ratio": 2.0,
            "profit_total": 50.0,
            "max_drawdown_abs": 0.15,
            "profit_factor": 2.0,
            "win_rate": 0.6,
            "total_trades": 10,  # Below minimum
        }
        
        result = calculate_fitness(backtest_result)
        
        assert "insufficient_trades" in result.penalties
        assert result.penalties["insufficient_trades"] > 0
    
    def test_calculate_fitness_multi_objective(self):
        """Test multi-objective fitness calculation."""
        backtest_result = {
            "sharpe_ratio": 1.5,
            "profit_total": 50.0,
            "max_drawdown_abs": 0.15,
        }
        
        result = calculate_fitness_multi_objective(backtest_result)
        
        assert isinstance(result, dict)
        assert "sharpe_fitness" in result
        assert "return_fitness" in result
        assert "drawdown_fitness" in result
    
    def test_calculate_fitness_sharpe_only(self):
        """Test Sharpe-only fitness calculation."""
        backtest_result = {
            "sharpe_ratio": 2.0,
            "profit_total": 30.0,
            "max_drawdown_abs": 0.2,
            "profit_factor": 1.3,
            "win_rate": 0.5,
            "total_trades": 50,
        }
        
        result = calculate_fitness_sharpe_only(backtest_result)
        
        assert isinstance(result, FitnessResult)
        assert result.fitness >= 0
    
    def test_calculate_fitness_profit_only(self):
        """Test profit-only fitness calculation."""
        backtest_result = {
            "sharpe_ratio": 1.0,
            "profit_total": 80.0,
            "max_drawdown_abs": 0.25,
            "profit_factor": 1.5,
            "win_rate": 0.5,
            "total_trades": 50,
        }
        
        result = calculate_fitness_profit_only(backtest_result)
        
        assert isinstance(result, FitnessResult)
        assert result.fitness >= 0
    
    def test_calculate_fitness_sortino(self):
        """Test Sortino-based fitness calculation."""
        backtest_result = {
            "sharpe_ratio": 1.5,
            "profit_total": 50.0,
            "max_drawdown_abs": 0.15,
            "profit_factor": 2.0,
            "win_rate": 0.55,
            "total_trades": 100,
        }
        
        result = calculate_fitness_sortino(backtest_result)
        
        assert isinstance(result, FitnessResult)
        assert result.fitness >= 0
    
    def test_rank_by_fitness(self, indicator_names):
        """Test ranking by fitness."""
        population = []
        for i in range(10):
            dna = create_random_dna(indicator_names)
            population.append((dna, np.random.random()))
        
        ranked = rank_by_fitness(population, descending=True)
        
        assert len(ranked) == len(population)
        # Check that fitness is in descending order
        fitnesses = [f for _, f in ranked]
        assert fitnesses == sorted(fitnesses, reverse=True)
    
    def test_calculate_population_statistics(self):
        """Test population statistics calculation."""
        fitness_values = [0.1, 0.5, 0.3, 0.8, 0.6]
        
        stats = calculate_population_statistics(fitness_values)
        
        assert isinstance(stats, dict)
        assert "mean" in stats
        assert "std" in stats
        assert "min" in stats
        assert "max" in stats
        assert "median" in stats
        assert stats["max"] == 0.8
        assert stats["min"] == 0.1


class TestGeneticEvolution:
    """Tests for genetic algorithm evolution orchestration."""
    
    def test_ga_config(self):
        """Test GA configuration."""
        config = GAConfig()
        
        assert config.population_size == 50
        assert config.generations == 20
        assert config.elite_size == 2
        assert config.tournament_size == 3
    
    def test_genetic_evolution_init(self, indicator_names):
        """Test GeneticEvolution initialization."""
        config = GAConfig(population_size=10, generations=5)
        evolution = GeneticEvolution(config, indicator_names)
        
        assert evolution.config.population_size == 10
        assert evolution.config.generations == 5
        assert evolution.indicator_names == indicator_names
    
    @pytest.mark.asyncio
    async def test_genetic_evolution_run(self, indicator_names):
        """Test running genetic algorithm evolution."""
        config = GAConfig(population_size=5, generations=3)
        evolution = GeneticEvolution(config, indicator_names)
        
        # Mock backtest function
        async def mock_backtest(dna):
            return {
                "sharpe_ratio": np.random.uniform(0.5, 2.0),
                "profit_total": np.random.uniform(-10, 50),
                "max_drawdown_abs": np.random.uniform(0.1, 0.3),
                "profit_factor": np.random.uniform(1.0, 2.0),
                "win_rate": np.random.uniform(0.4, 0.6),
                "total_trades": np.random.randint(20, 100),
            }
        
        result = await evolution.run_evolution(mock_backtest)
        
        assert isinstance(result, GAResult)
        assert isinstance(result.best_dna, StrategyDNA)
        assert result.best_fitness >= 0
        assert len(result.generation_history) > 0
        assert result.total_evaluations > 0
    
    @pytest.mark.asyncio
    async def test_run_genetic_evolution_convenience(self, indicator_names):
        """Test convenience function for running GA."""
        config = GAConfig(population_size=5, generations=3)
        
        async def mock_backtest(dna):
            return {
                "sharpe_ratio": 1.5,
                "profit_total": 30.0,
                "max_drawdown_abs": 0.2,
                "profit_factor": 1.5,
                "win_rate": 0.5,
                "total_trades": 50,
            }
        
        result = await run_genetic_evolution(
            backtest_func=mock_backtest,
            config=config,
            indicator_names=indicator_names,
        )
        
        assert isinstance(result, GAResult)
        assert result.best_dna is not None


class TestGeneticIntegration:
    """Integration tests for genetic algorithm workflow."""
    
    @pytest.mark.asyncio
    async def test_full_ga_workflow(self, indicator_names):
        """Test complete genetic algorithm workflow."""
        config = GAConfig(population_size=5, generations=3)
        
        # Create initial population
        initial_population = [create_random_dna(indicator_names) for _ in range(5)]
        
        # Mock backtest function
        async def mock_backtest(dna):
            return {
                "sharpe_ratio": np.random.uniform(0.5, 2.0),
                "profit_total": np.random.uniform(-10, 50),
                "max_drawdown_abs": np.random.uniform(0.1, 0.3),
                "profit_factor": np.random.uniform(1.0, 2.0),
                "win_rate": np.random.uniform(0.4, 0.6),
                "total_trades": np.random.randint(20, 100),
            }
        
        # Run evolution
        result = await run_genetic_evolution(
            backtest_func=mock_backtest,
            config=config,
            indicator_names=indicator_names,
            initial_population=initial_population,
        )
        
        # Verify results
        assert result.best_fitness >= 0
        assert len(result.generation_history) == 3
        assert result.total_evaluations > 0
        
        # Check that fitness improved over generations
        first_gen_fitness = result.generation_history[0]["best_fitness"]
        last_gen_fitness = result.generation_history[-1]["best_fitness"]
        # Fitness should not decrease significantly
        assert last_gen_fitness >= first_gen_fitness - 0.1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
