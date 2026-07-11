"""Tests for expectancy severity scale-invariance."""

import pytest
from backend.services.aeroing4.diagnosis.models import (
    DiagnosisCategory,
    DiagnosisCode,
    EvidenceQuality,
    Severity,
)
from backend.services.aeroing4.diagnosis.rules.edge_quality import NegativeExpectancyRule
from backend.services.aeroing4.diagnosis.rules.base import RuleEvaluationContext
from backend.services.aeroing4.diagnosis.resolver import EvidenceResolver
from backend.services.aeroing4.portfolio_baseline.models import (
    ConcentrationFlag,
    ConcentrationSummary,
    ExitReasonDistribution,
    PerPairContribution,
    PortfolioBaselineResult,
    PortfolioBaselineOutcome,
)
from backend.services.aeroing4.metrics.models import (
    CanonicalMetricsSnapshot,
    MetricAvailability,
    MetricProvenance,
    MetricValue,
)
from backend.services.aeroing4.metrics.provenance import SourceType


def create_baseline_with_metrics(expectancy, profit_factor):
    """Helper to create baseline with specific expectancy and profit factor."""
    metrics = CanonicalMetricsSnapshot(
        total_trades=MetricValue(
            availability=MetricAvailability.AVAILABLE,
            value=100,
        ),
        profit_factor=MetricValue(
            availability=MetricAvailability.AVAILABLE,
            value=profit_factor,
        ),
        expectancy=MetricValue(
            availability=MetricAvailability.AVAILABLE,
            value=expectancy,
        ),
        max_drawdown_pct=MetricValue(
            availability=MetricAvailability.AVAILABLE,
            value=15.0,
        ),
        sharpe=MetricValue(
            availability=MetricAvailability.AVAILABLE,
            value=1.5,
        ),
        winning_trades=MetricValue(
            availability=MetricAvailability.AVAILABLE,
            value=55,
        ),
        losing_trades=MetricValue(
            availability=MetricAvailability.AVAILABLE,
            value=45,
        ),
        average_trade_duration_minutes=MetricValue(
            availability=MetricAvailability.AVAILABLE,
            value=120.0,
        ),
        net_profit_abs=MetricValue(
            availability=MetricAvailability.AVAILABLE,
            value=1000.0,
        ),
        net_profit_pct=MetricValue(
            availability=MetricAvailability.AVAILABLE,
            value=10.0,
        ),
        win_rate=MetricValue(
            availability=MetricAvailability.AVAILABLE,
            value=0.55,
        ),
        sortino=MetricValue(
            availability=MetricAvailability.AVAILABLE,
            value=2.0,
        ),
        calmar=MetricValue(
            availability=MetricAvailability.AVAILABLE,
            value=1.0,
        ),
        max_drawdown_abs=MetricValue(
            availability=MetricAvailability.AVAILABLE,
            value=500.0,
        ),
        bootstrap_sharpe_p5=MetricValue(
            availability=MetricAvailability.AVAILABLE,
            value=1.2,
        ),
        provenance=MetricProvenance(
            metrics_version="1.0.0",
            source_type=SourceType.PARSED_SUMMARY,
            source_run_id="test-run",
            calculation_timestamp="2024-01-01T00:00:00Z",
        ),
    )

    baseline = PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT", "ETH/USDT"],
        canonical_metrics=metrics.model_dump(mode="json"),
        per_pair_contribution=[
            PerPairContribution(pair="BTC/USDT", trade_count=50, net_profit_pct=5.0),
            PerPairContribution(pair="ETH/USDT", trade_count=50, net_profit_pct=3.0),
        ],
        concentration_summary=ConcentrationSummary(
            concentration_flag=ConcentrationFlag.BALANCED_CONTRIBUTION,
            total_contributing_pairs=2,
            top_pair_profit_contribution_share=0.6,
        ),
        exit_reason_distribution=[
            ExitReasonDistribution(reason_name="take_profit", count=60, percentage_of_trades=0.6, total_profit_contribution=80.0),
            ExitReasonDistribution(reason_name="stop_loss", count=40, percentage_of_trades=0.4, total_profit_contribution=-20.0),
        ],
    )
    return baseline


def test_negative_expectancy_with_low_profit_factor_critical():
    """Test negative expectancy with profit factor < 1.0 triggers CRITICAL severity."""
    baseline = create_baseline_with_metrics(expectancy=-0.01, profit_factor=0.8)
    resolver = EvidenceResolver(baseline)
    context = RuleEvaluationContext(
        resolver=resolver,
        evidence_quality=EvidenceQuality.HIGH,
        timeframe="5m",
        run_id="test-run",
        champion_id="test-champion",
    )

    rule = NegativeExpectancyRule()
    finding = rule.evaluate(context)

    assert finding is not None
    assert finding.severity == Severity.CRITICAL
    assert finding.confidence == 0.95


