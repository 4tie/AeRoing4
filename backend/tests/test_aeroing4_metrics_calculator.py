"""Unit tests for the AeRoing4 Metrics SSOT calculator (Prompt 2)."""

from backend.services.aeroing4.metrics.calculator import (
    PROFIT_FACTOR_NO_LOSS_SENTINEL,
    compute_average_trade_duration_minutes,
    compute_bootstrap_sharpe_p5,
    compute_calmar,
    compute_expectancy_abs,
    compute_max_drawdown_abs,
    compute_max_drawdown_pct,
    compute_profit_factor,
    compute_sharpe,
    compute_sortino,
    compute_trade_counts,
    compute_win_rate,
)
from backend.services.aeroing4.metrics.models import MetricAvailability


class TestProfitFactor:
    def test_normal_case(self):
        mv = compute_profit_factor([10.0, -5.0, 20.0])
        assert mv.availability == MetricAvailability.AVAILABLE
        assert mv.value == 6.0

    def test_no_losing_trades(self):
        mv = compute_profit_factor([10.0, 20.0])
        assert mv.availability == MetricAvailability.AVAILABLE
        assert mv.value == PROFIT_FACTOR_NO_LOSS_SENTINEL

    def test_no_winning_trades(self):
        mv = compute_profit_factor([-10.0, -20.0])
        assert mv.availability == MetricAvailability.AVAILABLE
        assert mv.value == 0.0

    def test_zero_trades(self):
        mv = compute_profit_factor([])
        assert mv.availability == MetricAvailability.UNAVAILABLE
        assert mv.value is None

    def test_all_zero_profit_trades(self):
        mv = compute_profit_factor([0.0, 0.0])
        assert mv.availability == MetricAvailability.UNAVAILABLE


class TestExpectancy:
    def test_positive_expectancy(self):
        mv = compute_expectancy_abs([10.0, -5.0, 20.0])
        assert mv.availability == MetricAvailability.AVAILABLE
        assert mv.value == round(25.0 / 3, 6)

    def test_negative_expectancy(self):
        mv = compute_expectancy_abs([-10.0, -5.0, 2.0])
        assert mv.availability == MetricAvailability.AVAILABLE
        assert mv.value < 0

    def test_zero_trades(self):
        mv = compute_expectancy_abs([])
        assert mv.availability == MetricAvailability.UNAVAILABLE

    def test_equivalent_to_win_loss_decomposition_formula(self):
        """Matches ResultParser._derive_expectancy's win_rate*avg_win -
        loss_rate*avg_loss formula exactly (algebraic identity)."""
        profits = [10.0, -3.0, 7.0, -2.0, 0.0]
        wins = [p for p in profits if p > 0]
        losses = [abs(p) for p in profits if p <= 0]
        n = len(profits)
        win_rate = len(wins) / n
        loss_rate = len(losses) / n
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        legacy = win_rate * avg_win - loss_rate * avg_loss
        canonical = compute_expectancy_abs(profits)
        assert canonical.value == round(legacy, 6)


class TestWinRate:
    def test_normal(self):
        mv = compute_win_rate([10.0, -5.0, 20.0, -1.0])
        assert mv.value == 50.0

    def test_zero_trades(self):
        assert compute_win_rate([]).availability == MetricAvailability.UNAVAILABLE


class TestTradeCounts:
    def test_counts(self):
        total, wins, losses = compute_trade_counts([10.0, -5.0, 0.0, 20.0])
        assert total.value == 4
        assert wins.value == 2
        assert losses.value == 1

    def test_none_input(self):
        total, wins, losses = compute_trade_counts(None)
        assert total.availability == MetricAvailability.UNAVAILABLE
        assert wins.availability == MetricAvailability.UNAVAILABLE
        assert losses.availability == MetricAvailability.UNAVAILABLE

    def test_zero_trades_list(self):
        total, wins, losses = compute_trade_counts([])
        assert total.value == 0
        assert wins.availability == MetricAvailability.UNAVAILABLE
        assert losses.availability == MetricAvailability.UNAVAILABLE


