"""Tests for repair_plan_gate.py."""

from backend.models.strategy_spec import StrategySpec
from backend.services.execution.failure_analyzer import FailureClassification
from backend.services.execution.repair_plan_gate import build_repair_plan


def _make_classification(
    primary_class: str | None = None,
    next_route: str = "none_needed",
) -> FailureClassification:
    return FailureClassification(
        primary_class=primary_class,
        next_route=next_route,
        failed_metrics=[],
        metric_values={},
    )


def _make_spec(
    iteration_count: int = 0,
    max_iterations: int = 3,
) -> StrategySpec:
    return StrategySpec(
        name="TestStrategy",
        trading_style="trend_following",
        iteration_count=iteration_count,
        max_iterations=max_iterations,
    )


class TestDataQualityNoRepair:
    def test_data_quality_no_repair(self):
        plan = build_repair_plan(
            _make_classification("data_quality_failed", "check_data"),
        )
        assert plan.scope == "no_repair_possible"
        assert plan.can_repair is False


class TestBacktestFailedNoRepair:
    def test_backtest_failed_no_repair(self):
        plan = build_repair_plan(
            _make_classification("backtest_failed", "inspect_logs"),
        )
        assert plan.scope == "no_repair_possible"
        assert plan.can_repair is False


class TestNoTradesFirstAttempt:
    def test_no_trades_first_attempt_allowed(self):
        plan = build_repair_plan(
            _make_classification("no_trades", "discard_strategy"),
            spec=_make_spec(iteration_count=0),
        )
        assert plan.scope == "entry_logic"
        assert plan.can_repair is True


class TestNoTradesFinalRejectAfterOne:
    def test_no_trades_final_reject_after_one(self):
        plan = build_repair_plan(
            _make_classification("no_trades", "discard_strategy"),
            spec=_make_spec(iteration_count=1),
        )
        assert plan.scope == "final_reject"
        assert plan.can_repair is False


class TestTooFewTradesEntryParameter:
    def test_too_few_trades_entry_parameter(self):
        plan = build_repair_plan(
            _make_classification("too_few_trades", "extend_timerange_or_discard"),
            spec=_make_spec(iteration_count=0),
        )
        assert plan.scope == "entry_parameter"
        assert plan.can_repair is True


class TestNegativeExpectancyStoploss:
    def test_negative_expectancy_stoploss(self):
        plan = build_repair_plan(
            _make_classification("negative_expectancy", "adjust_stoploss_or_roi"),
            spec=_make_spec(iteration_count=0),
        )
        assert plan.scope == "stoploss"
        assert plan.can_repair is True


class TestHighDrawdownStoploss:
    def test_high_drawdown_stoploss(self):
        plan = build_repair_plan(
            _make_classification("high_drawdown", "tighten_stoploss_or_position_sizing"),
            spec=_make_spec(iteration_count=0),
        )
        assert plan.scope == "stoploss"
        assert plan.can_repair is True


class TestWeakProfitFactorExit:
    def test_weak_profit_factor_exit(self):
        plan = build_repair_plan(
            _make_classification("weak_profit_factor", "adjust_exit_conditions"),
            spec=_make_spec(iteration_count=0),
        )
        assert plan.scope == "exit_logic"
        assert plan.can_repair is True


class TestWeakSharpeEntryParameter:
    def test_weak_sharpe_entry_parameter(self):
        plan = build_repair_plan(
            _make_classification("weak_sharpe", "review_entry_consistency"),
            spec=_make_spec(iteration_count=0),
        )
        assert plan.scope == "entry_parameter"
        assert plan.can_repair is True


class TestWeakWinRateEntryLogic:
    def test_weak_win_rate_entry_logic(self):
        plan = build_repair_plan(
            _make_classification("weak_win_rate", "review_entry_logic"),
            spec=_make_spec(iteration_count=0),
        )
        assert plan.scope == "entry_logic"
        assert plan.can_repair is True


class TestMultipleMetricNoRepair:
    def test_multiple_metric_no_repair(self):
        plan = build_repair_plan(
            _make_classification("multiple_metric_failure", "fundamental_rework"),
        )
        assert plan.scope == "no_repair_possible"
        assert plan.can_repair is False


class TestMaxIterationsReached:
    def test_max_iterations_reached(self):
        spec = _make_spec(iteration_count=3, max_iterations=3)
        plan = build_repair_plan(
            _make_classification("weak_win_rate", "review_entry_logic"),
            spec=spec,
        )
        assert plan.scope == "final_reject"
        assert plan.can_repair is False


class TestIterationsRemaining:
    def test_iterations_remaining_correct(self):
        spec = _make_spec(iteration_count=1, max_iterations=3)
        plan = build_repair_plan(
            _make_classification("weak_sharpe", "review_entry_consistency"),
            spec=spec,
        )
        assert plan.max_iterations == 3
        assert plan.iteration_used == 1
        assert plan.iterations_remaining == 2
        assert plan.can_repair is True


class TestNoSpecUsesDefaults:
    def test_no_spec_uses_defaults(self):
        plan = build_repair_plan(
            _make_classification("no_trades", "discard_strategy"),
        )
        assert plan.max_iterations == 3
        assert plan.iteration_used == 0
        assert plan.iterations_remaining == 3
        assert plan.scope == "entry_logic"
        assert plan.can_repair is True


class TestPassedGateNoFailure:
    def test_passed_gate_no_failure(self):
        plan = build_repair_plan(
            _make_classification(primary_class=None, next_route="none_needed"),
            spec=_make_spec(iteration_count=0),
        )
        assert plan.failure_class is None
        assert plan.scope == "no_repair_possible"
        assert plan.can_repair is False
