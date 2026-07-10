"""Tests for centralized AI service."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import the service to test


@pytest.fixture
def temp_user_data_dir(tmp_path: Path) -> Path:
    """Create a temporary user data directory with settings."""
    user_data = tmp_path / "user_data"
    user_data.mkdir(parents=True, exist_ok=True)
    
    # Create data directory for settings
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    # Create minimal settings file
    settings_file = data_dir / "strategy_lab_settings.json"
    settings_file.write_text("""{
    "ollama_api_url": "http://localhost:11434",
    "ollama_model": "test-model",
    "ollama_provider": "local",
    "ollama_api_key": "",
    "ollama_timeout": 30
}""")
    
    return user_data


@pytest.mark.asyncio
async def test_ai_service_singleton(temp_user_data_dir: Path):
    """Test that AI service returns singleton instance."""
    from backend.services.ai import get_ai_service, cleanup_ai_service
    
    service1 = await get_ai_service(str(temp_user_data_dir))
    service2 = await get_ai_service(str(temp_user_data_dir))
    
    assert service1 is service2, "Should return same instance"
    
    await cleanup_ai_service()
    
    service3 = await get_ai_service(str(temp_user_data_dir))
    assert service3 is not service1, "Should create new instance after cleanup"
    
    await cleanup_ai_service()


@pytest.mark.asyncio
async def test_ai_service_client_context(temp_user_data_dir: Path):
    """Test AI service client context manager."""
    from backend.services.ai import get_ai_service, cleanup_ai_service
    
    service = await get_ai_service(str(temp_user_data_dir))
    
    # Mock the shared Ollama client creation
    with patch('backend.services.ai.ai_service.OllamaClient') as mock_create:
        mock_client = AsyncMock()
        mock_create.return_value = mock_client
        
        async with service.client_context() as client:
            assert client is mock_client
        
        # Verify client was created
        mock_create.assert_called_once()
    
    await cleanup_ai_service()


@pytest.mark.asyncio
async def test_ai_service_health_check(temp_user_data_dir: Path):
    """Test AI service health check."""
    from backend.services.ai import get_ai_service, cleanup_ai_service
    
    service = await get_ai_service(str(temp_user_data_dir))
    
    with patch('backend.services.ai.ai_service.OllamaClient') as mock_create:
        mock_client = AsyncMock()
        mock_client.check_health = AsyncMock(return_value=True)
        mock_create.return_value = mock_client
        
        is_healthy = await service.check_health()
        assert is_healthy is True
        mock_client.check_health.assert_called_once()
    
    await cleanup_ai_service()


@pytest.mark.asyncio
async def test_ai_service_generate(temp_user_data_dir: Path):
    """Test AI service generate method."""
    from backend.services.ai import get_ai_service, cleanup_ai_service
    
    service = await get_ai_service(str(temp_user_data_dir))
    
    with patch('backend.services.ai.ai_service.OllamaClient') as mock_create:
        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(return_value="Test response")
        mock_create.return_value = mock_client
        
        response = await service.generate("Test prompt", feature="test")
        assert response == "Test response"
        mock_client.generate.assert_called_once_with("Test prompt", system_prompt=None, feature="test")
    
    await cleanup_ai_service()


@pytest.mark.asyncio
async def test_ai_service_generate_with_error(temp_user_data_dir: Path):
    """Test AI service generate method with error handling."""
    from backend.services.ai import get_ai_service, cleanup_ai_service
    
    service = await get_ai_service(str(temp_user_data_dir))
    
    with patch('backend.services.ai.ai_service.OllamaClient') as mock_create:
        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(side_effect=Exception("API error"))
        mock_create.return_value = mock_client
        
        response = await service.generate("Test prompt", feature="test")
        assert response is None  # Should return None on error
    
    await cleanup_ai_service()


@pytest.mark.asyncio
async def test_ai_service_cleanup(temp_user_data_dir: Path):
    """Test AI service cleanup."""
    from backend.services.ai import get_ai_service, cleanup_ai_service
    
    service = await get_ai_service(str(temp_user_data_dir))
    
    with patch('backend.services.ai.ai_service.OllamaClient') as mock_create:
        mock_client = AsyncMock()
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client
        
        # Trigger client creation
        async with service.client_context():
            pass
        
        # Cleanup should close the client
        await service.close()
        mock_client.close.assert_called_once()
    
    await cleanup_ai_service()


@pytest.mark.asyncio
async def test_ai_service_concurrent_access(temp_user_data_dir: Path):
    """Test AI service handles concurrent access safely."""
    from backend.services.ai import get_ai_service, cleanup_ai_service
    
    service = await get_ai_service(str(temp_user_data_dir))
    
    with patch('backend.services.ai.ai_service.OllamaClient') as mock_create:
        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(return_value="Response")
        mock_create.return_value = mock_client
        
        # Make concurrent requests
        tasks = [
            service.generate(f"Prompt {i}", feature=f"test{i}")
            for i in range(5)
        ]
        
        results = await asyncio.gather(*tasks)
        
        # All should succeed
        assert all(result == "Response" for result in results)
    
    await cleanup_ai_service()
