"""Focused regression tests for optimizer scoring, params, and session status."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.api.routers import optimizer as optimizer_router
from backend.api.session_store import SessionStore
from backend.models import (
    OptimizerScoreMetric,
    OptimizerParameterMode,
    OptimizerSession,
    OptimizerSessionConfig,
    OptimizerSessionPhase,
    OptimizerTrial,
    OptimizerTrialMetrics,
    OptimizerTrialStatus,
    ParameterSearchSpace,
    ParameterSearchType,
    ParamsSchema,
    SearchStrategy,
)
from backend.services.strategy.optimizer_auto_safe import (
    apply_auto_safe_initial_spaces,
    build_auto_safe_narrowing_event,
)
from backend.services.strategy.optimizer_trial import OptimizerTrialExecutor
from backend.services.strategy.strategy_optimizer import StrategyOptimizerService
from backend.services.strategy.strategy_optimizer_search import select_parameters_for_trial
from backend.services.strategy.strategy_source import StrategySourceParser
from backend.services.strategy.version_manager import VersionManager


def _summary(**overrides):
    base = {
        "net_profit_pct": 12.0,
        "net_profit_currency": 120.0,
        "sharpe_ratio": 1.5,
        "profit_factor": 2.0,
        "win_rate_pct": 62.5,
        "max_drawdown_pct": -8.0,
        "total_trades": 42,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_compute_score_implements_all_exposed_metrics():
    executor = OptimizerTrialExecutor(None, None, None)
    summary = _summary()

    assert executor.compute_score(summary, OptimizerScoreMetric.TOTAL_PROFIT_PCT) == 12.0
    assert executor.compute_score(summary, OptimizerScoreMetric.NET_PROFIT_ABS) == 120.0
    assert executor.compute_score(summary, OptimizerScoreMetric.SHARPE_RATIO) == 1.5
    assert executor.compute_score(summary, OptimizerScoreMetric.PROFIT_FACTOR) == 2.0
    assert executor.compute_score(summary, OptimizerScoreMetric.WIN_RATE) == 62.5
    assert executor.compute_score(summary, OptimizerScoreMetric.MAX_DRAWDOWN_PCT) == -8.0
    assert executor.compute_score(summary, OptimizerScoreMetric.TOTAL_TRADES) == 42.0


def test_composite_penalizes_absolute_drawdown_for_either_sign():
    executor = OptimizerTrialExecutor(None, None, None)

    negative_dd = executor.compute_score(_summary(max_drawdown_pct=-8.0), OptimizerScoreMetric.COMPOSITE)
    positive_dd = executor.compute_score(_summary(max_drawdown_pct=8.0), OptimizerScoreMetric.COMPOSITE)

    assert negative_dd == pytest.approx(positive_dd)
    assert negative_dd == pytest.approx((12.0 * 0.35) + (1.5 * 0.25) + (2.0 * 0.20) - (8.0 * 0.20))


def test_missing_selected_metric_returns_none():
    executor = OptimizerTrialExecutor(None, None, None)

    assert executor.compute_score(_summary(sharpe_ratio=None), OptimizerScoreMetric.SHARPE_RATIO) is None
    assert executor.compute_score(_summary(max_drawdown_pct=None), OptimizerScoreMetric.MAX_DRAWDOWN_PCT) is None


def test_merge_trial_parameters_preserves_unselected_values():
    parent = ParamsSchema(
        strategy_name="Demo",
        version_id="v001",
        extracted_at=datetime.now(tz=UTC),
        pair_list=["BTC/USDT"],
        buy_params={"buy_window": 10, "locked_buy": 1},
        sell_params={"sell_window": 20},
        protection_params={"cooldown": 5},
        roi_table={"0": 0.1, "60": 0.02},
        stoploss=-0.1,
        trailing_stop=True,
        trailing_stop_positive=0.02,
        trailing_stop_positive_offset=0.03,
        trailing_only_offset_is_reached=True,
        custom_params={"custom_flag": "keep"},
    )

    manager = VersionManager.__new__(VersionManager)
    merged = manager.merge_trial_parameters(
        parent,
        {
            "buy_window": 14,
            "roi__60": 0.03,
            "trailing__stop": False,
        },
    )

    assert merged.buy_params == {"buy_window": 14, "locked_buy": 1}
    assert merged.sell_params == parent.sell_params
    assert merged.protection_params == parent.protection_params
    assert merged.custom_params == parent.custom_params
    assert merged.roi_table == {"0": 0.1, "60": 0.03}
    assert merged.trailing_stop is False
    assert merged.trailing_stop_positive is None
    assert merged.trailing_stop_positive_offset is None


def test_monitor_maps_cancelled_optimizer_session_to_cancelled_api_status(monkeypatch):
    async def fast_sleep(_seconds):
        return None

    monkeypatch.setattr(optimizer_router.asyncio, "sleep", fast_sleep)

    session = OptimizerSession(
        session_id="opt-1",
        strategy_name="Demo",
        config=OptimizerSessionConfig(
            strategy_name="Demo",
            timeframe="1h",
            timerange="20240101-20240131",
            pairs=["BTC/USDT"],
            config_file="config.json",
        ),
        phase=OptimizerSessionPhase.CANCELLED,
        created_at=datetime.now(tz=UTC),
        total_trials=10,
        completed_trials=2,
        failed_trials=1,
        stop_reason="Cancelled by user",
    )
    services = SimpleNamespace(
        optimizer_store=SimpleNamespace(load_session=lambda _session_id: session)
    )
    store = SessionStore()
    api_record = store.create("optimizer")

    asyncio.run(optimizer_router._monitor_optimizer(services, store, api_record.session_id, session.session_id))

    record = store.get(api_record.session_id)
    assert record.status == "cancelled"
    assert record.result["phase"] == "cancelled"


def test_parser_extracts_real_parameter_bounds_choices_and_sidecar_defaults(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("optimizer_parser")
    strategies_dir = tmp_path / "strategies"
    versions_dir = tmp_path / "versions"
    strategies_dir.mkdir()
    versions_dir.mkdir()
    strategy_path = strategies_dir / "DemoStrategy.py"
    strategy_path.write_text(
        """
