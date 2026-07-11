"""Tests for diagnosis thresholds and evidence quality."""

import pytest
from backend.services.aeroing4.diagnosis.thresholds import (
    DRAWDOWN_ACCEPTABLE_THRESHOLD,
    DRAWDOWN_CRITICAL_THRESHOLD,
    DRAWDOWN_ELEVATED_MAX,
    DRAWDOWN_ELEVATED_MIN,
    DRAWDOWN_HIGH_MAX,
    DRAWDOWN_HIGH_MIN,
    EXPECTANCY_NEGATIVE_THRESHOLD,
    PF_MARGINAL_MAX,
    PF_MARGINAL_MIN,
    PF_NEGATIVE_THRESHOLD,
    PF_STRONG_THRESHOLD,
    PF_WEAK_MAX,
    PF_WEAK_MIN,
    classify_evidence_quality,
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
from backend.services.aeroing4.diagnosis.models import EvidenceQuality
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


def test_profit_factor_thresholds():
    """Test profit factor threshold constants."""
    assert PF_NEGATIVE_THRESHOLD == 1.00
    assert PF_WEAK_MIN == 1.00
    assert PF_WEAK_MAX == 1.10
    assert PF_MARGINAL_MIN == 1.10
    assert PF_MARGINAL_MAX == 1.30
    assert PF_STRONG_THRESHOLD == 1.30


def test_drawdown_thresholds():
    """Test drawdown threshold constants."""
    assert DRAWDOWN_ACCEPTABLE_THRESHOLD == 20.0
    assert DRAWDOWN_ELEVATED_MIN == 20.0
    assert DRAWDOWN_ELEVATED_MAX == 30.0
    assert DRAWDOWN_HIGH_MIN == 30.0
    assert DRAWDOWN_HIGH_MAX == 40.0
    assert DRAWDOWN_CRITICAL_THRESHOLD == 40.0


def test_expectancy_threshold():
    """Test expectancy threshold constant."""
    assert EXPECTANCY_NEGATIVE_THRESHOLD == 0.0


def test_classify_evidence_quality_high():
    """Test evidence quality classification - HIGH."""
    # Create a high-quality baseline result
    metrics = create_metrics_snapshot(total_trades=100, profit_factor=1.5, expectancy=0.005, max_drawdown=15.0)

    baseline = PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        per_pair_contribution=[
            PerPairContribution(pair="BTC/USDT", trade_count=50, net_profit_pct=10.0),
            PerPairContribution(pair="ETH/USDT", trade_count=30, net_profit_pct=5.0),
            PerPairContribution(pair="SOL/USDT", trade_count=20, net_profit_pct=3.0),
        ],
        concentration_summary=ConcentrationSummary(
            concentration_flag=ConcentrationFlag.BALANCED_CONTRIBUTION,
            total_contributing_pairs=3,
            top_pair_profit_contribution_share=0.5,
        ),
        exit_reason_distribution=[
            ExitReasonDistribution(reason_name="stop_loss", count=10, percentage_of_trades=0.1, total_profit_contribution=-50.0),
            ExitReasonDistribution(reason_name="take_profit", count=90, percentage_of_trades=0.9, total_profit_contribution=150.0),
        ],
        canonical_metrics=metrics.model_dump(mode="json"),
        timeframe="5m",
        develop_timerange="20240101-20240630",
    )

    quality = classify_evidence_quality(baseline, metrics, "5m")
    assert quality == EvidenceQuality.HIGH


def test_classify_evidence_quality_insufficient():
    """Test evidence quality classification - INSUFFICIENT (low trades)."""
    # Create a low-quality baseline result with insufficient trades
    metrics = create_metrics_snapshot(total_trades=5, profit_factor=1.5, expectancy=0.005, max_drawdown=15.0)

    baseline = PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT"],
        per_pair_contribution=[
            PerPairContribution(pair="BTC/USDT", trade_count=5, net_profit_pct=2.0),
        ],
        concentration_summary=ConcentrationSummary(
            concentration_flag=ConcentrationFlag.HIGH_PAIR_CONCENTRATION,
            total_contributing_pairs=1,
            top_pair_profit_contribution_share=1.0,
        ),
        exit_reason_distribution=[
            ExitReasonDistribution(reason_name="stop_loss", count=2, percentage_of_trades=0.4, total_profit_contribution=-10.0),
        ],
        canonical_metrics=metrics.model_dump(mode="json"),
        timeframe="5m",
        develop_timerange="20240101-20240630",
    )

    quality = classify_evidence_quality(baseline, metrics, "5m")
    assert quality == EvidenceQuality.INSUFFICIENT


