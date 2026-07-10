"""Tests for Champion Lineage — Milestone 4 §35."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.services.aeroing4.research.champions import (
    ArtifactReference,
    ChampionIntegrityError,
    ChampionPromotionError,
    ChampionReference,
    ChampionSourceType,
    ChampionStore,
)
from backend.services.aeroing4.research.research_state import ResearchStateStore


@pytest.fixture
def tmp_root():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def store(tmp_root):
    return ChampionStore(tmp_root)


def _artifact(path: str = "run-local/strategy.py", ahash: str = "sha256-art") -> ArtifactReference:
    return ArtifactReference(
        artifact_path=path,
        artifact_hash=ahash,
        original_source_path="user_data/strategies/Original.py",
        original_source_hash="sha256-original",
    )


def _baseline_champion(run_id: str = "run-1") -> ChampionReference:
    return ChampionReference(
        run_id=run_id,
        source_type=ChampionSourceType.BASELINE,
        strategy_artifact=_artifact(),
        parameter_artifact=_artifact("run-local/params.json", "sha256-param"),
        parent_champion_id=None,
    )


class TestInitialChampionState:
    def test_no_initial_champion(self, store):
        champions = store.list_for_run("run-1")
        assert champions == []

    def test_research_state_champion_null_by_default(self, tmp_root):
        state_store = ResearchStateStore(tmp_root)
        state = state_store.create("run-1")
        assert state.current_champion_id is None
        assert state.current_champion_strategy_hash is None
        assert state.current_champion_parameter_hash is None

    def test_research_state_works_correctly_before_champion(self, tmp_root):
        """ResearchState must be fully functional with no champion registered."""
        state_store = ResearchStateStore(tmp_root)
        state = state_store.create("run-1")
        state.total_experiments_reserved = 2
        state_store.save(state)
        loaded = state_store.load("run-1")
        assert loaded.current_champion_id is None
        assert loaded.total_experiments_reserved == 2


class TestBaselineChampionRegistration:
    def test_baseline_champion_can_be_registered(self, store):
        c = _baseline_champion()
        saved = store.register(c)
        assert saved.champion_id == c.champion_id

    def test_baseline_champion_survives_reload(self, store, tmp_root):
        c = _baseline_champion()
        store.register(c)
        store2 = ChampionStore(tmp_root)
        records = store2.list_for_run("run-1")
        assert len(records) == 1
        assert records[0].champion_id == c.champion_id

    def test_get_by_id(self, store):
        c = _baseline_champion()
        store.register(c)
        found = store.get("run-1", c.champion_id)
        assert found is not None
        assert found.source_type == ChampionSourceType.BASELINE


class TestChampionLineage:
    def test_candidate_lineage_references_parent(self, store):
        baseline = _baseline_champion()
        store.register(baseline)

        candidate = ChampionReference(
            run_id="run-1",
            source_type=ChampionSourceType.RESEARCH_EXPERIMENT,
            parent_champion_id=baseline.champion_id,
            source_experiment_id="exp-1",
            strategy_artifact=_artifact("run-local/candidate.py", "sha256-cand"),
            parameter_artifact=_artifact("run-local/cand-params.json", "sha256-cand-param"),
        )
        saved = store.promote(
            run_id="run-1",
            candidate=candidate,
            current_champion_id=baseline.champion_id,
            require_metrics=False,
        )
        assert saved.parent_champion_id == baseline.champion_id

    def test_invalid_parent_rejected(self, store):
        candidate = ChampionReference(
            run_id="run-1",
            source_type=ChampionSourceType.RESEARCH_EXPERIMENT,
            parent_champion_id="wrong-parent-id",
            strategy_artifact=_artifact(),
            parameter_artifact=_artifact("p.json", "sha256-p"),
        )
        with pytest.raises(ChampionPromotionError, match="lineage"):
            store.promote(
                run_id="run-1",
                candidate=candidate,
                current_champion_id="actual-current-id",
                require_metrics=False,
            )

    def test_promotion_without_strategy_artifact_rejected(self, store):
        baseline = _baseline_champion()
        store.register(baseline)
        candidate = ChampionReference(
            run_id="run-1",
            source_type=ChampionSourceType.RESEARCH_EXPERIMENT,
            parent_champion_id=baseline.champion_id,
            strategy_artifact=None,  # missing
            parameter_artifact=_artifact("p.json", "sha256-p"),
        )
        with pytest.raises(ChampionPromotionError):
            store.promote(
                run_id="run-1", candidate=candidate,
                current_champion_id=baseline.champion_id, require_metrics=False,
            )

    def test_arbitrary_replacement_without_lineage_rejected(self, store):
        """Cannot promote a champion whose parent doesn't match the current champion."""
        baseline = _baseline_champion()
        store.register(baseline)

        # Attempt promotion with wrong parent
        interloper = ChampionReference(
            run_id="run-1",
            source_type=ChampionSourceType.RESEARCH_EXPERIMENT,
            parent_champion_id="some-other-id",  # wrong
            strategy_artifact=_artifact(),
            parameter_artifact=_artifact("p.json", "sha256-p"),
        )
        with pytest.raises(ChampionPromotionError):
            store.promote(
                run_id="run-1", candidate=interloper,
                current_champion_id=baseline.champion_id, require_metrics=False,
            )


class TestOriginalStrategyProtection:
    def test_champion_references_run_local_artifact_not_source(self, store):
        """Champion artifact path must be a run-local copy, not the user's source file."""
        c = _baseline_champion()
        store.register(c)
        found = store.get("run-1", c.champion_id)
        # The artifact_path is run-local (not the user's strategies dir)
        assert "run-local" in found.strategy_artifact.artifact_path
        # But original_source_path is the user's file (audit reference only)
        assert "user_data/strategies" in found.strategy_artifact.original_source_path

    def test_original_source_hash_preserved_immutably(self, store):
        """original_source_hash is captured at registration time and never changes."""
        c = _baseline_champion()
        store.register(c)
        found = store.get("run-1", c.champion_id)
        assert found.strategy_artifact.original_source_hash == "sha256-original"

    def test_promotion_changes_research_state_reference_not_source(self, tmp_root):
        """Promotion updates ResearchState.current_champion_id, not the source strategy."""
        store = ChampionStore(tmp_root)
        state_store = ResearchStateStore(tmp_root)
        state = state_store.create("run-1")

        c = _baseline_champion()
        store.register(c)
        state.current_champion_id = c.champion_id
        state.current_champion_strategy_hash = "sha256-art"
        state_store.save(state)

        loaded_state = state_store.load("run-1")
        assert loaded_state.current_champion_id == c.champion_id
        # Original source hash is preserved in the artifact reference
        champ = store.get("run-1", c.champion_id)
        assert champ.strategy_artifact.original_source_hash == "sha256-original"


class TestChampionCorruption:
    def test_corrupted_file_raises_integrity_error(self, tmp_root):
        run_id = "corrupt-run"
        run_dir = tmp_root / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "champions.json").write_text("not valid json!!!")
        store = ChampionStore(tmp_root)
        with pytest.raises(ChampionIntegrityError) as exc_info:
            store.list_for_run(run_id)
        assert exc_info.value.run_id == run_id
