"""Interface for settings store service."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import SaveSettingsRequest, SettingsModel


class ISettingsStore(ABC):
    """Interface for settings persistence operations."""
    
    @abstractmethod
    def defaults(self) -> SettingsModel:
        """Get default settings values."""
        pass
    
    @abstractmethod
    def load(self) -> SettingsModel:
        """Load settings from storage."""
        pass
    
    @abstractmethod
    def save(self, request: SaveSettingsRequest | SettingsModel) -> SettingsModel:
        """Save settings to storage."""
        pass
