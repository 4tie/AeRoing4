"""Discovery endpoints for AI agent router."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from .constants import SYSTEM_PROMPT, TOOLS
from .session_manager import get_session_manager


def register_discovery_endpoints(router: APIRouter) -> None:
    """Register discovery endpoints on the given router."""
    
    @router.get(
        "/tools",
        summary="Discover available AI agent tools",
        description="Returns all available tools with their schemas and the system prompt for the AutoQuant workflow.",
    )
    async def get_tools() -> dict:
        """Return all available tools with schemas."""
        return {
            "tools": TOOLS,
            "system_prompt": SYSTEM_PROMPT,
            "version": "1.0.0"
        }

    @router.get(
        "/sessions/{session_id}",
        summary="Get session status and logs",
        description="Retrieve the current status, logs, and tool calls for a specific session.",
    )
    async def get_session(session_id: str) -> dict:
        """Get session data by ID."""
        session = get_session_manager().get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        return session

    @router.post(
        "/sessions",
        summary="Create a new AI agent session",
        description="Create a new session for tracking AI agent workflow execution.",
    )
    async def create_session(request: Request) -> dict:
        """Create a new session."""
        ai_model = request.headers.get("X-AI-Model")  # Optional header to identify the AI model
        session_id = get_session_manager().create_session(ai_model=ai_model)
        return {
            "session_id": session_id,
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ai_model": ai_model or "unknown"
        }
