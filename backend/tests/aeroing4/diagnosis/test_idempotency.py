"""Tests for diagnosis idempotency.

Tests that identical inputs reuse existing diagnosis results,
and that changed inputs create new diagnoses.
"""

import pytest
from pathlib import Path
from datetime import UTC, datetime
from backend.services.aeroing4.diagnosis.models import (
    DiagnosisInput,
    DiagnosisResult,
    DiagnosisOutcome,
    DiagnosisCode,
    DiagnosisCategory,
    Severity,
    EvidenceQuality,
)
from backend.services.aeroing4.diagnosis.engine import DiagnosisEngine
from backend.services.aeroing4.diagnosis.persistence import DiagnosisStore
from backend.services.aeroing4.portfolio_baseline.models import (
    PortfolioBaselineResult,
    PortfolioBaselineOutcome,
)
from backend.services.aeroing4.research.champions import ChampionReference, ArtifactReference, ChampionSourceType


def create_test_baseline_result(input_hash: str = "test-hash-123") -> PortfolioBaselineResult:
    """Create a test portfolio baseline result."""
    # Create minimal canonical metrics in proper format
    canonical_metrics = {
        "total_trades": {"value": 100, "timestamp": "2024-01-01T00:00:00Z", "availability": "available"},
        "winning_trades": {"value": 60, "timestamp": "2024-01-01T00:00:00Z", "availability": "available"},
        "losing_trades": {"value": 40, "timestamp": "2024-01-01T00:00:00Z", "availability": "available"},
        "net_profit_abs": {"value": 1000.0, "timestamp": "2024-01-01T00:00:00Z", "availability": "available"},
        "net_profit_pct": {"value": 10.0, "timestamp": "2024-01-01T00:00:00Z", "availability": "available"},
        "win_rate": {"value": 0.6, "timestamp": "2024-01-01T00:00:00Z", "availability": "available"},
        "profit_factor": {"value": 1.5, "timestamp": "2024-01-01T00:00:00Z", "availability": "available"},
        "expectancy": {"value": 0.01, "timestamp": "2024-01-01T00:00:00Z", "availability": "available"},
        "sharpe": {"value": 1.0, "timestamp": "2024-01-01T00:00:00Z", "availability": "available"},
        "sortino": {"value": 1.2, "timestamp": "2024-01-01T00:00:00Z", "availability": "available"},
        "calmar": {"value": 0.8, "timestamp": "2024-01-01T00:00:00Z", "availability": "available"},
        "max_drawdown_abs": {"value": -500.0, "timestamp": "2024-01-01T00:00:00Z", "availability": "available"},
        "max_drawdown_pct": {"value": -0.1, "timestamp": "2024-01-01T00:00:00Z", "availability": "available"},
        "average_trade_duration_minutes": {"value": 120.0, "timestamp": "2024-01-01T00:00:00Z", "availability": "available"},
        "bootstrap_sharpe_p5": {"value": 0.9, "timestamp": "2024-01-01T00:00:00Z", "availability": "available"},
        "provenance": {
            "source_type": "parsed_summary",
            "metrics_version": "1.0.0",
            "calculation_timestamp": "2024-01-01T00:00:00Z",
        },
    }
    
    return PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT", "ETH/USDT"],
        strategy_name="test_strategy",
        strategy_hash="abc123",
        parameter_hash="def456",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        input_hash=input_hash,
        canonical_metrics=canonical_metrics,
    )


def create_test_champion_reference(strategy_hash: str = "abc123", parameter_hash: str = "def456") -> ChampionReference:
    """Create a test champion reference."""
    return ChampionReference(
        champion_id="champion-123",
        run_id="run-123",
        source_type=ChampionSourceType.BASELINE,
        strategy_artifact=ArtifactReference(
            artifact_path="/path/to/strategy.py",
            artifact_hash=strategy_hash,
            original_source_path="/original/strategy.py",
            original_source_hash=strategy_hash,
        ),
        parameter_artifact=ArtifactReference(
            artifact_path="/path/to/parameters.json",
            artifact_hash=parameter_hash,
            original_source_path="/original/parameters.json",
            original_source_hash=parameter_hash,
        ),
    )


def test_identical_input_reuses_diagnosis():
    """Test that identical input returns same diagnosis record."""
    runs_root = Path("/tmp/test_diagnosis_idempotency")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    # Create engine and store
    engine = DiagnosisEngine(str(runs_root))
    store = DiagnosisStore(str(runs_root))
    
    # Create baseline result
    baseline = create_test_baseline_result()
    
    # Create champion reference
    champion_ref = create_test_champion_reference()
    
    # Create diagnosis input
    input_data = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="1.0.0",
    )
    
    # Run diagnosis first time
    result1 = engine.diagnose(input_data)
    
    # Save the result
    store.save(result1)
    
    # Run diagnosis again with identical input
    result2 = engine.diagnose(input_data)
    
    # Should return the same diagnosis
    assert result2.diagnosis_id == result1.diagnosis_id
    assert result2.input_hash == result1.input_hash
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)


