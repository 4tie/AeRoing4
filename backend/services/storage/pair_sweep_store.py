"""services/storage/pair_sweep_store.py contains backend logic for pair sweep store.

This file is intentionally documented in plain English so readers can follow
what each section does even without deep Python experience.
"""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any

from ...models import (
    SweepPhase,
    SweepSession,
    SweepSessionConfig,
    SweepSessionSummary,
    SweepIterationRecord,
    SweepIterationStatus,
    SweepIterationMetrics,
)
from ...utils import atomic_write_json, read_json


class PairSweepStore:
    """Flat-file persistence for pair sweep sessions."""

    def __init__(self, sweep_root: Path) -> None:
        """__init__ implements function-level backend logic."""
        self.sweep_root = sweep_root
        self.sweep_root.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        """session_dir implements function-level backend logic."""
        return self.sweep_root / session_id

    def session_path(self, session_id: str) -> Path:
        """session_path implements function-level backend logic."""
        return self.session_dir(session_id) / "session.json"

    def save_session(self, session: SweepSession) -> None:
        """save_session implements function-level backend logic."""
        session_dir = self.session_dir(session.session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.session_path(session.session_id), session.model_dump(mode="json"))

    def load_session(self, session_id: str) -> SweepSession | None:
        """load_session implements function-level backend logic."""
        path = self.session_path(session_id)
        data = read_json(path)
        if data is None:
            return None
        return SweepSession.model_validate(data)

    def create_session(
        self,
        strategy_name: str,
        config_file: str,
        timerange: str,
        timeframe: str,
        fee_rate: float,
        dry_run_wallet: float,
        pairs: list[str],
    ) -> SweepSession:
        """Create a new pair sweep session."""
        import uuid
        from datetime import datetime
        
        session_id = str(uuid.uuid4())
        now = datetime.now()
        
        config = SweepSessionConfig(
            strategy_name=strategy_name,
            config_file=config_file,
            timerange=timerange,
            timeframe=timeframe,
            fee_rate=fee_rate,
            max_open_trades=1,  # Default for pair sweep
            dry_run_wallet=dry_run_wallet,
            iteration_count=len(pairs),
            pair_pool=pairs,
            locked_pairs=[],
        )
        
        session = SweepSession(
            session_id=session_id,
            strategy_name=strategy_name,
            config=config,
            phase=SweepPhase.RUNNING,
            created_at=now,
            started_at=now,
            total_iterations=len(pairs),
            completed_iterations=0,
            failed_iterations=0,
            iterations=[],
        )
        
        self.save_session(session)
        return session

    def is_cancelled(self, session_id: str) -> bool:
        """Check if a session is cancelled."""
        session = self.load_session(session_id)
        return session is not None and session.phase == SweepPhase.CANCELLED

    def add_pair_result(
        self,
        sweep_id: str,
        pair: str,
        win_rate_pct: float | None,
        net_profit_pct: float | None,
        max_drawdown_pct: float | None,
        status: str,
        error: str | None = None,
    ) -> None:
        """Add a pair result to a sweep session."""
        session = self.load_session(sweep_id)
        if session is None:
            return
            
        iteration_record = SweepIterationRecord(
            iteration_number=len(session.iterations) + 1,
            status=SweepIterationStatus.COMPLETED if status == "completed" else SweepIterationStatus.FAILED,
            pairs=[pair],
            run_id=None,  # We don't track individual run IDs in this implementation
            metrics=None if win_rate_pct is None else SweepIterationMetrics(
                net_profit_pct=net_profit_pct,
                total_trades=None,  # Not extracted in our current implementation
                win_rate_pct=win_rate_pct,
                max_drawdown_pct=max_drawdown_pct,
                profit_factor=None,  # Not extracted in our current implementation
            ),
            started_at=None,  # Not tracking individual timing
            completed_at=None,
            error=error,
        )
        
        session.iterations.append(iteration_record)
        
        if status == "completed":
            session.completed_iterations += 1
        else:
            session.failed_iterations += 1
            
        self.save_session(session)

    def emit_progress(
        self,
        sweep_id: str,
        current_index: int,
        total: int,
        result: dict,
    ) -> None:
        """Emit progress signal - in a real implementation this would use Qt signals.
        For now, we just update the session and let the UI poll for updates."""
        # In a full implementation, this would emit a Qt signal
        # For now, we just ensure the session is saved
        pass

    def mark_completed(self, sweep_id: str) -> None:
        """Mark a sweep as completed."""
        session = self.load_session(sweep_id)
        if session is None:
            return
            
        session.phase = SweepPhase.COMPLETED
        session.completed_at = datetime.now()
        self.save_session(session)

    def mark_cancelled(self, sweep_id: str) -> None:
        """Mark a sweep as cancelled."""
        session = self.load_session(sweep_id)
        if session is None:
            return
            
        session.phase = SweepPhase.CANCELLED
        session.completed_at = datetime.now()
        self.save_session(session)

    def get_session_status(self, sweep_id: str) -> dict[str, Any]:
        """Get the status of a pair sweep."""
        session = self.load_session(sweep_id)
        if session is None:
            return {}
            
        return {
            "session_id": session.session_id,
            "strategy_name": session.strategy_name,
            "phase": session.phase if isinstance(session.phase, str) else session.phase.value,
            "total_iterations": session.total_iterations,
            "completed_iterations": session.completed_iterations,
            "failed_iterations": session.failed_iterations,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        }

    def list_running_sessions(self) -> list[SweepSession]:
        """list_running_sessions implements function-level backend logic."""
        running: list[SweepSession] = []
        if not self.sweep_root.exists():
            return running
        for session_dir in self.sweep_root.iterdir():
            if not session_dir.is_dir():
                continue
            path = session_dir / "session.json"
            data = read_json(path)
            if data is None:
                continue
            try:
                session = SweepSession.model_validate(data)
            except Exception:
                continue
            if session.phase == SweepPhase.RUNNING:
                running.append(session)
        return running
