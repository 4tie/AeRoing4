"""Tests for ResearchState — Milestone 4 §29."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.services.aeroing4.research.research_state import (
    ResearchState,
    ResearchStateIntegrityError,
    ResearchStateStore,
    ResearchStatus,
)


@pytest.fixture
def tmp_root():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def store(tmp_root):
    return ResearchStateStore(tmp_root)


class TestResearchStateCreation:
    def test_creates_with_null_champion(self, store):
        state = store.create("run-1")
        assert state.run_id == "run-1"
        assert state.current_champion_id is None
        assert state.current_champion_strategy_hash is None
        assert state.current_champion_parameter_hash is None

    def test_initial_status_is_not_started(self, store):
        state = store.create("run-1")
        assert state.research_status == ResearchStatus.NOT_STARTED

    def test_initial_budget_counters(self, store):
        state = store.create("run-1", max_total_experiments=7)
        assert state.total_experiments_reserved == 0
        assert state.total_experiments_completed == 0
        assert state.max_total_experiments == 7
        assert state.hypotheses_created == 0
        assert state.hypotheses_completed == 0

    def test_no_active_hypothesis_or_experiment(self, store):
        state = store.create("run-1")
        assert state.current_hypothesis_id is None
        assert state.active_experiment_id is None

    def test_timestamps_set(self, store):
        state = store.create("run-1")
        assert state.created_at is not None
        assert state.updated_at is not None


class TestResearchStatePersistenceReload:
    def test_persist_and_reload(self, store, tmp_root):
        state = store.create("run-42")
        state.current_hypothesis_id = "hyp-1"
        state.total_experiments_reserved = 2
        store.save(state)

        store2 = ResearchStateStore(tmp_root)
        loaded = store2.load("run-42")
        assert loaded is not None
        assert loaded.current_hypothesis_id == "hyp-1"
        assert loaded.total_experiments_reserved == 2

    def test_load_returns_none_if_not_found(self, store):
        assert store.load("nonexistent-run") is None

    def test_load_or_create_creates_if_absent(self, store):
        state = store.load_or_create("new-run")
        assert state.run_id == "new-run"
        assert state.research_status == ResearchStatus.NOT_STARTED

    def test_load_or_create_returns_existing(self, store, tmp_root):
        state = store.create("run-x")
        state.current_hypothesis_id = "hyp-99"
        store.save(state)

        store2 = ResearchStateStore(tmp_root)
        loaded = store2.load_or_create("run-x")
        assert loaded.current_hypothesis_id == "hyp-99"

    def test_active_experiment_id_round_trips(self, store, tmp_root):
        state = store.create("run-c")
        state.active_experiment_id = "exp-7"
        store.save(state)

        store2 = ResearchStateStore(tmp_root)
        loaded = store2.load("run-c")
        assert loaded.active_experiment_id == "exp-7"


class TestResearchStatusTransitions:
    def test_valid_transition_not_started_to_active(self, store):
        state = store.create("run-1")
        state.transition_status(ResearchStatus.ACTIVE)
        assert state.research_status == ResearchStatus.ACTIVE

    def test_valid_transition_active_to_exhausted(self, store):
        state = store.create("run-1")
        state.transition_status(ResearchStatus.ACTIVE)
        state.transition_status(ResearchStatus.EXHAUSTED)
        assert state.research_status == ResearchStatus.EXHAUSTED

    def test_valid_transition_active_to_completed(self, store):
        state = store.create("run-1")
        state.transition_status(ResearchStatus.ACTIVE)
        state.transition_status(ResearchStatus.COMPLETED)
        assert state.research_status == ResearchStatus.COMPLETED

    def test_invalid_transition_raises(self, store):
        state = store.create("run-1")
        state.transition_status(ResearchStatus.ACTIVE)
        state.transition_status(ResearchStatus.COMPLETED)
        with pytest.raises(ValueError, match="terminal"):
            state.transition_status(ResearchStatus.ACTIVE)

    def test_terminal_to_active_rejected(self, store):
        state = store.create("run-1")
        state.transition_status(ResearchStatus.ACTIVE)
        state.transition_status(ResearchStatus.FAILED)
        with pytest.raises(ValueError):
            state.transition_status(ResearchStatus.ACTIVE)


class TestResearchStateCorruption:
    def test_corrupted_file_raises_integrity_error(self, tmp_root):
        run_id = "corrupt-run"
        run_dir = tmp_root / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "research_state.json").write_text("not valid json!!!")

        store = ResearchStateStore(tmp_root)
        with pytest.raises(ResearchStateIntegrityError) as exc_info:
            store.load(run_id)
        assert exc_info.value.run_id == run_id

    def test_corrupted_file_never_returns_empty(self, tmp_root):
        run_id = "corrupt-run2"
        run_dir = tmp_root / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "research_state.json").write_text("{broken}")

        store = ResearchStateStore(tmp_root)
        with pytest.raises(ResearchStateIntegrityError):
            store.load(run_id)


class TestResearchStateBudgetCounters:
    def test_increment_experiments_reserved(self, store):
        state = store.create("run-1")
        state.total_experiments_reserved += 1
        store.save(state)
        loaded = store.load("run-1")
        assert loaded.total_experiments_reserved == 1

    def test_increment_hypotheses_created(self, store):
        state = store.create("run-1")
        state.hypotheses_created += 3
        store.save(state)
        loaded = store.load("run-1")
        assert loaded.hypotheses_created == 3

    def test_accessed_data_zones_tracked(self, store, tmp_root):
        state = store.create("run-1")
        state.accessed_data_zones.append("develop")
        store.save(state)
        store2 = ResearchStateStore(tmp_root)
        loaded = store2.load("run-1")
        assert "develop" in loaded.accessed_data_zones
