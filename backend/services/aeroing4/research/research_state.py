"""Typed Research State for AeRoing4 — Milestone 4.

This is the SEPARATE ResearchState described in Prompt 4, distinct from:
- AeRoing4Run (workflow state: execution location, step status)
- ResearchProtocolState (protocol state: data access rules, boundary freeze)

ResearchState owns: research knowledge, budgets, active hypothesis,
experiment memory, and champion lineage — persisted as a sibling file
user_data/aeroing4/runs/{run_id}/research_state.json.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .errors import LedgerIntegrityError
from .file_lock_registry import get_lock_for_path


class ResearchStatus(str, Enum):
    """Overall research-loop status for a run."""

    NOT_STARTED = "not_started"
    READY = "ready"
    ACTIVE = "active"
    PAUSED = "paused"
    EXHAUSTED = "exhausted"
    COMPLETED = "completed"
    FAILED = "failed"


# Valid research status transitions
_RESEARCH_STATUS_TRANSITIONS: dict[ResearchStatus, frozenset[ResearchStatus]] = {
    ResearchStatus.NOT_STARTED: frozenset({ResearchStatus.READY, ResearchStatus.ACTIVE}),
    ResearchStatus.READY: frozenset({ResearchStatus.ACTIVE, ResearchStatus.FAILED}),
    ResearchStatus.ACTIVE: frozenset({
        ResearchStatus.PAUSED, ResearchStatus.EXHAUSTED,
        ResearchStatus.COMPLETED, ResearchStatus.FAILED,
    }),
    ResearchStatus.PAUSED: frozenset({ResearchStatus.ACTIVE, ResearchStatus.FAILED}),
    ResearchStatus.EXHAUSTED: frozenset({ResearchStatus.COMPLETED}),
    ResearchStatus.COMPLETED: frozenset(),
    ResearchStatus.FAILED: frozenset(),
}


class ResearchStateIntegrityError(Exception):
    """Raised when research_state.json exists but cannot be parsed."""

    def __init__(self, message: str, *, run_id: str, cause: Exception | None = None):
        super().__init__(message)
        self.message = message
        self.run_id = run_id
        self.cause = cause


class ResearchState(BaseModel):
    """Persistent research memory for one AeRoing4 run."""

    run_id: str

    # Champion tracking (null until Portfolio Baseline milestone)
    current_champion_id: Optional[str] = None
    current_champion_strategy_hash: Optional[str] = None
    current_champion_parameter_hash: Optional[str] = None

    # Active work pointers
    current_hypothesis_id: Optional[str] = None
    active_experiment_id: Optional[str] = None

    # Budget counters
    total_experiments_reserved: int = 0
    total_experiments_completed: int = 0
    max_total_experiments: int = 5  # default budget

    hypotheses_created: int = 0
    hypotheses_completed: int = 0

    # Summary of accessed data zones (list of zone names as strings)
    accessed_data_zones: list[str] = Field(default_factory=list)

    # Overall research status
    research_status: ResearchStatus = ResearchStatus.NOT_STARTED

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def transition_status(self, new_status: ResearchStatus) -> None:
        """Transition research_status with validation. Raises ValueError on invalid."""
        allowed = _RESEARCH_STATUS_TRANSITIONS.get(self.research_status, frozenset())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid ResearchStatus transition: {self.research_status.value} → "
                f"{new_status.value}. Allowed from {self.research_status.value}: "
                f"{sorted(s.value for s in allowed) or 'none (terminal)'}"
            )
        self.research_status = new_status
        self.updated_at = datetime.now(UTC)

    def touch(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.now(UTC)


class ResearchStateStore:
    """Persistent store for ResearchState, one file per run.

    File: user_data/aeroing4/runs/{run_id}/research_state.json
    Uses atomic temp-file + fsync + Path.replace() writes, guarded by a
    process-wide shared lock from file_lock_registry to ensure multi-instance
    write safety — mirrors AeRoing4StateStore and AccessLedger patterns.

    Fail-closed on corruption: if the file exists but cannot be parsed,
    raises ResearchStateIntegrityError rather than silently returning empty.
    """

    def __init__(self, runs_root: Path):
        self.runs_root = runs_root

    # ── Public API ────────────────────────────────────────────────────────

    def create(self, run_id: str, max_total_experiments: int = 5) -> ResearchState:
        """Create and persist a fresh ResearchState for run_id."""
        lock = get_lock_for_path(self._state_file(run_id))
        with lock:
            state = ResearchState(
                run_id=run_id,
                max_total_experiments=max_total_experiments,
            )
            self._save_locked(state)
            return state

    def load(self, run_id: str) -> Optional[ResearchState]:
        """Load ResearchState from disk. Returns None if file does not exist.

        Raises ResearchStateIntegrityError if the file exists but is corrupt.
        """
        lock = get_lock_for_path(self._state_file(run_id))
        with lock:
            return self._load_locked(run_id)

    def save(self, state: ResearchState) -> None:
        """Atomically save a ResearchState."""
        lock = get_lock_for_path(self._state_file(state.run_id))
        with lock:
            self._save_locked(state)

    def load_or_create(self, run_id: str, max_total_experiments: int = 5) -> ResearchState:
        """Load existing state or create a fresh one if absent."""
        lock = get_lock_for_path(self._state_file(run_id))
        with lock:
            existing = self._load_locked(run_id)
            if existing is not None:
                return existing
            state = ResearchState(
                run_id=run_id,
                max_total_experiments=max_total_experiments,
            )
            self._save_locked(state)
            return state

    # ── Private helpers ───────────────────────────────────────────────────

    def _state_file(self, run_id: str) -> Path:
        return self.runs_root / run_id / "research_state.json"

    def _load_locked(self, run_id: str) -> Optional[ResearchState]:
        f = self._state_file(run_id)
        if not f.exists():
            return None
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            return ResearchState.model_validate(data)
        except Exception as exc:
            raise ResearchStateIntegrityError(
                f"research_state.json for run '{run_id}' exists but cannot be "
                f"read/parsed — fail-closed to prevent silent data loss: {exc}",
                run_id=run_id,
                cause=exc,
            ) from exc

    def _save_locked(self, state: ResearchState) -> None:
        f = self._state_file(state.run_id)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(state.model_dump_json(indent=2))
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
