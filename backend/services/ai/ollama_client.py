"""Shared async Ollama client used by assistant, agent, and AutoQuant code."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .ollama_errors import response_error_text
from .ollama_types import OllamaChatResponse, OllamaConfig

logger = logging.getLogger(__name__)

SleepFunc = Callable[[float], Awaitable[None]]


class CircuitBreaker:
    """Small circuit breaker for repeated Ollama transport failures."""

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: int = 300) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failure_count = 0
        self.last_failure_time: datetime | None = None
        self.state = "closed"
        self.total_failures = 0
        self.total_successes = 0

    def record_failure(self) -> None:
        self.failure_count += 1
        self.total_failures += 1
        self.last_failure_time = datetime.now(timezone.utc)
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(
                "Ollama circuit breaker opened after %s failures for %ss",
                self.failure_count,
                self.cooldown_seconds,
            )

    def record_success(self) -> None:
        self.failure_count = 0
        self.total_successes += 1
        self.last_failure_time = None
        self.state = "closed"
        # Reset total failures on success to clear accumulated state
        if self.total_failures > 0:
            logger.info("Circuit breaker reset: clearing accumulated failures after successful call")
            self.total_failures = 0

    def should_allow_call(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if self.last_failure_time is None:
                return False
            elapsed = (datetime.now(timezone.utc) - self.last_failure_time).total_seconds()
            if elapsed >= self.cooldown_seconds:
                self.state = "half-open"
                return True
            return False
        return self.state == "half-open"

    def get_state_info(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "cooldown_seconds": self.cooldown_seconds,
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
        }


def build_headers(base_url: str, *, include_content_type: bool = False, api_key: str | None = None) -> dict[str, str]:
    parsed = urlparse(base_url)
    host = parsed.netloc or parsed.path
    headers = {"Host": host, "Accept": "application/json"}
    if include_content_type:
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _normalize_tool_call(tool_call: Any) -> dict[str, Any] | None:
    if tool_call is None:
        return None
    if isinstance(tool_call, dict):
        function = tool_call.get("function")
        if isinstance(function, dict):
            return {
                "name": function.get("name") or tool_call.get("name"),
                "arguments": function.get("arguments") or {},
            }
        return {
            "name": tool_call.get("name"),
            "arguments": tool_call.get("arguments") or {},
        }
    function = getattr(tool_call, "function", None)
    if function is not None:
        return {
            "name": getattr(function, "name", None),
            "arguments": getattr(function, "arguments", {}) or {},
        }
    return None


class OllamaClient:
    """One async transport for Ollama generate, chat, streaming, and models."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str = "",
        timeout: int | float = 30,
        health_timeout: int | float = 5,
        strict_json: bool = False,
        log_dir: str | None = None,
        api_key: str | None = None,
        *,
        config: OllamaConfig | None = None,
        retry_delays: list[float] | None = None,
        sleep: SleepFunc = asyncio.sleep,
        circuit_breaker: CircuitBreaker | None = None,
        connection_pool_size: int = 10,
        connection_keepalive: int = 30,
    ) -> None:
        if config is not None:
            base_url = config.base_url
            model = config.model
            timeout = config.timeout
            health_timeout = config.health_timeout
            strict_json = config.strict_json
            log_dir = config.log_dir
            api_key = config.auth_api_key
            # Use reliability settings from config if provided
            retry_delays = retry_delays if retry_delays is not None else list(config.retry_delays)
            circuit_breaker = circuit_breaker or CircuitBreaker(
                failure_threshold=config.circuit_breaker_threshold,
                cooldown_seconds=config.circuit_breaker_cooldown
            )
            connection_pool_size = config.connection_pool_size
            connection_keepalive = config.connection_keepalive
        self.base_url = str(base_url or "http://localhost:11434").rstrip("/")
        self.model = model
        self.timeout = float(timeout)
        self.health_timeout = float(health_timeout)
        self.strict_json = strict_json
        self.log_dir = log_dir
        self.api_key = api_key
        self.retry_delays = retry_delays if retry_delays is not None else [2, 5, 10, 15]
        self._sleep = sleep
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.connection_pool_size = connection_pool_size
        self.connection_keepalive = connection_keepalive
        self._client: httpx.AsyncClient | None = None
        self._metrics: dict[str, Any] = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_latency_ms": 0,
        }

    @property
    def cache_key(self) -> tuple[Any, ...]:
        return (
            self.base_url,
            self.model,
            bool(self.api_key),
            self.timeout,
            self.health_timeout,
            self.strict_json,
            self.log_dir,
            self.connection_pool_size,
            self.connection_keepalive,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(
                max_connections=self.connection_pool_size,
                max_keepalive_connections=self.connection_pool_size,
                keepalive_expiry=self.connection_keepalive,
            )
            self._client = httpx.AsyncClient(
                timeout=self.timeout + 10,
                headers=build_headers(self.base_url, api_key=self.api_key),
                limits=limits,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    def get_metrics(self) -> dict[str, Any]:
        """Get current metrics for monitoring."""
        return {
            "circuit_breaker": self.circuit_breaker.get_state_info(),
            "client_metrics": self._metrics.copy(),
            "success_rate": (
                self._metrics["successful_requests"] / self._metrics["total_requests"]
                if self._metrics["total_requests"] > 0
                else 0
            ),
            "average_latency_ms": (
                self._metrics["total_latency_ms"] / self._metrics["successful_requests"]
                if self._metrics["successful_requests"] > 0
                else 0
            ),
        }

    def _record_request_start(self) -> float:
        """Record request start time and increment total requests."""
        self._metrics["total_requests"] += 1
        return time.time()

    def _record_request_success(self, start_time: float) -> None:
        """Record successful request metrics."""
        duration_ms = (time.time() - start_time) * 1000
        self._metrics["successful_requests"] += 1
        self._metrics["total_latency_ms"] += duration_ms

    def _record_request_failure(self) -> None:
        """Record failed request metrics."""
        self._metrics["failed_requests"] += 1

    async def _retry(self, func: Callable[[], Awaitable[Any]]) -> Any:
        last_exc: Exception | None = None
        attempts = max(1, len(self.retry_delays) + 1)
        for attempt in range(attempts):
            try:
                return await func()
            except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError, asyncio.TimeoutError) as exc:
                last_exc = exc
                if attempt >= attempts - 1:
                    break
                delay = self.retry_delays[min(attempt, len(self.retry_delays) - 1)]
                if delay > 0:
                    await self._sleep(delay)
        if last_exc:
            raise last_exc
        raise RuntimeError("Ollama retry failed without an exception")

    async def health(self) -> dict[str, Any]:
        start = time.time()
        try:
            client = await self._get_client()
            resp = await client.get(
                f"{self.base_url}/api/tags",
                timeout=self.health_timeout,
                headers=build_headers(self.base_url, api_key=self.api_key),
            )
            resp.raise_for_status()
            try:
                data = resp.json()
                model_count = len(data.get("models", [])) if isinstance(data, dict) else 0
            except json.JSONDecodeError:
                model_count = 0
            return {
                "status": "healthy",
                "healthy": True,
                "reachable": True,
                "latency_ms": round((time.time() - start) * 1000, 2),
                "model_count": model_count,
                "ollama_api_url": self.base_url,
            }
        except httpx.ConnectError:
            error = "Connection refused - Ollama may not be running"
        except httpx.TimeoutException:
            error = f"Timeout after {self.health_timeout}s - Ollama may be overloaded"
        except Exception as exc:
            error = str(exc)
        return {
            "status": "unhealthy",
            "reachable": False,
            "latency_ms": round((time.time() - start) * 1000, 2),
            "error": error,
            "ollama_api_url": self.base_url,
        }

    async def check_health(self) -> bool:
        return bool((await self.health()).get("reachable"))

    async def list_models(self) -> dict[str, Any]:
        try:
            client = await self._get_client()
            resp = await client.get(
                f"{self.base_url}/api/tags",
                timeout=self.health_timeout,
                headers=build_headers(self.base_url, api_key=self.api_key),
            )
            resp.raise_for_status()
            try:
                data = resp.json()
            except json.JSONDecodeError:
                return {
                    "models": [],
                    "reachable": False,
                    "ollama_api_url": self.base_url,
                    "error": "Ollama returned non-JSON - check the URL is correct.",
                }
        except httpx.ConnectError:
            return {
                "models": [],
                "reachable": False,
                "ollama_api_url": self.base_url,
                "error": "Could not connect to Ollama. Make sure it is running and the URL is correct.",
            }
        except httpx.TimeoutException:
            return {
                "models": [],
                "reachable": False,
                "ollama_api_url": self.base_url,
                "error": f"Ollama did not respond within {self.health_timeout} seconds. It may be busy or unreachable. Try increasing the timeout in Settings.",
            }
        except Exception as exc:
            return {
                "models": [],
                "reachable": False,
                "ollama_api_url": self.base_url,
                "error": str(exc),
            }
        raw_models = data.get("models", []) if isinstance(data, dict) else []
        names = sorted(m.get("name", "") for m in raw_models if isinstance(m, dict) and m.get("name"))
        return {"models": names, "reachable": True, "ollama_api_url": self.base_url}

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        feature: str = "default",
        *,
        model: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> str | None:
        if not prompt or not isinstance(prompt, str):
            logger.error("Invalid prompt for feature '%s': must be non-empty string", feature)
            return None
        if not (model or self.model):
            logger.error("No Ollama model configured for feature '%s'", feature)
            return None
        if not self.circuit_breaker.should_allow_call():
            logger.warning("Ollama circuit breaker is open; skipping feature '%s'", feature)
            return None

        start = self._record_request_start()
        payload: dict[str, Any] = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if options:
            payload["options"] = options
        if self.strict_json:
            payload["format"] = "json"

        try:
            async def _call() -> httpx.Response:
                client = await self._get_client()
                return await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=self.timeout,
                    headers=build_headers(self.base_url, include_content_type=True, api_key=self.api_key),
                )

            resp = await self._retry(_call)
            if resp.status_code != 200:
                error = response_error_text(resp, f"HTTP {resp.status_code}")
                logger.warning("Ollama generate returned %s: %s", resp.status_code, error)
                self._log_interaction(feature, prompt, system_prompt, None, int((time.time() - start) * 1000), False, error)
                self.circuit_breaker.record_failure()
                self._record_request_failure()
                return None
            data = resp.json()
            result = data.get("response", "") if isinstance(data, dict) else ""
            if not result:
                self._log_interaction(feature, prompt, system_prompt, None, int((time.time() - start) * 1000), False, "Empty response")
                self._record_request_failure()
                return None
            self._log_interaction(feature, prompt, system_prompt, result, int((time.time() - start) * 1000), True, None)
            self.circuit_breaker.record_success()
            self._record_request_success(start)
            return str(result)
        except Exception as exc:
            logger.warning("Ollama generate failed for feature '%s': %s", feature, exc)
            self._log_interaction(feature, prompt, system_prompt, None, int((time.time() - start) * 1000), False, str(exc))
            self.circuit_breaker.record_failure()
            self._record_request_failure()
            return None

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        stream: bool = False,
        options: dict[str, Any] | None = None,
    ) -> OllamaChatResponse:
        if stream:
            raise ValueError("Use stream_chat for streaming responses")
        if not (model or self.model):
            raise RuntimeError("No Ollama model configured")

        start = self._record_request_start()
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        if options:
            payload["options"] = options

        try:
            async def _call() -> httpx.Response:
                client = await self._get_client()
                return await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=self.timeout,
                    headers=build_headers(self.base_url, include_content_type=True, api_key=self.api_key),
                )

            resp = await self._retry(_call)
            resp.raise_for_status()
            data = resp.json()
            message = data.get("message", {}) if isinstance(data, dict) else {}
            raw_tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
            tool_calls = [
                item for item in (_normalize_tool_call(call) for call in (raw_tool_calls or []))
                if item and item.get("name")
            ]
            content = message.get("content", "") if isinstance(message, dict) else ""
            if not content and isinstance(data, dict):
                content = data.get("response", "")
            self.circuit_breaker.record_success()
            self._record_request_success(start)
            return OllamaChatResponse(content=str(content or ""), tool_calls=tool_calls, raw=data if isinstance(data, dict) else None)
        except Exception as exc:
            self.circuit_breaker.record_failure()
            self._record_request_failure()
            raise

    async def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        feature: str = "chat_with_tools",
    ) -> OllamaChatResponse:
        start = self._record_request_start()
        try:
            result = await self.chat(messages, tools=tools, model=model)
            self._log_interaction(feature, str(messages), None, result.content, int((time.time() - start) * 1000), True, None)
            return result
        except Exception as exc:
            self._log_interaction(feature, str(messages), None, None, int((time.time() - start) * 1000), False, str(exc))
            logger.warning("Ollama chat failed for feature '%s': %s", feature, exc)
            return OllamaChatResponse(content=str(exc), tool_calls=[])

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        start = self._record_request_start()
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": True,
        }
        if options:
            payload["options"] = options

        try:
            client = await self._get_client()
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
                headers=build_headers(self.base_url, include_content_type=True, api_key=self.api_key),
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    yield json.loads(line)
            self.circuit_breaker.record_success()
            self._record_request_success(start)
        except Exception as exc:
            self.circuit_breaker.record_failure()
            self._record_request_failure()
            raise

    def _log_interaction(
        self,
        feature: str,
        prompt: str,
        system_prompt: str | None,
        response: str | None,
        duration_ms: int,
        success: bool,
        error: str | None,
    ) -> None:
        if not self.log_dir:
            return
        try:
            log_path = Path(self.log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "feature": feature,
                "model": self.model,
                "prompt": prompt,
                "system_prompt": system_prompt,
                "response": response,
                "duration_ms": duration_ms,
                "success": success,
                "error": error,
            }
            with (log_path / "ollama_interactions.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        except Exception as exc:
            logger.warning("Failed to log Ollama interaction: %s", exc)

