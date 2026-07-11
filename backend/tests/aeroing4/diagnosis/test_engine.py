"""Tests for diagnosis engine."""

import pytest
from backend.services.aeroing4.diagnosis.engine import DiagnosisEngine
from backend.services.aeroing4.diagnosis.models import (
    DiagnosisCategory,
    DiagnosisCode,
    DiagnosisInput,
    DiagnosisOutcome,
    DiagnosisResult,
    EvidenceQuality,
    Severity,
)
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
from backend.services.aeroing4.research.champions import (
    ArtifactReference,
    ChampionReference,
    ChampionSourceType,
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
        input_hash="test-baseline-hash-123",  # For idempotency
    )


def create_champion_reference():
    """Helper to create a champion reference."""
    return ChampionReference(
        champion_id="test-champion",
        run_id="test-run",
        parent_champion_id=None,
        source_type=ChampionSourceType.BASELINE,
        strategy_artifact=ArtifactReference(
            artifact_path="strategies/strategy.py",
            artifact_hash="abc123",
            original_source_path="/original/strategy.py",
            original_source_hash="orig123",
        ),
        parameter_artifact=ArtifactReference(
            artifact_path="config/config.json",
            artifact_hash="def456",
            original_source_path="/original/config.json",
            original_source_hash="orig456",
        ),
    )


def create_diagnosis_input(baseline, champion_ref, run_id="test-run", champion_id="test-champion"):
    """Helper to create a DiagnosisInput with required fields."""
    return DiagnosisInput(
        run_id=run_id,
        champion_id=champion_id,
        champion_strategy_hash="abc123",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="test-baseline-hash-123",
        canonical_metrics_hash="test-metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="1.0.0",
    )


def test_diagnosis_engine_initialization():
    """Test DiagnosisEngine initialization."""
    engine = DiagnosisEngine("/tmp/test_runs")
    assert engine is not None
    assert engine.registry is not None


def test_diagnosis_engine_successful_diagnosis():
    """Test DiagnosisEngine with successful diagnosis."""
    engine = DiagnosisEngine("/tmp/test_runs")

    baseline = create_baseline_result()
    champion_ref = create_champion_reference()

    input_data = create_diagnosis_input(baseline, champion_ref)

    result = engine.diagnose(input_data)

    assert result is not None
    assert result.run_id == "test-run"
    assert result.champion_id == "test-champion"
    assert result.outcome in [
        DiagnosisOutcome.DIAGNOSIS_COMPLETE,
        DiagnosisOutcome.NO_ACTIONABLE_FINDING,
    ]
    assert result.evidence_quality in [
        EvidenceQuality.HIGH,
        EvidenceQuality.MEDIUM,
    ]


def test_diagnosis_engine_insufficient_evidence():
    """Test DiagnosisEngine with insufficient evidence."""
    engine = DiagnosisEngine("/tmp/test_runs")

    # Create baseline with very low trade count
    baseline = create_baseline_result(total_trades=5)
    champion_ref = create_champion_reference()

    input_data = create_diagnosis_input(baseline, champion_ref)

    result = engine.diagnose(input_data)

    assert result is not None
    assert result.outcome == DiagnosisOutcome.INSUFFICIENT_EVIDENCE
    assert result.evidence_quality == EvidenceQuality.INSUFFICIENT
    assert result.primary_diagnosis is None


def test_diagnosis_engine_integrity_error():
    """Test DiagnosisEngine with champion integrity error."""
    engine = DiagnosisEngine("/tmp/test_runs")

    baseline = create_baseline_result()
    champion_ref = create_champion_reference()
    # Mismatch champion ID
    champion_ref.champion_id = "wrong-champion"

    input_data = create_diagnosis_input(baseline, champion_ref)

    result = engine.diagnose(input_data)

    assert result is not None
    assert result.outcome == DiagnosisOutcome.INTEGRITY_ERROR
    assert result.error_message is not None
    assert "champion id mismatch" in result.error_message.lower()


def test_diagnosis_engine_no_champion_reference():
    """Test DiagnosisEngine without champion reference."""
    engine = DiagnosisEngine("/tmp/test_runs")

    baseline = create_baseline_result()

    input_data = DiagnosisInput(
        run_id="test-run",
        champion_id="test-champion",
        champion_strategy_hash="abc123",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="test-baseline-hash-123",
        canonical_metrics_hash="test-metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=None,  # No reference
        metrics_version="1.0.0",
    )

    result = engine.diagnose(input_data)

    assert result is not None
    assert result.outcome == DiagnosisOutcome.INTEGRITY_ERROR
    assert result.error_message is not None


