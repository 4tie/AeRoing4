"""Shared Ollama error handling helpers."""

from __future__ import annotations

import json
from typing import Any

import httpx


def friendly_ollama_error(exc: Exception) -> str:
    """Return a user-facing error string for common Ollama failures."""
    if isinstance(exc, httpx.ConnectError):
        return "Ollama Offline: could not connect to the configured Ollama API URL."
    if isinstance(exc, httpx.TimeoutException):
        return "Ollama timed out. Try a smaller model or increase the timeout in Settings."
    if isinstance(exc, httpx.HTTPStatusError):
        detail = f"Ollama returned HTTP {exc.response.status_code}."
        try:
            payload = exc.response.json()
            if isinstance(payload, dict) and payload.get("error"):
                detail = str(payload["error"])
        except Exception:
            pass
        return detail
    if isinstance(exc, json.JSONDecodeError):
        return "Ollama returned non-JSON."
    return str(exc)


def ollama_status_code(exc: Exception) -> int:
    """Map transport exceptions to HTTP status codes."""
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
        return 503
    if isinstance(exc, (httpx.HTTPStatusError, json.JSONDecodeError)):
        return 502
    return 500


def response_error_text(response: Any, fallback: str) -> str:
    """Extract a helpful error from a response object."""
    try:
        payload = response.json()
        if isinstance(payload, dict) and payload.get("error"):
            return str(payload["error"])
    except Exception:
        pass
    try:
        text = response.text
        if text:
            return str(text)
    except Exception:
        pass
    return fallback

