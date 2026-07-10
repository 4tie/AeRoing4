"""Tests for Hypothesis Registry — Milestone 4 §30."""

from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

import pytest

from backend.services.aeroing4.research.hypotheses import (
    HypothesisEvidenceRef,
    HypothesisIntegrityError,
    HypothesisRecord,
    HypothesisSource,
    HypothesisStatus,
    HypothesisStore,
    HypothesisTransitionError,
)
from backend.services.aeroing4.research.budgets import (
    BudgetService,
    DEFAULT_MAX_EXPERIMENTS_PER_HYPOTHESIS,
)


@pytest.fixture
def tmp_root():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def store(tmp_root):
    return HypothesisStore(tmp_root)


def _make_hypothesis(run_id: str = "run-1", text: str = "Test hypothesis") -> HypothesisRecord:
    return HypothesisRecord(run_id=run_id, hypothesis_text=text)


class TestHypothesisCreation:
    def test_create_returns_record_with_stable_id(self, store):
        h = _make_hypothesis()
        saved = store.create(h)
        assert saved.hypothesis_id == h.hypothesis_id
        assert len(saved.hypothesis_id) == 36  # UUID

    def test_initial_status_is_proposed(self, store):
        h = _make_hypothesis()
        saved = store.create(h)
        assert saved.status == HypothesisStatus.PROPOSED

    def test_source_preserved(self, store):
        h = _make_hypothesis()
        h.source = HypothesisSource.DETERMINISTIC_DIAGNOSIS
        saved = store.create(h)
        assert saved.source == HypothesisSource.DETERMINISTIC_DIAGNOSIS

    def test_evidence_refs_preserved(self, store):
        h = _make_hypothesis()
        h.evidence_refs = [
            HypothesisEvidenceRef(ref_path="baseline.metrics.profit_factor"),
            HypothesisEvidenceRef(ref_path="pair_discovery.pairs.ETH_USDT.total_trades"),
        ]
        saved = store.create(h)
        assert len(saved.evidence_refs) == 2
        assert saved.evidence_refs[0].ref_path == "baseline.metrics.profit_factor"

    def test_list_for_run_empty_initially(self, store):
        assert store.list_for_run("empty-run") == []


class TestHypothesisPersistenceReload:
    def test_persist_and_reload(self, store, tmp_root):
        h = _make_hypothesis("run-1", "My hypothesis")
        store.create(h)

        store2 = HypothesisStore(tmp_root)
        records = store2.list_for_run("run-1")
        assert len(records) == 1
        assert records[0].hypothesis_text == "My hypothesis"

    def test_get_by_id(self, store):
        h = _make_hypothesis()
        store.create(h)
        found = store.get("run-1", h.hypothesis_id)
        assert found is not None
        assert found.hypothesis_id == h.hypothesis_id

    def test_get_by_id_returns_none_if_not_found(self, store):
        assert store.get("run-1", "nonexistent-id") is None

    def test_multiple_hypotheses_preserved(self, store, tmp_root):
        store.create(_make_hypothesis("run-1", "H1"))
        store.create(_make_hypothesis("run-1", "H2"))
        store2 = HypothesisStore(tmp_root)
        records = store2.list_for_run("run-1")
        assert len(records) == 2


class TestHypothesisStatusTransitions:
    def test_valid_proposed_to_approved(self, store):
        h = _make_hypothesis()
        store.create(h)
        updated = store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.APPROVED)
        assert updated.status == HypothesisStatus.APPROVED

    def test_valid_approved_to_active(self, store):
        h = _make_hypothesis()
        store.create(h)
        store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.APPROVED)
        updated = store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.ACTIVE)
        assert updated.status == HypothesisStatus.ACTIVE

    def test_valid_active_to_supported(self, store):
        h = _make_hypothesis()
        store.create(h)
        store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.APPROVED)
        store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.ACTIVE)
        updated = store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.SUPPORTED)
        assert updated.status == HypothesisStatus.SUPPORTED

    def test_valid_active_to_rejected(self, store):
        h = _make_hypothesis()
        store.create(h)
        store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.APPROVED)
        store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.ACTIVE)
        updated = store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.REJECTED)
        assert updated.status == HypothesisStatus.REJECTED

    def test_valid_active_to_exhausted(self, store):
        h = _make_hypothesis()
        store.create(h)
        store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.APPROVED)
        store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.ACTIVE)
        updated = store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.EXHAUSTED)
        assert updated.status == HypothesisStatus.EXHAUSTED

    def test_invalid_supported_to_active_raises(self, store):
        h = _make_hypothesis()
        store.create(h)
        store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.APPROVED)
        store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.ACTIVE)
        store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.SUPPORTED)
        with pytest.raises(HypothesisTransitionError):
            store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.ACTIVE)

    def test_invalid_rejected_to_active_raises(self, store):
        """REJECTED → ACTIVE must fail; a new HypothesisRecord is required instead."""
        h = _make_hypothesis()
        store.create(h)
        store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.APPROVED)
        store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.ACTIVE)
        store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.REJECTED)
        with pytest.raises(HypothesisTransitionError):
            store.transition_status("run-1", h.hypothesis_id, HypothesisStatus.ACTIVE)

    def test_transition_not_found_raises(self, store):
        with pytest.raises(KeyError):
            store.transition_status("run-1", "no-such-id", HypothesisStatus.APPROVED)


