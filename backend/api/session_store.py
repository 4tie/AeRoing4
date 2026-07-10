"""Disk-backed session/job registry for API background operations.

Every long-running endpoint (download, backtest, optimizer, stress-lab)
immediately returns a session_id. Callers then poll
/api/session/status/{session_id} to discover the current state.

Sessions are persisted to a JSON file so they survive --reload restarts.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _serialize(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def _deserialize_record(data: dict) -> "SessionRecord":
    def _dt(val: str | None) -> datetime | None:
        if val is None:
            return None
        try:
            return datetime.fromisoformat(val)
        except Exception:
            return None

    return SessionRecord(
        session_id=data["session_id"],
        operation=data.get("operation", "unknown"),
        status=data.get("status", "unknown"),
        created_at=_dt(data.get("created_at")) or _now(),
        started_at=_dt(data.get("started_at")),
        completed_at=_dt(data.get("completed_at")),
        result=data.get("result"),
        error=data.get("error"),
    )


@dataclass
class SessionRecord:
    """Single tracked background job."""

    session_id: str
    operation: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "operation": self.operation,
            "status": self.status,
            "created_at": _serialize(self.created_at),
            "started_at": _serialize(self.started_at),
            "completed_at": _serialize(self.completed_at),
            "result": self.result,
            "error": self.error,
        }


class SessionStore:
    """Disk-backed store keyed by session_id.

    Sessions are written to ``store_path`` on every mutation so they
    survive uvicorn --reload restarts. A threading lock keeps concurrent
    writes safe.
    """

    def __init__(self, store_path: Path | None = None) -> None:
        self._store_path = store_path
        self._lock = threading.Lock()
        self._sessions: dict[str, SessionRecord] = {}
        if self._store_path is not None:
            self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._store_path is None or not self._store_path.exists():
            return
        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8"))
            for item in raw if isinstance(raw, list) else []:
                try:
                    rec = _deserialize_record(item)
                    self._sessions[rec.session_id] = rec
                except Exception as exc:
                    logger.warning("Skipping malformed session record: %s", exc)
        except Exception as exc:
            logger.error("Failed to load session store from %s: %s", self._store_path, exc)

    def _flush(self) -> None:
        if self._store_path is None:
            return
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            payload = [rec.to_dict() for rec in self._sessions.values()]
            tmp = self._store_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self._store_path)
        except Exception as exc:
            logger.error("Failed to persist session store to %s: %s", self._store_path, exc)

    # ── public API ───────────────────────────────────────────────────────────

    def create(self, operation: str) -> SessionRecord:
        record = SessionRecord(
            session_id=str(uuid.uuid4()),
            operation=operation,
            status="queued",
            created_at=_now(),
        )
        with self._lock:
            self._sessions[record.session_id] = record
            self._flush()
        return record

    def get(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            return self._sessions.get(session_id)

    def update(self, session_id: str, **kwargs: Any) -> SessionRecord | None:
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                return None
            for key, value in kwargs.items():
                setattr(record, key, value)
            self._flush()
        return record

    def list_all(self) -> list[SessionRecord]:
        with self._lock:
            return list(self._sessions.values())