class DemoStrategy:
    buy_window = IntParameter(5, 20, default=10, space="buy")
    mode = CategoricalParameter(["fast", "slow"], default="slow", space="buy")
    gain = RealParameter(0.1, 0.9, default=0.3, space="sell")
    fixed_window = IntParameter(2, 8, default=4, space="buy", optimize=False)

    def populate_indicators(self): pass
    def populate_entry_trend(self): pass
    def populate_exit_trend(self): pass
""",
        encoding="utf-8",
    )
    strategy_path.with_suffix(".json").write_text(
        """
{
  "strategy_name": "DemoStrategy",
  "params": {
    "buy": {"buy_window": 14, "mode": "fast"},
    "sell": {"gain": 0.7}
  }
}
""",
        encoding="utf-8",
    )

    parsed = StrategySourceParser(strategies_dir, versions_dir).parse(strategy_path)

    buy_window = parsed.declared_parameters["buy_window"]
    mode = parsed.declared_parameters["mode"]
    gain = parsed.declared_parameters["gain"]
    fixed_window = parsed.declared_parameters["fixed_window"]

    assert buy_window.min_value == 5
    assert buy_window.max_value == 20
    assert buy_window.default == 14
    assert mode.choices == ["fast", "slow"]
    assert mode.default == "fast"
    assert gain.parameter_type == "RealParameter"
    assert gain.min_value == 0.1
    assert gain.max_value == 0.9
    assert gain.default == 0.7
    assert fixed_window.optimizable is False


def _space(name: str, space: str, enabled: bool = True, optimizable: bool = True):
    return ParameterSearchSpace(
        name=name,
        param_type=ParameterSearchType.INT,
        space=space,
        default=1,
        enabled=enabled,
        optimizable=optimizable,
        min_value=1,
        max_value=10,
        step=1,
    )


def _optimizer_session(
    spaces,
    trials=None,
    search_strategy=SearchStrategy.RANDOM,
    grid_epoch=1,
    grid_epoch_start_trial=1,
):
    return OptimizerSession(
        session_id="opt-1",
        strategy_name="Demo",
        config=OptimizerSessionConfig(
            strategy_name="Demo",
            timeframe="1h",
            timerange="20240101-20240131",
            pairs=["BTC/USDT"],
            config_file="config.json",
            search_strategy=search_strategy,
            parameter_mode=OptimizerParameterMode.AUTO_SAFE,
            search_spaces=list(spaces),
        ),
        phase=OptimizerSessionPhase.RUNNING,
        created_at=datetime.now(tz=UTC),
        total_trials=10,
        trials=list(trials or []),
        grid_epoch=grid_epoch,
        grid_epoch_start_trial=grid_epoch_start_trial,
    )


def test_auto_safe_initial_selection_locks_non_core_and_caps_at_six():
    spaces = [
        _space("buy_a", "buy"),
        _space("buy_b", "buy"),
        _space("buy_fixed", "buy", optimizable=False),
        _space("sell_a", "sell"),
        _space("sell_b", "sell"),
        _space("sell_c", "sell"),
        _space("sell_d", "sell"),
        _space("sell_e", "sell"),
        _space("roi__0", "roi"),
        _space("stoploss__value", "stoploss"),
    ]

    updated = apply_auto_safe_initial_spaces(spaces)
    enabled_names = [space.name for space in updated if space.enabled]

    assert enabled_names == ["buy_a", "buy_b", "sell_a", "sell_b", "sell_c", "sell_d"]
    assert "buy_fixed" not in enabled_names
    assert "roi__0" not in enabled_names
    assert "stoploss__value" not in enabled_names


def test_auto_safe_runtime_narrows_after_zero_trade_trials():
    spaces = [
        _space("buy_a", "buy"),
        _space("buy_b", "buy"),
        _space("buy_c", "buy"),
        _space("sell_a", "sell"),
        _space("sell_b", "sell"),
        _space("sell_c", "sell"),
    ]
    trials = [
        OptimizerTrial(
            trial_number=i,
            status=OptimizerTrialStatus.COMPLETED,
            parameters={},
            metrics=OptimizerTrialMetrics(total_trades=0),
        )
        for i in range(1, 4)
    ]
    session = _optimizer_session(spaces, trials)

    updated, event = build_auto_safe_narrowing_event(session, next_trial_number=4)

    assert event is not None
    assert event.reason == "zero_trade_trials"
    assert event.before_enabled_count == 6
    assert event.after_enabled_count == 4
    assert event.locked_params == ["sell_b", "sell_c"]
    assert [space.name for space in updated if space.enabled] == [
        "buy_a",
        "buy_b",
        "buy_c",
        "sell_a",
    ]


def test_auto_safe_grid_narrowing_records_epoch_reset():
    spaces = [
        _space("buy_a", "buy"),
        _space("buy_b", "buy"),
        _space("buy_c", "buy"),
        _space("sell_a", "sell"),
        _space("sell_b", "sell"),
    ]
    trials = [
        OptimizerTrial(
            trial_number=i,
            status=OptimizerTrialStatus.FAILED,
            parameters={},
        )
        for i in range(1, 4)
    ]
    session = _optimizer_session(
        spaces,
        trials,
        search_strategy=SearchStrategy.GRID,
        grid_epoch=2,
        grid_epoch_start_trial=1,
    )

    _updated, event = build_auto_safe_narrowing_event(session, next_trial_number=4)

    assert event is not None
    assert event.reason == "repeated_failures"
    assert event.grid_epoch_before == 2
    assert event.grid_epoch_after == 3
    assert event.grid_epoch_start_trial == 4


def test_grid_search_uses_epoch_local_trial_index():
    spaces = [
        ParameterSearchSpace(
            name="buy_window",
            param_type=ParameterSearchType.INT,
            space="buy",
            default=1,
            enabled=True,
            min_value=1,
            max_value=10,
            step=1,
        )
    ]
    session = _optimizer_session(
        spaces,
        search_strategy=SearchStrategy.GRID,
        grid_epoch=2,
        grid_epoch_start_trial=5,
    )

    assert select_parameters_for_trial(session, spaces, trial_number=5) == {"buy_window": 1}
    assert select_parameters_for_trial(session, spaces, trial_number=6) == {"buy_window": 2}


def test_optimizer_selects_screened_candidates_before_search_fallback():
    spaces = [_space("buy_a", "buy")]
    session = _optimizer_session(spaces, search_strategy=SearchStrategy.GRID)
    service = StrategyOptimizerService.__new__(StrategyOptimizerService)
    screened_candidates = [{"locked_param": 99}, {"buy_a": 7, "locked_param": 99}]

    selected = service._select_parameters_for_trial(
        session,
        spaces,
        trial_number=1,
        screened_candidates=screened_candidates,
    )

    assert selected == {"buy_a": 7}
    assert screened_candidates == []
