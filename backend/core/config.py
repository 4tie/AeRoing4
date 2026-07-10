import json
from pathlib import Path
from typing import Dict, Any
import os


class ThresholdConfig:
    """Load strategy-type-specific thresholds from JSON config files."""

    def __init__(self, strategy_type: str = "swing"):
        self.strategy_type = strategy_type
        self._thresholds = self._load()

    def _load(self) -> Dict[str, Any]:
        """Load threshold configuration from JSON file."""
        config_dir = Path(__file__).parent.parent / "config" / "thresholds"
        config_file = config_dir / f"{self.strategy_type}.json"

        if config_file.exists():
            try:
                with open(config_file) as f:
                    return json.load(f)
            except Exception:
                pass

        # Fallback defaults
        return {
            "discovery": {
                "min_profit_factor": 1.1,
                "min_trades": 10,
                "max_drawdown": 0.40,
            },
            "validation": {
                "min_profit_factor": 1.3,
                "max_drawdown": 0.30,
                "min_win_rate": 0.40,
            },
            "elite": {
                "min_profit_factor": 1.5,
                "max_drawdown": 0.25,
                "min_walk_forward": 0.70,
                "min_robustness": 0.70,
            },
        }

    def get_discovery_thresholds(self) -> Dict[str, Any]:
        """Get discovery stage thresholds."""
        return self._thresholds.get("discovery", {})

    def get_validation_thresholds(self) -> Dict[str, Any]:
        """Get validation stage thresholds."""
        return self._thresholds.get("validation", {})

    def get_elite_thresholds(self) -> Dict[str, Any]:
        """Get elite validation stage thresholds."""
        return self._thresholds.get("elite", {})
