"""Unit tests for VectorBT optimizer pre-screening."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.models import (
    OptimizerScoreMetric,
    OptimizerSession,
    OptimizerSessionConfig,
    OptimizerSessionPhase,
    OptimizerTrial,
    OptimizerTrialMetrics,
    OptimizerTrialStatus,
    ParameterSearchSpace,
    ParameterSearchType,
    SearchStrategy,
)
from backend.services.vectorbt.parameter_screener import VectorBTParameterScreener


class FakeTrades:
    def __init__(self, entries):
        self.entries = entries

    def count(self):
        return self.entries.astype(int).sum()

    def win_rate(self):
        return 0.5

    def profit_factor(self):
        return 1.5


class FakePortfolio:
    def __init__(self, close, entries, exits, **kwargs):
        self.close = close
        self.entries = entries
        self.exits = exits
        self.kwargs = kwargs
        self.trades = FakeTrades(entries)

    def total_return(self):
        return float(self.entries.astype(int).sum().sum()) / 100.0

    def total_profit(self):
        return float(self.entries.astype(int).sum().sum())

    def max_drawdown(self):
        return 0.02

    def sharpe_ratio(self):
        return self.total_return() * 10.0


class FakePortfolioFactory:
    @staticmethod
    def from_signals(close, entries, exits, **kwargs):
        return FakePortfolio(close, entries, exits, **kwargs)


class NonFiniteTrades:
    def count(self):
        return 0

    def win_rate(self):
        return float("nan")

    def profit_factor(self):
        return float("inf")


class NonFinitePortfolio:
    trades = NonFiniteTrades()

    def total_return(self):
        return float("nan")

    def total_profit(self):
        return 0.0

    def max_drawdown(self):
        return 0.0

    def sharpe_ratio(self):
        return float("inf")


class Parameter:
    def __init__(self, value):
        self.value = value


def _fake_vectorbt():
    return SimpleNamespace(Portfolio=FakePortfolioFactory)


def _space(name: str = "threshold", *, min_value: int = 1, max_value: int = 3):
    return ParameterSearchSpace(
        name=name,
        param_type=ParameterSearchType.INT,
        space="buy",
        default=min_value,
        enabled=True,
        optimizable=True,
        min_value=min_value,
        max_value=max_value,
        step=1,
    )


def _session(tmp_path, *, trials=None, **config_overrides):
    config_values = {
        "strategy_name": "DemoStrategy",
        "timeframe": "1h",
        "timerange": "20240101-20240105",
        "pairs": ["BTC/USDT"],
        "config_file": "config.json",
        "total_trials": 1,
        "search_strategy": SearchStrategy.GRID,
        "score_metric": OptimizerScoreMetric.TOTAL_TRADES,
        "vectorbt_candidate_count": 3,
        "vectorbt_keep_ratio": 0.34,
        "vectorbt_timeout_seconds": 120,
        "search_spaces": [_space()],
    }
    config_values.update(config_overrides)
    config = OptimizerSessionConfig(**config_values)
    return OptimizerSession(
        session_id="opt-1",
        strategy_name="DemoStrategy",
        config=config,
        phase=OptimizerSessionPhase.RUNNING,
        created_at=datetime.now(tz=UTC),
        total_trials=config.total_trials,
        trials=list(trials or []),
    )


def _write_strategy(tmp_path):
    strategy_path = tmp_path / "DemoStrategy.py"
    strategy_path.write_text(
        """
class Parameter:
    def __init__(self, value):
        self.value = value


class DemoStrategy:
    threshold = Parameter(1)

    def populate_indicators(self, dataframe, metadata):
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe["enter_long"] = dataframe["close"] > self.threshold.value
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe["exit_long"] = False
        return dataframe
