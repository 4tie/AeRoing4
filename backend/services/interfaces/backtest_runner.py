"""Interface for backtest runner service."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import RunMetadata, RunRequest


class IBacktestRunner(ABC):
    """Interface for backtest execution operations."""
    
    @abstractmethod
    def is_busy(self) -> bool:
        """Check if a backtest is currently running."""
        pass
    
    @abstractmethod
    def get_current_run_id(self) -> str | None:
        """Get the run ID of the currently running backtest."""
        pass
    
    @abstractmethod
    def set_log_callback(self, callback) -> None:
        """Set callback for log streaming."""
        pass
    
    @abstractmethod
    def run_backtest(self, request: RunRequest) -> RunMetadata:
        """Execute a backtest with the given request."""
        pass
    
    @abstractmethod
    def cancel(self) -> None:
        """Cancel the currently running backtest."""
        pass