class TestDrawdown:
    def test_max_drawdown_abs(self):
        mv = compute_max_drawdown_abs([1000.0, 1200.0, 900.0, 1100.0])
        assert mv.availability == MetricAvailability.AVAILABLE
        assert mv.value == 300.0

    def test_max_drawdown_pct(self):
        mv = compute_max_drawdown_pct([1000.0, 1200.0, 900.0, 1100.0])
        assert mv.availability == MetricAvailability.AVAILABLE
        assert round(mv.value, 2) == round(300 / 1200 * 100, 2)

    def test_insufficient_points(self):
        assert compute_max_drawdown_abs([1000.0]).availability == MetricAvailability.UNAVAILABLE
        assert compute_max_drawdown_pct([]).availability == MetricAvailability.UNAVAILABLE


class TestAverageTradeDuration:
    def test_normal(self):
        mv = compute_average_trade_duration_minutes([10.0, 20.0, 30.0])
        assert mv.value == 20.0

    def test_empty(self):
        assert compute_average_trade_duration_minutes([]).availability == MetricAvailability.UNAVAILABLE

    def test_filters_none(self):
        mv = compute_average_trade_duration_minutes([10.0, None, 30.0])
        assert mv.value == 20.0


class TestSharpe:
    def test_normal(self):
        mv = compute_sharpe([0.01, 0.02, -0.01, 0.03, -0.02])
        assert mv.availability == MetricAvailability.AVAILABLE

    def test_insufficient_sample(self):
        assert compute_sharpe([0.01]).availability == MetricAvailability.INSUFFICIENT_DATA
        assert compute_sharpe([]).availability == MetricAvailability.INSUFFICIENT_DATA

    def test_zero_volatility_edge_case(self):
        mv = compute_sharpe([0.01, 0.01, 0.01])
        assert mv.availability == MetricAvailability.NOT_APPLICABLE
        assert mv.value is None


class TestSortino:
    def test_normal(self):
        mv = compute_sortino([0.01, -0.02, 0.03, -0.01])
        assert mv.availability == MetricAvailability.AVAILABLE

    def test_no_downside_returns(self):
        mv = compute_sortino([0.01, 0.02, 0.03])
        assert mv.availability == MetricAvailability.NOT_APPLICABLE

    def test_insufficient_sample(self):
        assert compute_sortino([0.01]).availability == MetricAvailability.INSUFFICIENT_DATA


class TestCalmar:
    def test_normal(self):
        mv = compute_calmar(25.0, 10.0)
        assert mv.availability == MetricAvailability.AVAILABLE
        assert mv.value == 2.5

    def test_zero_drawdown_edge_case(self):
        mv = compute_calmar(25.0, 0.0)
        assert mv.availability == MetricAvailability.NOT_APPLICABLE

    def test_missing_inputs(self):
        assert compute_calmar(None, 10.0).availability == MetricAvailability.UNAVAILABLE
        assert compute_calmar(25.0, None).availability == MetricAvailability.UNAVAILABLE


class TestBootstrapSharpeP5:
    def test_deterministic_same_seed(self):
        returns = [0.01, -0.02, 0.03, -0.01, 0.02, 0.015, -0.005]
        mv1 = compute_bootstrap_sharpe_p5(returns, seed=42)
        mv2 = compute_bootstrap_sharpe_p5(returns, seed=42)
        assert mv1.value == mv2.value
        assert mv1.availability == MetricAvailability.AVAILABLE

    def test_different_seed_may_differ_but_is_valid(self):
        returns = [0.01, -0.02, 0.03, -0.01, 0.02, 0.015, -0.005]
        mv1 = compute_bootstrap_sharpe_p5(returns, seed=1)
        mv2 = compute_bootstrap_sharpe_p5(returns, seed=2)
        assert mv1.availability == MetricAvailability.AVAILABLE
        assert mv2.availability == MetricAvailability.AVAILABLE
        # Not asserting inequality (could coincide) — only that both are valid.

    def test_insufficient_data(self):
        mv = compute_bootstrap_sharpe_p5([0.01, 0.02])
        assert mv.availability == MetricAvailability.INSUFFICIENT_DATA
