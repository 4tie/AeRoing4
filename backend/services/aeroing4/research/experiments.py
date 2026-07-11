"""Experiment Memory — typed ExperimentRecord, status lifecycle, persistence.

Experiment status lifecycle (validated transitions only):
  PLANNED → RESERVED → READY → RUNNING → COMPLETED
                                        → FAILED_SYSTEM
                                        → CANCELLED
                                        → INTERRUPTED
                                        → INVALIDATED

Research decision is separate from execution status (spec §9):
  ExperimentDecision: KEEP | DROP | INCONCLUSIVE | PENDING

Atomic reservation order (spec §21):
  1. experiment identity persisted
  2. budget slot reserved
  3. protocol access requested and ledgered
  4. experiment marked READY
  5. (future) execution starts
  6. execution reference attached
  7. status RUNNING

Restart behavior (spec §10):
  PLANNED/RESERVED/READY on reload → remain, block duplicate creation
  RUNNING on reload → transition to INTERRUPTED (explicit, auditable)

Duplicate detection (spec §12-13):
  Before reservation, check ExperimentStore by identity hash.
  If found, return typed DUPLICATE_EXPERIMENT decision.
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

from ..metrics.models import CanonicalMetricsSnapshot
from ..metrics.provenance import METRICS_VERSION
from .budgets import BudgetDecision, BudgetDecisionCode, BudgetService
from .data_zones import RESEARCH_PROTOCOL_VERSION
from .file_lock_registry import get_lock_for_path
from .hypotheses import HypothesisStore
from .research_state import ResearchStateStore


class ExperimentStatus(str, Enum):
    """Execution lifecycle state of an experiment."""
    PLANNED = "planned"
    RESERVED = "reserved"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED_SYSTEM = "failed_system"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    INVALIDATED = "invalidated"


TERMINAL_STATUSES = frozenset({
    ExperimentStatus.COMPLETED,
    ExperimentStatus.FAILED_SYSTEM,
    ExperimentStatus.CANCELLED,
    ExperimentStatus.INTERRUPTED,
    ExperimentStatus.INVALIDATED,
})

IN_FLIGHT_STATUSES = frozenset({
    ExperimentStatus.PLANNED,
    ExperimentStatus.RESERVED,
    ExperimentStatus.READY,
    ExperimentStatus.RUNNING,
    ExperimentStatus.INTERRUPTED,
})

_EXPERIMENT_TRANSITIONS: dict[ExperimentStatus, frozenset[ExperimentStatus]] = {
    ExperimentStatus.PLANNED: frozenset({
        ExperimentStatus.RESERVED, ExperimentStatus.CANCELLED, ExperimentStatus.INVALIDATED
    }),
    ExperimentStatus.RESERVED: frozenset({
        ExperimentStatus.READY, ExperimentStatus.CANCELLED, ExperimentStatus.INVALIDATED
    }),
    ExperimentStatus.READY: frozenset({
        ExperimentStatus.RUNNING, ExperimentStatus.CANCELLED, ExperimentStatus.INVALIDATED
    }),
    ExperimentStatus.RUNNING: frozenset({
        ExperimentStatus.COMPLETED, ExperimentStatus.FAILED_SYSTEM,
        ExperimentStatus.CANCELLED, ExperimentStatus.INTERRUPTED, ExperimentStatus.INVALIDATED
    }),
    ExperimentStatus.COMPLETED: frozenset(),
    ExperimentStatus.FAILED_SYSTEM: frozenset(),
    ExperimentStatus.CANCELLED: frozenset(),
    ExperimentStatus.INTERRUPTED: frozenset(),
    ExperimentStatus.INVALIDATED: frozenset(),
}


class ExperimentDecision(str, Enum):
    """Research decision (separate from execution status)."""
    PENDING = "pending"
    KEEP = "keep"
    DROP = "drop"
    INCONCLUSIVE = "inconclusive"


class ExperimentTransitionError(Exception):
    """Raised on invalid experiment status transition."""
    def __init__(self, message: str, *, from_status: ExperimentStatus, to_status: ExperimentStatus):
        super().__init__(message)
        self.from_status = from_status
        self.to_status = to_status


class ExperimentIntegrityError(Exception):
    """Raised when experiments.json exists but cannot be parsed."""
    def __init__(self, message: str, *, run_id: str, cause: Exception | None = None):
        super().__init__(message)
        self.run_id = run_id
        self.cause = cause


class OriginalStrategyProvenance(BaseModel):
    """Typed provenance of the source strategy used in an experiment."""
    logical_name: str
    path_reference: Optional[str] = None   # safe path reference (not raw fs path)
    path_hash: Optional[str] = None        # hash of the strategy file path
    source_hash: Optional[str] = None      # hash of strategy file content at time of capture
    version_id: Optional[str] = None       # accepted version identifier


class ExactChange(BaseModel):
    """Typed description of the exact change proposed by a hypothesis."""
    change_type: str                        # e.g. "parameter", "indicator", "exit_logic"
    target: Optional[str] = None           # what was targeted
    before_value: Optional[object] = None  # value before the change
    after_value: Optional[object] = None   # value after the change
    description: Optional[str] = None
    raw_change: Optional[dict] = None      # full change spec if complex


class ExperimentRecord(BaseModel):
    """Complete typed record of one research experiment."""

    experiment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    hypothesis_id: str
    parent_champion_id: Optional[str] = None
    candidate_id: Optional[str] = None

    # Strategy provenance
    original_strategy_provenance: OriginalStrategyProvenance
    original_strategy_path_hash: Optional[str] = None

    strategy_version_before: Optional[str] = None
    strategy_version_after: Optional[str] = None
    strategy_hash_before: Optional[str] = None
    strategy_hash_after: Optional[str] = None

    parameter_hash_before: Optional[str] = None
    parameter_hash_after: Optional[str] = None

    exact_change: Optional[ExactChange] = None

    # Data zone and execution context
    dataset_zone: str = "develop"
    concrete_timerange: Optional[str] = None
    pair_set: list[str] = Field(default_factory=list)
    pair_set_hash: Optional[str] = None
    configuration_hash: Optional[str] = None
    input_hash: Optional[str] = None

    # Canonical identity (computed before reservation)
    experiment_identity_hash: str

    # Metrics (CanonicalMetricsSnapshot or None)
    metrics_before: Optional[CanonicalMetricsSnapshot] = None
    metrics_after: Optional[CanonicalMetricsSnapshot] = None
    metrics_availability_reason: Optional[str] = None  # typed reason when metrics_after is None
    metrics_version: str = METRICS_VERSION
    protocol_version: str = RESEARCH_PROTOCOL_VERSION

    # Execution references (assigned during/after execution)
    access_ledger_entry_id: Optional[str] = None
    underlying_execution_id: Optional[str] = None

    # Lifecycle
    status: ExperimentStatus = ExperimentStatus.PLANNED
    result: Optional[str] = None         # free-form result summary
    decision: ExperimentDecision = ExperimentDecision.PENDING

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    artifacts: dict[str, str] = Field(default_factory=dict)

    def transition_status(self, new_status: ExperimentStatus) -> None:
        """Validate and apply an experiment status transition."""
        allowed = _EXPERIMENT_TRANSITIONS.get(self.status, frozenset())
        if new_status not in allowed:
            raise ExperimentTransitionError(
                f"Invalid ExperimentStatus transition: {self.status.value} → "
                f"{new_status.value}. Allowed from {self.status.value}: "
                f"{sorted(s.value for s in allowed) or 'none (terminal)'}",
                from_status=self.status,
                to_status=new_status,
            )
        self.status = new_status
        self.updated_at = datetime.now(UTC)
        if new_status == ExperimentStatus.RUNNING:
            self.started_at = self.started_at or datetime.now(UTC)
        if new_status in TERMINAL_STATUSES:
            self.completed_at = self.completed_at or datetime.now(UTC)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def is_in_flight(self) -> bool:
        return self.status in IN_FLIGHT_STATUSES


class DuplicateExperimentDecision(BaseModel):
    """Typed result returned when a duplicate experiment identity is detected."""
    is_duplicate: bool = True
    existing_experiment_id: str
    existing_status: ExperimentStatus
    existing_decision: ExperimentDecision
    existing_result: Optional[str] = None
    identity_hash: str
    reason: str = "An experiment with the same identity hash already exists"


class ResumeSafetyReport(BaseModel):
    """Typed report on whether a new experiment can be started after a restart."""
    has_active_experiment: bool
    active_experiment_id: Optional[str] = None
    active_experiment_status: Optional[ExperimentStatus] = None
    is_resumable: bool
    must_reconcile_first: bool
    new_experiment_allowed: bool
    reason: str


class ExperimentStore:
    """Persistent store for ExperimentRecords, one file per run.

    File: user_data/aeroing4/runs/{run_id}/experiments.json
    Atomic writes + process-wide shared lock from file_lock_registry to ensure
    multi-instance write safety.
    Append-preserving — experiment history is never deleted.

    Atomic reservation protocol (§3, §21):
      All of: total budget check, per-hypothesis budget check, duplicate identity
      check, record creation, and persistence happen under one lock acquisition
      to prevent TOCTOU races.

    Restart recovery (§10):
      On reload, any experiment in RUNNING status is transitioned to INTERRUPTED
      automatically (if mark_interrupted_on_reload=True in __init__).
    """

    def __init__(
        self,
        runs_root: Path,
        budget_service: Optional[BudgetService] = None,
        hypothesis_store: Optional[HypothesisStore] = None,
        state_store: Optional[ResearchStateStore] = None,
        mark_interrupted_on_reload: bool = True,
    ):
        self.runs_root = runs_root
        self.budget_service = budget_service or BudgetService()
        self.hypothesis_store = hypothesis_store
        self.state_store = state_store
        self.mark_interrupted_on_reload = mark_interrupted_on_reload

    def reserve(
        self,
        experiment: ExperimentRecord,
    ) -> tuple[ExperimentRecord, Optional[DuplicateExperimentDecision]]:
        """Atomically check budget, detect duplicates, reserve, and persist.

        Returns (experiment, None) on success (status → RESERVED).
        Returns (None, DuplicateExperimentDecision) on duplicate detection.

        Raises:
            ValueError: If budget is exhausted.
            ExperimentTransitionError: If status transition is invalid.
        """
        lock = get_lock_for_path(self._experiment_file(experiment.run_id))
        with lock:
            records = self._load_locked(experiment.run_id)

            # 1. Check duplicate identity
            duplicate = self._find_by_identity_hash_in(
                records, experiment.experiment_identity_hash
            )
            if duplicate is not None:
                dup_decision = DuplicateExperimentDecision(
                    existing_experiment_id=duplicate.experiment_id,
                    existing_status=duplicate.status,
                    existing_decision=duplicate.decision,
                    existing_result=duplicate.result,
                    identity_hash=experiment.experiment_identity_hash,
                )
                return experiment, dup_decision

            # 2. Count current budget usage
            total_reserved = sum(
                1 for r in records if r.status in IN_FLIGHT_STATUSES
                or r.status in TERMINAL_STATUSES
            )
            hyp_count = sum(
                1 for r in records if r.hypothesis_id == experiment.hypothesis_id
            )

            # 3. Validate total + per-hypothesis budget
            budget_decision = self.budget_service.can_reserve(
                total_reserved=total_reserved,
                hypothesis_experiment_count=hyp_count,
            )
            if not budget_decision.allowed:
                raise ValueError(
                    f"Budget check failed [{budget_decision.code.value}]: {budget_decision.reason}"
                )

            # 4. Transition to RESERVED and persist
            experiment.transition_status(ExperimentStatus.RESERVED)
            records.append(experiment)
            self._save_locked(experiment.run_id, records)
            return experiment, None

    def get(self, run_id: str, experiment_id: str) -> Optional[ExperimentRecord]:
        """Load a specific experiment by ID."""
        lock = get_lock_for_path(self._experiment_file(run_id))
        with lock:
            for e in self._load_locked(run_id):
                if e.experiment_id == experiment_id:
                    return e
            return None

    def list_for_run(self, run_id: str) -> list[ExperimentRecord]:
        """List all experiments for a run in creation order."""
        lock = get_lock_for_path(self._experiment_file(run_id))
        with lock:
            return list(self._load_locked(run_id))

    def list_for_hypothesis(self, run_id: str, hypothesis_id: str) -> list[ExperimentRecord]:
        """List all experiments for a specific hypothesis."""
        lock = get_lock_for_path(self._experiment_file(run_id))
        with lock:
            return [
                e for e in self._load_locked(run_id)
                if e.hypothesis_id == hypothesis_id
            ]

    def find_by_identity_hash(
        self, run_id: str, identity_hash: str
    ) -> Optional[ExperimentRecord]:
        """Find an experiment by its identity hash (for duplicate detection)."""
        lock = get_lock_for_path(self._experiment_file(run_id))
        with lock:
            return self._find_by_identity_hash_in(
                self._load_locked(run_id), identity_hash
            )

    def transition_status(
        self, run_id: str, experiment_id: str, new_status: ExperimentStatus
    ) -> ExperimentRecord:
        """Atomically load, validate transition, persist, return updated record."""
        lock = get_lock_for_path(self._experiment_file(run_id))
        with lock:
            records = self._load_locked(run_id)
            target = self._find_by_id_in(records, experiment_id)
            if target is None:
                raise KeyError(f"Experiment '{experiment_id}' not found in run '{run_id}'")
            target.transition_status(new_status)
            updated = [target if e.experiment_id == experiment_id else e for e in records]
            self._save_locked(run_id, updated)
            return target

    def record_execution_reference(
        self, run_id: str, experiment_id: str,
        underlying_execution_id: str,
        access_ledger_entry_id: Optional[str] = None,
    ) -> ExperimentRecord:
        """Attach execution IDs to an experiment record."""
        lock = get_lock_for_path(self._experiment_file(run_id))
        with lock:
            records = self._load_locked(run_id)
            target = self._find_by_id_in(records, experiment_id)
            if target is None:
                raise KeyError(f"Experiment '{experiment_id}' not found in run '{run_id}'")
            target.underlying_execution_id = underlying_execution_id
            if access_ledger_entry_id is not None:
                target.access_ledger_entry_id = access_ledger_entry_id
            target.updated_at = datetime.now(UTC)
            updated = [target if e.experiment_id == experiment_id else e for e in records]
            self._save_locked(run_id, updated)
            return target

    def record_access_ledger_entry(
        self, run_id: str, experiment_id: str, access_ledger_entry_id: str,
        concrete_timerange: Optional[str] = None,
        protocol_version: Optional[str] = None,
    ) -> ExperimentRecord:
        """Record the protocol access ledger entry ID (and concrete timerange/version)."""
        lock = get_lock_for_path(self._experiment_file(run_id))
        with lock:
            records = self._load_locked(run_id)
            target = self._find_by_id_in(records, experiment_id)
            if target is None:
                raise KeyError(f"Experiment '{experiment_id}' not found in run '{run_id}'")
            target.access_ledger_entry_id = access_ledger_entry_id
            if concrete_timerange is not None:
                target.concrete_timerange = concrete_timerange
            if protocol_version is not None:
                target.protocol_version = protocol_version
            target.updated_at = datetime.now(UTC)
            updated = [target if e.experiment_id == experiment_id else e for e in records]
            self._save_locked(run_id, updated)
            return target

    def record_metrics(
        self,
        run_id: str,
        experiment_id: str,
        metrics_before: Optional[CanonicalMetricsSnapshot] = None,
        metrics_after: Optional[CanonicalMetricsSnapshot] = None,
        metrics_availability_reason: Optional[str] = None,
    ) -> ExperimentRecord:
        """Record metrics snapshots (before/after) for an experiment.

        When ``metrics_after`` is None, a typed ``metrics_availability_reason``
        MUST be persisted (never a bare None) so the absence is auditable.
        """
        lock = get_lock_for_path(self._experiment_file(run_id))
        with lock:
            records = self._load_locked(run_id)
            target = self._find_by_id_in(records, experiment_id)
            if target is None:
                raise KeyError(f"Experiment '{experiment_id}' not found in run '{run_id}'")
            if metrics_before is not None:
                target.metrics_before = metrics_before
            if metrics_after is not None:
                target.metrics_after = metrics_after
                target.metrics_availability_reason = None
            else:
                target.metrics_after = None
                target.metrics_availability_reason = metrics_availability_reason
            target.updated_at = datetime.now(UTC)
            updated = [target if e.experiment_id == experiment_id else e for e in records]
            self._save_locked(run_id, updated)
            return target

    def record_decision(
        self,
        run_id: str,
        experiment_id: str,
        decision: ExperimentDecision,
        result: Optional[str] = None,
    ) -> ExperimentRecord:
        """Record the research decision (KEEP/DROP/INCONCLUSIVE)."""
        lock = get_lock_for_path(self._experiment_file(run_id))
        with lock:
            records = self._load_locked(run_id)
            target = self._find_by_id_in(records, experiment_id)
            if target is None:
                raise KeyError(f"Experiment '{experiment_id}' not found in run '{run_id}'")
            target.decision = decision
            if result is not None:
                target.result = result
            target.updated_at = datetime.now(UTC)
            updated = [target if e.experiment_id == experiment_id else e for e in records]
            self._save_locked(run_id, updated)
            return target

    def resume_safety_report(self, run_id: str) -> ResumeSafetyReport:
        """Analyze restart/resume safety for a run.

        Returns a typed report answering:
        - Is there an active experiment?
        - Is it resumable?
        - Must it be reconciled first?
        - Is a new experiment allowed?
        """
        lock = get_lock_for_path(self._experiment_file(run_id))
        with lock:
            records = self._load_locked(run_id)

        in_flight = [e for e in records if e.is_in_flight]
        if not in_flight:
            return ResumeSafetyReport(
                has_active_experiment=False,
                is_resumable=False,
                must_reconcile_first=False,
                new_experiment_allowed=True,
                reason="No active experiments — new experiment can be created",
            )

        # RUNNING experiments become INTERRUPTED on reload (handled elsewhere);
        # here we classify what was found.
        running = [e for e in in_flight if e.status == ExperimentStatus.RUNNING]
        interrupted = [e for e in in_flight if e.status == ExperimentStatus.INTERRUPTED]
        other = [e for e in in_flight if e.status in (
            ExperimentStatus.PLANNED, ExperimentStatus.RESERVED, ExperimentStatus.READY
        )]

        if running:
            active = running[0]
            return ResumeSafetyReport(
                has_active_experiment=True,
                active_experiment_id=active.experiment_id,
                active_experiment_status=active.status,
                is_resumable=False,
                must_reconcile_first=True,
                new_experiment_allowed=False,
                reason=(
                    f"Experiment '{active.experiment_id}' is still RUNNING; "
                    "it must be reconciled (transition to INTERRUPTED/COMPLETED/FAILED_SYSTEM) "
                    "before a new experiment can be created"
                ),
            )

        if interrupted:
            active = interrupted[0]
            return ResumeSafetyReport(
                has_active_experiment=True,
                active_experiment_id=active.experiment_id,
                active_experiment_status=active.status,
                is_resumable=True,  # INTERRUPTED can be reconciled
                must_reconcile_first=True,
                new_experiment_allowed=False,
                reason=(
                    f"Experiment '{active.experiment_id}' is INTERRUPTED; "
                    "it must be reconciled before a new experiment can be created"
                ),
            )

        if other:
            active = other[0]
            return ResumeSafetyReport(
                has_active_experiment=True,
                active_experiment_id=active.experiment_id,
                active_experiment_status=active.status,
                is_resumable=True,
                must_reconcile_first=False,
                new_experiment_allowed=False,
                reason=(
                    f"Experiment '{active.experiment_id}' is {active.status.value}; "
                    "it is resumable but a second experiment cannot be created until it completes"
                ),
            )

        return ResumeSafetyReport(
            has_active_experiment=False,
            is_resumable=False,
            must_reconcile_first=False,
            new_experiment_allowed=True,
            reason="No blocking in-flight experiments",
        )

    def reconcile_interrupted_experiments(self, run_id: str) -> list[ExperimentRecord]:
        """Transition any RUNNING experiments to INTERRUPTED (restart recovery).

        Called on reload/restart to prevent silent duplicate execution.
        Returns the list of experiments that were transitioned.
        """
        lock = get_lock_for_path(self._experiment_file(run_id))
        with lock:
            records = self._load_locked(run_id)
            changed = []
            updated_records = []
            for e in records:
                if e.status == ExperimentStatus.RUNNING:
                    e.status = ExperimentStatus.INTERRUPTED
                    e.updated_at = datetime.now(UTC)
                    if e.completed_at is None:
                        e.completed_at = datetime.now(UTC)
                    changed.append(e)
                updated_records.append(e)
            if changed:
                self._save_locked(run_id, updated_records)
            return changed

    # ── Private helpers ───────────────────────────────────────────────────

    def _experiment_file(self, run_id: str) -> Path:
        return self.runs_root / run_id / "experiments.json"

    def _load_locked(self, run_id: str) -> list[ExperimentRecord]:
        f = self._experiment_file(run_id)
        if not f.exists():
            return []
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            return [ExperimentRecord.model_validate(item) for item in raw]
        except Exception as exc:
            raise ExperimentIntegrityError(
                f"experiments.json for run '{run_id}' exists but cannot be "
                f"read/parsed — fail-closed: {exc}",
                run_id=run_id,
                cause=exc,
            ) from exc

    def _save_locked(self, run_id: str, records: list[ExperimentRecord]) -> None:
        f = self._experiment_file(run_id)
        f.parent.mkdir(parents=True, exist_ok=True)
        payload = [json.loads(r.model_dump_json()) for r in records]
        # Unique temp name per attempt: avoids shared "experiments.tmp"
        # contention across concurrent writers and makes a missing-temp-file
        # race unrecoverable -> each attempt opens a fresh, uniquely named
        # file and writes its content before the atomic swap.
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
                tmp.replace(f)  # atomic swap — only point that mutates the real file
                return
            except PermissionError:
                # Transient lock held on the target (e.g. AV scan). Back off and retry.
                if attempt == max_retries - 1:
                    raise
                import time

                time.sleep(0.05 * (attempt + 1))  # Linear backoff
            except FileNotFoundError:
                # Temp file vanished before replace (rare). Retry rewrites fresh content.
                if attempt == max_retries - 1:
                    raise
                import time

                time.sleep(0.05 * (attempt + 1))
        # Unreachable: loop returns on success or raises on last attempt.
        if last_tmp is not None:
            last_tmp.unlink(missing_ok=True)
        raise ExperimentIntegrityError(
            f"Failed to persist experiments.json for run '{run_id}' after "
            f"{max_retries} attempts",
            run_id=run_id,
        )

    @staticmethod
    def _find_by_id_in(
        records: list[ExperimentRecord], experiment_id: str
    ) -> Optional[ExperimentRecord]:
        for e in records:
            if e.experiment_id == experiment_id:
                return e
        return None

    @staticmethod
    def _find_by_identity_hash_in(
        records: list[ExperimentRecord], identity_hash: str
    ) -> Optional[ExperimentRecord]:
        for e in records:
            if e.experiment_identity_hash == identity_hash:
                return e
        return None
