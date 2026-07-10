"""Enhanced session manager with locking, validation, and proper lifecycle management."""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from backend.core.optimizer_errors import (
    OptimizerError,
    SessionAlreadyRunningError,
)
from backend.models import (
    OptimizerSession,
    OptimizerSessionConfig,
    OptimizerSessionPhase,
    StartOptimizerRequest,
)
from backend.services.optimizer.session_validator import SessionValidator
from backend.services.storage.optimizer_store import OptimizerStore
from backend.services.strategy.strategy_registry import StrategyRegistry
from backend.services.strategy.version_manager import VersionManager
from backend.utils import utc_now


class EnhancedSessionManager:
    """Enhanced session manager with locking, validation, and proper lifecycle management."""

    def __init__(
        self,
        optimizer_store: OptimizerStore,
        registry: StrategyRegistry,
        version_manager: VersionManager,
    ):
        self.optimizer_store = optimizer_store
        self.registry = registry
        self.version_manager = version_manager
        self.validator = SessionValidator()
        
        # Session state tracking
        self._lock = threading.RLock()
        self._active_session_id: str | None = None
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._session_cleanup_queue: list[str] = []

    @asynccontextmanager
    async def session_lock(self, session_id: str):
        """Context manager for session-level locking."""
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        
        async with self._session_locks[session_id]:
            yield

    def get_active_session_id(self) -> str | None:
        """Get the currently active session ID."""
        with self._lock:
            return self._active_session_id

    def is_session_active(self, session_id: str) -> bool:
        """Check if a specific session is currently active."""
        with self._lock:
            return self._active_session_id == session_id

    async def create_session(self, request: StartOptimizerRequest) -> OptimizerSession:
        """Create a new optimizer session with validation and state management."""
        with self._lock:
            if self._active_session_id is not None:
                # Verify the active session is still running
                try:
                    active_session = self.optimizer_store.load_session(self._active_session_id)
                    active_phase = getattr(
                        getattr(active_session, "phase", None),
                        "value",
                        getattr(active_session, "phase", None),
                    )
                    if active_session and active_phase == OptimizerSessionPhase.RUNNING.value:
                        raise SessionAlreadyRunningError(self._active_session_id)
                except SessionAlreadyRunningError:
                    raise
                except Exception:
                    # If we can't verify, assume it's not running
                    self._active_session_id = None

        # Validate strategy exists and has accepted version
        strategy = self.registry.get_strategy(request.strategy_name)
        pointer = self.version_manager.get_current_pointer(request.strategy_name)
        if pointer is None:
            # Auto-register the strategy
            self.version_manager.ensure_registered(strategy)

        # Create session
        import uuid
        session_id = str(uuid.uuid4())
        config = OptimizerSessionConfig(
            strategy_name=request.strategy_name,
            timeframe=request.timeframe,
            timerange=request.timerange,
            pairs=request.pairs,
            config_file=request.config_file,
            dry_run_wallet=request.dry_run_wallet,
            max_open_trades=request.max_open_trades,
            fee_rate=request.fee_rate,
            total_trials=request.total_trials,
            search_strategy=request.search_strategy,
            parameter_mode=request.parameter_mode,
            score_metric=request.score_metric,
            score_weights=request.score_weights,
            target_trades=request.target_trades,
            target_profit_pct=request.target_profit_pct,
            max_drawdown_pct=request.max_drawdown_pct,
            target_romad=request.target_romad,
            search_spaces=request.search_spaces,
            enable_vectorbt_screening=request.enable_vectorbt_screening,
            vectorbt_candidate_count=request.vectorbt_candidate_count,
            vectorbt_keep_ratio=request.vectorbt_keep_ratio,
            vectorbt_timeout_seconds=request.vectorbt_timeout_seconds,
        )

        session = OptimizerSession(
            session_id=session_id,
            strategy_name=request.strategy_name,
            config=config,
            phase=OptimizerSessionPhase.IDLE,
            created_at=utc_now(),
            total_trials=request.total_trials,
        )

        # Validate session before saving
        self.validator.validate_session_integrity(session)
        
        # Save session
        self.optimizer_store.save_session(session)

        with self._lock:
            self._active_session_id = session_id

        return session

    async def load_session(self, session_id: str) -> OptimizerSession:
        """Load and validate a session."""
        async with self.session_lock(session_id):
            session = self.optimizer_store.load_session(session_id)
            self.validator.validate_session_exists(session, session_id)
            self.validator.validate_session_integrity(session)
            self.validator.validate_session_state(session)
            self.validator.validate_trial_consistency(session)
            return session

    async def update_session(self, session: OptimizerSession) -> OptimizerSession:
        """Update a session with validation and state management."""
        async with self.session_lock(session.session_id):
            # Validate session before updating
            self.validator.validate_session_integrity(session)
            self.validator.validate_trial_consistency(session)

            # Save the updated session
            self.optimizer_store.save_session(session)

            # Update active session tracking
            phase_value = getattr(session.phase, "value", session.phase)
            with self._lock:
                if phase_value == OptimizerSessionPhase.RUNNING.value:
                    self._active_session_id = session.session_id
                elif phase_value in {
                    OptimizerSessionPhase.COMPLETED.value,
                    OptimizerSessionPhase.FAILED.value,
                    OptimizerSessionPhase.CANCELLED.value,
                } and self._active_session_id == session.session_id:
                    self._active_session_id = None
                    self._queue_session_cleanup(session.session_id)

            return session

    async def mark_session_running(self, session_id: str) -> OptimizerSession:
        """Mark session as running with validation."""
        session = await self.load_session(session_id)
        self.validator.validate_session_for_operation(session, "start")

        session = session.model_copy(
            update={
                "phase": OptimizerSessionPhase.RUNNING,
                "started_at": utc_now(),
            }
        )

        return await self.update_session(session)

    async def mark_session_completed(self, session_id: str) -> OptimizerSession:
        """Mark session as completed with validation."""
        session = await self.load_session(session_id)
        self.validator.validate_session_for_operation(session, "complete")

        session = session.model_copy(
            update={
                "phase": OptimizerSessionPhase.COMPLETED,
                "completed_at": utc_now(),
            }
        )

        return await self.update_session(session)

    async def mark_session_failed(self, session_id: str, reason: str) -> OptimizerSession:
        """Mark session as failed with validation."""
        session = await self.load_session(session_id)

        session = session.model_copy(
            update={
                "phase": OptimizerSessionPhase.FAILED,
                "completed_at": utc_now(),
                "stop_reason": reason,
            }
        )

        return await self.update_session(session)

    async def mark_session_cancelled(self, session_id: str, reason: str = "Cancelled by user") -> OptimizerSession:
        """Mark session as cancelled with validation."""
        session = await self.load_session(session_id)

        session = session.model_copy(
            update={
                "phase": OptimizerSessionPhase.CANCELLED,
                "completed_at": utc_now(),
                "stop_reason": reason,
            }
        )

        return await self.update_session(session)

    def _queue_session_cleanup(self, session_id: str) -> None:
        """Queue a session for cleanup after completion."""
        if session_id not in self._session_cleanup_queue:
            self._session_cleanup_queue.append(session_id)

    async def cleanup_completed_sessions(self, max_age_hours: int = 24) -> int:
        """Clean up old completed sessions."""
        cleaned_count = 0
        cutoff_time = datetime.now(tz=UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        sessions = self.optimizer_store.list_sessions()
        for session_summary in sessions:
            phase_value = getattr(session_summary.phase, "value", session_summary.phase)
            if phase_value in {
                OptimizerSessionPhase.COMPLETED.value,
                OptimizerSessionPhase.FAILED.value,
                OptimizerSessionPhase.CANCELLED.value,
            }:
                if session_summary.completed_at:
                    session_age = (cutoff_time - session_summary.completed_at).total_seconds()
                    if session_age > max_age_hours * 3600:
                        try:
                            if self.optimizer_store.delete_session(session_summary.session_id):
                                cleaned_count += 1
                                # Remove from tracking
                                with self._lock:
                                    if session_summary.session_id in self._session_locks:
                                        del self._session_locks[session_summary.session_id]
                        except Exception:
                            # Log but continue with other cleanups
                            pass

        return cleaned_count

    async def get_session_status(self, session_id: str) -> dict[str, Any]:
        """Get session status with validation."""
        try:
            session = await self.load_session(session_id)
            return {
                "session_id": session.session_id,
                "phase": getattr(session.phase, "value", session.phase),
                "total_trials": session.total_trials,
                "completed_trials": session.completed_trials,
                "failed_trials": session.failed_trials,
                "elapsed_seconds": session.elapsed_seconds,
                "eta_seconds": session.eta_seconds,
                "best_trial_number": session.best_trial_number,
                "is_active": self.is_session_active(session_id),
            }
        except OptimizerError as e:
            return {
                "session_id": session_id,
                "error": e.to_dict(),
                "is_active": False,
            }
