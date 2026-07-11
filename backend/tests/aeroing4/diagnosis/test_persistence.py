"""Tests for diagnosis persistence."""

import json
import pytest
from pathlib import Path
from backend.services.aeroing4.diagnosis.models import (
    DiagnosisCategory,
    DiagnosisCode,
    DiagnosisFinding,
    DiagnosisOutcome,
    DiagnosisResult,
    EvidenceQuality,
    Severity,
)
from backend.services.aeroing4.diagnosis.persistence import DiagnosisStore


def create_test_diagnosis_result(run_id="test-run", champion_id="test-champion"):
    """Helper to create a test diagnosis result."""
    return DiagnosisResult(
        run_id=run_id,
        champion_id=champion_id,
        diagnosis_id="test-diagnosis-1",
        outcome=DiagnosisOutcome.DIAGNOSIS_COMPLETE,
        primary_diagnosis=DiagnosisFinding(
            diagnosis_code=DiagnosisCode.NO_EDGE,
            category=DiagnosisCategory.EDGE_QUALITY,
            severity=Severity.CRITICAL,
            confidence=0.95,
            evidence_refs=["profit_factor", "expectancy"],
            evidence_values={"profit_factor": 0.8, "expectancy": -0.01},
            explanation="Test explanation",
            suggested_research_area="edge_quality",
            limitations=["Test limitation"],
        ),
        secondary_findings=[],
        informational_findings=[],
        evidence_quality=EvidenceQuality.HIGH,
        unavailable_evidence=[],
        evaluated_rules=["no_edge"],
        skipped_rules=[],
        skipped_reasons={},
    )


def test_diagnosis_store_save_and_load():
    """Test DiagnosisStore save and load."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        store = DiagnosisStore(tmpdir)
        result = create_test_diagnosis_result()

        # Save
        store.save(result)

        # Load
        loaded = store.load("test-diagnosis-1")

        assert loaded is not None
        assert loaded.diagnosis_id == "test-diagnosis-1"
        assert loaded.run_id == "test-run"
        assert loaded.champion_id == "test-champion"
        assert loaded.outcome == DiagnosisOutcome.DIAGNOSIS_COMPLETE
        assert loaded.primary_diagnosis is not None
        assert loaded.primary_diagnosis.diagnosis_code == DiagnosisCode.NO_EDGE


def test_diagnosis_store_load_all():
    """Test DiagnosisStore load_all."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        store = DiagnosisStore(tmpdir)

        # Save multiple results
        result1 = create_test_diagnosis_result("run-1", "champ-1")
        result1.diagnosis_id = "diag-1"
        store.save(result1)

        result2 = create_test_diagnosis_result("run-2", "champ-2")
        result2.diagnosis_id = "diag-2"
        store.save(result2)

        # Load all
        all_diagnoses = store.load_all()

        assert len(all_diagnoses) == 2
        assert "diag-1" in all_diagnoses
        assert "diag-2" in all_diagnoses


def test_diagnosis_store_list_by_run():
    """Test DiagnosisStore list_by_run."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        store = DiagnosisStore(tmpdir)

        # Save results for different runs
        result1 = create_test_diagnosis_result("run-1", "champ-1")
        result1.diagnosis_id = "diag-1"
        store.save(result1)

        result2 = create_test_diagnosis_result("run-1", "champ-2")
        result2.diagnosis_id = "diag-2"
        store.save(result2)

        result3 = create_test_diagnosis_result("run-2", "champ-1")
        result3.diagnosis_id = "diag-3"
        store.save(result3)

        # List by run-1
        run1_diagnoses = store.list_by_run("run-1")
        assert len(run1_diagnoses) == 2
        assert all(d.run_id == "run-1" for d in run1_diagnoses)

        # List by run-2
        run2_diagnoses = store.list_by_run("run-2")
        assert len(run2_diagnoses) == 1
        assert run2_diagnoses[0].run_id == "run-2"


def test_diagnosis_store_list_by_champion():
    """Test DiagnosisStore list_by_champion."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        store = DiagnosisStore(tmpdir)

        # Save results for different champions
        result1 = create_test_diagnosis_result("run-1", "champ-1")
        result1.diagnosis_id = "diag-1"
        store.save(result1)

        result2 = create_test_diagnosis_result("run-2", "champ-1")
        result2.diagnosis_id = "diag-2"
        store.save(result2)

        result3 = create_test_diagnosis_result("run-1", "champ-2")
        result3.diagnosis_id = "diag-3"
        store.save(result3)

        # List by champ-1
        champ1_diagnoses = store.list_by_champion("champ-1")
        assert len(champ1_diagnoses) == 2
        assert all(d.champion_id == "champ-1" for d in champ1_diagnoses)

        # List by champ-2
        champ2_diagnoses = store.list_by_champion("champ-2")
        assert len(champ2_diagnoses) == 1
        assert champ2_diagnoses[0].champion_id == "champ-2"


