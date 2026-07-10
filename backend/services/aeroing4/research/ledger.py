"""Access Ledger — typed, persistent, crash-safe audit trail of every
protected data-zone access attempt (allowed AND denied).

Persistence follows the exact pattern already used by `state_store.py`:
one JSON file per run, atomic temp-file + `Path.replace()` writes, guarded
by a lock. Ordering is never timestamp-only — every entry gets a
monotonically increasing per-run `sequence` assigned while holding the
lock, so concurrent/near-simultaneous writes cannot silently overwrite
each other or land in ambiguous order.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from .data_zones import ResearchZone
from .errors import LedgerIntegrityError
from .file_lock_registry import get_lock_for_path
from .stages import ResearchStage


class AccessDecisionCode(str, Enum):
    """Typed decision codes for `AccessDecision` (never a bare boolean)."""

    ALLOWED = "allowed"
    ZONE_NOT_ALLOWED_FOR_STAGE = "zone_not_allowed_for_stage"
    BOUNDARIES_NOT_INITIALIZED = "boundaries_not_initialized"
    BOUNDARIES_NOT_FROZEN = "boundaries_not_frozen"
    CONFIRMATION_NOT_PASSED = "confirmation_not_passed"
    FINAL_UNSEEN_ALREADY_CONSUMED = "final_unseen_already_consumed"
    PROTOCOL_VERSION_MISMATCH = "protocol_version_mismatch"
    INVALID_BOUNDARY_STATE = "invalid_boundary_state"


class AccessDecision(BaseModel):
    """Typed result of a `can_access` / `request_access` query.

    Never a bare boolean — always carries a decision code, a human reason,
    and the exact stage/zone/protocol_version the decision was made under.
    """

    allowed: bool
    decision_code: AccessDecisionCode
    reason: str
    run_id: str
    stage: ResearchStage
    zone: ResearchZone
    protocol_version: str
    strategy_hash: str | None = None
    parameter_hash: str | None = None
    experiment_id: str | None = None


class AccessLedgerEntry(BaseModel):
    """One persisted, immutable audit record of a protected-zone access attempt."""

    access_id: str
    sequence: int
    run_id: str
    stage: ResearchStage
    zone: ResearchZone
    allowed: bool
    decision_code: AccessDecisionCode
    reason: str
    timestamp: datetime
    protocol_version: str

    strategy_hash: str | None = None
    parameter_hash: str | None = None
    pair_set_hash: str | None = None
    experiment_id: str | None = None
    underlying_result_id: str | None = None


class AccessLedger:
    """Persistent, append-only Access Ledger.

    One file per run at `{runs_root}/{run_id}/access_ledger.json`, sibling
    to `state.json` — same directory convention as `AeRoing4StateStore`.
    Uses process-wide shared lock from file_lock_registry to ensure
    multi-instance write safety.
    """

    def __init__(self, runs_root: Path):
        self.runs_root = runs_root

    def append(
        self,
        *,
        run_id: str,
        stage: ResearchStage,
        zone: ResearchZone,
        decision: AccessDecision,
        pair_set_hash: str | None = None,
        underlying_result_id: str | None = None,
    ) -> AccessLedgerEntry:
        """Append one access record; assigns a unique, ordered access_id/sequence.

        Read-modify-write happens entirely under the shared lock so
        concurrent/near-simultaneous callers can never silently overwrite
        each other's entries.
        """
        lock = get_lock_for_path(self._ledger_file(run_id))
        with lock:
            existing = self._load_locked(run_id)
            entry = AccessLedgerEntry(
                access_id=str(uuid.uuid4()),
                sequence=len(existing),
                run_id=run_id,
                stage=stage,
                zone=zone,
                allowed=decision.allowed,
                decision_code=decision.decision_code,
                reason=decision.reason,
                timestamp=datetime.now(UTC),
                protocol_version=decision.protocol_version,
                strategy_hash=decision.strategy_hash,
                parameter_hash=decision.parameter_hash,
                pair_set_hash=pair_set_hash,
                experiment_id=decision.experiment_id,
                underlying_result_id=underlying_result_id,
            )
            existing.append(entry)
            self._save_locked(run_id, existing)
            return entry

    def load_entries(self, run_id: str) -> list[AccessLedgerEntry]:
        """Load all persisted entries for a run, in stable sequence order."""
        lock = get_lock_for_path(self._ledger_file(run_id))
        with lock:
            return self._load_locked(run_id)

    def has_allowed_access(self, run_id: str, *, zone: ResearchZone) -> bool:
        """Whether any *allowed* access to `zone` has ever been recorded for this run."""
        return any(
            e.allowed and e.zone == zone for e in self.load_entries(run_id)
        )

    def atomic_final_unseen_append(
        self,
        *,
        run_id: str,
        stage: ResearchStage,
        pre_check_decision: "AccessDecision",
        denied_decision: "AccessDecision",
        pair_set_hash: str | None = None,
        underlying_result_id: str | None = None,
    ) -> tuple["AccessDecision", "AccessLedgerEntry"]:
        """Check-and-append for FINAL_UNSEEN atomically under the shared lock.

        ``pre_check_decision`` is the decision computed by ``can_access`` just
        before this call (``allowed=True``).  While holding the write lock this
        method re-reads the ledger and checks whether a *different* concurrent
        caller already consumed FINAL_UNSEEN; if so, the actual decision is
        overridden to ``denied_decision`` before the entry is written.

        This prevents the TOCTOU race that exists when ``can_access`` and
        ``append`` are called sequentially without holding a shared lock: two
        concurrent callers can both observe an empty FINAL_UNSEEN history and
        both be granted access before either write lands.
        """
        lock = get_lock_for_path(self._ledger_file(run_id))
        with lock:
            existing = self._load_locked(run_id)
            already_consumed = any(
                e.allowed and e.zone == ResearchZone.FINAL_UNSEEN for e in existing
            )
            actual_decision = denied_decision if already_consumed else pre_check_decision
            entry = AccessLedgerEntry(
                access_id=str(uuid.uuid4()),
                sequence=len(existing),
                run_id=run_id,
                stage=stage,
                zone=ResearchZone.FINAL_UNSEEN,
                allowed=actual_decision.allowed,
                decision_code=actual_decision.decision_code,
                reason=actual_decision.reason,
                timestamp=datetime.now(UTC),
                protocol_version=actual_decision.protocol_version,
                strategy_hash=actual_decision.strategy_hash,
                parameter_hash=actual_decision.parameter_hash,
                pair_set_hash=pair_set_hash,
                experiment_id=actual_decision.experiment_id,
                underlying_result_id=underlying_result_id,
            )
            existing.append(entry)
            self._save_locked(run_id, existing)
            return actual_decision, entry

    # ── Private I/O helpers (mirrors AeRoing4StateStore's atomic pattern) ──

    def _ledger_file(self, run_id: str) -> Path:
        return self.runs_root / run_id / "access_ledger.json"

    def _load_locked(self, run_id: str) -> list[AccessLedgerEntry]:
        """Load ledger entries from disk.

        Fail-closed: returns ``[]`` only when the file does not yet exist (no
        accesses have been recorded yet).  If the file *exists* but cannot be
        read or parsed, raises ``LedgerIntegrityError`` rather than silently
        returning an empty list — an empty list would erase audit history and
        could allow a second FINAL_UNSEEN access to pass through a guard that
        considers the zone unconsumed.
        """
        ledger_file = self._ledger_file(run_id)
        if not ledger_file.exists():
            return []
        try:
            raw = json.loads(ledger_file.read_text(encoding="utf-8"))
            return sorted(
                (AccessLedgerEntry.model_validate(item) for item in raw),
                key=lambda e: e.sequence,
            )
        except Exception as exc:
            raise LedgerIntegrityError(
                f"Access ledger for run '{run_id}' exists but could not be read "
                f"or parsed — treating as integrity failure to prevent fail-open "
                f"behaviour: {exc}",
                run_id=run_id,
                cause=exc,
            ) from exc

    def _save_locked(self, run_id: str, entries: list[AccessLedgerEntry]) -> None:
        ledger_file = self._ledger_file(run_id)
        ledger_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file = ledger_file.with_suffix(".tmp")
        payload = [json.loads(e.model_dump_json()) for e in entries]
        try:
            with open(temp_file, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
                fh.flush()
                import os

                os.fsync(fh.fileno())
            # Retry replace on Windows to handle transient file locking
            max_retries = 10
            for attempt in range(max_retries):
                try:
                    temp_file.replace(ledger_file)
                    break
                except (PermissionError, FileNotFoundError):
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(0.05 * (attempt + 1))  # Linear backoff
        except Exception:
            temp_file.unlink(missing_ok=True)
            raise
