"""Tests for diagnosis rules."""

import pytest
from backend.services.aeroing4.diagnosis.models import (
    DiagnosisCategory,
    DiagnosisCode,
    Severity,
)
from backend.services.aeroing4.diagnosis.rules.base import BaseRule, RuleEvaluationContext
from backend.services.aeroing4.diagnosis.rules.edge_quality import NoEdgeRule
from backend.services.aeroing4.diagnosis.rules.sample_quality import InsufficientSampleRule
from backend.services.aeroing4.diagnosis.rules.risk import ExcessiveDrawdownRule
from backend.services.aeroing4.diagnosis.rules.pair_structure import SinglePairDependenceRule
from backend.services.aeroing4.diagnosis.rules.exit_behavior import StoplossDominanceRule
from backend.services.aeroing4.diagnosis.rules.entry_behavior import EntryTooRestrictiveRule
from backend.services.aeroing4.diagnosis.rules.parameter_research import ParameterResearchRules
from backend.services.aeroing4.diagnosis.resolver import EvidenceResolver
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


def create_baseline_result(
    total_trades=100,
    profit_factor=1.5,
    expectancy=0.005,
    max_drawdown=15.0,
    selected_pairs=None,
    per_pair_contributions=None,
    concentration_summary=None,
    exit_reason_distribution=None,
):
    """Helper to create a baseline result for testing."""
    if selected_pairs is None:
        selected_pairs = ["BTC/USDT", "ETH/USDT"]
    if per_pair_contributions is None:
        per_pair_contributions = [
            PerPairContribution(pair="BTC/USDT", trade_count=50, net_profit_pct=10.0),
            PerPairContribution(pair="ETH/USDT", trade_count=50, net_profit_pct=8.0),
        ]
    if concentration_summary is None:
        concentration_summary = ConcentrationSummary(
            concentration_flag=ConcentrationFlag.BALANCED_CONTRIBUTION,
            total_contributing_pairs=2,
            top_pair_profit_contribution_share=0.55,
        )
    if exit_reason_distribution is None:
        exit_reason_distribution = [
            ExitReasonDistribution(reason_name="take_profit", count=80, percentage_of_trades=0.8, total_profit_contribution=100.0),
            ExitReasonDistribution(reason_name="stop_loss", count=20, percentage_of_trades=0.2, total_profit_contribution=-20.0),
        ]

    metrics = create_metrics_snapshot(total_trades, profit_factor, expectancy, max_drawdown)

    return PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=selected_pairs,
        per_pair_contribution=per_pair_contributions,
        concentration_summary=concentration_summary,
        exit_reason_distribution=exit_reason_distribution,
        canonical_metrics=metrics.model_dump(mode="json"),
        timeframe="5m",
        develop_timerange="20240101-20240630",
    )


def create_context(baseline_result):
    """Helper to create a rule evaluation context."""
    resolver = EvidenceResolver(baseline_result)
    from backend.services.aeroing4.diagnosis.thresholds import classify_evidence_quality
    from backend.services.aeroing4.diagnosis.models import EvidenceQuality

    evidence_quality = classify_evidence_quality(
        baseline_result, baseline_result.canonical_metrics, "5m"
    )

    return RuleEvaluationContext(
        resolver=resolver,
        evidence_quality=evidence_quality,
        timeframe="5m",
        run_id="test-run",
        champion_id="test-champion",
    )


def test_insufficient_sample_rule_triggers():
    """Test InsufficientSampleRule triggers with low trades."""
    # Create baseline with insufficient trades (below minimum for 5m)
    baseline = create_baseline_result(total_trades=5)  # Very low
    context = create_context(baseline)

    rule = InsufficientSampleRule()
    finding = rule.evaluate(context)

    assert finding is not None
    assert finding.diagnosis_code == DiagnosisCode.INSUFFICIENT_SAMPLE
    assert finding.category == DiagnosisCategory.SAMPLE_QUALITY
    assert finding.severity in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM]


