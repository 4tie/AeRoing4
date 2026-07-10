"""Shared Ollama transport types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OllamaConfig:
    """Resolved Ollama connection settings."""

    base_url: str
    model: str
    provider: str = "local"
    api_key: str | None = None
    timeout: float = 30.0
    health_timeout: float = 5.0
    strict_json: bool = False
    log_dir: str | None = None
    # Reliability settings
    retry_delays: list[float] = (2, 5, 10, 15)
    circuit_breaker_threshold: int = 5
    circuit_breaker_cooldown: int = 300
    connection_pool_size: int = 10
    connection_keepalive: int = 30

    @property
    def auth_api_key(self) -> str | None:
        return self.api_key if self.provider == "ollama_cloud" else None

    @property
    def cache_key(self) -> tuple[Any, ...]:
        return (
            self.base_url.rstrip("/"),
            self.model,
            self.provider,
            bool(self.auth_api_key),
            self.timeout,
            self.health_timeout,
            self.strict_json,
            self.log_dir,
            self.connection_pool_size,
            self.connection_keepalive,
        )


@dataclass
class OllamaChatResponse:
    """Normalized response from Ollama /api/chat."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] | None = None

