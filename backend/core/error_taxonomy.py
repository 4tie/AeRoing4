"""Error taxonomy system for deterministic error classification and suggestions.

This module provides:
- Error code definitions with severity and auto-fix permissions
- Deterministic suggestion mappings based on error type
- Helper functions for error classification and suggestion retrieval
"""

from __future__ import annotations

from typing import Literal


# ── Error Codes and Classifications ────────────────────────────────────────────

ErrorSeverity = Literal["critical", "high", "medium", "low", "info"]
ErrorCode = Literal[
    "optimization_failed",
    "robustness_failed",
    "sharp_peak",
    "low_trades",
    "high_drawdown",
    "missing_data",
    "config_error",
    "strategy_syntax_error",
    "empty_pair_list",
    "exchange_download_failure",
    "export_ready",
    "overfit_roi",
    "aggressive_stoploss",
    "aggressive_trailing",
]

ERROR_DEFINITIONS: dict[ErrorCode, dict] = {
    "optimization_failed": {
        "severity": "high",
        "auto_fix_allowed": True,
        "title": "Optimization Failed",
        "description": "Hyperopt failed to find profitable parameters",
    },
    "robustness_failed": {
        "severity": "high",
        "auto_fix_allowed": True,
        "title": "Robustness Check Failed",
        "description": "Strategy parameters are too sensitive to small changes",
    },
    "sharp_peak": {
        "severity": "high",
        "auto_fix_allowed": True,
        "title": "Sharp Peak Detected",
        "description": "Strategy sits on a sharp peak - nearby params cause massive performance drops",
    },
    "low_trades": {
        "severity": "medium",
        "auto_fix_allowed": True,
        "title": "Low Trade Count",
        "description": "Strategy generates too few trades for reliable statistics",
    },
    "high_drawdown": {
        "severity": "medium",
        "auto_fix_allowed": True,
        "title": "High Drawdown",
        "description": "Maximum drawdown exceeds acceptable threshold",
    },
    "missing_data": {
        "severity": "critical",
        "auto_fix_allowed": False,
        "title": "Missing Data",
        "description": "Required historical data is not available",
    },
    "config_error": {
        "severity": "critical",
        "auto_fix_allowed": False,
        "title": "Configuration Error",
        "description": "Invalid or missing configuration parameters",
    },
    "strategy_syntax_error": {
        "severity": "critical",
        "auto_fix_allowed": False,
        "title": "Strategy Syntax Error",
        "description": "Strategy file contains syntax or import errors",
    },
    "empty_pair_list": {
        "severity": "critical",
        "auto_fix_allowed": False,
        "title": "Empty Pair List",
        "description": "No trading pairs specified for backtesting",
    },
    "exchange_download_failure": {
        "severity": "critical",
        "auto_fix_allowed": False,
        "title": "Exchange Data Download Failed",
        "description": "Failed to download data from exchange",
    },
    "export_ready": {
        "severity": "info",
        "auto_fix_allowed": False,
        "title": "Export Ready",
        "description": "Strategy is ready for export to live trading",
    },
    "overfit_roi": {
        "severity": "high",
        "auto_fix_allowed": True,
        "title": "Overfit ROI",
        "description": "ROI table is too aggressive and overfitted to in-sample data",
    },
    "aggressive_stoploss": {
        "severity": "medium",
        "auto_fix_allowed": True,
        "title": "Aggressive Stoploss",
        "description": "Stoploss is too tight, causing premature exits",
    },
    "aggressive_trailing": {
        "severity": "medium",
        "auto_fix_allowed": True,
        "title": "Aggressive Trailing",
        "description": "Trailing stop is too aggressive, reducing profits",
    },
}


# ── Deterministic Suggestion Mappings ───────────────────────────────────────────

SUGGESTION_MAPPINGS: dict[ErrorCode, str] = {
    "optimization_failed": "Review Optimizer settings / try Auto Safe mode",
    "robustness_failed": "Go to AutoQuant for WFO/robustness validation",
    "sharp_peak": "Apply ROI smoothing auto-fix to reduce parameter sensitivity",
    "low_trades": "Relax entry conditions or test larger pair universe",
    "high_drawdown": "Tighten stoploss or reduce position sizing",
    "missing_data": "Download data first using the Data Management tab",
    "config_error": "Review and fix configuration parameters in Settings",
    "strategy_syntax_error": "Fix syntax errors in Strategy Editor",
    "empty_pair_list": "Add trading pairs in Pair Screener or Settings",
    "exchange_download_failure": "Check exchange connection and API keys",
    "export_ready": "Go to Results / Export to download strategy files",
    "overfit_roi": "Apply ROI smoothing auto-fix to reduce overfitting",
    "aggressive_stoploss": "Widen stoploss to allow trades more room to breathe",
    "aggressive_trailing": "Reduce trailing stop aggression to preserve profits",
}


# ── Auto-Fix Action Definitions ─────────────────────────────────────────────────

AutoFixAction = Literal[
    "smooth_minimal_roi",
    "cap_early_roi_spike",
    "increase_roi_time_window",
    "reduce_trailing_aggression",
    "widen_entry_thresholds_if_low_trades",
    "tighten_stoploss_if_drawdown_high",
    "disable_overfit_param_if_sensitivity_bad",
    "fallback_to_best_stable_trial",
]

