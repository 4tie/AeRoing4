"""Resolve Ollama settings from app settings or user_data."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .ollama_types import OllamaConfig

logger = logging.getLogger(__name__)


def _get(settings: Any, key: str, default: Any = None) -> Any:
    if isinstance(settings, dict):
        return settings.get(key, default)
    return getattr(settings, key, default)


def config_from_settings(
    settings: Any,
    *,
    model_override: str | None = None,
    timeout: int | float | None = None,
    health_timeout: int | float = 5,
    strict_json: bool = False,
    log_dir: str | None = None,
    require_model: bool = True,
) -> OllamaConfig | None:
    """Build an OllamaConfig from a SettingsModel-like object or dict."""
    if settings is None:
        return None

    base_url = str(_get(settings, "ollama_api_url", "http://localhost:11434") or "").strip()

    # Handle model_override: can be a key name (e.g., "ollama_model_strategylab") or a direct model name
    if model_override is not None and model_override.startswith("ollama_model_"):
        # model_override is a settings key name
        model = str(_get(settings, model_override, "") or "").strip()
    elif model_override is not None:
        # model_override is a direct model name
        model = str(model_override).strip()
    else:
        # Use default ollama_model
        model = str(_get(settings, "ollama_model", "") or "").strip()

    provider = str(_get(settings, "ollama_provider", "local") or "local").strip()
    raw_api_key = str(_get(settings, "ollama_api_key", "") or "").strip()
    resolved_timeout = timeout if timeout is not None else _get(settings, "ollama_timeout", 30)

    # Reliability settings
    retry_delays = _get(settings, "ollama_retry_delays", [2, 5, 10, 15]) or [2, 5, 10, 15]
    circuit_breaker_threshold = _get(settings, "ollama_circuit_breaker_threshold", 5) or 5
    circuit_breaker_cooldown = _get(settings, "ollama_circuit_breaker_cooldown", 300) or 300
    connection_pool_size = _get(settings, "ollama_connection_pool_size", 10) or 10
    connection_keepalive = _get(settings, "ollama_connection_keepalive", 30) or 30

    if not base_url:
        logger.warning("Ollama API URL is not configured")
        return None
    if require_model and not model:
        logger.warning("Ollama model is not configured")
        return None

    api_key = raw_api_key if provider == "ollama_cloud" else None
    return OllamaConfig(
        base_url=base_url.rstrip("/"),
        model=model,
        provider=provider,
        api_key=api_key,
        timeout=float(resolved_timeout or 30),
        health_timeout=float(health_timeout or 5),
        strict_json=bool(strict_json),
        log_dir=log_dir,
        retry_delays=tuple(retry_delays) if isinstance(retry_delays, list) else retry_delays,
        circuit_breaker_threshold=int(circuit_breaker_threshold),
        circuit_breaker_cooldown=int(circuit_breaker_cooldown),
        connection_pool_size=int(connection_pool_size),
        connection_keepalive=int(connection_keepalive),
    )


def load_settings_dict(user_data_dir: str | Path) -> dict[str, Any] | None:
    settings_file = Path(user_data_dir) / "strategy_lab_settings.json"
    if not settings_file.exists():
        logger.warning("Settings file not found: %s", settings_file)
        return None
    try:
        return json.loads(settings_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read Ollama settings from %s: %s", settings_file, exc)
        return None


def config_from_user_data_dir(
    user_data_dir: str | Path,
    *,
    model_override: str | None = None,
    timeout: int | float | None = None,
    health_timeout: int | float = 5,
    strict_json: bool = False,
    log_dir: str | None = None,
    require_model: bool = True,
) -> OllamaConfig | None:
    """Build an OllamaConfig from data/strategy_lab_settings.json."""
    settings = load_settings_dict(user_data_dir)
    if settings is None:
        return None
    if log_dir is None:
        log_dir = str(Path(user_data_dir) / "data" / "ai")
    return config_from_settings(
        settings,
        model_override=model_override,
        timeout=timeout,
        health_timeout=health_timeout,
        strict_json=strict_json,
        log_dir=log_dir,
        require_model=require_model,
    )


def resolve_user_data_dir(value: Any) -> str:
    """Accept a path string or SettingsModel-like object and return user_data path."""
    if isinstance(value, (str, Path)):
        return str(value)
    path = _get(value, "user_data_directory_path", None)
    if path:
        return str(path)
    raise TypeError("Expected user_data directory path or settings with user_data_directory_path")
