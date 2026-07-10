"""Validation functions for Ollama AI service."""

from typing import Any


# Safe ranges for parameter validation
SAFE_RANGES = {
    "stoploss": {"min": -0.35, "max": -0.01},
    "max_drawdown_threshold": {"min": 0.05, "max": 0.50},
    "hyperopt_epochs": {"min": 50, "max": 500},
    "min_win_rate": {"min": 0.1, "max": 0.9},
    "min_sharpe": {"min": 0.5, "max": 5.0},
    "min_profit_factor": {"min": 1.0, "max": 5.0},
}


def validate_ollama_suggestions(
    suggestions: dict[str, Any],
    strategy_template: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """Validate ollama suggestions for Freqtrade-specific constraints and safe ranges.
    
    Args:
        suggestions: Dict with suggested parameters from ollama
        strategy_template: Optional strategy template to check for conflicts
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    errors = []
    
    # 0. Convert boolean strings to actual booleans in param_overrides
    if "param_overrides" in suggestions and suggestions["param_overrides"]:
        param_overrides = suggestions["param_overrides"]
        for key, value in param_overrides.items():
            if isinstance(value, str) and value.lower() in ["true", "false"]:
                param_overrides[key] = True if value.lower() == "true" else False
    
    # 1. Validate stoploss sign (must be negative)
    if "param_overrides" in suggestions and suggestions["param_overrides"]:
        param_overrides = suggestions["param_overrides"]
        if "stoploss" in param_overrides:
            stoploss = param_overrides["stoploss"]
            if stoploss is not None and stoploss >= 0:
                errors.append(f"Stoploss must be negative, got {stoploss}")
    
    # 2. Validate ROI monotonicity (must decrease as time increases)
    if "param_overrides" in suggestions and suggestions["param_overrides"]:
        param_overrides = suggestions["param_overrides"]
        if "roi" in param_overrides and isinstance(param_overrides["roi"], dict):
            roi = param_overrides["roi"]
            # ROI should be a dict with time keys and profit values
            # Check that profits decrease as time increases
            time_values = []
            for key, value in roi.items():
                try:
                    time_val = int(key)
                    profit_val = float(value)
                    time_values.append((time_val, profit_val))
                except (ValueError, TypeError):
                    continue
            
            # Sort by time and check monotonicity
            time_values.sort(key=lambda x: x[0])
            for i in range(1, len(time_values)):
                if time_values[i][1] > time_values[i-1][1]:
                    errors.append(
                        f"ROI must be monotonically decreasing: "
                        f"at {time_values[i][0]}min profit is {time_values[i][1]} "
                        f"but at {time_values[i-1][0]}min profit is {time_values[i-1][1]}"
                    )
                    break
    
    # 3. Validate hyperopt_spaces are valid Freqtrade spaces
    if "hyperopt_spaces" in suggestions:
        suggested_spaces = suggestions["hyperopt_spaces"]
        if isinstance(suggested_spaces, list):
            valid_spaces = {"buy", "sell", "roi", "stoploss", "trailing", "default", "all"}
            invalid_spaces = [s for s in suggested_spaces if s not in valid_spaces]
            if invalid_spaces:
                errors.append(f"Invalid hyperopt_spaces: {invalid_spaces}. Valid spaces: {valid_spaces}")
    
    # 4. Validate space conflicts against strategy template
    if strategy_template and "hyperopt_spaces" in suggestions:
        suggested_spaces = suggestions["hyperopt_spaces"]
        if isinstance(suggested_spaces, list):
            # Check if strategy disables trailing stops
            if strategy_template.get("trailing_stop", False) is False:
                if "trailing" in suggested_spaces:
                    errors.append("Strategy disables trailing stops, but AI suggested trailing space")
    
    # 5. Validate safe ranges
    # Check hyperopt_epochs
    if "hyperopt_epochs" in suggestions:
        epochs = suggestions["hyperopt_epochs"]
        if epochs is not None:
            if not (SAFE_RANGES["hyperopt_epochs"]["min"] <= epochs <= SAFE_RANGES["hyperopt_epochs"]["max"]):
                errors.append(
                    f"hyperopt_epochs {epochs} outside safe range "
                    f"[{SAFE_RANGES['hyperopt_epochs']['min']}, {SAFE_RANGES['hyperopt_epochs']['max']}]"
                )
    
    # Check param_overrides against safe ranges
    if "param_overrides" in suggestions and suggestions["param_overrides"]:
        param_overrides = suggestions["param_overrides"]
        
        if "max_drawdown_threshold" in param_overrides:
            dd = param_overrides["max_drawdown_threshold"]
            if dd is not None and not (SAFE_RANGES["max_drawdown_threshold"]["min"] <= dd <= SAFE_RANGES["max_drawdown_threshold"]["max"]):
                errors.append(
                    f"max_drawdown_threshold {dd} outside safe range "
                    f"[{SAFE_RANGES['max_drawdown_threshold']['min']}, {SAFE_RANGES['max_drawdown_threshold']['max']}]"
                )
        
        if "min_win_rate" in param_overrides:
            wr = param_overrides["min_win_rate"]
            if wr is not None and not (SAFE_RANGES["min_win_rate"]["min"] <= wr <= SAFE_RANGES["min_win_rate"]["max"]):
                errors.append(
                    f"min_win_rate {wr} outside safe range "
                    f"[{SAFE_RANGES['min_win_rate']['min']}, {SAFE_RANGES['min_win_rate']['max']}]"
                )
        
        if "min_sharpe" in param_overrides:
            sharpe = param_overrides["min_sharpe"]
            if sharpe is not None and not (SAFE_RANGES["min_sharpe"]["min"] <= sharpe <= SAFE_RANGES["min_sharpe"]["max"]):
                errors.append(
                    f"min_sharpe {sharpe} outside safe range "
                    f"[{SAFE_RANGES['min_sharpe']['min']}, {SAFE_RANGES['min_sharpe']['max']}]"
                )
    
    if errors:
        return False, "; ".join(errors)
    
    return True, None