class TestHypothesisEvidenceImmutability:
    def test_evidence_mutable_before_activation(self):
        h = _make_hypothesis()
        ref = HypothesisEvidenceRef(ref_path="baseline.metrics.profit_factor")
        h.add_evidence_ref(ref)
        assert len(h.evidence_refs) == 1

    def test_evidence_locked_after_active(self):
        h = _make_hypothesis()
        h.transition_status(HypothesisStatus.APPROVED)
        h.transition_status(HypothesisStatus.ACTIVE)
        with pytest.raises(HypothesisTransitionError):
            h.add_evidence_ref(HypothesisEvidenceRef(ref_path="new.ref"))

    def test_evidence_locked_after_supported(self):
        h = _make_hypothesis()
        h.transition_status(HypothesisStatus.APPROVED)
        h.transition_status(HypothesisStatus.ACTIVE)
        h.transition_status(HypothesisStatus.SUPPORTED)
        with pytest.raises(HypothesisTransitionError):
            h.add_evidence_ref(HypothesisEvidenceRef(ref_path="new.ref"))


class TestHypothesisExperimentAssociation:
    def test_associate_experiment(self, store):
        h = _make_hypothesis()
        store.create(h)
        updated = store.associate_experiment("run-1", h.hypothesis_id, "exp-1")
        assert "exp-1" in updated.experiment_ids

    def test_associate_experiment_idempotent(self, store):
        h = _make_hypothesis()
        store.create(h)
        store.associate_experiment("run-1", h.hypothesis_id, "exp-1")
        store.associate_experiment("run-1", h.hypothesis_id, "exp-1")
        h2 = store.get("run-1", h.hypothesis_id)
        assert h2.experiment_ids.count("exp-1") == 1

    def test_experiment_count(self, store):
        h = _make_hypothesis()
        store.create(h)
        store.associate_experiment("run-1", h.hypothesis_id, "exp-1")
        store.associate_experiment("run-1", h.hypothesis_id, "exp-2")
        assert store.experiment_count("run-1", h.hypothesis_id) == 2

    def test_per_hypothesis_budget_exhaustion(self, store):
        """Verify budget is properly tracked via experiment count."""
        h = _make_hypothesis()
        store.create(h)
        budget = BudgetService()
        for i in range(DEFAULT_MAX_EXPERIMENTS_PER_HYPOTHESIS):
            store.associate_experiment("run-1", h.hypothesis_id, f"exp-{i}")

        count = store.experiment_count("run-1", h.hypothesis_id)
        decision = budget.can_reserve(
            total_reserved=count,
            hypothesis_experiment_count=count,
        )
        assert not decision.allowed


class TestHypothesisCorruption:
    def test_corrupted_file_raises_integrity_error(self, tmp_root):
        run_id = "corrupt-run"
        run_dir = tmp_root / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "hypotheses.json").write_text("not valid json!!!")
        store = HypothesisStore(tmp_root)
        with pytest.raises(HypothesisIntegrityError) as exc_info:
            store.list_for_run(run_id)
        assert exc_info.value.run_id == run_id


class TestHypothesisSimultaneousCreation:
    @pytest.mark.skipif(sys.platform == "win32", reason="Concurrent file writes have platform-specific issues on Windows")
    def test_simultaneous_creation_safety(self, tmp_root):
        """Concurrent hypothesis creation must not lose records."""
        store = HypothesisStore(tmp_root)
        n = 20
        errors = []

        def create_one(i: int):
            try:
                store.create(_make_hypothesis("run-concurrent", f"Hypothesis {i}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_one, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors: {errors}"
        records = store.list_for_run("run-concurrent")
        assert len(records) == n
