"""Request/Response schemas for AI agent router."""

from typing import Any

from pydantic import BaseModel, Field


class ToolExecutionRequest(BaseModel):
    session_id: str | None = Field(None, description="Session ID for tracking")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Tool parameters")


class ToolExecutionResponse(BaseModel):
    success: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    logs: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message to the AI agent")
    session_id: str | None = Field(None, description="Session ID for tracking")
    model: str | None = Field(None, description="Ollama model to use (optional)")


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
