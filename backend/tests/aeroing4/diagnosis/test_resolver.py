"""Tests for evidence resolver and exit reason mapper."""

import pytest
from backend.services.aeroing4.diagnosis.resolver import (
    CanonicalExitCategory,
    EvidenceResolver,
    map_exit_reason,
)
from backend.services.aeroing4.metrics.models import (
    CanonicalMetricsSnapshot,
    MetricAvailability,
    MetricProvenance,
    MetricValue,
)
from backend.services.aeroing4.metrics.provenance import SourceType
from backend.services.aeroing4.portfolio_baseline.models import (
    ConcentrationFlag,
    ConcentrationSummary,
    ExitReasonDistribution,
    PerPairContribution,
    PortfolioBaselineResult,
    PortfolioBaselineOutcome,
)
from datetime import datetime, UTC


def create_metrics_snapshot(
    total_trades=100,
    profit_factor=1.5,
    expectancy=0.005,
    max_drawdown=15.0,
):
    """Helper to create a complete CanonicalMetricsSnapshot for testing."""
    return CanonicalMetricsSnapshot(
        total_trades=MetricValue(value=total_trades, availability=MetricAvailability.AVAILABLE),
        winning_trades=MetricValue(value=int(total_trades * 0.6), availability=MetricAvailability.AVAILABLE),
        losing_trades=MetricValue(value=int(total_trades * 0.4), availability=MetricAvailability.AVAILABLE),
        net_profit_abs=MetricValue(value=1000, availability=MetricAvailability.AVAILABLE),
        net_profit_pct=MetricValue(value=10.0, availability=MetricAvailability.AVAILABLE),
        win_rate=MetricValue(value=60.0, availability=MetricAvailability.AVAILABLE),
        profit_factor=MetricValue(value=profit_factor, availability=MetricAvailability.AVAILABLE),
        expectancy=MetricValue(value=expectancy, availability=MetricAvailability.AVAILABLE),
        sharpe=MetricValue(value=1.2, availability=MetricAvailability.AVAILABLE),
        sortino=MetricValue(value=1.5, availability=MetricAvailability.AVAILABLE),
        calmar=MetricValue(value=0.8, availability=MetricAvailability.AVAILABLE),
        max_drawdown_abs=MetricValue(value=500, availability=MetricAvailability.AVAILABLE),
        max_drawdown_pct=MetricValue(value=max_drawdown, availability=MetricAvailability.AVAILABLE),
        average_trade_duration_minutes=MetricValue(value=120, availability=MetricAvailability.AVAILABLE),
        bootstrap_sharpe_p5=MetricValue(value=1.0, availability=MetricAvailability.AVAILABLE),
        provenance=MetricProvenance(
            metrics_version="1.0.0",
            source_type=SourceType.PARSED_SUMMARY,
            source_run_id="test-run",
            calculation_timestamp=datetime.now(UTC),
        ),
    )


def test_map_exit_reason_stoploss():
    """Test exit reason mapping for stop loss."""
    raw, canonical = map_exit_reason("stop_loss")
    assert raw == "stop_loss"
    assert canonical == CanonicalExitCategory.STOP_RISK_EXIT

    raw, canonical = map_exit_reason("stoploss")
    assert raw == "stoploss"
    assert canonical == CanonicalExitCategory.STOP_RISK_EXIT

    raw, canonical = map_exit_reason("trailing_stop_loss")
    assert raw == "trailing_stop_loss"
    assert canonical == CanonicalExitCategory.STOP_RISK_EXIT


def test_map_exit_reason_profit():
    """Test exit reason mapping for profit targets."""
    raw, canonical = map_exit_reason("roi")
    assert raw == "roi"
    assert canonical == CanonicalExitCategory.PROFIT_TARGET_EXIT

    raw, canonical = map_exit_reason("take_profit")
    assert raw == "take_profit"
    assert canonical == CanonicalExitCategory.PROFIT_TARGET_EXIT


def test_map_exit_reason_strategy():
    """Test exit reason mapping for strategy exits."""
    raw, canonical = map_exit_reason("exit_signal")
    assert raw == "exit_signal"
    assert canonical == CanonicalExitCategory.STRATEGY_EXIT


def test_map_exit_reason_operational():
    """Test exit reason mapping for operational exits."""
    raw, canonical = map_exit_reason("force_exit")
    assert raw == "force_exit"
    assert canonical == CanonicalExitCategory.OPERATIONAL_EXIT


def test_map_exit_reason_unknown():
    """Test exit reason mapping for unknown reasons."""
    raw, canonical = map_exit_reason("unknown_reason")
    assert raw == "unknown_reason"
    assert canonical == CanonicalExitCategory.OTHER


def test_evidence_resolver_get_total_trades():
    """Test EvidenceResolver.get_total_trades."""
    metrics = create_metrics_snapshot(total_trades=100)

    baseline = PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT"],
        per_pair_contribution=[],
        concentration_summary=None,
        exit_reason_distribution=[],
        canonical_metrics=metrics.model_dump(mode="json"),
        timeframe="5m",
        develop_timerange="20240101-20240630",
    )

    resolver = EvidenceResolver(baseline)
    assert resolver.get_total_trades() == 100


def test_evidence_resolver_get_profit_factor():
    """Test EvidenceResolver.get_profit_factor."""
    metrics = create_metrics_snapshot(profit_factor=1.5)

    baseline = PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT"],
        per_pair_contribution=[],
        concentration_summary=None,
        exit_reason_distribution=[],
        canonical_metrics=metrics.model_dump(mode="json"),
        timeframe="5m",
        develop_timerange="20240101-20240630",
    )

    resolver = EvidenceResolver(baseline)
    assert resolver.get_profit_factor() == 1.5


