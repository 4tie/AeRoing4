"""Champion Lineage — typed ChampionReference, promotion contract, persistence.

Champion tracking:
- ResearchState.current_champion_id starts null (no fake baseline champion).
- Promotion requires: experiment terminal + evaluated, artifact hashes present,
  parent relationship valid, canonical metrics present when required.
- No arbitrary champion replacement without lineage.
- Original user strategy file is NEVER mutated — champions reference
  run-local artifact copies only.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .file_lock_registry import get_lock_for_path

from ..metrics.models import CanonicalMetricsSnapshot


class ChampionSourceType(str, Enum):
    """How a champion was established."""
    BASELINE = "baseline"
    RESEARCH_EXPERIMENT = "research_experiment"
    HYPEROPT = "hyperopt"


class ArtifactReference(BaseModel):
    """Reference to a run-local artifact (strategy or parameter file copy)."""
    artifact_path: str            # relative path within the run directory
    artifact_hash: str            # SHA-256 of the artifact content
    original_source_path: str     # the user's original file path (for audit; never mutated)
    original_source_hash: str     # hash of original at time of capture (immutable reference)


class ChampionReference(BaseModel):
    """Typed record of one champion in the lineage."""

    champion_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    parent_champion_id: Optional[str] = None   # null for the first baseline champion

    source_type: ChampionSourceType
    source_experiment_id: Optional[str] = None  # set when source_type == RESEARCH_EXPERIMENT

    # Artifact references (run-local copies, never the source strategy file)
    strategy_artifact: Optional[ArtifactReference] = None
    parameter_artifact: Optional[ArtifactReference] = None

    # Canonical metrics snapshot (if available)
    metrics: Optional[CanonicalMetricsSnapshot] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChampionPromotionError(Exception):
    """Raised when champion promotion validation fails."""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ChampionIntegrityError(Exception):
    """Raised when champions.json exists but cannot be parsed."""
    def __init__(self, message: str, *, run_id: str, cause: Exception | None = None):
        super().__init__(message)
        self.run_id = run_id
        self.cause = cause


class ChampionStore:
    """Persistent champion lineage store.

    File: user_data/aeroing4/runs/{run_id}/champions.json
    Atomic writes + process-wide shared lock from file_lock_registry to ensure
    multi-instance write safety.
    Append-preserving — complete lineage is never deleted.
    """

    def __init__(self, runs_root: Path):
        self.runs_root = runs_root

    def register(self, champion: ChampionReference) -> ChampionReference:
        """Persist a new champion reference. Returns the saved record."""
        lock = get_lock_for_path(self._champion_file(champion.run_id))
        with lock:
            records = self._load_locked(champion.run_id)
            records.append(champion)
            self._save_locked(champion.run_id, records)
            return champion

    def get(self, run_id: str, champion_id: str) -> Optional[ChampionReference]:
        """Load a specific champion by ID."""
        lock = get_lock_for_path(self._champion_file(run_id))
        with lock:
            for c in self._load_locked(run_id):
                if c.champion_id == champion_id:
                    return c
            return None

    def list_for_run(self, run_id: str) -> list[ChampionReference]:
        """List all champions for a run in creation order."""
        lock = get_lock_for_path(self._champion_file(run_id))
        with lock:
            return list(self._load_locked(run_id))

    def validate_promotion(
        self,
        *,
        run_id: str,
        candidate: ChampionReference,
        current_champion_id: Optional[str],
        require_metrics: bool = True,
    ) -> None:
        """Validate that a champion can be promoted.

        Raises ChampionPromotionError on any violation.
        """
        # Candidate must have strategy artifact hashes
        if candidate.strategy_artifact is None:
            raise ChampionPromotionError(
                "Promotion requires a strategy artifact reference (run-local copy)"
            )
        if not candidate.strategy_artifact.artifact_hash:
            raise ChampionPromotionError(
                "Promotion requires a non-empty strategy artifact hash"
            )

        # Parameter hash must exist
        if candidate.parameter_artifact is None:
            raise ChampionPromotionError(
                "Promotion requires a parameter artifact reference"
            )
        if not candidate.parameter_artifact.artifact_hash:
            raise ChampionPromotionError(
                "Promotion requires a non-empty parameter artifact hash"
            )

        # Canonical metrics required when caller opts in
        if require_metrics and candidate.metrics is None:
            raise ChampionPromotionError(
                "Promotion requires a canonical metrics snapshot"
            )

        # Parent lineage validation
        if current_champion_id is None:
            # No current champion — only BASELINE source allowed (or first champion)
            if candidate.parent_champion_id is not None:
                raise ChampionPromotionError(
                    f"Cannot promote a candidate with parent_champion_id="
                    f"'{candidate.parent_champion_id}' when there is no current champion"
                )
        else:
            # Must reference the current champion as parent
            if candidate.parent_champion_id != current_champion_id:
                raise ChampionPromotionError(
                    f"Candidate parent_champion_id='{candidate.parent_champion_id}' "
                    f"does not match current champion '{current_champion_id}'. "
                    "Champion replacement requires valid lineage."
                )

    def promote(
        self,
        *,
        run_id: str,
        candidate: ChampionReference,
        current_champion_id: Optional[str],
        require_metrics: bool = True,
    ) -> ChampionReference:
        """Validate and register a new champion. Returns the saved record.

        Raises ChampionPromotionError if validation fails.
        No arbitrary champion replacement without valid lineage.
        """
        self.validate_promotion(
            run_id=run_id,
            candidate=candidate,
            current_champion_id=current_champion_id,
            require_metrics=require_metrics,
        )
        return self.register(candidate)

    # ── Private helpers ───────────────────────────────────────────────────

    def _champion_file(self, run_id: str) -> Path:
        return self.runs_root / run_id / "champions.json"

    def _load_locked(self, run_id: str) -> list[ChampionReference]:
        f = self._champion_file(run_id)
        if not f.exists():
            return []
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            return [ChampionReference.model_validate(item) for item in raw]
        except Exception as exc:
            raise ChampionIntegrityError(
                f"champions.json for run '{run_id}' exists but cannot be "
                f"read/parsed — fail-closed: {exc}",
                run_id=run_id,
                cause=exc,
            ) from exc

    def _save_locked(self, run_id: str, records: list[ChampionReference]) -> None:
        f = self._champion_file(run_id)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        payload = [json.loads(r.model_dump_json()) for r in records]
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            # Retry replace on Windows to handle transient file locking
            max_retries = 10
            for attempt in range(max_retries):
                try:
                    tmp.replace(f)
                    break
                except PermissionError:
                    if attempt == max_retries - 1:
                        raise
                    import time
                    time.sleep(0.05 * (attempt + 1))  # Linear backoff
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
