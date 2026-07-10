"""Options Migration Adapter - Migrate old options to new backend format.

This module provides functions to migrate old AutoQuant options to the new
robustness-first workflow format, ensuring backward compatibility.
"""

from __future__ import annotations

from typing import Any


def migrate_old_options(old_options: dict[str, Any]) -> dict[str, Any]:
    """Migrate old AutoQuant options to new backend format.
    
    Args:
        old_options: Dictionary of old-style options
        
    Returns:
        Dictionary of new-style options compatible with the robustness-first workflow
    """
    migrated = {}
    
    # Copy over fields that exist in both formats
    if "strategy" in old_options:
        migrated["strategy"] = old_options["strategy"]
    
    if "timeframe" in old_options:
        migrated["timeframe"] = old_options["timeframe"]
    
    if "in_sample_range" in old_options:
        migrated["in_sample_range"] = old_options["in_sample_range"]
    
    if "out_sample_range" in old_options:
        migrated["out_sample_range"] = old_options["out_sample_range"]
    
    if "exchange" in old_options:
        migrated["exchange"] = old_options["exchange"]
    
    if "config_file" in old_options:
        migrated["config_file"] = old_options["config_file"]
    
    # Migrate threshold fields
    if "max_drawdown_threshold" in old_options:
        migrated["max_drawdown_threshold"] = old_options["max_drawdown_threshold"]
    
    if "min_win_rate" in old_options:
        migrated["min_win_rate"] = old_options["min_win_rate"]
    
    if "min_profit_factor" in old_options:
        migrated["min_profit_factor"] = old_options["min_profit_factor"]
    
    if "min_sharpe" in old_options:
        migrated["min_sharpe"] = old_options["min_sharpe"]
    
    if "min_oos_profit" in old_options:
        migrated["min_oos_profit"] = old_options["min_oos_profit"]
    
    if "monte_carlo_threshold" in old_options:
        migrated["monte_carlo_threshold"] = old_options["monte_carlo_threshold"]
    
    # Migrate hyperopt settings
    if "hyperopt_loss" in old_options:
        migrated["hyperopt_loss"] = old_options["hyperopt_loss"]
    
    if "hyperopt_spaces" in old_options:
        migrated["hyperopt_spaces"] = old_options["hyperopt_spaces"]
    
    if "hyperopt_epochs" in old_options:
        migrated["hyperopt_epochs"] = old_options["hyperopt_epochs"]
    
    # Migrate WFO settings
    if "wfo_enabled" in old_options:
        migrated["wfo_enabled"] = old_options["wfo_enabled"]
    
    if "wfo_is_months" in old_options:
        migrated["wfo_is_months"] = old_options["wfo_is_months"]
    
    if "wfo_oos_months" in old_options:
        migrated["wfo_oos_months"] = old_options["wfo_oos_months"]
    
    if "wfo_recency_weight" in old_options:
        migrated["wfo_recency_weight"] = old_options["wfo_recency_weight"]
    
    # Migrate ensemble settings
    if "ensemble_enabled" in old_options:
        migrated["ensemble_enabled"] = old_options["ensemble_enabled"]
    
    # Migrate pair settings
    if "pair" in old_options:
        migrated["pair"] = old_options["pair"]
    
    if "pair_universe" in old_options:
        migrated["pair_universe"] = old_options["pair_universe"]
    
    # Add new robustness-first fields with defaults if not present
    migrated.setdefault("strategy_source", "existing")
    migrated.setdefault("trading_style", infer_trading_style_from_timeframe(old_options.get("timeframe")))
    migrated.setdefault("risk_profile", "balanced")
    migrated.setdefault("analysis_depth", infer_analysis_depth_from_date_range(old_options.get("in_sample_range")))
    migrated.setdefault("uploaded_strategy_id", None)
    migrated.setdefault("advanced_overrides", {})
    
    return migrated


def infer_trading_style_from_timeframe(timeframe: str | None) -> str:
    """Infer trading style from timeframe.
    
    Args:
        timeframe: Timeframe string (e.g., "5m", "1h", "1d")
        
    Returns:
        Trading style: scalping, intraday, swing, or position
    """
    if not timeframe:
        return "swing"
    
    if timeframe in ["1m", "3m", "5m"]:
        return "scalping"
    elif timeframe in ["15m", "30m"]:
        return "intraday"
    elif timeframe in ["1h", "4h"]:
        return "swing"
    else:
        return "position"


def infer_analysis_depth_from_date_range(date_range: str | None) -> str:
    """Infer analysis depth from in-sample date range.
    
    Args:
        date_range: Date range string (e.g., "20230101-20240101")
        
    Returns:
        Analysis depth: quick, standard, or deep
    """
    if not date_range:
        return "standard"
    
    try:
        parts = date_range.split("-")
        if len(parts) != 2:
            return "standard"
        
        from datetime import datetime
        start = datetime.strptime(parts[0], "%Y%m%d")
        end = datetime.strptime(parts[1], "%Y%m%d")
        days = (end - start).days
        
        if days < 90:
            return "quick"
        elif days < 180:
            return "standard"
        else:
            return "deep"
    except Exception:
        return "standard"


def migrate_frontend_form_to_api_payload(form_data: dict[str, Any]) -> dict[str, Any]:
    """Migrate frontend form data to API payload format.
    
    Args:
        form_data: Frontend form data
        
    Returns:
        API payload compatible with StartAutoQuantRequest
    """
    payload = {}
    
    # Copy all fields
    for key, value in form_data.items():
        if value is not None and value != "":
            payload[key] = value
    
    # Ensure new fields have defaults
    payload.setdefault("strategy_source", "existing")
    payload.setdefault("trading_style", "swing")
    payload.setdefault("risk_profile", "balanced")
    payload.setdefault("analysis_depth", "standard")
    payload.setdefault("uploaded_strategy_id", None)
    payload.setdefault("advanced_overrides", {})
    
    return payload


__all__ = [
    "migrate_old_options",
    "infer_trading_style_from_timeframe",
    "infer_analysis_depth_from_date_range",
    "migrate_frontend_form_to_api_payload",
]