AUTO_FIX_ACTIONS: dict[AutoFixAction, dict] = {
    "smooth_minimal_roi": {
        "description": "Smooth ROI table to reduce sharp peaks",
        "affects": ["minimal_roi"],
        "requires_confirmation": True,
    },
    "cap_early_roi_spike": {
        "description": "Cap unrealistic early ROI targets",
        "affects": ["minimal_roi"],
        "requires_confirmation": True,
    },
    "increase_roi_time_window": {
        "description": "Increase ROI time windows for more gradual exits",
        "affects": ["minimal_roi"],
        "requires_confirmation": True,
    },
    "reduce_trailing_aggression": {
        "description": "Reduce trailing stop aggression to preserve profits",
        "affects": ["trailing_stop"],
        "requires_confirmation": True,
    },
    "widen_entry_thresholds_if_low_trades": {
        "description": "Widen entry conditions to increase trade count",
        "affects": ["buy_space_params"],
        "requires_confirmation": True,
    },
    "tighten_stoploss_if_drawdown_high": {
        "description": "Tighten stoploss to reduce drawdown",
        "affects": ["stoploss"],
        "requires_confirmation": True,
    },
    "disable_overfit_param_if_sensitivity_bad": {
        "description": "Disable overfitting parameters causing sensitivity",
        "affects": ["buy_space_params", "indicator_params"],
        "requires_confirmation": True,
    },
    "fallback_to_best_stable_trial": {
        "description": "Fallback to best stable trial from retry history",
        "affects": ["all_params"],
        "requires_confirmation": True,
    },
}


# ── Error to Auto-Fix Action Mappings ───────────────────────────────────────────

ERROR_TO_AUTO_FIX: dict[ErrorCode, list[AutoFixAction]] = {
    "sharp_peak": ["smooth_minimal_roi", "cap_early_roi_spike", "increase_roi_time_window"],
    "overfit_roi": ["smooth_minimal_roi", "cap_early_roi_spike"],
    "aggressive_trailing": ["reduce_trailing_aggression"],
    "aggressive_stoploss": ["tighten_stoploss_if_drawdown_high"],
    "low_trades": ["widen_entry_thresholds_if_low_trades"],
    "high_drawdown": ["tighten_stoploss_if_drawdown_high"],
    "robustness_failed": ["disable_overfit_param_if_sensitivity_bad", "fallback_to_best_stable_trial"],
}


# ── Public API Functions ───────────────────────────────────────────────────────

def get_error_definition(error_code: ErrorCode) -> dict | None:
    """Return the definition for a given error code."""
    return ERROR_DEFINITIONS.get(error_code)


def get_error_severity(error_code: ErrorCode) -> ErrorSeverity | None:
    """Return the severity level for a given error code."""
    definition = ERROR_DEFINITIONS.get(error_code)
    return definition["severity"] if definition else None


def is_auto_fix_allowed(error_code: ErrorCode) -> bool:
    """Check if auto-fix is allowed for a given error code."""
    definition = ERROR_DEFINITIONS.get(error_code)
    return definition["auto_fix_allowed"] if definition else False


def get_suggestion(error_code: ErrorCode) -> str | None:
    """Return the deterministic suggestion for a given error code."""
    return SUGGESTION_MAPPINGS.get(error_code)


def get_auto_fix_actions(error_code: ErrorCode) -> list[AutoFixAction]:
    """Return the list of applicable auto-fix actions for a given error code."""
    return ERROR_TO_AUTO_FIX.get(error_code, [])


def get_auto_fix_action_definition(action: AutoFixAction) -> dict | None:
    """Return the definition for a given auto-fix action."""
    return AUTO_FIX_ACTIONS.get(action)


def classify_error(
    error_message: str,
    context: dict | None = None,
) -> ErrorCode:
    """Classify an error message into an error code based on context.

    This is a simplified classifier. In production, this would use more
    sophisticated pattern matching or ML-based classification.

    Args:
        error_message: The error message to classify
        context: Additional context (stage, metrics, etc.) to aid classification

    Returns:
        The classified error code
    """
    error_lower = error_message.lower()

    # Check for specific error patterns
    if "sharp peak" in error_lower or "sensitivity" in error_lower:
        return "sharp_peak"
    if "robustness" in error_lower:
        return "robustness_failed"
    if "optimization" in error_lower or "hyperopt" in error_lower:
        return "optimization_failed"
    if "low trade" in error_lower or "not enough trades" in error_lower:
        return "low_trades"
    if "drawdown" in error_lower:
        return "high_drawdown"
    if "missing data" in error_lower or "no data" in error_lower:
        return "missing_data"
    if "config" in error_lower or "configuration" in error_lower:
        return "config_error"
    if "syntax" in error_lower or "import" in error_lower:
        return "strategy_syntax_error"
    if "empty pair" in error_lower or "no pairs" in error_lower:
        return "empty_pair_list"
    if "exchange" in error_lower or "download" in error_lower:
        return "exchange_download_failure"
    if "export" in error_lower or "ready" in error_lower:
        return "export_ready"
    if "overfit" in error_lower or "roi" in error_lower:
        return "overfit_roi"
    if "stoploss" in error_lower:
        return "aggressive_stoploss"
    if "trailing" in error_lower:
        return "aggressive_trailing"

    # Default to optimization_failed if no pattern matches
    return "optimization_failed"
