"""Service groups for organized dependency injection."""

from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .interfaces import IStrategyRegistry, IRunRepository, ISettingsStore, IBacktestRunner
    from .strategy.strategy_registry import StrategyRegistry
    from .strategy.version_manager import VersionManager
    from .strategy.strategy_git import StrategyGitService
    from .strategy.snapshot_service import SnapshotService
    from .strategy.strategy_source import StrategySourceParser
    from .storage.run_repository import RunRepository
    from .storage.result_parser import ResultParser
    from .execution.backtest_runner import BacktestRunner
    from .execution.data_download_runner import DataDownloadRunner
    from .execution.run_progress import RunProgressService
    from .execution.bias_check_runner import BiasCheckRunner
    from .settings_store import SettingsStore


class StrategyServices:
    """Group of strategy-related services."""
    
    def __init__(
        self,
        registry: IStrategyRegistry,
        version_manager: VersionManager,
        strategy_git_service: StrategyGitService,
        snapshot_service: SnapshotService,
        strategy_parser: StrategySourceParser,
    ) -> None:
        self.registry: IStrategyRegistry = registry
        self.version_manager: VersionManager = version_manager
        self.strategy_git_service: StrategyGitService = strategy_git_service
        self.snapshot_service: SnapshotService = snapshot_service
        self.strategy_parser: StrategySourceParser = strategy_parser


class ExecutionServices:
    """Group of execution-related services."""
    
    def __init__(
        self,
        backtest_runner: IBacktestRunner,
        data_download_runner: DataDownloadRunner,
        progress_service: RunProgressService,
        bias_check_runner: BiasCheckRunner,
    ) -> None:
        self.backtest_runner: IBacktestRunner = backtest_runner
        self.data_download_runner: DataDownloadRunner = data_download_runner
        self.progress_service: RunProgressService = progress_service
        self.bias_check_runner: BiasCheckRunner = bias_check_runner


class StorageServices:
    """Group of storage-related services."""
    
    def __init__(
        self,
        run_repository: IRunRepository,
        settings_store: ISettingsStore,
        result_parser: ResultParser,
    ) -> None:
        self.run_repository: IRunRepository = run_repository
        self.settings_store: ISettingsStore = settings_store
        self.result_parser: ResultParser = result_parser


class AIServices:
    """Group of AI-related services."""
    
    def __init__(
        self,
        assistant_service: object,  # Will be typed when imported
        agent_context_service: object,  # Will be typed when imported
    ) -> None:
        self.assistant_service: object = assistant_service
        self.agent_context_service: object = agent_context_service