def test_insufficient_sample_rule_no_trigger():
    """Test InsufficientSampleRule does not trigger with sufficient trades."""
    baseline = create_baseline_result(total_trades=100)
    context = create_context(baseline)

    rule = InsufficientSampleRule()
    finding = rule.evaluate(context)

    assert finding is None


def test_no_edge_rule_triggers():
    """Test NoEdgeRule triggers with PF < 1.0 and negative expectancy."""
    baseline = create_baseline_result(profit_factor=0.8, expectancy=-0.01)
    context = create_context(baseline)

    rule = NoEdgeRule()
    finding = rule.evaluate(context)

    assert finding is not None
    assert finding.diagnosis_code == DiagnosisCode.NO_EDGE
    assert finding.category == DiagnosisCategory.EDGE_QUALITY
    assert finding.severity == Severity.CRITICAL
    assert finding.confidence >= 0.9


def test_no_edge_rule_no_trigger_pf_ok():
    """Test NoEdgeRule does not trigger when PF >= 1.0."""
    baseline = create_baseline_result(profit_factor=1.2, expectancy=-0.01)
    context = create_context(baseline)

    rule = NoEdgeRule()
    finding = rule.evaluate(context)

    assert finding is None


def test_no_edge_rule_no_trigger_expectancy_ok():
    """Test NoEdgeRule does not trigger when expectancy >= 0."""
    baseline = create_baseline_result(profit_factor=0.8, expectancy=0.005)
    context = create_context(baseline)

    rule = NoEdgeRule()
    finding = rule.evaluate(context)

    assert finding is None


def test_excessive_drawdown_rule_critical():
    """Test ExcessiveDrawdownRule triggers with critical drawdown."""
    baseline = create_baseline_result(max_drawdown=45.0)  # > 40%
    context = create_context(baseline)

    rule = ExcessiveDrawdownRule()
    finding = rule.evaluate(context)

    assert finding is not None
    assert finding.diagnosis_code == DiagnosisCode.EXCESSIVE_DRAWDOWN
    assert finding.severity == Severity.CRITICAL


def test_excessive_drawdown_rule_high():
    """Test ExcessiveDrawdownRule triggers with high drawdown."""
    baseline = create_baseline_result(max_drawdown=35.0)  # 30-40%
    context = create_context(baseline)

    rule = ExcessiveDrawdownRule()
    finding = rule.evaluate(context)

    assert finding is not None
    assert finding.diagnosis_code == DiagnosisCode.EXCESSIVE_DRAWDOWN
    assert finding.severity == Severity.HIGH


def test_excessive_drawdown_rule_no_trigger():
    """Test ExcessiveDrawdownRule does not trigger with acceptable drawdown."""
    baseline = create_baseline_result(max_drawdown=15.0)  # < 20%
    context = create_context(baseline)

    rule = ExcessiveDrawdownRule()
    finding = rule.evaluate(context)

    assert finding is None


def test_single_pair_dependence_rule_triggers():
    """Test SinglePairDependenceRule triggers with single pair."""
    baseline = create_baseline_result(
        selected_pairs=["BTC/USDT"],
        per_pair_contributions=[
            PerPairContribution(pair="BTC/USDT", trade_count=100, net_profit_pct=15.0)
        ],
        concentration_summary=ConcentrationSummary(
            concentration_flag=ConcentrationFlag.HIGH_PAIR_CONCENTRATION,
            total_contributing_pairs=1,
            top_pair_profit_contribution_share=1.0,
        ),
    )
    context = create_context(baseline)

    rule = SinglePairDependenceRule()
    finding = rule.evaluate(context)

    assert finding is not None
    assert finding.diagnosis_code == DiagnosisCode.SINGLE_PAIR_DEPENDENCE
    assert finding.severity == Severity.CRITICAL


def test_single_pair_dependence_rule_no_trigger():
    """Test SinglePairDependenceRule does not trigger with multiple pairs."""
    baseline = create_baseline_result()
    context = create_context(baseline)

    rule = SinglePairDependenceRule()
    finding = rule.evaluate(context)

    assert finding is None


