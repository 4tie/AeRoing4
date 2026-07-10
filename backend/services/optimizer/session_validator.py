"""Session validation and integrity checking for optimizer operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.core.optimizer_errors import (
    SessionCorruptedError,
    SessionNotFoundError,
    OptimizerErrorCode,
)
from backend.models import OptimizerSession, OptimizerSessionPhase


class SessionValidator:
    """Validates optimizer session integrity and consistency."""

    @staticmethod
    def validate_session_exists(session: OptimizerSession | None, session_id: str) -> OptimizerSession:
        """Validate that a session exists and return it."""
        if session is None:
            raise SessionNotFoundError(session_id)
        return session

    @staticmethod
    def validate_session_integrity(session: OptimizerSession) -> None:
        """Validate the structural integrity of a session."""
        errors = []

        # Check required fields
        if not session.session_id:
            errors.append("Missing session_id")
        if not session.strategy_name:
            errors.append("Missing strategy_name")
        if session.config is None:
            errors.append("Missing config")

        # Validate phase
        if not isinstance(session.phase, OptimizerSessionPhase):
            try:
                OptimizerSessionPhase(session.phase)
            except ValueError:
                errors.append(f"Invalid phase: {session.phase}")

        # Validate trial count consistency
        if session.completed_trials > session.total_trials:
            errors.append(
                f"completed_trials ({session.completed_trials}) > total_trials ({session.total_trials})"
            )

        # Validate best trial reference
        if session.best_trial_number is not None:
            matching_trials = [
                t for t in session.trials if t.trial_number == session.best_trial_number
            ]
            if not matching_trials:
                errors.append(
                    f"best_trial_number ({session.best_trial_number}) not found in trials"
                )
            elif len(matching_trials) > 1:
                errors.append(
                    f"Multiple trials with trial_number {session.best_trial_number}"
                )

        # Validate trial numbering
        trial_numbers = [t.trial_number for t in session.trials]
        if len(trial_numbers) != len(set(trial_numbers)):
            errors.append("Duplicate trial numbers found")

        # Validate timestamps
        if session.started_at and session.completed_at:
            if session.completed_at < session.started_at:
                errors.append("completed_at < started_at")

        if errors:
            raise SessionCorruptedError(
                session.session_id,
                f"Session integrity check failed: {', '.join(errors)}",
            )

    @staticmethod
    def validate_session_state(session: OptimizerSession, expected_state: str | None = None) -> None:
        """Validate that session is in expected state."""
        phase_value = getattr(session.phase, "value", session.phase)
        if expected_state and phase_value != expected_state:
            raise ValueError(
                f"Session {session.session_id} is in {phase_value} state, "
                f"expected {expected_state}"
            )

        # Check for stuck sessions
        if phase_value == OptimizerSessionPhase.RUNNING.value:
            # If running for more than 24 hours, it might be stuck
            if session.started_at:
                started_at = session.started_at
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=UTC)
                elapsed = (datetime.now(tz=UTC) - started_at).total_seconds()
                if elapsed > 86400:  # 24 hours
                    raise ValueError(
                        f"Session {session.session_id} appears stuck (running for {elapsed}s)"
                    )

    @staticmethod
    def validate_trial_consistency(session: OptimizerSession) -> None:
        """Validate trial data consistency within a session."""
        completed_count = len(
            [t for t in session.trials if getattr(t.status, "value", t.status) == "completed"]
        )
        failed_count = len(
            [t for t in session.trials if getattr(t.status, "value", t.status) == "failed"]
        )

        if completed_count != session.completed_trials:
            raise SessionCorruptedError(
                session.session_id,
                f"Trial count mismatch: completed_trials={session.completed_trials}, "
                f"but found {completed_count} completed trials",
            )

        if failed_count != session.failed_trials:
            raise SessionCorruptedError(
                session.session_id,
                f"Trial count mismatch: failed_trials={session.failed_trials}, "
                f"but found {failed_count} failed trials",
            )

    @staticmethod
    def validate_session_for_operation(
        session: OptimizerSession, operation: str
    ) -> None:
        """Validate that session is in appropriate state for given operation."""
        phase_value = getattr(session.phase, "value", session.phase)
        if operation == "start":
            if phase_value != OptimizerSessionPhase.IDLE.value:
                raise ValueError(
                    f"Cannot start session in {phase_value} state"
                )

        elif operation == "cancel":
            if phase_value not in {
                OptimizerSessionPhase.RUNNING.value,
                OptimizerSessionPhase.IDLE.value,
            }:
                raise ValueError(
                    f"Cannot cancel session in {phase_value} state"
                )

        elif operation == "add_trial":
            if phase_value != OptimizerSessionPhase.RUNNING.value:
                raise ValueError(
                    f"Cannot add trials to session in {phase_value} state"
                )

        elif operation == "complete":
            if phase_value != OptimizerSessionPhase.RUNNING.value:
                raise ValueError(
                    f"Cannot complete session in {phase_value} state"
                )