def test_input_hash_changes_with_baseline_input_hash():
    """Test that input hash changes when baseline input hash changes."""
    runs_root = Path("/tmp/test_diagnosis_hash_baseline")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    engine = DiagnosisEngine(str(runs_root))
    
    baseline = create_test_baseline_result()
    champion_ref = create_test_champion_reference()
    
    # Input with baseline hash A
    input1 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-A",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="1.0.0",
    )
    
    hash1 = engine._compute_input_hash(input1)
    
    # Input with baseline hash B
    input2 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-B",  # Changed
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="1.0.0",
    )
    
    hash2 = engine._compute_input_hash(input2)
    
    # Hashes should be different
    assert hash1 != hash2
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)


def test_input_hash_changes_with_metrics_version():
    """Test that input hash changes when metrics version changes."""
    runs_root = Path("/tmp/test_diagnosis_hash_metrics_version")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    engine = DiagnosisEngine(str(runs_root))
    
    baseline = create_test_baseline_result()
    champion_ref = create_test_champion_reference()
    
    # Input with metrics version 1.0.0
    input1 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="1.0.0",
    )
    
    hash1 = engine._compute_input_hash(input1)
    
    # Input with metrics version 2.0.0
    input2 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="2.0.0",  # Changed
    )
    
    hash2 = engine._compute_input_hash(input2)
    
    # Hashes should be different
    assert hash1 != hash2
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)


def test_input_hash_changes_with_strategy_hash():
    """Test that input hash changes when strategy hash changes."""
    runs_root = Path("/tmp/test_diagnosis_hash_strategy")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    engine = DiagnosisEngine(str(runs_root))
    
    baseline = create_test_baseline_result()
    champion_ref = create_test_champion_reference()
    
    # Input with strategy hash A
    input1 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="strategy-hash-A",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="1.0.0",
    )
    
    hash1 = engine._compute_input_hash(input1)
    
    # Input with strategy hash B
    input2 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="strategy-hash-B",  # Changed
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="1.0.0",
    )
    
    hash2 = engine._compute_input_hash(input2)
    
    # Hashes should be different
    assert hash1 != hash2
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)


def test_input_hash_changes_with_parameter_hash():
    """Test that input hash changes when parameter hash changes."""
    runs_root = Path("/tmp/test_diagnosis_hash_parameter")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    engine = DiagnosisEngine(str(runs_root))
    
    baseline = create_test_baseline_result()
    champion_ref = create_test_champion_reference()
    
    # Input with parameter hash A
    input1 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="param-hash-A",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="1.0.0",
    )
    
    hash1 = engine._compute_input_hash(input1)
    
    # Input with parameter hash B
    input2 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="param-hash-B",  # Changed
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="1.0.0",
    )
    
    hash2 = engine._compute_input_hash(input2)
    
    # Hashes should be different
    assert hash1 != hash2
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)


def test_input_hash_changes_with_canonical_metrics_hash():
    """Test that input hash changes when canonical metrics hash changes."""
    runs_root = Path("/tmp/test_diagnosis_hash_metrics")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    engine = DiagnosisEngine(str(runs_root))
    
    baseline = create_test_baseline_result()
    champion_ref = create_test_champion_reference()
    
    # Input with metrics hash A
    input1 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-A",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="1.0.0",
    )
    
    hash1 = engine._compute_input_hash(input1)
    
    # Input with metrics hash B
    input2 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-B",  # Changed
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="1.0.0",
    )
    
    hash2 = engine._compute_input_hash(input2)
    
    # Hashes should be different
    assert hash1 != hash2
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)


def test_changed_baseline_evidence_creates_new_diagnosis():
    """Test that same champion with changed baseline evidence produces new diagnosis."""
    runs_root = Path("/tmp/test_diagnosis_baseline_change")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    engine = DiagnosisEngine(str(runs_root))
    store = DiagnosisStore(str(runs_root))
    
    champion_ref = create_test_champion_reference()
    
    # First diagnosis with baseline hash A
    baseline1 = create_test_baseline_result(input_hash="baseline-hash-A")
    input1 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline1,
        baseline_input_hash="baseline-hash-A",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="1.0.0",
    )
    
    result1 = engine.diagnose(input1)
    store.save(result1)
    
    # Second diagnosis with baseline hash B (changed evidence)
    baseline2 = create_test_baseline_result(input_hash="baseline-hash-B")
    input2 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-456",
        baseline_result=baseline2,
        baseline_input_hash="baseline-hash-B",  # Changed
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="1.0.0",
    )
    
    result2 = engine.diagnose(input2)
    
    # Should create new diagnosis
    assert result2.diagnosis_id != result1.diagnosis_id
    assert result2.input_hash != result1.input_hash
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)


