"""Session manager for AI agent sessions with disk persistence."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SessionManager:
    """Session manager for AI agent sessions with disk persistence."""
    
    def __init__(self, user_data_dir: str | None = None):
        self.sessions: dict[str, dict[str, Any]] = {}
        self.user_data_dir = Path(user_data_dir) if user_data_dir else None
        self.logs_dir = self._init_logs_dir()
    
    def _init_logs_dir(self) -> Path | None:
        """Initialize logs directory."""
        if not self.user_data_dir:
            return None
        logs_dir = self.user_data_dir / "ai_agent_logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir
    
    def create_session(self, ai_model: str | None = None) -> str:
        """Create a new session and return its ID."""
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "logs": [],
            "tool_calls": [],
            "status": "active",
            "ai_model": ai_model or "unknown"
        }
        self._persist_session(session_id)
        return session_id
    
    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get session data by ID."""
        return self.sessions.get(session_id)
    
    def add_log(self, session_id: str, log_entry: dict[str, Any]) -> None:
        """Add a log entry to a session."""
        if session_id in self.sessions:
            log_entry["timestamp"] = log_entry.get("timestamp", datetime.now(timezone.utc).isoformat())
            self.sessions[session_id]["logs"].append(log_entry)
            self._persist_log(session_id, log_entry)
    
    def add_tool_call(self, session_id: str, tool_call: dict[str, Any]) -> None:
        """Add a tool call record to a session."""
        if session_id in self.sessions:
            tool_call["timestamp"] = tool_call.get("timestamp", datetime.now(timezone.utc).isoformat())
            self.sessions[session_id]["tool_calls"].append(tool_call)
            self._persist_log(session_id, tool_call)
    
    def _persist_session(self, session_id: str) -> None:
        """Persist session metadata to disk."""
        if not self.logs_dir:
            return
        try:
            session_file = self.logs_dir / f"session_{session_id}.json"
            session_data = self.sessions[session_id]
            session_file.write_text(json.dumps(session_data, indent=2), encoding="utf-8")
        except Exception:
            pass
    
    def _persist_log(self, session_id: str, log_entry: dict[str, Any]) -> None:
        """Persist a log entry to disk in JSONL format."""
        if not self.logs_dir:
            return
        try:
            log_file = self.logs_dir / f"session_{session_id}.jsonl"
            log_entry["session_id"] = session_id
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass
    
    def load_session(self, session_id: str) -> dict[str, Any] | None:
        """Load session from disk."""
        if not self.logs_dir:
            return None
        try:
            session_file = self.logs_dir / f"session_{session_id}.json"
            if session_file.exists():
                data = json.loads(session_file.read_text(encoding="utf-8"))
                self.sessions[session_id] = data
                return data
        except Exception:
            pass
        return None


# Global session manager (will be initialized with user_data_dir in lifespan)
_session_manager: SessionManager | None = None


def get_session_manager(request=None) -> SessionManager:
    """Get the session manager instance.
    
    If request is provided and app.state.ai_agent_session_manager exists, use that.
    Otherwise, fall back to the global instance.
    """
    if request and hasattr(request.app.state, "ai_agent_session_manager"):
        return request.app.state.ai_agent_session_manager
    
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
