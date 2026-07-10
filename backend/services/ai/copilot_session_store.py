"""Copilot session store - unified session management for AI copilot.

This replaces the split between AssistantService sessions and ai_agent session_manager.
Provides persistent storage for conversation state, tool runs, pending actions,
and active job references.

Compatible with existing assistant_chat_session_v1 format.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...utils import atomic_write_json, read_json


COPILOT_SESSION_SCHEMA = "assistant_copilot_session_v2"
ASSISTANT_CHAT_SCHEMA = "assistant_chat_session_v1"


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


class CopilotSessionStore:
    """Persistent store for copilot conversation and tool state."""

    def __init__(self, user_data_dir: Path | str):
        self.user_data_dir = Path(user_data_dir)
        self.session_dir = self.user_data_dir / "assistant" / "chat_sessions"
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def create_session(
        self,
        model: str,
        title: str | None = None,
        mode: str = "analysis",
    ) -> dict[str, Any]:
        """Create a new copilot session."""
        session_id = str(uuid.uuid4())
        now = _now()
        return {
            "schema_version": COPILOT_SESSION_SCHEMA,
            "session_id": session_id,
            "created_at": now,
            "updated_at": now,
            "model": model,
            "mode": mode,
            "title": title or "AI Copilot Chat",
            "messages": [],
            "tool_runs": [],
            "pending_actions": [],
            "active_jobs": [],
            "last_context_summary": None,
            "last_context_overrides": {},
        }

    def load_session(self, session_id: str) -> dict[str, Any]:
        """Load a session by ID, with compatibility migration for v1."""
        path = self.session_dir / f"{session_id}.json"
        data = read_json(path)
        
        if not isinstance(data, dict):
            raise ValueError(f"Session '{session_id}' is not a valid dict")
        
        # Migrate from v1 to v2 if needed
        if data.get("schema_version") == ASSISTANT_CHAT_SCHEMA:
            data = self._migrate_v1_to_v2(data)
        
        # Ensure v2 structure
        if data.get("schema_version") != COPILOT_SESSION_SCHEMA:
            data = self._ensure_v2_structure(data)
        
        return data

    def save_session(self, session: dict[str, Any]) -> None:
        """Save a session atomically."""
        session["updated_at"] = _now()
        atomic_write_json(self.session_dir / f"{session['session_id']}.json", session)

    def add_message(
        self,
        session: dict[str, Any],
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
    ) -> dict[str, Any]:
        """Add a message to the session."""
        message = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "created_at": _now(),
        }
        if tool_calls:
            message["tool_calls"] = tool_calls
        if tool_call_id:
            message["tool_call_id"] = tool_call_id
        
        session.setdefault("messages", []).append(message)
        return message

    def add_tool_run(self, session: dict[str, Any], tool_run: dict[str, Any]) -> None:
        """Add a tool run record to the session."""
        session.setdefault("tool_runs", []).append(tool_run)

    def add_pending_action(self, session: dict[str, Any], action: dict[str, Any]) -> None:
        """Add a pending action awaiting confirmation."""
        session.setdefault("pending_actions", []).append(action)

    def remove_pending_action(self, session: dict[str, Any], action_id: str) -> bool:
        """Remove a pending action by ID. Returns True if found and removed."""
        pending = session.get("pending_actions", [])
        original_len = len(pending)
        session["pending_actions"] = [a for a in pending if a.get("action_id") != action_id]
        return len(session["pending_actions"]) < original_len

    def get_pending_action(self, session: dict[str, Any], action_id: str) -> dict[str, Any] | None:
        """Get a pending action by ID."""
        for action in session.get("pending_actions", []):
            if action.get("action_id") == action_id:
                return action
        return None

    def add_active_job(self, session: dict[str, Any], job_ref: dict[str, Any]) -> None:
        """Add or update an active job reference."""
        active_jobs = session.setdefault("active_jobs", [])
        # Remove existing job of same type if present
        active_jobs = [j for j in active_jobs if j.get("job_type") != job_ref.get("job_type")]
        active_jobs.append(job_ref)
        session["active_jobs"] = active_jobs

    def update_job_status(self, session: dict[str, Any], job_type: str, status: str) -> None:
        """Update status of an active job by type."""
        for job in session.get("active_jobs", []):
            if job.get("job_type") == job_type:
                job["status"] = status
                if status in ("completed", "failed", "cancelled"):
                    job["completed_at"] = _now()

    def remove_completed_jobs(self, session: dict[str, Any]) -> None:
        """Remove jobs that are in terminal states."""
        session["active_jobs"] = [
            j for j in session.get("active_jobs", [])
            if j.get("status") not in ("completed", "failed", "cancelled")
        ]

    def _migrate_v1_to_v2(self, v1_session: dict[str, Any]) -> dict[str, Any]:
        """Migrate assistant_chat_session_v1 to assistant_copilot_session_v2."""
        return {
            "schema_version": COPILOT_SESSION_SCHEMA,
            "session_id": v1_session.get("session_id"),
            "created_at": v1_session.get("created_at", _now()),
            "updated_at": v1_session.get("updated_at", _now()),
            "model": v1_session.get("model"),
            "mode": v1_session.get("mode", "analysis"),
            "title": v1_session.get("title", "AI Copilot Chat"),
            "messages": v1_session.get("messages", []),
            "tool_runs": [],
            "pending_actions": [],
            "active_jobs": [],
            "last_context_summary": v1_session.get("last_context_summary"),
            "last_context_overrides": v1_session.get("last_context_overrides", {}),
        }

    def _ensure_v2_structure(self, session: dict[str, Any]) -> dict[str, Any]:
        """Ensure session has v2 structure, filling missing fields with defaults."""
        defaults = {
            "schema_version": COPILOT_SESSION_SCHEMA,
            "mode": "analysis",
            "title": "AI Copilot Chat",
            "tool_runs": [],
            "pending_actions": [],
            "active_jobs": [],
            "last_context_overrides": {},
        }
        for key, default_value in defaults.items():
            if key not in session:
                session[key] = default_value
        return session

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all sessions with metadata."""
        sessions = []
        for path in self.session_dir.glob("*.json"):
            try:
                data = read_json(path)
                if isinstance(data, dict):
                    sessions.append({
                        "session_id": data.get("session_id"),
                        "title": data.get("title"),
                        "model": data.get("model"),
                        "mode": data.get("mode"),
                        "created_at": data.get("created_at"),
                        "updated_at": data.get("updated_at"),
                        "message_count": len(data.get("messages", [])),
                    })
            except Exception:
                continue
        return sorted(sessions, key=lambda s: s.get("updated_at", ""), reverse=True)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session by ID. Returns True if deleted."""
        path = self.session_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False
