"""Unit tests for refactored AgentContextService."""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock
from backend.services.agent_context import AgentContextService
from backend.services.interfaces import IRunRepository, ISettingsStore


def test_agent_context_service_with_specific_dependencies():
    """Test that AgentContextService can be instantiated with specific dependencies."""
    # Create mock dependencies
    mock_run_repository = Mock(spec=IRunRepository)
    mock_settings_store = Mock(spec=ISettingsStore)
    mock_version_manager = Mock()
    mock_strategy_optimizer = Mock()
    mock_backtest_runner = Mock()
    mock_optimizer_store = Mock()
    mock_run_detail_callable = Mock()
    
    # Instantiate with specific dependencies
    service = AgentContextService(
        root_dir=Path('/tmp/test'),
        run_repository=mock_run_repository,
        settings_store=mock_settings_store,
        version_manager=mock_version_manager,
        strategy_optimizer=mock_strategy_optimizer,
        backtest_runner=mock_backtest_runner,
        optimizer_store=mock_optimizer_store,
        run_detail_callable=mock_run_detail_callable,
    )
    
    # Verify dependencies are stored
    assert service.root_dir == Path('/tmp/test')
    assert service.run_repository is mock_run_repository
    assert service.settings_store is mock_settings_store
    assert service.version_manager is mock_version_manager


def test_agent_context_service_minimal_dependencies():
    """Test that AgentContextService can be instantiated with minimal dependencies."""
    mock_run_repository = Mock(spec=IRunRepository)
    mock_settings_store = Mock(spec=ISettingsStore)
    
    service = AgentContextService(
        root_dir=Path('/tmp/test'),
        run_repository=mock_run_repository,
        settings_store=mock_settings_store,
    )
    
    assert service.root_dir == Path('/tmp/test')
    assert service.run_repository is mock_run_repository
    assert service.settings_store is mock_settings_store
    assert service.version_manager is None


def test_agent_context_service_ui_state_path():
    """Test that ui_state_path property returns correct path."""
    mock_run_repository = Mock(spec=IRunRepository)
    mock_settings_store = Mock(spec=ISettingsStore)
    
    service = AgentContextService(
        root_dir=Path('/tmp/test'),
        run_repository=mock_run_repository,
        settings_store=mock_settings_store,
    )
    
    expected_path = Path('/tmp/test/data/agent_ui_state.json')
    assert service.ui_state_path == expected_path


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
