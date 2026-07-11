"""Tests for Diagnosis Store safety.

Tests for concurrency, atomic writes, and corruption handling.
"""

import pytest
import json
from pathlib import Path
from datetime import UTC, datetime
from backend.services.aeroing4.diagnosis.models import (
    DiagnosisResult,
    DiagnosisOutcome,
    EvidenceQuality,
)
from backend.services.aeroing4.diagnosis.persistence import DiagnosisStore
from backend.services.aeroing4.research.file_lock_registry import clear_registry


def create_test_diagnosis_result(diagnosis_id: str = "test-diagnosis-1") -> DiagnosisResult:
    """Create a test diagnosis result."""
    return DiagnosisResult(
        run_id="run-123",
        champion_id="champion-123",
        diagnosis_id=diagnosis_id,
        outcome=DiagnosisOutcome.DIAGNOSIS_COMPLETE,
        primary_diagnosis=None,
        secondary_findings=[],
        informational_findings=[],
        evidence_quality=EvidenceQuality.HIGH,
        unavailable_evidence=[],
        evaluated_rules=[],
        skipped_rules=[],
        skipped_reasons={},
        input_hash="test-hash-123",
    )


def test_save_and_load():
    """Test that save and load work correctly."""
    runs_root = Path("/tmp/test_diagnosis_store_save_load")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    store = DiagnosisStore(str(runs_root))
    result = create_test_diagnosis_result()
    
    # Save the result
    store.save(result)
    
    # Load the result
    loaded = store.load(result.diagnosis_id)
    
    assert loaded is not None
    assert loaded.diagnosis_id == result.diagnosis_id
    assert loaded.run_id == result.run_id
    assert loaded.champion_id == result.champion_id
    assert loaded.outcome == result.outcome
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)
    clear_registry()


def test_save_updates_existing():
    """Test that save updates an existing diagnosis."""
    runs_root = Path("/tmp/test_diagnosis_store_update")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    store = DiagnosisStore(str(runs_root))
    result = create_test_diagnosis_result()
    
    # Save the result
    store.save(result)
    
    # Update the result
    result.evidence_quality = EvidenceQuality.MEDIUM
    store.save(result)
    
    # Load the updated result
    loaded = store.load(result.diagnosis_id)
    
    assert loaded is not None
    assert loaded.evidence_quality == EvidenceQuality.MEDIUM
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)
    clear_registry()


def test_load_nonexistent_returns_none():
    """Test that loading a non-existent diagnosis returns None."""
    runs_root = Path("/tmp/test_diagnosis_store_nonexistent")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    store = DiagnosisStore(str(runs_root))
    
    # Try to load a non-existent diagnosis
    loaded = store.load("non-existent-id")
    
    assert loaded is None
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)
    clear_registry()


def test_list_by_run():
    """Test listing diagnoses by run ID."""
    runs_root = Path("/tmp/test_diagnosis_store_list_run")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    store = DiagnosisStore(str(runs_root))
    
    # Create diagnoses for two different runs
    result1 = create_test_diagnosis_result("diagnosis-1")
    result1.run_id = "run-1"
    
    result2 = create_test_diagnosis_result("diagnosis-2")
    result2.run_id = "run-1"
    
    result3 = create_test_diagnosis_result("diagnosis-3")
    result3.run_id = "run-2"
    
    # Save all
    store.save(result1)
    store.save(result2)
    store.save(result3)
    
    # List for run-1
    run1_diagnoses = store.list_by_run("run-1")
    assert len(run1_diagnoses) == 2
    assert all(d.run_id == "run-1" for d in run1_diagnoses)
    
    # List for run-2
    run2_diagnoses = store.list_by_run("run-2")
    assert len(run2_diagnoses) == 1
    assert run2_diagnoses[0].run_id == "run-2"
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)
    clear_registry()


def test_list_by_champion():
    """Test listing diagnoses by champion ID."""
    runs_root = Path("/tmp/test_diagnosis_store_list_champion")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    store = DiagnosisStore(str(runs_root))
    
    # Create diagnoses for two different champions
    result1 = create_test_diagnosis_result("diagnosis-1")
    result1.champion_id = "champion-1"
    
    result2 = create_test_diagnosis_result("diagnosis-2")
    result2.champion_id = "champion-1"
    
    result3 = create_test_diagnosis_result("diagnosis-3")
    result3.champion_id = "champion-2"
    
    # Save all
    store.save(result1)
    store.save(result2)
    store.save(result3)
    
    # List for champion-1
    champion1_diagnoses = store.list_by_champion("champion-1")
    assert len(champion1_diagnoses) == 2
    assert all(d.champion_id == "champion-1" for d in champion1_diagnoses)
    
    # List for champion-2
    champion2_diagnoses = store.list_by_champion("champion-2")
    assert len(champion2_diagnoses) == 1
    assert champion2_diagnoses[0].champion_id == "champion-2"
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)
    clear_registry()