def test_changed_metrics_version_invalidates_reuse():
    """Test that changed metrics version invalidates reuse."""
    runs_root = Path("/tmp/test_diagnosis_metrics_version")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    engine = DiagnosisEngine(str(runs_root))
    store = DiagnosisStore(str(runs_root))
    
    baseline = create_test_baseline_result()
    champion_ref = create_test_champion_reference()
    
    # First diagnosis with metrics version 1.0.0
    input1 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="1.0.0",
    )
    
    result1 = engine.diagnose(input1)
    store.save(result1)
    
    # Second diagnosis with metrics version 2.0.0
    input2 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="2.0.0",  # Changed
    )
    
    result2 = engine.diagnose(input2)
    
    # Should create new diagnosis
    assert result2.diagnosis_id != result1.diagnosis_id
    assert result2.input_hash != result1.input_hash
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)


def test_changed_strategy_hash_creates_new_diagnosis():
    """Test that changed strategy hash produces new diagnosis."""
    runs_root = Path("/tmp/test_diagnosis_strategy_hash")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    engine = DiagnosisEngine(str(runs_root))
    store = DiagnosisStore(str(runs_root))
    
    baseline = create_test_baseline_result()
    
    # First diagnosis with strategy hash A
    champion_ref1 = create_test_champion_reference(strategy_hash="strategy-hash-A")
    input1 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="strategy-hash-A",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref1,
        metrics_version="1.0.0",
    )
    
    result1 = engine.diagnose(input1)
    store.save(result1)
    
    # Second diagnosis with strategy hash B
    champion_ref2 = create_test_champion_reference(strategy_hash="strategy-hash-B")
    input2 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="strategy-hash-B",  # Changed
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref2,
        metrics_version="1.0.0",
    )
    
    result2 = engine.diagnose(input2)
    
    # Should create new diagnosis
    assert result2.diagnosis_id != result1.diagnosis_id
    assert result2.input_hash != result1.input_hash
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)


def test_changed_parameter_hash_creates_new_diagnosis():
    """Test that changed parameter hash produces new diagnosis."""
    runs_root = Path("/tmp/test_diagnosis_parameter_hash")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    engine = DiagnosisEngine(str(runs_root))
    store = DiagnosisStore(str(runs_root))
    
    baseline = create_test_baseline_result()
    
    # First diagnosis with parameter hash A
    champion_ref1 = create_test_champion_reference(parameter_hash="param-hash-A")
    input1 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="param-hash-A",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref1,
        metrics_version="1.0.0",
    )
    
    result1 = engine.diagnose(input1)
    store.save(result1)
    
    # Second diagnosis with parameter hash B
    champion_ref2 = create_test_champion_reference(parameter_hash="param-hash-B")
    input2 = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="param-hash-B",  # Changed
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref2,
        metrics_version="1.0.0",
    )
    
    result2 = engine.diagnose(input2)
    
    # Should create new diagnosis
    assert result2.diagnosis_id != result1.diagnosis_id
    assert result2.input_hash != result1.input_hash
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)


def test_restart_reload_finds_reusable_diagnosis():
    """Test that restart/reload still finds reusable diagnosis."""
    runs_root = Path("/tmp/test_diagnosis_reload")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    # First engine instance
    engine1 = DiagnosisEngine(str(runs_root))
    store1 = DiagnosisStore(str(runs_root))
    
    baseline = create_test_baseline_result()
    champion_ref = create_test_champion_reference()
    
    input_data = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="1.0.0",
    )
    
    result1 = engine1.diagnose(input_data)
    store1.save(result1)
    
    # Simulate restart: create new engine and store instances
    engine2 = DiagnosisEngine(str(runs_root))
    store2 = DiagnosisStore(str(runs_root))
    
    # Run diagnosis with same input on new instance
    result2 = engine2.diagnose(input_data)
    
    # Should find and reuse the existing diagnosis
    assert result2.diagnosis_id == result1.diagnosis_id
    assert result2.input_hash == result1.input_hash
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)


def test_input_hash_includes_all_identity_fields():
    """Test that input hash includes all required identity fields."""
    runs_root = Path("/tmp/test_diagnosis_hash_fields")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    engine = DiagnosisEngine(str(runs_root))
    
    baseline = create_test_baseline_result()
    champion_ref = create_test_champion_reference()
    
    input_data = DiagnosisInput(
        run_id="run-123",
        champion_id="champion-123",
        champion_strategy_hash="abc123",
        champion_parameter_hash="def456",
        baseline_result_id="baseline-123",
        baseline_result=baseline,
        baseline_input_hash="baseline-hash-123",
        canonical_metrics_hash="metrics-hash-123",
        timeframe="5m",
        develop_timerange="20240101-20240630",
        champion_reference=champion_ref,
        metrics_version="1.0.0",
    )
    
    input_hash = engine._compute_input_hash(input_data)
    
    # Hash should be deterministic
    input_hash2 = engine._compute_input_hash(input_data)
    assert input_hash == input_hash2
    
    # Hash should be non-empty
    assert len(input_hash) == 64  # SHA-256 hex length
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)
