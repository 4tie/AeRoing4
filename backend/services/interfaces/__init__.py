"""Service interfaces for dependency injection and loose coupling."""

from .strategy_registry import IStrategyRegistry
from .run_repository import IRunRepository
from .settings_store import ISettingsStore
from .backtest_runner import IBacktestRunner

__all__ = [
    "IStrategyRegistry",
    "IRunRepository", 
    "ISettingsStore",
    "IBacktestRunner",
]
