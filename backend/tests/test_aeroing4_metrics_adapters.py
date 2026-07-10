"""Adapter tests for the AeRoing4 Metrics SSOT (Prompt 2)."""

from backend.models.runs import ExitReasonStat, ParsedSummary
from backend.services.aeroing4.metrics.adapters import (
    from_pair_discovery_group,
    from_parsed_summary,
    from_parsed_summary_with_trades,
)
from backend.services.aeroing4.metrics.models import MetricAvailability
from backend.services.aeroing4.metrics.provenance import METRICS_VERSION, SourceType


def _make_summary(**overrides) -> ParsedSummary:
    base = dict(
        run_id="run-1",
        starting_balance=1000.0,
        final_balance=1120.0,
        net_profit_currency=120.0,
        net_profit_pct=12.0,
        total_trades=20,
        trades_per_day=2.0,
        win_rate_pct=60.0,
        loss_rate_pct=40.0,
        max_drawdown_pct=8.0,
        max_drawdown_currency=80.0,
        avg_trade_duration_minutes=45.0,
        profit_factor=1.8,
        expectancy=6.0,
        sharpe_ratio=1.2,
        sortino_ratio=1.5,
        calmar_ratio=2.1,
        exit_reason_distribution=[],
    )
    base.update(overrides)
    return ParsedSummary(**base)


class TestFromParsedSummary:
    def test_all_available(self):
        summary = _make_summary()
        snapshot = from_parsed_summary(summary)
        assert snapshot.net_profit_abs.value == 120.0
        assert snapshot.net_profit_pct.value == 12.0
        assert snapshot.profit_factor.value == 1.8
        assert snapshot.expectancy.value == 6.0
        assert snapshot.sharpe.value == 1.2
        assert snapshot.sortino.value == 1.5
        assert snapshot.calmar.value == 2.1
        assert snapshot.max_drawdown_abs.value == 80.0
        assert snapshot.max_drawdown_pct.value == 8.0
        assert snapshot.average_trade_duration_minutes.value == 45.0
        assert snapshot.total_trades.value == 20
        assert snapshot.winning_trades.value == 12
        assert snapshot.losing_trades.value == 8
        assert all(
            getattr(snapshot, f).availability == MetricAvailability.AVAILABLE
            for f in (
                "net_profit_abs", "net_profit_pct", "profit_factor", "expectancy",
                "sharpe", "sortino", "calmar", "max_drawdown_abs", "max_drawdown_pct",
                "average_trade_duration_minutes", "total_trades",
            )
        )

    def test_all_unavailable(self):
        summary = _make_summary(
            net_profit_currency=None, net_profit_pct=None, total_trades=None,
            trades_per_day=None, win_rate_pct=None, loss_rate_pct=None,
            max_drawdown_pct=None, max_drawdown_currency=None,
            avg_trade_duration_minutes=None, profit_factor=None, expectancy=None,
            sharpe_ratio=None, sortino_ratio=None, calmar_ratio=None,
        )
        snapshot = from_parsed_summary(summary)
        for field in (
            "net_profit_abs", "net_profit_pct", "profit_factor", "expectancy",
            "sharpe", "sortino", "calmar", "max_drawdown_abs", "max_drawdown_pct",
            "average_trade_duration_minutes", "total_trades", "winning_trades", "losing_trades",
        ):
            assert getattr(snapshot, field).availability == MetricAvailability.UNAVAILABLE
            assert getattr(snapshot, field).value is None

    def test_partial_availability(self):
        summary = _make_summary(sharpe_ratio=None, sortino_ratio=None)
        snapshot = from_parsed_summary(summary)
        assert snapshot.sharpe.availability == MetricAvailability.UNAVAILABLE
        assert snapshot.sortino.availability == MetricAvailability.UNAVAILABLE
        assert snapshot.profit_factor.availability == MetricAvailability.AVAILABLE
        assert snapshot.calmar.availability == MetricAvailability.AVAILABLE

    def test_bootstrap_sharpe_unavailable_without_trades(self):
        snapshot = from_parsed_summary(_make_summary())
        assert snapshot.bootstrap_sharpe_p5.availability == MetricAvailability.UNAVAILABLE

    def test_provenance_stamped(self):
        snapshot = from_parsed_summary(_make_summary(), source_run_id="run-1")
        assert snapshot.provenance.metrics_version == METRICS_VERSION
        assert snapshot.provenance.source_type == SourceType.PARSED_SUMMARY
        assert snapshot.provenance.source_run_id == "run-1"
        assert "profit_factor" in snapshot.provenance.adapted_metrics
        assert "bootstrap_sharpe_p5" in snapshot.provenance.unavailable_metrics

    def test_serialization_round_trip_preserves_null_and_availability(self):
        summary = _make_summary(sharpe_ratio=None)
        snapshot = from_parsed_summary(summary, source_run_id="run-1")
        dumped = snapshot.model_dump(mode="json")
        assert dumped["sharpe"]["value"] is None
        assert dumped["sharpe"]["availability"] == "unavailable"
        assert dumped["provenance"]["metrics_version"] == METRICS_VERSION

        from backend.services.aeroing4.metrics.models import CanonicalMetricsSnapshot
        reloaded = CanonicalMetricsSnapshot.model_validate(dumped)
        assert reloaded.sharpe.availability == MetricAvailability.UNAVAILABLE
        assert reloaded.provenance.metrics_version == METRICS_VERSION


