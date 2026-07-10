"""Interface for strategy registry service."""

from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import RegistryDiff, StrategyRecord


class IStrategyRegistry(ABC):
    """Interface for strategy registry operations."""
    
    @abstractmethod
    def scan(self) -> RegistryDiff:
        """Scan strategies directory and return diff of changes."""
        pass
    
    @abstractmethod
    def ensure_scanned(self) -> None:
        """Ensure strategies have been scanned at least once."""
        pass
    
    @abstractmethod
    def list_strategies(self) -> list[StrategyRecord]:
        """List all available strategies."""
        pass
    
    @abstractmethod
    def get_strategy(self, strategy_name: str) -> StrategyRecord:
        """Get a specific strategy by name."""
        pass
    
    @abstractmethod
    def parse_strategy(self, strategy_name: str):
        """Parse a strategy file and return parsed data."""
        pass
    
    @property
    @abstractmethod
    def parse_errors(self) -> list[dict[str, str]]:
        """Get list of parsing errors from last scan."""
        pass
    
    @property
    @abstractmethod
    def last_diff(self) -> RegistryDiff:
        """Get the diff from the last scan."""
        pass
