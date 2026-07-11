"""Hypothesis Registry — typed HypothesisRecord, status lifecycle, persistence.

Status lifecycle (validated transitions only):
  PROPOSED → APPROVED → ACTIVE → SUPPORTED
                                → REJECTED
                                → EXHAUSTED
  PROPOSED → REJECTED  (if never approved)

Invalid transitions raise HypothesisTransitionError (never silent).
REJECTED → ACTIVE requires a new HypothesisRecord, never history rewrite.
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


class HypothesisSource(str, Enum):
    """Origin of the hypothesis."""
    DETERMINISTIC_DIAGNOSIS = "deterministic_diagnosis"
    AI_PROPOSAL = "ai_proposal"
    USER = "user"


class HypothesisStatus(str, Enum):
    """Lifecycle state of a hypothesis."""
    PROPOSED = "proposed"
    APPROVED = "approved"
    ACTIVE = "active"
    SUPPORTED = "supported"
    REJECTED = "rejected"
    EXHAUSTED = "exhausted"


# Valid transitions
_HYPOTHESIS_TRANSITIONS: dict[HypothesisStatus, frozenset[HypothesisStatus]] = {
    HypothesisStatus.PROPOSED: frozenset({
        HypothesisStatus.APPROVED, HypothesisStatus.REJECTED
    }),
    HypothesisStatus.APPROVED: frozenset({
        HypothesisStatus.ACTIVE, HypothesisStatus.REJECTED
    }),
    HypothesisStatus.ACTIVE: frozenset({
        HypothesisStatus.SUPPORTED,
        HypothesisStatus.REJECTED,
        HypothesisStatus.EXHAUSTED,
    }),
    HypothesisStatus.SUPPORTED: frozenset(),   # terminal
    HypothesisStatus.REJECTED: frozenset(),    # terminal — new record required
    HypothesisStatus.EXHAUSTED: frozenset(),   # terminal
}


class HypothesisTransitionError(Exception):
    """Raised on an invalid hypothesis status transition."""
    def __init__(self, message: str, *, from_status: HypothesisStatus, to_status: HypothesisStatus):
        super().__init__(message)
        self.from_status = from_status
        self.to_status = to_status


class HypothesisEvidenceRef(BaseModel):
    """Typed evidence reference (e.g. 'baseline.metrics.profit_factor')."""
    ref_path: str          # dotted path, e.g. "baseline.metrics.profit_factor"
    source_result_id: Optional[str] = None   # backtest run ID or result ID
    description: Optional[str] = None


class HypothesisIntegrityError(Exception):
    """Raised when hypotheses.json exists but cannot be parsed."""
    def __init__(self, message: str, *, run_id: str, cause: Exception | None = None):
        super().__init__(message)
        self.run_id = run_id
        self.cause = cause


class HypothesisRecord(BaseModel):
    """Typed, persistent record of one hypothesis."""

    hypothesis_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str

    diagnosis_code: Optional[str] = None
    hypothesis_text: str
    evidence_refs: list[HypothesisEvidenceRef] = Field(default_factory=list)
    evidence_values: dict[str, object] = Field(default_factory=dict)

    proposed_change_type: Optional[str] = None
    target_scope: Optional[str] = None
    expected_effect: Optional[str] = None
    success_criteria: Optional[str] = None
    risks: Optional[str] = None
    confidence: Optional[float] = None   # 0.0 – 1.0

    source: HypothesisSource = HypothesisSource.USER
    status: HypothesisStatus = HypothesisStatus.PROPOSED

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    experiment_ids: list[str] = Field(default_factory=list)

    # Immutability guard: evidence is locked after activation
    _evidence_locked: bool = False  # not persisted; derived from status

    @property
    def evidence_locked(self) -> bool:
        return self.status in (
            HypothesisStatus.ACTIVE,
            HypothesisStatus.SUPPORTED,
            HypothesisStatus.REJECTED,
            HypothesisStatus.EXHAUSTED,
        )

    def transition_status(self, new_status: HypothesisStatus) -> None:
        """Validate and apply a status transition. Raises HypothesisTransitionError."""
        allowed = _HYPOTHESIS_TRANSITIONS.get(self.status, frozenset())
        if new_status not in allowed:
            raise HypothesisTransitionError(
                f"Invalid HypothesisStatus transition: {self.status.value} → "
                f"{new_status.value}. Allowed from {self.status.value}: "
                f"{sorted(s.value for s in allowed) or 'none (terminal)'}",
                from_status=self.status,
                to_status=new_status,
            )
        self.status = new_status
        self.updated_at = datetime.now(UTC)

    def add_evidence_ref(self, ref: HypothesisEvidenceRef) -> None:
        """Add an evidence reference. Raises if hypothesis is ACTIVE or later."""
        if self.evidence_locked:
            raise HypothesisTransitionError(
                f"Cannot mutate evidence of an {self.status.value} hypothesis; "
                "create a new hypothesis record instead",
                from_status=self.status,
                to_status=self.status,
            )
        self.evidence_refs.append(ref)
        self.updated_at = datetime.now(UTC)

    def associate_experiment(self, experiment_id: str) -> None:
        """Associate an experiment with this hypothesis."""
        if experiment_id not in self.experiment_ids:
            self.experiment_ids.append(experiment_id)
            self.updated_at = datetime.now(UTC)


class HypothesisStore:
    """Persistent store for HypothesisRecords, one file per run.

    File: user_data/aeroing4/runs/{run_id}/hypotheses.json
    Atomic writes + process-wide shared lock from file_lock_registry to ensure
    multi-instance write safety — mirrors AeRoing4StateStore pattern.
    Fail-closed: if file exists but is corrupt, raises HypothesisIntegrityError.
    History is append-preserving — old hypothesis records are never deleted.
    """

    def __init__(self, runs_root: Path):
        self.runs_root = runs_root

    def create(self, hypothesis: HypothesisRecord) -> HypothesisRecord:
        """Persist a new hypothesis record. Returns the saved record."""
        lock = get_lock_for_path(self._hypothesis_file(hypothesis.run_id))
        with lock:
            existing = self._load_locked(hypothesis.run_id)
            existing.append(hypothesis)
            self._save_locked(hypothesis.run_id, existing)
            return hypothesis

    def get(self, run_id: str, hypothesis_id: str) -> Optional[HypothesisRecord]:
        """Load a specific hypothesis by ID."""
        lock = get_lock_for_path(self._hypothesis_file(run_id))
        with lock:
            for h in self._load_locked(run_id):
                if h.hypothesis_id == hypothesis_id:
                    return h
            return None

    def list_for_run(self, run_id: str) -> list[HypothesisRecord]:
        """List all hypotheses for a run, in creation order."""
        lock = get_lock_for_path(self._hypothesis_file(run_id))
        with lock:
            return list(self._load_locked(run_id))

    def update(self, hypothesis: HypothesisRecord) -> HypothesisRecord:
        """Persist an updated hypothesis record (replaces by hypothesis_id)."""
        lock = get_lock_for_path(self._hypothesis_file(hypothesis.run_id))
        with lock:
            records = self._load_locked(hypothesis.run_id)
            updated = []
            found = False
            for h in records:
                if h.hypothesis_id == hypothesis.hypothesis_id:
                    updated.append(hypothesis)
                    found = True
                else:
                    updated.append(h)
            if not found:
                raise KeyError(
                    f"Hypothesis '{hypothesis.hypothesis_id}' not found in run '{hypothesis.run_id}'"
                )
            self._save_locked(hypothesis.run_id, updated)
            return hypothesis

    def transition_status(
        self, run_id: str, hypothesis_id: str, new_status: HypothesisStatus
    ) -> HypothesisRecord:
        """Atomically load, validate transition, persist, return updated record."""
        lock = get_lock_for_path(self._hypothesis_file(run_id))
        with lock:
            records = self._load_locked(run_id)
            target = None
            for h in records:
                if h.hypothesis_id == hypothesis_id:
                    target = h
                    break
            if target is None:
                raise KeyError(f"Hypothesis '{hypothesis_id}' not found in run '{run_id}'")
            target.transition_status(new_status)
            updated = [target if h.hypothesis_id == hypothesis_id else h for h in records]
            self._save_locked(run_id, updated)
            return target

    def associate_experiment(
        self, run_id: str, hypothesis_id: str, experiment_id: str
    ) -> HypothesisRecord:
        """Atomically associate an experiment with a hypothesis."""
        lock = get_lock_for_path(self._hypothesis_file(run_id))
        with lock:
            records = self._load_locked(run_id)
            target = None
            for h in records:
                if h.hypothesis_id == hypothesis_id:
                    target = h
                    break
            if target is None:
                raise KeyError(f"Hypothesis '{hypothesis_id}' not found in run '{run_id}'")
            target.associate_experiment(experiment_id)
            updated = [target if h.hypothesis_id == hypothesis_id else h for h in records]
            self._save_locked(run_id, updated)
            return target

    def experiment_count(self, run_id: str, hypothesis_id: str) -> int:
        """Return the number of experiments associated with this hypothesis."""
        h = self.get(run_id, hypothesis_id)
        return len(h.experiment_ids) if h else 0

    # ── Private helpers ───────────────────────────────────────────────────

    def _hypothesis_file(self, run_id: str) -> Path:
        return self.runs_root / run_id / "hypotheses.json"

    def _load_locked(self, run_id: str) -> list[HypothesisRecord]:
        f = self._hypothesis_file(run_id)
        if not f.exists():
            return []
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            return [HypothesisRecord.model_validate(item) for item in raw]
        except Exception as exc:
            raise HypothesisIntegrityError(
                f"hypotheses.json for run '{run_id}' exists but cannot be "
                f"read/parsed — fail-closed: {exc}",
                run_id=run_id,
                cause=exc,
            ) from exc

    def _save_locked(self, run_id: str, records: list[HypothesisRecord]) -> None:
        f = self._hypothesis_file(run_id)
        f.parent.mkdir(parents=True, exist_ok=True)
        payload = [json.loads(r.model_dump_json()) for r in records]
        # Unique temp name per attempt — mirrors ExperimentStore fix. Avoids
        # shared "hypotheses.tmp" contention and recovers from a vanished temp.
        max_retries = 10
        last_tmp = None
        for attempt in range(max_retries):
            tmp = f.with_name(f"{f.stem}.{uuid.uuid4().hex}.tmp")
            last_tmp = tmp
            try:
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, indent=2)
                    fh.flush()
                    os.fsync(fh.fileno())
                tmp.replace(f)
                return
            except PermissionError:
                if attempt == max_retries - 1:
                    raise
                import time

                time.sleep(0.05 * (attempt + 1))
            except FileNotFoundError:
                if attempt == max_retries - 1:
                    raise
                import time

                time.sleep(0.05 * (attempt + 1))
        if last_tmp is not None:
            last_tmp.unlink(missing_ok=True)
        raise HypothesisIntegrityError(
            f"hypotheses.json for run '{run_id}' could not be persisted after "
            f"{max_retries} attempts",
            run_id=run_id,
        )
