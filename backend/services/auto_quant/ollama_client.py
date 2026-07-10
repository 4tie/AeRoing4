"""Ollama client creation functions."""

import logging

from ..ai.ollama_client import OllamaClient
from ..ai.ollama_config import config_from_user_data_dir

logger = logging.getLogger(__name__)


def create_ollama_client_from_settings(
    user_data_dir: str,
    timeout: int | None = None,
    health_timeout: int = 5,
    strict_json: bool = True,
    log_dir: str | None = None,
) -> OllamaClient | None:
    """Create OllamaClient instance by reading from settings file.
    
    This helper function reads Ollama configuration from the settings file
    (data/strategy_lab_settings.json) and creates an OllamaClient instance.
    
    Args:
        user_data_dir: Path to user_data directory containing settings file
        timeout: Timeout in seconds for generate requests (overrides settings if provided)
        health_timeout: Timeout in seconds for health checks
        strict_json: Whether to use format="json" parameter
        log_dir: Directory to store prompt/response logs
        
    Returns:
        OllamaClient instance or None if settings cannot be read
    """
    try:
        config = config_from_user_data_dir(
            user_data_dir,
            timeout=timeout,
            health_timeout=health_timeout,
            strict_json=strict_json,
            log_dir=log_dir,
        )
        if config is None:
            return None
        logger.info(
            "Creating shared OllamaClient from settings: base_url=%s, model=%s, timeout=%s, provider=%s",
            config.base_url,
            config.model,
            config.timeout,
            config.provider,
        )
        return OllamaClient(config=config)
    except Exception as e:
        logger.warning(f"Failed to create OllamaClient from settings: {e}")
        return None


def create_strategy_lab_client(
    user_data_dir: str,
    timeout: int | None = None,
    health_timeout: int = 5,
    strict_json: bool = True,
    log_dir: str | None = None,
) -> OllamaClient | None:
    """Create OllamaClient instance specifically for Strategy Lab using ollama_model_strategylab.
    
    This helper function reads Ollama configuration from the settings file
    and creates an OllamaClient instance configured with the strategy lab model override.
    
    Args:
        user_data_dir: Path to user_data directory containing settings file
        timeout: Timeout in seconds for generate requests (overrides settings if provided)
        health_timeout: Timeout in seconds for health checks
        strict_json: Whether to use format="json" parameter
        log_dir: Directory to store prompt/response logs
        
    Returns:
        OllamaClient instance or None if settings cannot be read
    """
    try:
        config = config_from_user_data_dir(
            user_data_dir,
            model_override="ollama_model_strategylab",
            timeout=timeout,
            health_timeout=health_timeout,
            strict_json=strict_json,
            log_dir=log_dir,
        )
        if config is None:
            return None
        logger.info(
            "Creating Strategy Lab OllamaClient: base_url=%s, model=%s, timeout=%s, provider=%s",
            config.base_url,
            config.model,
            config.timeout,
            config.provider,
        )
        return OllamaClient(config=config)
    except Exception as e:
        logger.warning(f"Failed to create Strategy Lab OllamaClient from settings: {e}")
        return None