def test_negative_expectancy_with_marginal_profit_factor_high():
    """Test negative expectancy with weak profit factor triggers HIGH severity."""
    baseline = create_baseline_with_metrics(expectancy=-0.01, profit_factor=1.05)
    resolver = EvidenceResolver(baseline)
    context = RuleEvaluationContext(
        resolver=resolver,
        evidence_quality=EvidenceQuality.HIGH,
        timeframe="5m",
        run_id="test-run",
        champion_id="test-champion",
    )

    rule = NegativeExpectancyRule()
    finding = rule.evaluate(context)

    assert finding is not None
    assert finding.severity == Severity.HIGH
    assert finding.confidence == 0.90


def test_negative_expectancy_without_profit_factor_medium():
    """Test negative expectancy without profit factor triggers MEDIUM severity (conservative)."""
    baseline = create_baseline_with_metrics(expectancy=-0.01, profit_factor=None)
    resolver = EvidenceResolver(baseline)
    context = RuleEvaluationContext(
        resolver=resolver,
        evidence_quality=EvidenceQuality.HIGH,
        timeframe="5m",
        run_id="test-run",
        champion_id="test-champion",
    )

    rule = NegativeExpectancyRule()
    finding = rule.evaluate(context)

    assert finding is not None
    assert finding.severity == Severity.MEDIUM
    assert finding.confidence == 0.85


def test_expectancy_severity_scale_invariant():
    """Test that severity does not change based on absolute expectancy magnitude alone."""
    # Small account: expectancy = -0.001 (small absolute value)
    baseline_small = create_baseline_with_metrics(expectancy=-0.001, profit_factor=0.8)
    resolver_small = EvidenceResolver(baseline_small)
    context_small = RuleEvaluationContext(
        resolver=resolver_small,
        evidence_quality=EvidenceQuality.HIGH,
        timeframe="5m",
        run_id="test-run",
        champion_id="test-champion",
    )

    # Large account: expectancy = -100.0 (large absolute value)
    baseline_large = create_baseline_with_metrics(expectancy=-100.0, profit_factor=0.8)
    resolver_large = EvidenceResolver(baseline_large)
    context_large = RuleEvaluationContext(
        resolver=resolver_large,
        evidence_quality=EvidenceQuality.HIGH,
        timeframe="5m",
        run_id="test-run",
        champion_id="test-champion",
    )

    rule = NegativeExpectancyRule()
    finding_small = rule.evaluate(context_small)
    finding_large = rule.evaluate(context_large)

    # Both should have CRITICAL severity because profit factor < 1.0
    # Severity should be based on profit factor, not absolute expectancy
    assert finding_small is not None
    assert finding_large is not None
    assert finding_small.severity == Severity.CRITICAL
    assert finding_large.severity == Severity.CRITICAL


def test_expectancy_severity_uses_profit_factor_not_magnitude():
    """Test that profit factor determines severity, not expectancy magnitude."""
    # Case 1: Small negative expectancy, poor profit factor
    baseline1 = create_baseline_with_metrics(expectancy=-0.001, profit_factor=0.8)
    resolver1 = EvidenceResolver(baseline1)
    context1 = RuleEvaluationContext(
        resolver=resolver1,
        evidence_quality=EvidenceQuality.HIGH,
        timeframe="5m",
        run_id="test-run",
        champion_id="test-champion",
    )

    # Case 2: Large negative expectancy, good profit factor
    baseline2 = create_baseline_with_metrics(expectancy=-100.0, profit_factor=1.2)
    resolver2 = EvidenceResolver(baseline2)
    context2 = RuleEvaluationContext(
        resolver=resolver2,
        evidence_quality=EvidenceQuality.HIGH,
        timeframe="5m",
        run_id="test-run",
        champion_id="test-champion",
    )

    rule = NegativeExpectancyRule()
    finding1 = rule.evaluate(context1)
    finding2 = rule.evaluate(context2)

    # Case 1 should be CRITICAL (poor profit factor)
    # Case 2 should be MEDIUM (good profit factor, negative expectancy alone)
    assert finding1 is not None
    assert finding2 is not None
    assert finding1.severity == Severity.CRITICAL
    assert finding2.severity == Severity.MEDIUM


def test_positive_expectancy_no_trigger():
    """Test that positive expectancy does not trigger the rule regardless of profit factor."""
    baseline = create_baseline_with_metrics(expectancy=0.01, profit_factor=0.8)
    resolver = EvidenceResolver(baseline)
    context = RuleEvaluationContext(
        resolver=resolver,
        evidence_quality=EvidenceQuality.HIGH,
        timeframe="5m",
        run_id="test-run",
        champion_id="test-champion",
    )

    rule = NegativeExpectancyRule()
    finding = rule.evaluate(context)

    assert finding is None


def test_zero_expectancy_no_trigger():
    """Test that zero expectancy does not trigger the rule."""
    baseline = create_baseline_with_metrics(expectancy=0.0, profit_factor=0.8)
    resolver = EvidenceResolver(baseline)
    context = RuleEvaluationContext(
        resolver=resolver,
        evidence_quality=EvidenceQuality.HIGH,
        timeframe="5m",
        run_id="test-run",
        champion_id="test-champion",
    )

    rule = NegativeExpectancyRule()
    finding = rule.evaluate(context)

    assert finding is None
