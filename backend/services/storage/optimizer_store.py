"""services/storage/optimizer_store.py contains backend logic for optimizer store.

This file is intentionally documented in plain English so readers can follow
what each section does even without deep Python experience.
"""

from __future__ import annotations
from pathlib import Path

from ...models import OptimizerSession, OptimizerSessionSummary
from ...utils import atomic_write_json, read_json, utc_now


class OptimizerStore:
    """Flat-file persistence for optimizer sessions."""

    def __init__(self, optimizer_root: Path) -> None:
        """__init__ implements function-level backend logic."""
        self.optimizer_root = optimizer_root
        self.optimizer_root.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        """session_dir implements function-level backend logic."""
        return self.optimizer_root / session_id

    def session_path(self, session_id: str) -> Path:
        """session_path implements function-level backend logic."""
        return self.session_dir(session_id) / "session.json"

    def save_session(self, session: OptimizerSession) -> None:
        """save_session implements function-level backend logic."""
        session_dir = self.session_dir(session.session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.session_path(session.session_id), session.model_dump(mode="json"))

    def load_session(self, session_id: str) -> OptimizerSession | None:
        """load_session implements function-level backend logic."""
        path = self.session_path(session_id)
        if not path.exists():
            return None
        data = read_json(path)
        if data is None:
            return None
        try:
            return OptimizerSession.model_validate(data)
        except Exception:
            # Return None if validation fails - session file is corrupted
            return None

    def list_sessions(self, strategy_name: str | None = None) -> list[OptimizerSessionSummary]:
        """list_sessions implements function-level backend logic."""
        summaries: list[OptimizerSessionSummary] = []
        if not self.optimizer_root.exists():
            return summaries
        for session_dir in sorted(self.optimizer_root.iterdir(), reverse=True):
            if not session_dir.is_dir():
                continue
            path = session_dir / "session.json"
            data = read_json(path)
            if data is None:
                continue
            try:
                session = OptimizerSession.model_validate(data)
            except Exception:
                continue
            if strategy_name and session.strategy_name != strategy_name:
                continue
            best_score: float | None = None
            if session.best_metrics is not None:
                best_score = session.best_metrics.score
            summaries.append(
                OptimizerSessionSummary(
                    session_id=session.session_id,
                    strategy_name=session.strategy_name,
                    created_at=session.created_at,
                    started_at=session.started_at,
                    completed_at=session.completed_at,
                    phase=session.phase,
                    total_trials=session.total_trials,
                    completed_trials=session.completed_trials,
                    best_score=best_score,
                    score_metric=session.config.score_metric,
                )
            )
        return summaries

    def delete_session(self, session_id: str) -> bool:
        """delete_session implements function-level backend logic."""
        session_dir = self.session_dir(session_id)
        if not session_dir.exists():
            return False
        import shutil
        shutil.rmtree(session_dir)
        return True
