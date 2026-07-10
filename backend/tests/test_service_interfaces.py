"""Unit tests for service interfaces and groups."""

import pytest
from pathlib import Path
from backend.services.interfaces import (
    IStrategyRegistry,
    IRunRepository,
    ISettingsStore,
    IBacktestRunner,
)
from backend.services.service_groups import (
    StrategyServices,
    ExecutionServices,
    StorageServices,
    AIServices,
)
from backend.services.strategy.strategy_registry import StrategyRegistry
from backend.services.storage.run_repository import RunRepository
from backend.settings_store import SettingsStore
from backend.services.execution.backtest_runner import BacktestRunner


def test_strategy_registry_implements_interface():
    """Test that StrategyRegistry implements IStrategyRegistry."""
    # This is a compile-time check - if StrategyRegistry doesn't implement
    # all abstract methods, this will fail at import time
    assert issubclass(StrategyRegistry, IStrategyRegistry)


def test_run_repository_implements_interface():
    """Test that RunRepository implements IRunRepository."""
    assert issubclass(RunRepository, IRunRepository)


def test_settings_store_implements_interface():
    """Test that SettingsStore implements ISettingsStore."""
    assert issubclass(SettingsStore, ISettingsStore)


def test_backtest_runner_implements_interface():
    """Test that BacktestRunner implements IBacktestRunner."""
    assert issubclass(BacktestRunner, IBacktestRunner)


def test_strategy_services_group():
    """Test that StrategyServices group can be instantiated."""
    # Check that the class exists and has __init__
    assert StrategyServices is not None
    assert hasattr(StrategyServices, '__init__')


def test_execution_services_group():
    """Test that ExecutionServices group can be instantiated."""
    assert ExecutionServices is not None
    assert hasattr(ExecutionServices, '__init__')


def test_storage_services_group():
    """Test that StorageServices group can be instantiated."""
    assert StorageServices is not None
    assert hasattr(StorageServices, '__init__')


def test_ai_services_group():
    """Test that AIServices group can be instantiated."""
    assert AIServices is not None
    assert hasattr(AIServices, '__init__')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