def test_delete():
    """Test deleting a diagnosis."""
    runs_root = Path("/tmp/test_diagnosis_store_delete")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    store = DiagnosisStore(str(runs_root))
    result = create_test_diagnosis_result()
    
    # Save the result
    store.save(result)
    
    # Verify it exists
    loaded = store.load(result.diagnosis_id)
    assert loaded is not None
    
    # Delete it
    deleted = store.delete(result.diagnosis_id)
    assert deleted is True
    
    # Verify it's gone
    loaded = store.load(result.diagnosis_id)
    assert loaded is None
    
    # Try to delete again
    deleted = store.delete(result.diagnosis_id)
    assert deleted is False
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)
    clear_registry()


def test_atomic_write():
    """Test that writes are atomic (temp file + rename)."""
    runs_root = Path("/tmp/test_diagnosis_store_atomic")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    store = DiagnosisStore(str(runs_root))
    result = create_test_diagnosis_result()
    
    # Save the result
    store.save(result)
    
    # Verify the main file exists and temp file does not
    assert store.diagnoses_file.exists()
    assert not store.diagnoses_file.with_suffix(".tmp").exists()
    
    # Verify the file is valid JSON
    with open(store.diagnoses_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    assert result.diagnosis_id in data
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)
    clear_registry()


def test_corrupt_file_fails_closed():
    """Test that a corrupt file fails gracefully."""
    runs_root = Path("/tmp/test_diagnosis_store_corrupt")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    store = DiagnosisStore(str(runs_root))
    
    # Write corrupt JSON
    with open(store.diagnoses_file, "w", encoding="utf-8") as f:
        f.write("{ invalid json")
    
    # load_all should raise json.JSONDecodeError
    with pytest.raises(json.JSONDecodeError):
        store.load_all()
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)
    clear_registry()


def test_concurrent_saves():
    """Test that concurrent saves don't lose data."""
    import threading
    import time
    
    runs_root = Path("/tmp/test_diagnosis_store_concurrent")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    store = DiagnosisStore(str(runs_root))
    
    # Create multiple results
    results = [create_test_diagnosis_result(f"diagnosis-{i}") for i in range(10)]
    
    # Save them concurrently
    def save_result(result):
        store.save(result)
    
    threads = [threading.Thread(target=save_result, args=(r,)) for r in results]
    
    for t in threads:
        t.start()
    
    for t in threads:
        t.join()
    
    # Verify all results were saved
    all_diagnoses = store.load_all()
    assert len(all_diagnoses) == 10
    
    for result in results:
        assert result.diagnosis_id in all_diagnoses
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)
    clear_registry()


def test_history_remains_available():
    """Test that diagnosis history is preserved across saves."""
    runs_root = Path("/tmp/test_diagnosis_store_history")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    store = DiagnosisStore(str(runs_root))
    
    # Save multiple diagnoses for the same champion
    for i in range(5):
        result = create_test_diagnosis_result(f"diagnosis-{i}")
        result.champion_id = "champion-123"
        store.save(result)
    
    # List all diagnoses for the champion
    champion_diagnoses = store.list_by_champion("champion-123")
    assert len(champion_diagnoses) == 5
    
    # Verify all diagnosis IDs are present
    diagnosis_ids = {d.diagnosis_id for d in champion_diagnoses}
    for i in range(5):
        assert f"diagnosis-{i}" in diagnosis_ids
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)
    clear_registry()


def test_get_latest_for_run():
    """Test getting the latest diagnosis for a run."""
    runs_root = Path("/tmp/test_diagnosis_store_latest_run")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    store = DiagnosisStore(str(runs_root))
    
    # Create diagnoses with different timestamps
    result1 = create_test_diagnosis_result("diagnosis-1")
    result1.run_id = "run-123"
    result1.created_at = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    
    result2 = create_test_diagnosis_result("diagnosis-2")
    result2.run_id = "run-123"
    result2.created_at = datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC)
    
    result3 = create_test_diagnosis_result("diagnosis-3")
    result3.run_id = "run-123"
    result3.created_at = datetime(2024, 1, 3, 0, 0, 0, tzinfo=UTC)
    
    # Save all
    store.save(result1)
    store.save(result2)
    store.save(result3)
    
    # Get latest
    latest = store.get_latest_for_run("run-123")
    
    assert latest is not None
    assert latest.diagnosis_id == "diagnosis-3"
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)
    clear_registry()


def test_get_latest_for_champion():
    """Test getting the latest diagnosis for a champion."""
    runs_root = Path("/tmp/test_diagnosis_store_latest_champion")
    runs_root.mkdir(parents=True, exist_ok=True)
    
    store = DiagnosisStore(str(runs_root))
    
    # Create diagnoses with different timestamps
    result1 = create_test_diagnosis_result("diagnosis-1")
    result1.champion_id = "champion-123"
    result1.created_at = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    
    result2 = create_test_diagnosis_result("diagnosis-2")
    result2.champion_id = "champion-123"
    result2.created_at = datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC)
    
    result3 = create_test_diagnosis_result("diagnosis-3")
    result3.champion_id = "champion-123"
    result3.created_at = datetime(2024, 1, 3, 0, 0, 0, tzinfo=UTC)
    
    # Save all
    store.save(result1)
    store.save(result2)
    store.save(result3)
    
    # Get latest
    latest = store.get_latest_for_champion("champion-123")
    
    assert latest is not None
    assert latest.diagnosis_id == "diagnosis-3"
    
    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)
    clear_registry()
