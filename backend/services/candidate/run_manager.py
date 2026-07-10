"""In-memory run manager for Candidate evaluation progress."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from backend.models.strategy_spec import StrategySpec
from backend.utils import utc_now

from .models import (
    CANDIDATE_GATE_NAMES,
    CandidateConfig,
    CandidateGateProgress,
    CandidateRunState,
    CandidateRunStatus,
    CandidateVerdict,
)


class CandidateRunManager:
    """Tracks async Candidate runs for polling."""

    def __init__(self) -> None:
        self._runs: dict[str, CandidateRunState] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    def create_run(self, spec: StrategySpec, config: CandidateConfig) -> CandidateRunState:
        run_id = f"candidate_{uuid4()}"
        now = utc_now()
        state = CandidateRunState(
            run_id=run_id,
            status=CandidateRunStatus.PENDING,
            created_at=now,
            gates=[
                CandidateGateProgress(run_id=run_id, gate_name=gate_name)
                for gate_name in CANDIDATE_GATE_NAMES
            ],
        )
        self._runs[run_id] = state
        return state.model_copy(deep=True)

    def get_run(self, run_id: str) -> CandidateRunState | None:
        state = self._runs.get(run_id)
        return state.model_copy(deep=True) if state is not None else None

    def mark_running(self, run_id: str) -> CandidateRunState | None:
        state = self._runs.get(run_id)
        if state is None:
            return None
        now = utc_now()
        if state.started_at is None:
            state.started_at = now
        state.status = CandidateRunStatus.RUNNING
        state.error = None
        return state.model_copy(deep=True)

    def update_gate(
        self,
        run_id: str,
        gate_update: CandidateGateProgress | dict[str, Any],
    ) -> CandidateRunState | None:
        state = self._runs.get(run_id)
        if state is None:
            return None
        payload = (
            gate_update.model_dump()
            if isinstance(gate_update, CandidateGateProgress)
            else dict(gate_update)
        )
        payload["run_id"] = run_id
        update = CandidateGateProgress.model_validate(payload)

        replaced = False
        gates = []
        for gate in state.gates:
            if gate.gate_name == update.gate_name:
                gates.append(update)
                replaced = True
            else:
                gates.append(gate)
        if not replaced:
            gates.append(update)
        state.gates = gates
        state.current_gate = update.gate_name
        if state.status == CandidateRunStatus.PENDING:
            state.status = CandidateRunStatus.RUNNING
        self._publish(run_id, self._gate_update_event(run_id, update))
        return state.model_copy(deep=True)

    def mark_completed(
        self,
        run_id: str,
        verdict: CandidateVerdict,
    ) -> CandidateRunState | None:
        state = self._runs.get(run_id)
        if state is None:
            return None
        now = utc_now()
        state.status = CandidateRunStatus.COMPLETED
        state.finished_at = now
        state.verdict = verdict
        state.error = None
        self._sync_verdict_gates(state, verdict, now)
        self._skip_pending_gates(state, now)
        state.current_gate = None
        self._publish(run_id, self._final_event(state))
        return state.model_copy(deep=True)

    def mark_failed(self, run_id: str, error: str) -> CandidateRunState | None:
        state = self._runs.get(run_id)
        if state is None:
            return None
        now = utc_now()
        state.status = CandidateRunStatus.FAILED
        state.finished_at = now
        state.error = error
        state.current_gate = None
        self._skip_pending_gates(state, now)
        self._publish(run_id, self._final_event(state))
        return state.model_copy(deep=True)

    def clear(self) -> None:
        self._runs.clear()
        self._subscribers.clear()

    def subscribe(self, run_id: str) -> asyncio.Queue | None:
        if run_id not in self._runs:
            return None
        queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subscribers.setdefault(run_id, []).append(queue)
        return queue

    def release(self, run_id: str, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(run_id)
        if not subscribers:
            return
        try:
            subscribers.remove(queue)
        except ValueError:
            pass
        if not subscribers:
            self._subscribers.pop(run_id, None)

    def subscriber_count(self, run_id: str) -> int:
        return len(self._subscribers.get(run_id, []))

    def _sync_verdict_gates(
        self,
        state: CandidateRunState,
        verdict: CandidateVerdict,
        now,
    ) -> None:
        for result in verdict.gate_results:
            current = self._find_gate(state, result.gate_name)
            if current and current.status != "pending":
                continue
            started_at = current.started_at if current else now
            finished_at = current.finished_at if current else now
            state_update = CandidateGateProgress(
                run_id=state.run_id,
                gate_name=result.gate_name,
                status="passed" if result.passed else "failed",
                started_at=started_at,
                finished_at=finished_at or now,
                duration_ms=_duration_ms(started_at, finished_at or now),
                metrics=result.metrics or {},
                details=result.details or {},
            )
            self.update_gate(state.run_id, state_update)

    def _skip_pending_gates(self, state: CandidateRunState, now) -> None:
        skipped = []
        for gate in state.gates:
            if gate.status == "pending":
                skipped.append(
                    gate.model_copy(
                        update={
                            "status": "skipped",
                            "finished_at": now,
                            "duration_ms": 0,
                        }
                    )
                )
            else:
                skipped.append(gate)
        state.gates = skipped

    def _find_gate(
        self,
        state: CandidateRunState,
        gate_name: str,
    ) -> CandidateGateProgress | None:
        for gate in state.gates:
            if gate.gate_name == gate_name:
                return gate
        return None

    def _publish(self, run_id: str, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(run_id, [])):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def _gate_update_event(
        self,
        run_id: str,
        gate: CandidateGateProgress,
    ) -> dict[str, Any]:
        return {
            "type": "gate_update",
            "run_id": run_id,
            "data": gate.model_dump(mode="json"),
        }

    def _final_event(self, state: CandidateRunState) -> dict[str, Any]:
        return {
            "type": "final",
            "run_id": state.run_id,
            "data": state.model_dump(mode="json"),
        }


def _duration_ms(started_at, finished_at) -> int | None:
    if started_at is None or finished_at is None:
        return 0
    return max(0, round((finished_at - started_at).total_seconds() * 1000))