def test_stoploss_dominance_rule_triggers():
    """Test StoplossDominanceRule triggers with high stoploss share."""
    exit_dist = [
        ExitReasonDistribution(reason_name="stop_loss", count=70, percentage_of_trades=0.7, total_profit_contribution=-70.0),
        ExitReasonDistribution(reason_name="take_profit", count=30, percentage_of_trades=0.3, total_profit_contribution=30.0),
    ]
    baseline = create_baseline_result(exit_reason_distribution=exit_dist)
    context = create_context(baseline)

    rule = StoplossDominanceRule()
    finding = rule.evaluate(context)

    assert finding is not None
    assert finding.diagnosis_code == DiagnosisCode.STOPLOSS_DOMINANCE
    assert finding.severity in [Severity.HIGH, Severity.MEDIUM]


def test_stoploss_dominance_rule_no_trigger():
    """Test StoplossDominanceRule does not trigger with low stoploss share."""
    exit_dist = [
        ExitReasonDistribution(reason_name="stop_loss", count=20, percentage_of_trades=0.2, total_profit_contribution=-20.0),
        ExitReasonDistribution(reason_name="take_profit", count=80, percentage_of_trades=0.8, total_profit_contribution=100.0),
    ]
    baseline = create_baseline_result(exit_reason_distribution=exit_dist)
    context = create_context(baseline)

    rule = StoplossDominanceRule()
    finding = rule.evaluate(context)

    assert finding is None


def test_entry_too_restrictive_rule_triggers():
    """Test EntryTooRestrictiveRule triggers with very low trade count."""
    baseline = create_baseline_result(total_trades=10)  # Very low
    context = create_context(baseline)

    rule = EntryTooRestrictiveRule()
    finding = rule.evaluate(context)

    assert finding is not None
    assert finding.diagnosis_code == DiagnosisCode.ENTRY_TOO_RESTRICTIVE
    assert finding.severity in [Severity.HIGH, Severity.MEDIUM]


def test_entry_too_restrictive_rule_no_trigger():
    """Test EntryTooRestrictiveRule does not trigger with sufficient trades."""
    baseline = create_baseline_result(total_trades=100)
    context = create_context(baseline)

    rule = EntryTooRestrictiveRule()
    finding = rule.evaluate(context)

    assert finding is None


def test_parameter_research_rules_are_derived():
    """Test that parameter research rules are marked as derived."""
    rules = ParameterResearchRules.get_all_rules()

    for rule in rules:
        assert rule.is_derived is True
        assert rule.priority == 10  # Lowest priority


def test_parameter_research_rules_do_not_evaluate():
    """Test that parameter research rules return None when evaluated."""
    baseline = create_baseline_result()
    context = create_context(baseline)

    rules = ParameterResearchRules.get_all_rules()

    for rule in rules:
        finding = rule.evaluate(context)
        assert finding is None  # Derived rules don't evaluate independently


def test_rule_check_required_evidence():
    """Test BaseRule.check_required_evidence."""
    baseline = create_baseline_result()
    context = create_context(baseline)

    rule = InsufficientSampleRule()
    # This rule requires total_trades, which is available
    assert rule.check_required_evidence(context) is True


def test_rule_missing_required_evidence():
    """Test BaseRule.check_required_evidence with missing evidence."""
    # Create baseline without per_pair_contribution
    baseline = PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT"],
        per_pair_contribution=[],  # Empty
        concentration_summary=None,
        exit_reason_distribution=[],
        canonical_metrics=create_metrics_snapshot(total_trades=100).model_dump(mode="json"),
        timeframe="5m",
        develop_timerange="20240101-20240630",
    )
    context = create_context(baseline)

    # Use a rule that requires per_pair_contribution
    rule = SinglePairDependenceRule()
    assert rule.check_required_evidence(context) is False
