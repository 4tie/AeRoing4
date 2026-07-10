"""Protocol Integration tests — Milestone 4 §34."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.services.aeroing4.research.access_guard import DataZoneGuard
from backend.services.aeroing4.research.data_zones import RESEARCH_PROTOCOL_VERSION, ResearchZone
from backend.services.aeroing4.research.experiments import (
    ExperimentRecord,
    ExperimentStatus,
    ExperimentStore,
    OriginalStrategyProvenance,
)
from backend.services.aeroing4.research.identity import compute_experiment_identity_hash
from backend.services.aeroing4.research.ledger import AccessDecisionCode
from backend.services.aeroing4.research.stages import ResearchStage
from backend.services.aeroing4.state_store import AeRoing4StateStore


@pytest.fixture
def tmp_root():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def state_store(tmp_root):
    return AeRoing4StateStore(tmp_root)


@pytest.fixture
def guard(state_store, tmp_root):
    return DataZoneGuard(state_store, tmp_root)


@pytest.fixture
def run(state_store):
    return state_store.create_run(strategy_name="TestStrategy")


def _init_run_with_boundaries(guard, run):
    return guard.initialize_boundaries(
        run,
        develop_timerange="20240101-20240630",
        confirmation_timerange="20240705-20240831",
        final_unseen_timerange="20240901-20241231",
    )


class TestExperimentPlanningNoDataAccess:
    def test_planning_does_not_require_data_access(self, tmp_root):
        """An ExperimentRecord can be created without any protocol access."""
        identity = compute_experiment_identity_hash(
            original_strategy_provenance_hash="prov",
            strategy_hash_before="s", parameter_hash_before="p",
            proposed_change={"x": 1}, dataset_zone="develop",
            concrete_timerange="20240101-20240630",
            pair_set_hash="ps", configuration_hash="cfg", timeframe="5m",
        )
        exp = ExperimentRecord(
            run_id="run-plan", hypothesis_id="hyp-1",
            original_strategy_provenance=OriginalStrategyProvenance(logical_name="S"),
            experiment_identity_hash=identity,
        )
        store = ExperimentStore(tmp_root)
        saved, dup = store.reserve(exp)
        assert dup is None
        assert saved.status == ExperimentStatus.RESERVED
        assert saved.access_ledger_entry_id is None


class TestExecutionReadinessRequestsDevelop:
    def test_experiment_readiness_uses_develop_zone(self, guard, run, tmp_root):
        """Transitioning to READY should use DEVELOP zone access."""
        run = _init_run_with_boundaries(guard, run)
        decision, run = guard.request_access(
            run, ResearchStage.RESEARCH_EXPERIMENT, ResearchZone.DEVELOP,
            strategy_hash="strat-hash",
        )
        assert decision.allowed
        assert decision.decision_code == AccessDecisionCode.ALLOWED

    def test_access_ledger_entry_id_stored(self, guard, run, tmp_root):
        run = _init_run_with_boundaries(guard, run)
        decision, run = guard.request_access(
            run, ResearchStage.RESEARCH_EXPERIMENT, ResearchZone.DEVELOP,
        )
        assert decision.allowed

        identity = compute_experiment_identity_hash(
            original_strategy_provenance_hash="prov",
            strategy_hash_before="s", parameter_hash_before="p",
            proposed_change={"x": 1}, dataset_zone="develop",
            concrete_timerange="20240101-20240630",
            pair_set_hash="ps", configuration_hash="cfg", timeframe="5m",
        )
        exp = ExperimentRecord(
            run_id=run.run_id, hypothesis_id="hyp-1",
            original_strategy_provenance=OriginalStrategyProvenance(logical_name="S"),
            experiment_identity_hash=identity,
        )
        store = ExperimentStore(tmp_root)
        saved, _ = store.reserve(exp)

        # Simulate recording the ledger entry after DEVELOP access is granted
        entries = guard.ledger.load_entries(run.run_id)
        assert len(entries) >= 1
        ledger_entry_id = entries[-1].access_id
        updated = store.record_access_ledger_entry(
            run.run_id, saved.experiment_id, ledger_entry_id,
            concrete_timerange="20240101-20240630",
            protocol_version=RESEARCH_PROTOCOL_VERSION,
        )
        assert updated.access_ledger_entry_id == ledger_entry_id
        assert updated.concrete_timerange == "20240101-20240630"
        assert updated.protocol_version == RESEARCH_PROTOCOL_VERSION


class TestConfirmationAndFinalUnseenDenied:
    def test_research_experiment_denied_for_confirmation_zone(self, guard, run):
        run = _init_run_with_boundaries(guard, run)
        # Freeze via DEVELOP first
        guard.request_access(run, ResearchStage.RESEARCH_EXPERIMENT, ResearchZone.DEVELOP)
        run = guard.state_store.load_run(run.run_id)

        # RESEARCH_EXPERIMENT cannot access CONFIRMATION
        decision = guard.can_access(run, ResearchStage.RESEARCH_EXPERIMENT, ResearchZone.CONFIRMATION)
        assert not decision.allowed
        assert decision.decision_code == AccessDecisionCode.ZONE_NOT_ALLOWED_FOR_STAGE

    def test_research_experiment_denied_for_final_unseen_zone(self, guard, run):
        run = _init_run_with_boundaries(guard, run)
        decision = guard.can_access(run, ResearchStage.RESEARCH_EXPERIMENT, ResearchZone.FINAL_UNSEEN)
        assert not decision.allowed
        assert decision.decision_code == AccessDecisionCode.ZONE_NOT_ALLOWED_FOR_STAGE

    def test_stage_allowed_zones_confirms_develop_only(self):
        from backend.services.aeroing4.research.stages import STAGE_ALLOWED_ZONES
        zones = STAGE_ALLOWED_ZONES.get(ResearchStage.RESEARCH_EXPERIMENT, frozenset())
        assert ResearchZone.DEVELOP in zones
        assert ResearchZone.CONFIRMATION not in zones
        assert ResearchZone.FINAL_UNSEEN not in zones


class TestProtocolVersionAndTimerangePersistence:
    def test_protocol_version_stored_in_experiment(self, guard, run, tmp_root):
        run = _init_run_with_boundaries(guard, run)
        decision, run = guard.request_access(run, ResearchStage.RESEARCH_EXPERIMENT, ResearchZone.DEVELOP)
        entries = guard.ledger.load_entries(run.run_id)
        last_entry = entries[-1]
        assert last_entry.protocol_version == RESEARCH_PROTOCOL_VERSION

        identity = compute_experiment_identity_hash(
            original_strategy_provenance_hash="p", strategy_hash_before="s",
            parameter_hash_before="q", proposed_change={"x": 1},
            dataset_zone="develop", concrete_timerange="20240101-20240630",
            pair_set_hash="ps", configuration_hash="cfg", timeframe="5m",
        )
        exp = ExperimentRecord(
            run_id=run.run_id, hypothesis_id="hyp-1",
            original_strategy_provenance=OriginalStrategyProvenance(logical_name="S"),
            experiment_identity_hash=identity,
        )
        store = ExperimentStore(tmp_root)
        saved, _ = store.reserve(exp)
        store.record_access_ledger_entry(
            run.run_id, saved.experiment_id, last_entry.access_id,
            concrete_timerange="20240101-20240630",
            protocol_version=RESEARCH_PROTOCOL_VERSION,
        )
        loaded = store.get(run.run_id, saved.experiment_id)
        assert loaded.protocol_version == RESEARCH_PROTOCOL_VERSION

    def test_restart_preserves_protocol_association(self, guard, run, tmp_root):
        run = _init_run_with_boundaries(guard, run)
        guard.request_access(run, ResearchStage.RESEARCH_EXPERIMENT, ResearchZone.DEVELOP)

        identity = compute_experiment_identity_hash(
            original_strategy_provenance_hash="p", strategy_hash_before="s",
            parameter_hash_before="q", proposed_change={"x": 1},
            dataset_zone="develop", concrete_timerange="20240101-20240630",
            pair_set_hash="ps", configuration_hash="cfg", timeframe="5m",
        )
        exp = ExperimentRecord(
            run_id=run.run_id, hypothesis_id="hyp-1",
            original_strategy_provenance=OriginalStrategyProvenance(logical_name="S"),
            experiment_identity_hash=identity,
            access_ledger_entry_id="ledger-entry-1",
            protocol_version=RESEARCH_PROTOCOL_VERSION,
        )
        store = ExperimentStore(tmp_root)
        saved, _ = store.reserve(exp)

        store2 = ExperimentStore(tmp_root)
        loaded = store2.get(run.run_id, saved.experiment_id)
        assert loaded.access_ledger_entry_id == "ledger-entry-1"
        assert loaded.protocol_version == RESEARCH_PROTOCOL_VERSION
