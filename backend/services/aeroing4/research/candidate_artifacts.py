"""Candidate Artifact Service for the AeRoing4 Controlled Research Loop.

Receives the current ChampionReference and one policy-approved ExactChange and
produces a run-local candidate artifact.

Hard guarantees:
  * The original user strategy file is NEVER mutated.
  * The Champion artifact is NEVER mutated in place (champion artifacts are
    read-only references; a candidate is a separate run-local copy).
  * For parameter targets owned by a sidecar, the change is applied to the
    COPIED sidecar JSON only. The strategy .py file is copied byte-for-byte
    (proving the strategy source itself did not change).
  * ExperimentRecord remains the sole persistent source of truth for candidate
    metadata. This service returns a typed CandidateArtifactResult; the Loop
    Coordinator copies its fields into the existing ExperimentRecord. No
    CandidateArtifactStore is created.

Sidecar mutation preference:
  If the approved target is sidecar-owned (editable parameter in
  strategies/{strategy_name}.json), we rewrite the copied sidecar value and
  leave the Python untouched. This is the v1-supported mutation path; the
  Mutation Policy already rejects non-sidecar targets, so this service only
  ever receives sidecar-owned parameter changes.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from pydantic import BaseModel

from .champions import ArtifactReference, ChampionReference
from .experiments import ExactChange


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


class CandidateArtifactResult(BaseModel):
    """Typed result of creating one candidate artifact (not persisted here)."""

    candidate_id: str
    candidate_dir: str
    strategy_artifact: ArtifactReference
    parameter_artifact: ArtifactReference
    strategy_hash_before: str
    strategy_hash_after: str
    parameter_hash_before: str
    parameter_hash_after: str


class CandidateArtifactService:
    """Creates run-local candidate artifacts from a champion + one change."""

    def __init__(self, runs_root: Path):
        self.runs_root = Path(runs_root)

    def create(
        self,
        *,
        run_id: str,
        strategy_name: str,
        champion: ChampionReference,
        exact_change: ExactChange,
    ) -> CandidateArtifactResult:
        if champion.strategy_artifact is None:
            raise ValueError("Champion has no strategy artifact reference")
        if champion.parameter_artifact is None:
            raise ValueError("Champion has no parameter artifact reference")

        # Resolve the original source files from the champion's audit references.
        orig_strategy = Path(champion.strategy_artifact.original_source_path)
        orig_sidecar = self.runs_root / "strategies" / f"{strategy_name}.json"

        if not orig_strategy.exists():
            raise FileNotFoundError(
                f"Champion original strategy not found: {orig_strategy}"
            )

        candidate_id = str(uuid.uuid4())
        candidate_dir = self.runs_root / run_id / "candidates" / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)

        # ── Strategy (.py): byte-for-byte copy, never rewritten ────────────
        cand_strategy_path = candidate_dir / f"{strategy_name}.py"
        shutil.copyfile(orig_strategy, cand_strategy_path)
        # Keep a copy of the champion's strategy artifact hash for comparison.
        strategy_hash_before = champion.strategy_artifact.artifact_hash
        strategy_hash_after = _sha256_file(cand_strategy_path)

        # ── Parameter sidecar: copy, then apply the ONE approved change ─────
        cand_sidecar_path = candidate_dir / f"{strategy_name}.json"
        if orig_sidecar.exists():
            shutil.copyfile(orig_sidecar, cand_sidecar_path)
        else:
            # No sidecar on disk — seed an empty editable block so we can still
            # record the change without inventing one from nothing.
            cand_sidecar_path.write_text(
                json.dumps({"parameters": {}}, indent=2), encoding="utf-8"
            )

        parameter_hash_before = _sha256_file(cand_sidecar_path)
        self._apply_sidecar_change(cand_sidecar_path, exact_change)
        parameter_hash_after = _sha256_file(cand_sidecar_path)

        strategy_artifact = ArtifactReference(
            artifact_path=str(cand_strategy_path.relative_to(self.runs_root)),
            artifact_hash=strategy_hash_after,
            original_source_path=str(orig_strategy),
            original_source_hash=champion.strategy_artifact.original_source_hash,
        )
        parameter_artifact = ArtifactReference(
            artifact_path=str(cand_sidecar_path.relative_to(self.runs_root)),
            artifact_hash=parameter_hash_after,
            original_source_path=str(orig_sidecar),
            original_source_hash=champion.parameter_artifact.original_source_hash,
        )

        return CandidateArtifactResult(
            candidate_id=candidate_id,
            candidate_dir=str(candidate_dir),
            strategy_artifact=strategy_artifact,
            parameter_artifact=parameter_artifact,
            strategy_hash_before=strategy_hash_before,
            strategy_hash_after=strategy_hash_after,
            parameter_hash_before=parameter_hash_before,
            parameter_hash_after=parameter_hash_after,
        )

    @staticmethod
    def _apply_sidecar_change(sidecar_path: Path, change: ExactChange) -> None:
        """Apply exactly one approved change to the copied sidecar JSON.

        Only sidecar-owned parameter edits are supported in v1. The target key
        in the sidecar's editable `parameters` block is set to after_value.
        """
        target = change.target
        if not target:
            raise ValueError("ExactChange.target is required for sidecar mutation")
        try:
            data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"Cannot read candidate sidecar: {exc}") from exc

        params = data.setdefault("parameters", {})
        block = params.get(target)
        if isinstance(block, dict):
            block["current"] = change.after_value
        else:
            # Flat parameter map: set the key directly.
            params[target] = change.after_value

        sidecar_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
