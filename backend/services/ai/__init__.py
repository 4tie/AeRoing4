"""AI services module.

Provides centralized AI client management and Ollama transport helpers.
"""

from .ai_service import AIService, cleanup_ai_service, get_ai_service
from .ollama_client import CircuitBreaker, OllamaClient, build_headers
from .ollama_config import config_from_settings, config_from_user_data_dir
from .ollama_errors import friendly_ollama_error, ollama_status_code
from .ollama_types import OllamaChatResponse, OllamaConfig

__all__ = [
    "AIService",
    "CircuitBreaker",
    "OllamaChatResponse",
    "OllamaClient",
    "OllamaConfig",
    "build_headers",
    "cleanup_ai_service",
    "config_from_settings",
    "config_from_user_data_dir",
    "friendly_ollama_error",
    "get_ai_service",
    "ollama_status_code",
]
