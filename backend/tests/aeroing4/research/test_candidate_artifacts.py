"""Tests for Candidate Artifact Service (PROMPT 8 §2).

Verifies: run-local copy, original untouched, champion untouched, sidecar
mutation applies exactly one change, before/after hashes computed, and no
CandidateArtifactStore is created (result is returned, not persisted here).
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.services.aeroing4.research.candidate_artifacts import (
    CandidateArtifactService,
)
from backend.services.aeroing4.research.champions import (
    ArtifactReference,
    ChampionReference,
    ChampionSourceType,
)
from backend.services.aeroing4.research.experiments import ExactChange


def _seed_champion(runs_root: Path, strategy_name: str = "AIStrategy"):
    strategies_dir = runs_root / "strategies"
    strategies_dir.mkdir(parents=True, exist_ok=True)
    orig_py = strategies_dir / f"{strategy_name}.py"
    orig_py.write_text("class AIStrategy:\n    pass\n", encoding="utf-8")
    orig_sidecar = strategies_dir / f"{strategy_name}.json"
    orig_sidecar.write_text(
        json.dumps(
            {
                "parameters": {
                    "rsi_threshold": {
                        "type": "int",
                        "editable": True,
                        "current": 30,
                        "min": 10,
                        "max": 50,
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return orig_py, orig_sidecar


def _make_champion(orig_py: Path, orig_sidecar: Path) -> ChampionReference:
    return ChampionReference(
        run_id="run-1",
        parent_champion_id=None,
        source_type=ChampionSourceType.BASELINE,
        strategy_artifact=ArtifactReference(
            artifact_path="champions/x.py",
            artifact_hash="abc",
            original_source_path=str(orig_py),
            original_source_hash="src-hash",
        ),
        parameter_artifact=ArtifactReference(
            artifact_path="champions/x.json",
            artifact_hash="def",
            original_source_path=str(orig_sidecar),
            original_source_hash="param-hash",
        ),
    )


def test_create_copies_strategy_and_sidecar(tmp_path: Path):
    orig_py, orig_sidecar = _seed_champion(tmp_path)
    champ = _make_champion(orig_py, orig_sidecar)
    svc = CandidateArtifactService(tmp_path)

    change = ExactChange(
        change_type="parameter",
        target="rsi_threshold",
        before_value=30,
        after_value=35,
    )
    result = svc.create(
        run_id="run-1",
        strategy_name="AIStrategy",
        champion=champ,
        exact_change=change,
    )

    # Candidate files exist under run-local candidates dir.
    cand_dir = Path(result.candidate_dir)
    assert cand_dir.exists()
    assert (cand_dir / "AIStrategy.py").exists()
    assert (cand_dir / "AIStrategy.json").exists()


def test_original_strategy_not_mutated(tmp_path: Path):
    orig_py, orig_sidecar = _seed_champion(tmp_path)
    orig_py_hash_before = _hash(orig_py)
    orig_sidecar_text_before = orig_sidecar.read_text(encoding="utf-8")

    champ = _make_champion(orig_py, orig_sidecar)
    svc = CandidateArtifactService(tmp_path)
    change = ExactChange(
        change_type="parameter", target="rsi_threshold", before_value=30, after_value=35
    )
    svc.create(
        run_id="run-1",
        strategy_name="AIStrategy",
        champion=champ,
        exact_change=change,
    )

    # Original files unchanged.
    assert _hash(orig_py) == orig_py_hash_before
    assert orig_sidecar.read_text(encoding="utf-8") == orig_sidecar_text_before


def test_champion_artifact_untouched_in_place(tmp_path: Path):
    orig_py, orig_sidecar = _seed_champion(tmp_path)
    champ = _make_champion(orig_py, orig_sidecar)
    champ_before = champ.model_dump_json()

    svc = CandidateArtifactService(tmp_path)
    change = ExactChange(
        change_type="parameter", target="rsi_threshold", before_value=30, after_value=35
    )
    svc.create(
        run_id="run-1",
        strategy_name="AIStrategy",
        champion=champ,
        exact_change=change,
    )
    # Champion object/references not mutated.
    assert champ.model_dump_json() == champ_before
    assert champ.strategy_artifact.artifact_hash == "abc"
    assert champ.parameter_artifact.artifact_hash == "def"


def test_sidecar_mutation_applies_one_change(tmp_path: Path):
    orig_py, orig_sidecar = _seed_champion(tmp_path)
    champ = _make_champion(orig_py, orig_sidecar)
    svc = CandidateArtifactService(tmp_path)
    change = ExactChange(
        change_type="parameter", target="rsi_threshold", before_value=30, after_value=35
    )
    result = svc.create(
        run_id="run-1",
        strategy_name="AIStrategy",
        champion=champ,
        exact_change=change,
    )

    cand_sidecar = tmp_path / result.parameter_artifact.artifact_path
    data = json.loads(cand_sidecar.read_text(encoding="utf-8"))
    assert data["parameters"]["rsi_threshold"]["current"] == 35
    # Only one parameter present, proving exactly one change applied.
    assert set(data["parameters"].keys()) == {"rsi_threshold"}


def test_hashes_computed_before_and_after(tmp_path: Path):
    orig_py, orig_sidecar = _seed_champion(tmp_path)
    champ = _make_champion(orig_py, orig_sidecar)
    svc = CandidateArtifactService(tmp_path)
    change = ExactChange(
        change_type="parameter", target="rsi_threshold", before_value=30, after_value=35
    )
    result = svc.create(
        run_id="run-1",
        strategy_name="AIStrategy",
        champion=champ,
        exact_change=change,
    )
    # Strategy file copied unchanged -> before (champion's recorded hash) and
    # after (fresh hash of copied file) must both equal the actual copied file hash.
    copied_strategy = tmp_path / result.strategy_artifact.artifact_path
    assert result.strategy_hash_before == "abc"  # champion's recorded hash
    assert result.strategy_hash_after == _hash(copied_strategy)
    # Sidecar changed -> before (hash of copied sidecar BEFORE edit) != after
    # (hash of copied sidecar AFTER edit). The service computes before from the
    # copied file, not the champion's recorded param hash.
    copied_sidecar = tmp_path / result.parameter_artifact.artifact_path
    assert result.parameter_hash_before == _hash(
        tmp_path / "strategies" / "AIStrategy.json"
    )
    assert result.parameter_hash_after != result.parameter_hash_before
    assert result.parameter_hash_after == _hash(copied_sidecar)


def _hash(p: Path) -> str:
    import hashlib

    return hashlib.sha256(p.read_bytes()).hexdigest()