""",
        encoding="utf-8",
    )
    return strategy_path


def _write_candles(tmp_path):
    data_dir = tmp_path / "data" / "binance"
    data_dir.mkdir(parents=True)
    candles = [
        [1704067200000, 1, 1, 1, 1, 100],
        [1704070800000, 2, 2, 2, 2, 100],
        [1704074400000, 3, 3, 3, 3, 100],
        [1704078000000, 4, 4, 4, 4, 100],
        [1704081600000, 5, 5, 5, 5, 100],
    ]
    (data_dir / "BTC_USDT-1h.json").write_text(json.dumps(candles), encoding="utf-8")


def _screener(tmp_path, *, vectorbt_module=None):
    strategy_path = _write_strategy(tmp_path)
    return VectorBTParameterScreener(
        settings_store=SimpleNamespace(
            load=lambda: SimpleNamespace(user_data_directory_path=str(tmp_path))
        ),
        registry=SimpleNamespace(
            get_strategy=lambda _name: SimpleNamespace(file_path=str(strategy_path))
        ),
        vectorbt_module=vectorbt_module,
    )


def test_screener_ranks_and_filters_candidates_by_score(tmp_path):
    _write_candles(tmp_path)
    screener = _screener(tmp_path, vectorbt_module=_fake_vectorbt())
    session = _session(tmp_path)

    outcome = screener.screen_parameter_spaces_sync(session, [_space()])

    assert outcome.report.status == "completed"
    assert outcome.report.evaluated_count == 3
    assert outcome.report.selected_count == 2
    assert outcome.report.reduction_pct == pytest.approx(33.333)
    assert outcome.report.top_candidates[0].parameters == {"threshold": 1}
    assert outcome.report.top_candidates[0].metrics.total_trades == 4
    assert outcome.selected_parameters == [{"threshold": 1}, {"threshold": 2}]


def test_missing_vectorbt_import_skips_without_error(tmp_path, monkeypatch):
    screener = _screener(tmp_path)
    session = _session(tmp_path)

    def raise_import_error():
        raise ImportError("No module named vectorbt")

    monkeypatch.setattr(screener, "_load_vectorbt", raise_import_error)

    outcome = screener.screen_parameter_spaces_sync(session, [_space()])

    assert outcome.report.status == "skipped"
    assert outcome.report.skipped_reason == "vectorbt_unavailable"
    assert outcome.selected_parameters == []


def test_missing_candle_data_skips_screening(tmp_path):
    screener = _screener(tmp_path, vectorbt_module=_fake_vectorbt())
    session = _session(tmp_path)

    outcome = screener.screen_parameter_spaces_sync(session, [_space()])

    assert outcome.report.status == "skipped"
    assert outcome.report.skipped_reason == "missing_data"
    assert outcome.selected_parameters == []


def test_strategy_parameter_value_injection_updates_generic_parameters(tmp_path):
    screener = _screener(tmp_path, vectorbt_module=_fake_vectorbt())
    strategy = SimpleNamespace(
        threshold=Parameter(1),
        buy_params={"threshold": 1},
        minimal_roi={"0": 0.1},
        stoploss=-0.1,
    )

    screener._apply_parameters(
        strategy,
        {
            "threshold": 7,
            "roi__60": 0.03,
            "stoploss__value": -0.2,
            "trailing__stop": True,
            "trailing__positive": 0.02,
            "trailing__offset": 0.03,
        },
    )

    assert strategy.threshold.value == 7
    assert strategy.buy_params["threshold"] == 7
    assert strategy.minimal_roi["60"] == 0.03
    assert strategy.stoploss == -0.2
    assert strategy.trailing_stop is True
    assert strategy.trailing_stop_positive == 0.02
    assert strategy.trailing_stop_positive_offset == 0.03


def test_candidate_generation_removes_duplicates_and_existing_trials(tmp_path):
    screener = _screener(tmp_path, vectorbt_module=_fake_vectorbt())
    spaces = [_space(max_value=2)]
    existing = OptimizerTrial(
        trial_number=1,
        status=OptimizerTrialStatus.COMPLETED,
        parameters={"threshold": 1},
        metrics=OptimizerTrialMetrics(score=1.0),
    )
    session = _session(
        tmp_path,
        trials=[existing],
        search_spaces=spaces,
        vectorbt_candidate_count=5,
    )

    candidates = screener._generate_candidates(session, spaces)

    assert candidates == [{"threshold": 2}]


def test_timeout_returns_partial_screening_without_blocking_trials(tmp_path, monkeypatch):
    _write_candles(tmp_path)
    screener = _screener(tmp_path, vectorbt_module=_fake_vectorbt())
    session = _session(tmp_path, vectorbt_timeout_seconds=1)
    monotonic_values = iter([0.0, 0.0, 2.0, 2.2])

    monkeypatch.setattr(
        "backend.services.vectorbt.parameter_screener.time.monotonic",
        lambda: next(monotonic_values),
    )
    monkeypatch.setattr(
        screener,
        "_evaluate_candidate",
        lambda **_kwargs: OptimizerTrialMetrics(total_trades=1, score=1.0),
    )

    outcome = screener.screen_parameter_spaces_sync(session, [_space()])

    assert outcome.report.status == "partial"
    assert outcome.report.skipped_reason == "timeout"
    assert outcome.report.evaluated_count == 1
    assert outcome.selected_parameters == [{"threshold": 1}]


def test_non_finite_portfolio_metrics_are_normalized_for_json(tmp_path):
    screener = _screener(tmp_path, vectorbt_module=_fake_vectorbt())

    metrics = screener._portfolio_metrics(NonFinitePortfolio())

    assert metrics.net_profit_pct is None
    assert metrics.net_profit_abs == 0.0
    assert metrics.win_rate_pct is None
    assert metrics.max_drawdown_pct == 0.0
    assert metrics.total_trades == 0
    assert metrics.profit_factor is None
    assert metrics.sharpe_ratio is None