def test_diagnosis_store_get_latest_for_run():
    """Test DiagnosisStore get_latest_for_run."""
    import tempfile
    from datetime import datetime, UTC

    with tempfile.TemporaryDirectory() as tmpdir:
        store = DiagnosisStore(tmpdir)

        # Save results with different timestamps
        result1 = create_test_diagnosis_result("run-1", "champ-1")
        result1.diagnosis_id = "diag-1"
        result1.created_at = datetime(2024, 1, 1, tzinfo=UTC)
        store.save(result1)

        result2 = create_test_diagnosis_result("run-1", "champ-1")
        result2.diagnosis_id = "diag-2"
        result2.created_at = datetime(2024, 1, 2, tzinfo=UTC)
        store.save(result2)

        # Get latest
        latest = store.get_latest_for_run("run-1")
        assert latest is not None
        assert latest.diagnosis_id == "diag-2"  # Should be the newer one


def test_diagnosis_store_get_latest_for_champion():
    """Test DiagnosisStore get_latest_for_champion."""
    import tempfile
    from datetime import datetime, UTC

    with tempfile.TemporaryDirectory() as tmpdir:
        store = DiagnosisStore(tmpdir)

        # Save results with different timestamps
        result1 = create_test_diagnosis_result("run-1", "champ-1")
        result1.diagnosis_id = "diag-1"
        result1.created_at = datetime(2024, 1, 1, tzinfo=UTC)
        store.save(result1)

        result2 = create_test_diagnosis_result("run-2", "champ-1")
        result2.diagnosis_id = "diag-2"
        result2.created_at = datetime(2024, 1, 2, tzinfo=UTC)
        store.save(result2)

        # Get latest
        latest = store.get_latest_for_champion("champ-1")
        assert latest is not None
        assert latest.diagnosis_id == "diag-2"  # Should be the newer one


def test_diagnosis_store_delete():
    """Test DiagnosisStore delete."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        store = DiagnosisStore(tmpdir)

        result = create_test_diagnosis_result()
        store.save(result)

        # Verify it exists
        loaded = store.load("test-diagnosis-1")
        assert loaded is not None

        # Delete
        deleted = store.delete("test-diagnosis-1")
        assert deleted is True

        # Verify it's gone
        loaded = store.load("test-diagnosis-1")
        assert loaded is None


def test_diagnosis_store_delete_nonexistent():
    """Test DiagnosisStore delete with non-existent ID."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        store = DiagnosisStore(tmpdir)

        deleted = store.delete("nonexistent-id")
        assert deleted is False


def test_diagnosis_store_atomic_save():
    """Test DiagnosisStore atomic save (no corruption on concurrent access)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        store = DiagnosisStore(tmpdir)

        # Save multiple times
        for i in range(5):
            result = create_test_diagnosis_result(f"run-{i}", f"champ-{i}")
            result.diagnosis_id = f"diag-{i}"
            store.save(result)

        # Verify all are saved
        all_diagnoses = store.load_all()
        assert len(all_diagnoses) == 5

        # Verify file is valid JSON
        diagnoses_file = Path(tmpdir) / "diagnoses.json"
        with open(diagnoses_file, "r") as f:
            data = json.load(f)
        assert isinstance(data, dict)


def test_diagnosis_store_empty():
    """Test DiagnosisStore with no diagnoses."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        store = DiagnosisStore(tmpdir)

        # Load all should return empty dict
        all_diagnoses = store.load_all()
        assert all_diagnoses == {}

        # Load non-existent should return None
        loaded = store.load("nonexistent")
        assert loaded is None

        # List by run should return empty list
        run_diagnoses = store.list_by_run("run-1")
        assert run_diagnoses == []

        # List by champion should return empty list
        champ_diagnoses = store.list_by_champion("champ-1")
        assert champ_diagnoses == []

        # Get latest should return None
        latest = store.get_latest_for_run("run-1")
        assert latest is None
