"""Unit tests for refactored AssistantService."""

import pytest
from pathlib import Path
from unittest.mock import Mock
from backend.services.assistant_service import AssistantService
from backend.services.agent_context import AgentContextService
from backend.services.interfaces import ISettingsStore


def test_assistant_service_with_specific_dependencies():
    """Test that AssistantService can be instantiated with specific dependencies."""
    # Create mock dependencies
    mock_settings_store = Mock(spec=ISettingsStore)
    mock_context_service = Mock(spec=AgentContextService)
    mock_optimizer_store = Mock()
    mock_version_manager = Mock()
    mock_exported_trial_store = Mock()
    
    # Instantiate with specific dependencies
    service = AssistantService(
        settings_store=mock_settings_store,
        context_service=mock_context_service,
        optimizer_store=mock_optimizer_store,
        version_manager=mock_version_manager,
        exported_trial_store=mock_exported_trial_store,
        root_dir=Path('/tmp/test'),
    )
    
    # Verify dependencies are stored
    assert service.settings_store is mock_settings_store
    assert service.context_service is mock_context_service
    assert service.optimizer_store is mock_optimizer_store
    assert service.version_manager is mock_version_manager
    assert service.exported_trial_store is mock_exported_trial_store
    assert service.root_dir == Path('/tmp/test')


def test_assistant_service_minimal_dependencies():
    """Test that AssistantService can be instantiated with minimal dependencies."""
    mock_settings_store = Mock(spec=ISettingsStore)
    mock_context_service = Mock(spec=AgentContextService)
    
    service = AssistantService(
        settings_store=mock_settings_store,
        context_service=mock_context_service,
    )
    
    assert service.settings_store is mock_settings_store
    assert service.context_service is mock_context_service
    assert service.optimizer_store is None
    assert service.version_manager is None


def test_assistant_service_user_data_dir():
    """Test that user_data_dir property returns correct path."""
    mock_settings_store = Mock(spec=ISettingsStore)
    mock_settings_store.load.return_value = Mock(user_data_directory_path='/tmp/user_data')
    mock_context_service = Mock(spec=AgentContextService)
    
    service = AssistantService(
        settings_store=mock_settings_store,
        context_service=mock_context_service,
    )
    
    assert service.user_data_dir == Path('/tmp/user_data')


def test_assistant_service_user_data_dir_fallback():
    """Test that user_data_dir falls back to root_dir/user_data when settings fail."""
    mock_settings_store = Mock(spec=ISettingsStore)
    mock_settings_store.load.side_effect = Exception("Settings load failed")
    mock_context_service = Mock(spec=AgentContextService)
    
    service = AssistantService(
        settings_store=mock_settings_store,
        context_service=mock_context_service,
        root_dir=Path('/tmp/test'),
    )
    
    assert service.user_data_dir == Path('/tmp/test/user_data')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