def test_evidence_resolver_get_expectancy():
    """Test EvidenceResolver.get_expectancy."""
    metrics = create_metrics_snapshot(expectancy=0.005)

    baseline = PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT"],
        per_pair_contribution=[],
        concentration_summary=None,
        exit_reason_distribution=[],
        canonical_metrics=metrics.model_dump(mode="json"),
        timeframe="5m",
        develop_timerange="20240101-20240630",
    )

    resolver = EvidenceResolver(baseline)
    assert resolver.get_expectancy() == 0.005


def test_evidence_resolver_get_max_drawdown():
    """Test EvidenceResolver.get_max_drawdown_pct."""
    metrics = create_metrics_snapshot(max_drawdown=15.0)

    baseline = PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT"],
        per_pair_contribution=[],
        concentration_summary=None,
        exit_reason_distribution=[],
        canonical_metrics=metrics.model_dump(mode="json"),
        timeframe="5m",
        develop_timerange="20240101-20240630",
    )

    resolver = EvidenceResolver(baseline)
    assert resolver.get_max_drawdown_pct() == 15.0


def test_evidence_resolver_get_selected_pairs():
    """Test EvidenceResolver.get_selected_pairs."""
    baseline = PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        per_pair_contribution=[],
        concentration_summary=None,
        exit_reason_distribution=[],
        canonical_metrics=create_metrics_snapshot().model_dump(mode="json"),
        timeframe="5m",
        develop_timerange="20240101-20240630",
    )

    resolver = EvidenceResolver(baseline)
    pairs = resolver.get_selected_pairs()
    assert len(pairs) == 3
    assert "BTC/USDT" in pairs
    assert "ETH/USDT" in pairs
    assert "SOL/USDT" in pairs


def test_evidence_resolver_get_per_pair_contributions():
    """Test EvidenceResolver.get_per_pair_contributions."""
    contributions = [
        PerPairContribution(pair="BTC/USDT", trade_count=50, net_profit_pct=10.0),
        PerPairContribution(pair="ETH/USDT", trade_count=30, net_profit_pct=5.0),
    ]

    baseline = PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT", "ETH/USDT"],
        per_pair_contribution=contributions,
        concentration_summary=None,
        exit_reason_distribution=[],
        canonical_metrics=create_metrics_snapshot().model_dump(mode="json"),
        timeframe="5m",
        develop_timerange="20240101-20240630",
    )

    resolver = EvidenceResolver(baseline)
    result = resolver.get_per_pair_contributions()
    assert len(result) == 2
    assert result[0].pair == "BTC/USDT"
    assert result[1].pair == "ETH/USDT"


def test_evidence_resolver_get_negative_contributing_pairs():
    """Test EvidenceResolver.get_negative_contributing_pairs."""
    contributions = [
        PerPairContribution(pair="BTC/USDT", trade_count=50, net_profit_pct=10.0),
        PerPairContribution(pair="ETH/USDT", trade_count=30, net_profit_pct=-5.0),
        PerPairContribution(pair="SOL/USDT", trade_count=20, net_profit_pct=-3.0),
    ]

    baseline = PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        per_pair_contribution=contributions,
        concentration_summary=None,
        exit_reason_distribution=[],
        canonical_metrics=create_metrics_snapshot(total_trades=100).model_dump(mode="json"),
        timeframe="5m",
        develop_timerange="20240101-20240630",
    )

    resolver = EvidenceResolver(baseline)
    negative_count = resolver.get_negative_contributing_pairs()
    assert negative_count == 2


def test_evidence_resolver_get_stoploss_exit_share():
    """Test EvidenceResolver.get_stoploss_exit_share."""
    exit_dist = [
        ExitReasonDistribution(reason_name="stop_loss", count=60, percentage_of_trades=0.6, total_profit_contribution=-60.0),
        ExitReasonDistribution(reason_name="take_profit", count=40, percentage_of_trades=0.4, total_profit_contribution=80.0),
    ]

    metrics = create_metrics_snapshot(total_trades=100)

    baseline = PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT"],
        per_pair_contribution=[],
        concentration_summary=None,
        exit_reason_distribution=exit_dist,
        canonical_metrics=metrics.model_dump(mode="json"),
        timeframe="5m",
        develop_timerange="20240101-20240630",
    )

    resolver = EvidenceResolver(baseline)
    stoploss_share = resolver.get_stoploss_exit_share()
    assert stoploss_share == 0.6


def test_evidence_resolver_is_metric_available():
    """Test EvidenceResolver.is_metric_available."""
    metrics = create_metrics_snapshot(total_trades=100, profit_factor=1.5, expectancy=0.005, max_drawdown=15.0)

    baseline = PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT"],
        per_pair_contribution=[],
        concentration_summary=None,
        exit_reason_distribution=[],
        canonical_metrics=metrics.model_dump(mode="json"),
        timeframe="5m",
        develop_timerange="20240101-20240630",
    )

    resolver = EvidenceResolver(baseline)
    assert resolver.is_metric_available("total_trades") is True
    assert resolver.is_metric_available("profit_factor") is True
    assert resolver.is_metric_available("expectancy") is True
    assert resolver.is_metric_available("max_drawdown_pct") is True
    assert resolver.is_metric_available("sharpe") is True
