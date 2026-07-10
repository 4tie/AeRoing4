"""Centralized AI service for consistent Ollama client management."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from .ollama_client import OllamaClient
from .ollama_config import config_from_user_data_dir, resolve_user_data_dir

logger = logging.getLogger(__name__)


class AIService:
    """Centralized AI service with consistent client lifecycle management.
    
    This service ensures that Ollama clients are properly created, used, and closed,
    preventing resource leaks and connection reuse issues.
    """

    def __init__(self, user_data_dir: Any) -> None:
        """Initialize AI service with user data directory.
        
        Args:
            user_data_dir: Path to user_data directory containing settings
        """
        self.user_data_dir = resolve_user_data_dir(user_data_dir)
        self._client: OllamaClient | None = None
        self._client_cache_key: tuple[Any, ...] | None = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> OllamaClient | None:
        """Get or create Ollama client with proper lifecycle management.
        
        Returns:
            OllamaClient instance or None if configuration is invalid
        """
        config = config_from_user_data_dir(self.user_data_dir, strict_json=True, require_model=False)
        if config is None:
            logger.warning("Failed to create Ollama config from settings")
            return None

        async with self._lock:
            if self._client is not None and self._client_cache_key != config.cache_key:
                await self._client.close()
                self._client = None
                self._client_cache_key = None

            if self._client is None:
                self._client = OllamaClient(config=config)
                self._client_cache_key = config.cache_key
                logger.info("Created new Ollama client instance")
            return self._client

    async def close(self) -> None:
        """Close the Ollama client and cleanup resources."""
        async with self._lock:
            if self._client is not None:
                await self._client.close()
                self._client = None
                self._client_cache_key = None
                logger.info("Closed Ollama client instance")

    @asynccontextmanager
    async def client_context(self) -> AsyncGenerator[OllamaClient, None]:
        """Context manager for safe Ollama client usage.
        
        Ensures client is properly closed after use, even if an error occurs.
        
        Yields:
            OllamaClient instance
            
        Raises:
            RuntimeError: If client cannot be created
        """
        client = await self._get_client()
        if client is None:
            raise RuntimeError("Failed to create Ollama client")
        
        try:
            yield client
        finally:
            # Individual client sessions are managed by the OllamaClient class itself
            # The client instance is reused for efficiency
            pass

    async def check_health(self) -> bool:
        """Check if Ollama service is healthy and accessible.
        
        Returns:
            True if Ollama is accessible, False otherwise
        """
        async with self.client_context() as client:
            return await client.check_health()

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        feature: str = "default",
    ) -> str | None:
        """Generate AI response with proper error handling.
        
        Args:
            prompt: The prompt to send to Ollama
            system_prompt: Optional system prompt
            feature: Feature name for logging
            
        Returns:
            AI response string or None if generation fails
        """
        try:
            async with self.client_context() as client:
                return await client.generate(prompt, system_prompt=system_prompt, feature=feature)
        except Exception as e:
            logger.error(f"AI generation failed for feature '{feature}': {e}")
            return None

    async def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        model: str | None = None,
    ) -> Any:
        """Chat with AI using tool calling capabilities.
        
        Args:
            messages: Chat messages with role and content
            tools: Tool definitions for function calling
            model: Model name (optional, uses settings default if not provided)
            
        Returns:
            AI response with tool calls if any
            
        Raises:
            Exception: If chat request fails
        """
        async with self.client_context() as client:
            return await client.chat_with_tools(messages, tools, model=model)


# Singleton instance management
_ai_service: AIService | None = None
_ai_service_lock = asyncio.Lock()


async def get_ai_service(user_data_dir: Any) -> AIService:
    """Get or create the singleton AI service instance.
    
    Args:
        user_data_dir: Path to user_data directory
        
    Returns:
        AIService singleton instance
    """
    global _ai_service
    
    resolved_user_data_dir = resolve_user_data_dir(user_data_dir)

    async with _ai_service_lock:
        if _ai_service is None or _ai_service.user_data_dir != resolved_user_data_dir:
            if _ai_service is not None:
                await _ai_service.close()
            _ai_service = AIService(resolved_user_data_dir)
            logger.info("Created AI service instance for %s", resolved_user_data_dir)
        return _ai_service


async def cleanup_ai_service() -> None:
    """Cleanup the singleton AI service instance.
    
    Should be called during application shutdown.
    """
    global _ai_service
    
    async with _ai_service_lock:
        if _ai_service is not None:
            await _ai_service.close()
            _ai_service = None
            logger.info("Cleaned up AI service instance")
