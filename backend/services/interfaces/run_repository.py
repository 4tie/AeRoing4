"""Interface for run repository service."""

from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import RunDetail, RunMetadata


class IRunRepository(ABC):
    """Interface for backtest run data operations."""
    
    @abstractmethod
    def strategy_root(self, strategy_name: str) -> Path:
        """Get the root directory for a strategy."""
        pass
    
    @abstractmethod
    def run_dir(self, strategy_name: str, run_id: str) -> Path:
        """Get the directory for a specific run."""
        pass
    
    @abstractmethod
    def find_run_dir(self, run_id: str) -> Path:
        """Find a run directory by run ID."""
        pass
    
    @abstractmethod
    def list_runs(self, strategy_name: str | None = None) -> list[RunMetadata]:
        """List runs, optionally filtered by strategy."""
        pass
    
    @abstractmethod
    def load_metadata(self, run_id: str) -> RunMetadata:
        """Load metadata for a specific run."""
        pass
    
    @abstractmethod
    def save_metadata(self, run_id: str, metadata: RunMetadata) -> None:
        """Save metadata for a specific run."""
        pass
    
    @abstractmethod
    def load_detail(self, run_id: str) -> RunDetail:
        """Load full details for a specific run."""
        pass
    
    @abstractmethod
    def load_trades(self, run_id: str):
        """Load trades data for a specific run."""
        pass
