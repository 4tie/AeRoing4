"""Optimizer session management and persistence.

Handles session creation, state management, and persistence operations.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Callable

from ...core.errors import BackendError
from ...models import (
    AcceptanceStatus,
    OptimizerSession,
    OptimizerSessionConfig,
    OptimizerSessionPhase,
    ParameterSearchSpace,
    StartOptimizerRequest,
    VersionChangeType,
    VersionCreationSource,
    VersionMetadata,
)
from ...utils import utc_now
from ..optimizer.session_validator import SessionValidator
from ..storage.optimizer_store import OptimizerStore
from ..strategy.strategy_registry import StrategyRegistry
from ..strategy.version_manager import VersionManager


class OptimizerSessionManager:
    """Manages optimizer session lifecycle and persistence."""

    def __init__(
        self,
        optimizer_store: OptimizerStore,
        registry: StrategyRegistry,
        version_manager: VersionManager,
    ) -> None:
        self.optimizer_store = optimizer_store
        self.registry = registry
        self.version_manager = version_manager
        self.log_callback: Callable[[str], None] | None = None
        self.validator = SessionValidator()

    def set_log_callback(self, callback: Callable[[str], None] | None) -> None:
        """Set callback for real-time log streaming."""
        self.log_callback = callback

    def create_session(self, request: StartOptimizerRequest) -> OptimizerSession:
        """Create a new optimizer session record."""
        # Ensure strategy is registered (has an accepted version)
        strategy = self.registry.get_strategy(request.strategy_name)
        pointer = self.version_manager.get_current_pointer(request.strategy_name)
        if pointer is None:
            # Auto-register the strategy
            self.version_manager.ensure_registered(strategy)

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
        
        self.optimizer_store.save_session(session)
        return session

    def load_session(self, session_id: str) -> OptimizerSession | None:
        """Load a session by ID with validation."""
        session = self.optimizer_store.load_session(session_id)
        if session is not None:
            try:
                self.validator.validate_session_integrity(session)
                self.validator.validate_trial_consistency(session)
            except Exception:
                # If validation fails, log but still return the session
                # to maintain backward compatibility
                if self.log_callback:
                    self.log_callback(f"Warning: Session {session_id} validation failed")
        return session

    def save_session(self, session: OptimizerSession) -> None:
        """Persist session state with validation."""
        self.validator.validate_session_integrity(session)
        self.validator.validate_trial_consistency(session)
        self.optimizer_store.save_session(session)

    def mark_session_running(self, session_id: str) -> OptimizerSession:
        """Mark session as running with validation."""
        session = self.optimizer_store.load_session(session_id)
        if session is None:
            raise BackendError(f"Optimizer session '{session_id}' not found.", status_code=404)
        
        self.validator.validate_session_for_operation(session, "start")
        
        session = session.model_copy(
            update={
                "phase": OptimizerSessionPhase.RUNNING,
                "started_at": utc_now(),
            }
        )
        self.optimizer_store.save_session(session)
        return session

    def mark_session_completed(self, session_id: str) -> OptimizerSession:
        """Mark session as completed with validation."""
        session = self.optimizer_store.load_session(session_id)
        if session is None:
            raise BackendError(f"Optimizer session '{session_id}' not found.", status_code=404)
        
        self.validator.validate_session_for_operation(session, "complete")
        
        session = session.model_copy(
            update={
                "phase": OptimizerSessionPhase.COMPLETED,
                "completed_at": utc_now(),
            }
        )
        self.optimizer_store.save_session(session)
        return session

    def mark_session_failed(self, session_id: str, reason: str) -> OptimizerSession:
        """Mark session as failed."""
        session = self.optimizer_store.load_session(session_id)
        if session is None:
            raise BackendError(f"Optimizer session '{session_id}' not found.", status_code=404)
        
        session = session.model_copy(
            update={
                "phase": OptimizerSessionPhase.FAILED,
                "completed_at": utc_now(),
                "stop_reason": reason,
            }
        )
        self.optimizer_store.save_session(session)
        return session

    def mark_session_cancelled(self, session_id: str, reason: str = "Cancelled by user") -> OptimizerSession:
        """Mark session as cancelled with validation."""
        session = self.optimizer_store.load_session(session_id)
        if session is None:
            raise BackendError(f"Optimizer session '{session_id}' not found.", status_code=404)
        
        self.validator.validate_session_for_operation(session, "cancel")
        
        session = session.model_copy(
            update={
                "phase": OptimizerSessionPhase.CANCELLED,
                "completed_at": utc_now(),
                "stop_reason": reason,
            }
        )
        self.optimizer_store.save_session(session)
        return session
