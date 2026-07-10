"""Restart and Resume tests — Milestone 4 §33."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.services.aeroing4.research.experiments import (
    ExperimentRecord,
    ExperimentStatus,
    ExperimentStore,
    OriginalStrategyProvenance,
)
from backend.services.aeroing4.research.budgets import BudgetService
from backend.services.aeroing4.research.hypotheses import HypothesisRecord, HypothesisStore
from backend.services.aeroing4.research.identity import compute_experiment_identity_hash
from backend.services.aeroing4.research.research_state import ResearchState, ResearchStateStore


def _make_exp(run_id: str, suffix: str = "a") -> ExperimentRecord:
    identity = compute_experiment_identity_hash(
        original_strategy_provenance_hash=f"prov{suffix}",
        strategy_hash_before=f"s{suffix}", parameter_hash_before=f"p{suffix}",
        proposed_change={"s": suffix}, dataset_zone="develop",
        concrete_timerange="20240101-20240630", pair_set_hash="ps",
        configuration_hash="cfg", timeframe="5m",
    )
    return ExperimentRecord(
        run_id=run_id, hypothesis_id="hyp-1",
        original_strategy_provenance=OriginalStrategyProvenance(logical_name="S"),
        experiment_identity_hash=identity,
    )


@pytest.fixture
def tmp_root():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


class TestScenarioA:
    """RESERVED experiment survives reload without duplicate creation."""

    def test_reserved_survives_reload(self, tmp_root):
        store = ExperimentStore(tmp_root)
        exp = _make_exp("run-a")
        saved, _ = store.reserve(exp)
        assert saved.status == ExperimentStatus.RESERVED

        store2 = ExperimentStore(tmp_root)
        records = store2.list_for_run("run-a")
        assert len(records) == 1
        assert records[0].status == ExperimentStatus.RESERVED

    def test_reserved_blocks_duplicate_creation(self, tmp_root):
        store = ExperimentStore(tmp_root)
        exp = _make_exp("run-a")
        store.reserve(exp)

        # Same identity → duplicate
        store2 = ExperimentStore(tmp_root)
        exp2 = _make_exp("run-a")
        _, dup = store2.reserve(exp2)
        assert dup is not None
        assert dup.existing_experiment_id == exp.experiment_id


class TestScenarioB:
    """RUNNING experiment becomes reconcilable on reload; duplicate is blocked."""

    def test_running_becomes_interrupted_on_reconcile(self, tmp_root):
        store = ExperimentStore(tmp_root)
        exp = _make_exp("run-b")
        saved, _ = store.reserve(exp)
        store.transition_status("run-b", saved.experiment_id, ExperimentStatus.READY)
        store.transition_status("run-b", saved.experiment_id, ExperimentStatus.RUNNING)

        store2 = ExperimentStore(tmp_root)
        changed = store2.reconcile_interrupted_experiments("run-b")
        assert len(changed) == 1
        assert changed[0].status == ExperimentStatus.INTERRUPTED

    def test_interrupted_experiment_blocks_new_experiment(self, tmp_root):
        store = ExperimentStore(tmp_root)
        exp = _make_exp("run-b")
        saved, _ = store.reserve(exp)
        store.transition_status("run-b", saved.experiment_id, ExperimentStatus.READY)
        store.transition_status("run-b", saved.experiment_id, ExperimentStatus.RUNNING)
        store.reconcile_interrupted_experiments("run-b")

        report = store.resume_safety_report("run-b")
        # INTERRUPTED is now considered in-flight and resumable
        assert report.has_active_experiment
        assert report.must_reconcile_first
        assert not report.new_experiment_allowed
        assert report.active_experiment_status == ExperimentStatus.INTERRUPTED
        assert report.is_resumable  # INTERRUPTED can be reconciled

    def test_running_experiment_requires_reconciliation_before_duplicate(self, tmp_root):
        store = ExperimentStore(tmp_root)
        exp = _make_exp("run-b")
        saved, _ = store.reserve(exp)
        store.transition_status("run-b", saved.experiment_id, ExperimentStatus.READY)
        store.transition_status("run-b", saved.experiment_id, ExperimentStatus.RUNNING)

        # Even with a different identity, new experiment blocked by running status
        report = store.resume_safety_report("run-b")
        assert report.must_reconcile_first
        assert not report.new_experiment_allowed


class TestScenarioC:
    """active_experiment_id round-trips through ResearchStateStore."""

    def test_active_experiment_id_round_trips(self, tmp_root):
        state_store = ResearchStateStore(tmp_root)
        state = state_store.create("run-c")
        state.active_experiment_id = "exp-xyz"
        state_store.save(state)

        state_store2 = ResearchStateStore(tmp_root)
        loaded = state_store2.load("run-c")
        assert loaded.active_experiment_id == "exp-xyz"


class TestScenarioD:
    """Hypothesis budget partial consumption round-trips."""

    def test_hypothesis_budget_partial_consumption_survives_reload(self, tmp_root):
        hyp_store = HypothesisStore(tmp_root)
        h = HypothesisRecord(run_id="run-d", hypothesis_text="H1")
        hyp_store.create(h)
        hyp_store.associate_experiment("run-d", h.hypothesis_id, "exp-1")
        hyp_store.associate_experiment("run-d", h.hypothesis_id, "exp-2")

        hyp_store2 = HypothesisStore(tmp_root)
        count = hyp_store2.experiment_count("run-d", h.hypothesis_id)
        assert count == 2

        budget = BudgetService(max_experiments_per_hypothesis=3)
        remaining = budget.remaining_for_hypothesis(hypothesis_experiment_count=count)
        assert remaining == 1
