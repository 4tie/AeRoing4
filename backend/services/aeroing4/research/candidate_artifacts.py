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
  leave the Python untouched. The copied sidecar must keep AeRoing4's internal
  tracking shape (`parameters.<target>.current`) synchronized with the
  Freqtrade runtime shape (`params.*`) that backtesting actually consumes.
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
            with cand_sidecar_path.open("w", encoding="utf-8") as f:
                json.dump({"parameters": {}}, f, indent=2)

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

        Only runtime-executable sidecar edits are supported in v1. The target
        key in AeRoing4's editable `parameters` block is set to after_value,
        and the corresponding Freqtrade `params.*` location is updated too.
        """
        target = change.target
        if not target:
            raise ValueError("ExactChange.target is required for sidecar mutation")
        try:
            data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"Cannot read candidate sidecar: {exc}") from exc

        CandidateArtifactService._apply_runtime_params_change(
            data, target=target, after_value=change.after_value
        )

        params = data.setdefault("parameters", {})
        block = params.get(target)
        if isinstance(block, dict):
            block["current"] = change.after_value
        else:
            params[target] = {
                "editable": True,
                "current": change.after_value,
            }

        with sidecar_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def _apply_runtime_params_change(data: dict, *, target: str, after_value) -> None:
        """Apply a mutation to the Freqtrade-consumed `params.*` location."""
        runtime = data.get("params")
        if not isinstance(runtime, dict):
            raise ValueError(
                f"Target {target!r} is not runtime-executable: sidecar has no params block"
            )

        if target.startswith("buy_"):
            CandidateArtifactService._set_runtime_group_value(
                runtime, "buy", target, after_value
            )
            return

        if target.startswith("sell_"):
            CandidateArtifactService._set_runtime_group_value(
                runtime, "sell", target, after_value
            )
            return

        if target == "stoploss":
            group = runtime.get("stoploss")
            if not isinstance(group, dict) or "stoploss" not in group:
                raise ValueError(
                    "Target 'stoploss' is not runtime-executable: "
                    "params.stoploss.stoploss is missing"
                )
            group["stoploss"] = after_value
            return

        if target in {"roi", "minimal_roi"}:
            if "roi" not in runtime:
                raise ValueError(
                    f"Target {target!r} is not runtime-executable: params.roi is missing"
                )
            if not isinstance(after_value, dict):
                raise ValueError("ROI mutation requires a dict after_value")
            runtime["roi"] = after_value
            return

        if target.startswith("trailing_"):
            CandidateArtifactService._set_runtime_group_value(
                runtime, "trailing", target, after_value
            )
            return

        raise ValueError(f"Target {target!r} is not runtime-executable")

    @staticmethod
    def _set_runtime_group_value(
        runtime: dict, group_name: str, target: str, after_value
    ) -> None:
        group = runtime.get(group_name)
        if not isinstance(group, dict) or target not in group:
            raise ValueError(
                f"Target {target!r} is not runtime-executable: "
                f"params.{group_name}.{target} is missing"
            )
        group[target] = after_value