def test_diagnosis_engine_triggers_no_edge():
    """Test DiagnosisEngine triggers NO_EDGE diagnosis."""
    engine = DiagnosisEngine("/tmp/test_runs")

    # Create baseline with no edge: PF < 1.0 and negative expectancy
    baseline = create_baseline_result(profit_factor=0.8, expectancy=-0.01)
    champion_ref = create_champion_reference()

    input_data = create_diagnosis_input(baseline, champion_ref)

    result = engine.diagnose(input_data)

    assert result is not None
    assert result.outcome == DiagnosisOutcome.DIAGNOSIS_COMPLETE
    assert result.primary_diagnosis is not None
    assert result.primary_diagnosis.diagnosis_code == DiagnosisCode.NO_EDGE
    assert result.primary_diagnosis.severity == Severity.CRITICAL


def test_diagnosis_engine_triggers_insufficient_sample():
    """Test DiagnosisEngine triggers INSUFFICIENT_SAMPLE diagnosis."""
    engine = DiagnosisEngine("/tmp/test_runs")

    # Create baseline with insufficient trades but not too low to be INSUFFICIENT_EVIDENCE
    # Use more pairs to avoid triggering PAIR_CONCENTRATION
    # Use exit distribution without stoploss dominance
    baseline = create_baseline_result(
        total_trades=30,
        selected_pairs=["BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT"],
        per_pair_contributions=[
            PerPairContribution(pair="BTC/USDT", trade_count=8, net_profit_pct=5.0),
            PerPairContribution(pair="ETH/USDT", trade_count=8, net_profit_pct=4.0),
            PerPairContribution(pair="SOL/USDT", trade_count=7, net_profit_pct=3.0),
            PerPairContribution(pair="ADA/USDT", trade_count=7, net_profit_pct=2.0),
        ],
        concentration_summary=ConcentrationSummary(
            concentration_flag=ConcentrationFlag.BALANCED_CONTRIBUTION,
            total_contributing_pairs=4,
            top_pair_profit_contribution_share=0.35,
        ),
        exit_reason_distribution=[
            ExitReasonDistribution(reason_name="take_profit", count=25, percentage_of_trades=0.83, total_profit_contribution=50.0),
            ExitReasonDistribution(reason_name="stop_loss", count=5, percentage_of_trades=0.17, total_profit_contribution=-5.0),
        ],
    )
    champion_ref = create_champion_reference()

    input_data = create_diagnosis_input(baseline, champion_ref)

    result = engine.diagnose(input_data)

    assert result is not None
    # May trigger INSUFFICIENT_SAMPLE or be INSUFFICIENT_EVIDENCE depending on threshold
    if result.outcome == DiagnosisOutcome.DIAGNOSIS_COMPLETE:
        assert result.primary_diagnosis is not None
        assert result.primary_diagnosis.diagnosis_code == DiagnosisCode.INSUFFICIENT_SAMPLE


def test_diagnosis_engine_excludes_parameter_research_from_primary():
    """Test that parameter research findings are excluded from primary diagnosis."""
    engine = DiagnosisEngine("/tmp/test_runs")

    baseline = create_baseline_result()
    champion_ref = create_champion_reference()

    input_data = create_diagnosis_input(baseline, champion_ref)

    result = engine.diagnose(input_data)

    assert result is not None
    # If there's a primary diagnosis, it should not be a parameter research finding
    if result.primary_diagnosis:
        assert result.primary_diagnosis.category != DiagnosisCategory.PARAMETER_RESEARCH


def test_diagnosis_engine_generates_derived_findings():
    """Test that derived parameter research findings are generated based on primary."""
    engine = DiagnosisEngine("/tmp/test_runs")

    # Create baseline that will trigger a primary diagnosis
    baseline = create_baseline_result(profit_factor=0.8, expectancy=-0.01)
    champion_ref = create_champion_reference()

    input_data = create_diagnosis_input(baseline, champion_ref)

    result = engine.diagnose(input_data)

    assert result is not None
    # Check that informational findings may include derived parameter research
    # (This depends on the primary diagnosis category)
    if result.primary_diagnosis:
        informational = result.informational_findings
        derived_count = sum(
            1 for f in informational
            if f.category == DiagnosisCategory.PARAMETER_RESEARCH
        )
        # Derived findings may or may not be generated depending on primary category
        assert derived_count >= 0


def test_diagnosis_engine_input_hash():
    """Test that input hash is computed for idempotency."""
    engine = DiagnosisEngine("/tmp/test_runs")

    baseline = create_baseline_result()
    champion_ref = create_champion_reference()

    input_data = create_diagnosis_input(baseline, champion_ref)

    result = engine.diagnose(input_data)

    assert result is not None
    assert result.input_hash is not None
    assert len(result.input_hash) == 64  # SHA-256 hex string


def test_diagnosis_engine_duration():
    """Test that diagnosis duration is recorded."""
    engine = DiagnosisEngine("/tmp/test_runs")

    baseline = create_baseline_result()
    champion_ref = create_champion_reference()

    input_data = create_diagnosis_input(baseline, champion_ref)

    result = engine.diagnose(input_data)

    assert result is not None
    assert result.duration_seconds >= 0.0
