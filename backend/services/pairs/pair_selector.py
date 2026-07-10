"""services/pairs/pair_selector.py contains backend logic for pair selector.

This file is intentionally documented in plain English so readers can follow
what each section does even without deep Python experience.
"""

from __future__ import annotations
import json
import random
from pathlib import Path
from typing import Any

from ...models import (
    PairSelectorConfig,
    PairSelectorState,
    PairListResponse,
    PairSelectionValidation,
    SearchPairsRequest,
    SelectPairRequest,
    ToggleFavoriteRequest,
    ToggleLockRequest,
    RandomizePairsRequest,
    UpdateMaxTradesRequest,
)
from ...utils import atomic_write_json, read_json


class PairSelectorService:
    """Service for managing pair selection state and operations."""
    
    def __init__(self, data_dir: Path):
        """__init__ implements function-level backend logic."""
        self.data_dir = data_dir
        self.state_file = data_dir / "pair_selector_state.json"
        self.config_file = data_dir / "pair_selector_config.json"
        
        # Load or initialize state
        self.state = self._load_state()
        self.config = self._load_config()
        
        # Ensure available pairs are populated
        self._ensure_available_pairs()
    
    def _load_state(self) -> PairSelectorState:
        """Load pair selector state from file."""
        data = read_json(self.state_file, default={})
        if not data:
            return PairSelectorState()
        
        # Convert lists back to sets for favorite_pairs and locked_pairs
        if "favorite_pairs" in data and isinstance(data["favorite_pairs"], list):
            data["favorite_pairs"] = set(data["favorite_pairs"])
        if "locked_pairs" in data and isinstance(data["locked_pairs"], list):
            data["locked_pairs"] = set(data["locked_pairs"])
        
        return PairSelectorState.model_validate(data)
    
    def _save_state(self) -> None:
        """Save pair selector state to file."""
        state_data = self.state.model_dump(mode="json")
        # Convert sets to lists for JSON serialization
        state_data["favorite_pairs"] = list(state_data["favorite_pairs"])
        state_data["locked_pairs"] = list(state_data["locked_pairs"])
        atomic_write_json(self.state_file, state_data)
    
    def _load_config(self) -> PairSelectorConfig:
        """Load pair selector configuration from file."""
        data = read_json(self.config_file, default={})
        if not data:
            config = PairSelectorConfig()
            self._save_config(config)
            return config
        return PairSelectorConfig.model_validate(data)
    
    def _save_config(self, config: PairSelectorConfig | None = None) -> None:
        """Save pair selector configuration to file."""
        config_to_save = config or self.config
        atomic_write_json(self.config_file, config_to_save.model_dump(mode="json"))
    
    def _ensure_available_pairs(self) -> None:
        """Ensure available pairs are populated from config, merging in any new defaults."""
        default_set = set(self.config.default_pairs)
        existing_set = set(self.state.available_pairs)
        new_pairs = [p for p in self.config.default_pairs if p not in existing_set]
        if not self.state.available_pairs:
            self.state.available_pairs = self.config.default_pairs.copy()
            self._save_state()
        elif new_pairs:
            # Append newly added default pairs so existing users see them
            self.state.available_pairs.extend(new_pairs)
            self._save_state()
        # Always sync extended_pairs from config (not persisted separately)
        self.state.extended_pairs = [
            p for p in self.config.extended_pairs
            if p not in set(self.state.available_pairs)
        ]
    
    def get_state(self) -> PairSelectorState:
        """Get current pair selector state."""
        return self.state
    
    def get_config(self) -> PairSelectorConfig:
        """Get current pair selector configuration."""
        return self.config
    
    def update_config(self, config: PairSelectorConfig) -> PairSelectorConfig:
        """Update pair selector configuration."""
        self.config = config
        self._save_config(config)
        
        # Update available pairs if default pairs changed
        if not self.state.available_pairs:
            self.state.available_pairs = self.config.default_pairs.copy()
            self._save_state()
        
        return self.config
    
    def _all_known_pairs(self) -> set[str]:
        """Return the union of available and extended pairs."""
        return set(self.state.available_pairs) | set(self.state.extended_pairs)

    def toggle_favorite(self, request: ToggleFavoriteRequest) -> PairSelectorState:
        """Toggle favorite status of a pair."""
        pair = request.pair

        if pair not in self._all_known_pairs():
            raise ValueError(f"Pair '{pair}' is not in available pairs")

        if pair in self.state.favorite_pairs:
            self.state.favorite_pairs.remove(pair)
        else:
            self.state.favorite_pairs.add(pair)

        self._save_state()
        return self.state

    def toggle_lock(self, request: ToggleLockRequest) -> PairSelectorState:
        """Toggle lock status of a pair."""
        pair = request.pair

        if pair not in self._all_known_pairs():
            raise ValueError(f"Pair '{pair}' is not in available pairs")

        if pair in self.state.locked_pairs:
            self.state.locked_pairs.remove(pair)
        else:
            self.state.locked_pairs.add(pair)

        self._save_state()
        return self.state

    def select_pair(self, request: SelectPairRequest) -> PairSelectorState:
        """Select or deselect a pair."""
        pair = request.pair

        if pair not in self._all_known_pairs():
            raise ValueError(f"Pair '{pair}' is not in available pairs")
        
        validation = self.validate_pair_selection(pair, request.selected)
        if not validation.is_valid:
            raise ValueError(validation.error_message or "Invalid selection")
        
        if request.selected:
            if pair not in self.state.selected_pairs:
                self.state.selected_pairs.append(pair)
        else:
            # Cannot remove locked pairs
            if pair in self.state.locked_pairs:
                raise ValueError(f"Cannot remove locked pair '{pair}'")
            if pair in self.state.selected_pairs:
                self.state.selected_pairs.remove(pair)
        
        self._save_state()
        return self.state
    
    def randomize_pairs(self, request: RandomizePairsRequest) -> PairSelectorState:
        """Randomize pair selection."""
        max_pairs = request.max_pairs or self.state.max_open_trades
        
        # Start with locked pairs if preserve_locked is True
        selected = []
        if request.preserve_locked:
            selected = [pair for pair in self.state.selected_pairs if pair in self.state.locked_pairs]
        
        # Get available pairs for randomization
        available_for_random = [
            pair for pair in self.state.available_pairs
            if pair not in self.state.locked_pairs and pair not in selected
        ]
        
        # Calculate how many more pairs to add
        remaining_slots = max_pairs - len(selected)
        if remaining_slots > 0 and available_for_random:
            # Random selection
            random.shuffle(available_for_random)
            to_add = min(remaining_slots, len(available_for_random))
            selected.extend(available_for_random[:to_add])
        
        # Update state
        self.state.selected_pairs = selected
        self._save_state()
        return self.state
    
    def update_max_trades(self, request: UpdateMaxTradesRequest) -> PairSelectorState:
        """Update maximum open trades."""
        self.state.max_open_trades = request.max_open_trades
        
        # Ensure selected pairs don't exceed new limit
        if len(self.state.selected_pairs) > request.max_open_trades:
            # Remove non-locked pairs first
            removable = [
                pair for pair in self.state.selected_pairs
                if pair not in self.state.locked_pairs
            ]
            to_remove = len(self.state.selected_pairs) - request.max_open_trades
            for pair in removable[:to_remove]:
                self.state.selected_pairs.remove(pair)
        
        self._save_state()
        return self.state
    
    def search_pairs(self, request: SearchPairsRequest) -> PairListResponse:
        """Search and filter pairs."""
        search_term = request.search_term.lower().strip()
        
        # Filter available pairs based on search term
        if search_term:
            filtered_pairs = [
                pair for pair in self.state.available_pairs
                if search_term in pair.lower()
            ]
        else:
            filtered_pairs = self.state.available_pairs.copy()
        
        # Separate favorites and others
        favorites = []
        other_pairs = []
        
        for pair in filtered_pairs:
            if pair in self.state.favorite_pairs:
                favorites.append(pair)
            elif not request.show_favorites_only:
                other_pairs.append(pair)
        
        # Sort both lists alphabetically
        favorites.sort()
        other_pairs.sort()
        
        return PairListResponse(
            favorites=favorites,
            other_pairs=other_pairs,
            total_count=len(favorites) + len(other_pairs)
        )
    
    def validate_pair_selection(self, pair: str, selected: bool) -> PairSelectionValidation:
        """Validate pair selection."""
        current_count = len(self.state.selected_pairs)
        max_allowed = self.state.max_open_trades
        
        if selected:
            # Adding a pair
            if pair in self.state.selected_pairs:
                return PairSelectionValidation(
                    is_valid=False,
                    error_message=f"Pair '{pair}' is already selected",
                    current_count=current_count,
                    max_allowed=max_allowed,
                    can_add_more=False
                )
            
            if current_count >= max_allowed:
                return PairSelectionValidation(
                    is_valid=False,
                    error_message=f"Cannot select more than {max_allowed} pairs",
                    current_count=current_count,
                    max_allowed=max_allowed,
                    can_add_more=False
                )
        else:
            # Removing a pair
            if pair not in self.state.selected_pairs:
                return PairSelectionValidation(
                    is_valid=False,
                    error_message=f"Pair '{pair}' is not selected",
                    current_count=current_count,
                    max_allowed=max_allowed,
                    can_add_more=current_count < max_allowed
                )
            
            if pair in self.state.locked_pairs:
                return PairSelectionValidation(
                    is_valid=False,
                    error_message=f"Cannot remove locked pair '{pair}'",
                    current_count=current_count,
                    max_allowed=max_allowed,
                    can_add_more=current_count < max_allowed
                )
        
        return PairSelectionValidation(
            is_valid=True,
            current_count=current_count,
            max_allowed=max_allowed,
            can_add_more=current_count < max_allowed
        )
    
    def get_selected_pairs(self) -> list[str]:
        """Get list of selected pairs."""
        return self.state.selected_pairs.copy()
    
    def clear_selection(self) -> PairSelectorState:
        """Clear all selected pairs (except locked ones)."""
        # Keep only locked pairs
        self.state.selected_pairs = [
            pair for pair in self.state.selected_pairs
            if pair in self.state.locked_pairs
        ]
        self._save_state()
        return self.state
    
    def reset_to_defaults(self) -> PairSelectorState:
        """Reset state to defaults."""
        self.state = PairSelectorState(
            available_pairs=self.config.default_pairs.copy(),
            max_open_trades=self.config.default_max_trades
        )
        self._save_state()
        return self.state
    
    def set_selected(self, pairs: list[str]) -> PairSelectorState:
        """Set the selected pairs to exactly the provided list.

        Unknown pairs are added to available_pairs automatically.
        max_open_trades is expanded when the list exceeds the current limit.
        Locked pairs that are not in the new list are appended at the end.
        """
        cleaned = [p.strip().upper() for p in pairs if p.strip()]
        known = self._all_known_pairs()
        for p in cleaned:
            if p not in known:
                self.state.available_pairs.append(p)
        if len(cleaned) > self.state.max_open_trades:
            self.state.max_open_trades = len(cleaned)
        locked_extras = [
            p for p in self.state.selected_pairs
            if p in self.state.locked_pairs and p not in cleaned
        ]
        self.state.selected_pairs = list(dict.fromkeys(cleaned + locked_extras))
        self._save_state()
        return self.state

    def get_pair_status(self, pair: str) -> dict[str, Any]:
        """Get status information for a specific pair."""
        if pair not in self._all_known_pairs():
            raise ValueError(f"Pair '{pair}' is not in available pairs")
        
        return {
            "pair": pair,
            "is_selected": pair in self.state.selected_pairs,
            "is_favorite": pair in self.state.favorite_pairs,
            "is_locked": pair in self.state.locked_pairs,
            "can_select": self.validate_pair_selection(pair, True).is_valid,
            "can_deselect": self.validate_pair_selection(pair, False).is_valid,
        }