class _FakeTrade:
    """Minimal stand-in for a typed BacktestTrade-like object (attribute
    access, not dict access)."""

    def __init__(self, profit_ratio):
        self.profit_ratio = profit_ratio


class TestFromParsedSummaryWithTrades:
    def test_derives_bootstrap_sharpe_from_object_trades(self):
        summary = _make_summary()
        trades = [_FakeTrade(r) for r in [0.01, -0.02, 0.03, -0.01, 0.02, 0.015]]
        snapshot = from_parsed_summary_with_trades(summary, trades, source_run_id="run-1")
        assert snapshot.bootstrap_sharpe_p5.availability == MetricAvailability.AVAILABLE
        assert "bootstrap_sharpe_p5" in snapshot.provenance.derived_metrics

    def test_derives_bootstrap_sharpe_from_dict_trades(self):
        summary = _make_summary()
        trades = [{"profit_ratio": r} for r in [0.01, -0.02, 0.03, -0.01, 0.02, 0.015]]
        snapshot = from_parsed_summary_with_trades(summary, trades, source_run_id="run-1")
        assert snapshot.bootstrap_sharpe_p5.availability == MetricAvailability.AVAILABLE

    def test_dict_and_object_trades_agree(self):
        summary = _make_summary()
        returns = [0.01, -0.02, 0.03, -0.01, 0.02, 0.015]
        obj_snapshot = from_parsed_summary_with_trades(summary, [_FakeTrade(r) for r in returns])
        dict_snapshot = from_parsed_summary_with_trades(summary, [{"profit_ratio": r} for r in returns])
        assert obj_snapshot.bootstrap_sharpe_p5.value == dict_snapshot.bootstrap_sharpe_p5.value

    def test_missing_profit_ratio_is_skipped_not_treated_as_zero(self):
        summary = _make_summary()
        trades = [{"profit_ratio": None}, {"exit_reason": "roi"}, _FakeTrade(None)]
        snapshot = from_parsed_summary_with_trades(summary, trades)
        assert snapshot.bootstrap_sharpe_p5.availability == MetricAvailability.INSUFFICIENT_DATA

    def test_backfills_sharpe_when_summary_lacks_it(self):
        summary = _make_summary(sharpe_ratio=None)
        trades = [_FakeTrade(r) for r in [0.01, -0.02, 0.03, -0.01, 0.02, 0.015]]
        snapshot = from_parsed_summary_with_trades(summary, trades)
        assert snapshot.sharpe.availability == MetricAvailability.AVAILABLE
        assert "sharpe" in snapshot.provenance.derived_metrics
        assert "sharpe" not in snapshot.provenance.unavailable_metrics


class TestFromPairDiscoveryGroup:
    def test_derives_profit_factor_and_expectancy_from_trades(self):
        pair_data = {
            "trades": [
                {"profit_abs": 10.0, "trade_duration": 30},
                {"profit_abs": -5.0, "trade_duration": 45},
                {"profit_abs": 20.0, "trade_duration": 60},
            ],
            "net_profit_pct": 15.0,
            "win_rate": 66.7,
        }
        snapshot = from_pair_discovery_group(pair_data, pair="BTC/USDT", source_run_id="sess-1")
        assert snapshot.profit_factor.value == 6.0
        assert snapshot.expectancy.value == round(25.0 / 3, 6)
        assert snapshot.total_trades.value == 3
        assert snapshot.net_profit_pct.value == 15.0
        assert snapshot.average_trade_duration_minutes.value == 45.0
        assert snapshot.provenance.source_type == SourceType.PAIR_DISCOVERY_GROUP
        assert snapshot.provenance.source_artifact == "BTC/USDT"
        assert "profit_factor" in snapshot.provenance.derived_metrics
        assert "expectancy" in snapshot.provenance.derived_metrics

    def test_zero_trades_produces_unavailable_not_zero(self):
        snapshot = from_pair_discovery_group({"trades": []}, pair="ETH/USDT")
        assert snapshot.profit_factor.availability == MetricAvailability.UNAVAILABLE
        assert snapshot.expectancy.availability == MetricAvailability.UNAVAILABLE
        assert snapshot.total_trades.value == 0

    def test_empty_pair_data(self):
        snapshot = from_pair_discovery_group({}, pair="SOL/USDT")
        assert snapshot.total_trades.availability == MetricAvailability.UNAVAILABLE
        assert snapshot.net_profit_pct.availability == MetricAvailability.UNAVAILABLE