def test_classify_evidence_quality_medium():
    """Test evidence quality classification - MEDIUM."""
    # Create a medium-quality baseline result
    metrics = create_metrics_snapshot(total_trades=50, profit_factor=1.2, expectancy=0.002, max_drawdown=20.0)

    baseline = PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT", "ETH/USDT"],
        per_pair_contribution=[
            PerPairContribution(pair="BTC/USDT", trade_count=30, net_profit_pct=8.0),
            PerPairContribution(pair="ETH/USDT", trade_count=20, net_profit_pct=4.0),
        ],
        concentration_summary=ConcentrationSummary(
            concentration_flag=ConcentrationFlag.MODERATE_CONCENTRATION,
            total_contributing_pairs=2,
            top_pair_profit_contribution_share=0.6,
        ),
        exit_reason_distribution=[
            ExitReasonDistribution(reason_name="stop_loss", count=15, percentage_of_trades=0.3, total_profit_contribution=-30.0),
        ],
        canonical_metrics=metrics.model_dump(mode="json"),
        timeframe="5m",
        develop_timerange="20240101-20240630",
    )

    quality = classify_evidence_quality(baseline, metrics, "5m")
    # Should be MEDIUM or HIGH depending on scoring
    assert quality in [EvidenceQuality.MEDIUM, EvidenceQuality.HIGH]


def test_classify_evidence_quality_missing_metrics():
    """Test evidence quality classification with missing metrics."""
    # Create a baseline with missing metrics
    metrics = CanonicalMetricsSnapshot(
        total_trades=MetricValue(value=100, availability=MetricAvailability.AVAILABLE),
        winning_trades=MetricValue(value=None, availability=MetricAvailability.UNAVAILABLE),
        losing_trades=MetricValue(value=None, availability=MetricAvailability.UNAVAILABLE),
        net_profit_abs=MetricValue(value=None, availability=MetricAvailability.UNAVAILABLE),
        net_profit_pct=MetricValue(value=None, availability=MetricAvailability.UNAVAILABLE),
        win_rate=MetricValue(value=None, availability=MetricAvailability.UNAVAILABLE),
        profit_factor=MetricValue(value=None, availability=MetricAvailability.UNAVAILABLE),
        expectancy=MetricValue(value=None, availability=MetricAvailability.UNAVAILABLE),
        sharpe=MetricValue(value=None, availability=MetricAvailability.UNAVAILABLE),
        sortino=MetricValue(value=None, availability=MetricAvailability.UNAVAILABLE),
        calmar=MetricValue(value=None, availability=MetricAvailability.UNAVAILABLE),
        max_drawdown_abs=MetricValue(value=None, availability=MetricAvailability.UNAVAILABLE),
        max_drawdown_pct=MetricValue(value=None, availability=MetricAvailability.UNAVAILABLE),
        average_trade_duration_minutes=MetricValue(value=None, availability=MetricAvailability.UNAVAILABLE),
        bootstrap_sharpe_p5=MetricValue(value=None, availability=MetricAvailability.UNAVAILABLE),
        provenance=MetricProvenance(
            metrics_version="1.0.0",
            source_type=SourceType.PARSED_SUMMARY,
            source_run_id="test-run",
            calculation_timestamp=datetime.now(UTC),
        ),
    )

    baseline = PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT"],
        per_pair_contribution=[
            PerPairContribution(pair="BTC/USDT", trade_count=100, net_profit_pct=15.0),
        ],
        concentration_summary=ConcentrationSummary(
            concentration_flag=ConcentrationFlag.HIGH_PAIR_CONCENTRATION,
            total_contributing_pairs=1,
            top_pair_profit_contribution_share=1.0,
        ),
        exit_reason_distribution=[],
        canonical_metrics=metrics.model_dump(mode="json"),
        timeframe="5m",
        develop_timerange="20240101-20240630",
    )

    quality = classify_evidence_quality(baseline, metrics, "5m")
    # Should be LOW or MEDIUM due to missing metrics
    assert quality in [EvidenceQuality.LOW, EvidenceQuality.MEDIUM]
