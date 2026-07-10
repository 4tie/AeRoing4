"""Auto-fix permission system for safe error correction.

This module defines which error types can be auto-fixed and which require
manual intervention. Auto-fixes that modify strategy parameters or files
require user confirmation, except for internal retries in AutoQuant auto mode.
"""

from __future__ import annotations

from typing import Literal

from .error_taxonomy import ErrorCode


# ── Auto-Fix Permission Rules ─────────────────────────────────────────────────

# Error types where auto-fix is ALLOWED
AUTO_FIX_ALLOWED: set[ErrorCode] = {
    "robustness_failed",
    "sharp_peak",
    "overfit_roi",
    "aggressive_stoploss",
    "aggressive_trailing",
    "low_trades",  # Only when due to narrow thresholds
    "high_drawdown",
}

# Error types where auto-fix is FORBIDDEN (requires manual intervention)
AUTO_FIX_FORBIDDEN: set[ErrorCode] = {
    "missing_data",
    "config_error",
    "strategy_syntax_error",
    "empty_pair_list",
    "exchange_download_failure",
    "export_ready",
    "optimization_failed",  # Requires user to review optimizer settings
}


# ── Auto-Fix Mode Types ───────────────────────────────────────────────────────

AutoFixMode = Literal["manual", "auto_mode_internal"]


# ── Public API Functions ───────────────────────────────────────────────────────

def is_auto_fix_allowed(error_code: ErrorCode) -> bool:
    """Check if auto-fix is allowed for a given error code.

    Args:
        error_code: The error code to check

    Returns:
        True if auto-fix is allowed, False otherwise
    """
    return error_code in AUTO_FIX_ALLOWED


def is_auto_fix_forbidden(error_code: ErrorCode) -> bool:
    """Check if auto-fix is forbidden for a given error code.

    Args:
        error_code: The error code to check

    Returns:
        True if auto-fix is forbidden, False otherwise
    """
    return error_code in AUTO_FIX_FORBIDDEN


def requires_user_confirmation(
    error_code: ErrorCode,
    auto_fix_mode: AutoFixMode = "manual",
    modifies_strategy_params: bool = False,
    modifies_strategy_file: bool = False,
) -> bool:
    """Determine if user confirmation is required for an auto-fix.

    User confirmation is required when:
    - Auto-fix modifies strategy parameters or files (in manual mode)
    - Error type is in AUTO_FIX_FORBIDDEN

    Exception: In AutoQuant "auto_mode_internal", internal retries can proceed
    without confirmation, but all changes must be logged in retry history.

    Args:
        error_code: The error code being fixed
        auto_fix_mode: The auto-fix mode (manual or auto_mode_internal)
        modifies_strategy_params: Whether the fix modifies strategy parameters
        modifies_strategy_file: Whether the fix modifies the strategy file

    Returns:
        True if user confirmation is required, False otherwise
    """
    # Forbidden error types always require manual intervention
    if is_auto_fix_forbidden(error_code):
        return True

    # In auto mode, internal retries don't require confirmation
    if auto_fix_mode == "auto_mode_internal":
        return False

    # In manual mode, any fix that modifies strategy requires confirmation
    if modifies_strategy_params or modifies_strategy_file:
        return True

    # Other fixes (e.g., threshold adjustments) may not require confirmation
    return False


def get_auto_fix_permission_summary(error_code: ErrorCode) -> dict:
    """Return a summary of auto-fix permissions for a given error code.

    Args:
        error_code: The error code to check

    Returns:
        A dict with permission details
    """
    return {
        "error_code": error_code,
        "allowed": is_auto_fix_allowed(error_code),
        "forbidden": is_auto_fix_forbidden(error_code),
        "requires_confirmation": requires_user_confirmation(error_code),
    }


def validate_auto_fix_request(
    error_code: ErrorCode,
    auto_fix_mode: AutoFixMode = "manual",
    modifies_strategy_params: bool = False,
    modifies_strategy_file: bool = False,
) -> tuple[bool, str | None]:
    """Validate an auto-fix request.

    Args:
        error_code: The error code being fixed
        auto_fix_mode: The auto-fix mode (manual or auto_mode_internal)
        modifies_strategy_params: Whether the fix modifies strategy parameters
        modifies_strategy_file: Whether the fix modifies the strategy file

    Returns:
        A tuple of (is_valid, error_message). If is_valid is True, error_message is None.
    """
    if is_auto_fix_forbidden(error_code):
        return False, f"Auto-fix is forbidden for error type: {error_code}"

    if requires_user_confirmation(error_code, auto_fix_mode, modifies_strategy_params, modifies_strategy_file):
        if auto_fix_mode == "manual":
            return False, f"Auto-fix requires user confirmation for error type: {error_code}"

    return True, None
