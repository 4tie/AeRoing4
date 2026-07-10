"""Auto-fix engine for strategy parameter corrections.

This module provides:
- ROI smoothing algorithms for Sharp Peak detection
- Parameter adjustment utilities
- Auto-fix action implementations
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

from core.error_taxonomy import AutoFixAction, ErrorCode
from core.retry_history import RetryAttempt

logger = logging.getLogger("auto_quant.auto_fix")


# ── ROI Smoothing Algorithms ───────────────────────────────────────────────────

def smooth_minimal_roi(roi_dict: dict[str, float]) -> dict[str, float]:
    """Smooth ROI table to reduce sharp peaks.

    This function:
    1. Caps early ROI targets to realistic values
    2. Makes the ROI table more gradual
    3. Reduces unrealistic early ROI spikes

    Args:
        roi_dict: The minimal_roi dictionary (e.g., {"0": 0.30, "60": 0.20, ...})

    Returns:
        A smoothed ROI dictionary
    """
    if not roi_dict:
        return roi_dict

    smoothed = copy.deepcopy(roi_dict)
    time_keys = sorted([int(k) for k in roi_dict.keys()])

    if len(time_keys) < 2:
        return smoothed

    # Cap early ROI to maximum of 30% for first 30 minutes
    for key in time_keys:
        if key <= 30:
            smoothed[str(key)] = min(smoothed[str(key)], 0.30)

    # Apply gradual smoothing between time points
    for i in range(1, len(time_keys)):
        prev_key = time_keys[i - 1]
        curr_key = time_keys[i]
        prev_val = smoothed[str(prev_key)]
        curr_val = smoothed[str(curr_key)]

        # Ensure ROI doesn't increase sharply (should decrease or stay flat)
        if curr_val > prev_val:
            # Cap the increase to 10% of previous value
            smoothed[str(curr_key)] = min(curr_val, prev_val * 1.1)

    # Ensure final ROI is reasonable (not too aggressive)
    final_key = str(time_keys[-1])
    smoothed[final_key] = min(smoothed[final_key], 0.05)

    logger.info(
        "smooth_minimal_roi: smoothed ROI table from %s to %s",
        roi_dict,
        smoothed,
    )

    return smoothed


def cap_early_roi_spike(roi_dict: dict[str, float]) -> dict[str, float]:
    """Cap unrealistic early ROI targets.

    This function specifically targets early time windows (first 15 minutes)
    and caps them to prevent overfitting to short-term gains.

    Args:
        roi_dict: The minimal_roi dictionary

    Returns:
        An ROI dictionary with capped early targets
    """
    if not roi_dict:
        return roi_dict

    capped = copy.deepcopy(roi_dict)

    # Cap ROI for first 15 minutes to maximum 25%
    for key in roi_dict:
        if int(key) <= 15:
            capped[key] = min(capped[key], 0.25)

    logger.info("cap_early_roi_spike: capped early ROI targets")

    return capped


def increase_roi_time_window(roi_dict: dict[str, float]) -> dict[str, float]:
    """Increase ROI time windows for more gradual exits.

    This function stretches the ROI table to make exits more gradual,
    reducing the impact of sharp parameter changes.

    Args:
        roi_dict: The minimal_roi dictionary

    Returns:
        An ROI dictionary with stretched time windows
    """
    if not roi_dict:
        return roi_dict

    stretched = {}
    time_keys = sorted([int(k) for k in roi_dict.keys()])

    # Stretch time windows by 1.5x
    for i, key in enumerate(time_keys):
        new_key = int(key * 1.5)
        stretched[str(new_key)] = roi_dict[str(key)]

    logger.info("increase_roi_time_window: stretched ROI time windows")

    return stretched


# ── Parameter Adjustment Utilities ─────────────────────────────────────────────

def reduce_trailing_aggression(params_dict: dict[str, Any]) -> dict[str, Any]:
    """Reduce trailing stop aggression to preserve profits.

    Args:
        params_dict: The parameters dictionary

    Returns:
        Updated parameters with reduced trailing aggression
    """
    updated = copy.deepcopy(params_dict)

    # Reduce trailing stop positive offset
    if "trailing_stop_positive" in updated:
        updated["trailing_stop_positive"] = max(
            0.01, updated["trailing_stop_positive"] * 0.8
        )

    # Reduce trailing stop positive offset
    if "trailing_stop_positive_offset" in updated:
        updated["trailing_stop_positive_offset"] = max(
            0.01, updated["trailing_stop_positive_offset"] * 0.8
        )

    # Increase trailing stop offset (gives more room)
    if "trailing_stop_offset" in updated:
        updated["trailing_stop_offset"] = max(
            0.01, updated["trailing_stop_offset"] * 1.2
        )

    logger.info("reduce_trailing_aggression: reduced trailing stop parameters")

    return updated


def tighten_stoploss_if_drawdown_high(params_dict: dict[str, Any]) -> dict[str, Any]:
    """Tighten stoploss to reduce drawdown.

    Args:
        params_dict: The parameters dictionary

    Returns:
        Updated parameters with tightened stoploss
    """
    updated = copy.deepcopy(params_dict)

    # Tighten stoploss (reduce the percentage)
    if "stoploss" in updated:
        current_stoploss = updated["stoploss"]
        # Ensure stoploss is not too tight (minimum 2%)
        updated["stoploss"] = max(0.02, current_stoploss * 0.9)

    logger.info("tighten_stoploss_if_drawdown_high: tightened stoploss")

    return updated


def widen_entry_thresholds_if_low_trades(params_dict: dict[str, Any]) -> dict[str, Any]:
    """Widen entry conditions to increase trade count.

    Args:
        params_dict: The parameters dictionary

    Returns:
        Updated parameters with widened entry thresholds
    """
    updated = copy.deepcopy(params_dict)

    # Widen entry thresholds by reducing them
    for key in updated:
        if "threshold" in key.lower() or "trigger" in key.lower():
            if isinstance(updated[key], (int, float)) and not isinstance(updated[key], bool):
                # Reduce threshold by 10%
                updated[key] = max(0.01, updated[key] * 0.9)

    logger.info("widen_entry_thresholds_if_low_trades: widened entry thresholds")

    return updated


def disable_overfit_param_if_sensitivity_bad(
    params_dict: dict[str, Any],
    sensitivity_result: dict[str, Any],
) -> dict[str, Any]:
    """Disable overfitting parameters causing sensitivity issues.

    Args:
        params_dict: The parameters dictionary
        sensitivity_result: The sensitivity check result

    Returns:
        Updated parameters with overfitting parameters disabled
    """
    updated = copy.deepcopy(params_dict)

    # If sensitivity check failed, disable the problematic parameter
    if not sensitivity_result.get("passed", True):
        param_name = sensitivity_result.get("param")
        if param_name and param_name in updated:
            # For boolean parameters, flip to False
            if isinstance(updated[param_name], bool):
                updated[param_name] = False
            # For numeric parameters, set to a conservative default
            elif isinstance(updated[param_name], (int, float)):
                if "stoploss" in param_name:
                    updated[param_name] = 0.10  # 10% stoploss
                elif "roi" in param_name:
                    # Keep ROI but make it more conservative
                    pass
                else:
                    # Set to a moderate value
                    updated[param_name] = 0.5

    logger.info("disable_overfit_param_if_sensitivity_bad: disabled problematic parameter")

    return updated


# ── Auto-Fix Action Dispatcher ─────────────────────────────────────────────────

AUTO_FIX_IMPLEMENTATIONS = {
    "smooth_minimal_roi": smooth_minimal_roi,
    "cap_early_roi_spike": cap_early_roi_spike,
    "increase_roi_time_window": increase_roi_time_window,
    "reduce_trailing_aggression": reduce_trailing_aggression,
    "widen_entry_thresholds_if_low_trades": widen_entry_thresholds_if_low_trades,
    "tighten_stoploss_if_drawdown_high": tighten_stoploss_if_drawdown_high,
    "disable_overfit_param_if_sensitivity_bad": disable_overfit_param_if_sensitivity_bad,
}


def apply_auto_fix(
    action: AutoFixAction,
    params_dict: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply an auto-fix action to the parameters.

    Args:
        action: The auto-fix action to apply
        params_dict: The current parameters
        context: Additional context (e.g., sensitivity result)

    Returns:
        Updated parameters after applying the fix

    Raises:
        ValueError: If the action is not implemented
    """
    implementation = AUTO_FIX_IMPLEMENTATIONS.get(action)
    if not implementation:
        raise ValueError(f"Auto-fix action not implemented: {action}")

    # Some actions need additional context
    if action == "disable_overfit_param_if_sensitivity_bad":
        if not context or "sensitivity_result" not in context:
            logger.warning(
                "disable_overfit_param_if_sensitivity_bad requires sensitivity_result in context"
            )
            return params_dict
        return implementation(params_dict, context["sensitivity_result"])

    return implementation(params_dict)


def apply_auto_fix_to_strategy_source(
    action: AutoFixAction,
    strategy_source: str,
    params_dict: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> str:
    """Apply an auto-fix action to strategy source code.

    Args:
        action: The auto-fix action to apply
        strategy_source: The strategy source code
        params_dict: The current parameters
        context: Additional context

    Returns:
        Updated strategy source code
    """
    import re

    # Apply the fix to parameters
    updated_params = apply_auto_fix(action, params_dict, context)

    # Update the source code with new parameters
    updated_source = strategy_source

    # Update stoploss
    if "stoploss" in updated_params:
        stoploss_val = updated_params["stoploss"]
        updated_source = re.sub(
            r'(stoploss\s*=\s*)[-\d.]+',
            f'\\g<1>{stoploss_val}',
            updated_source,
        )

    # Update minimal_roi
    if "minimal_roi" in updated_params:
        roi = updated_params["minimal_roi"]
        roi_str = json.dumps(roi, indent=4)
        updated_source = re.sub(
            r'(minimal_roi\s*=\s*)\{[^}]*\}',
            f'\\g<1>{roi_str}',
            updated_source,
            flags=re.DOTALL,
        )

    # Update other parameters
    for key, val in updated_params.items():
        if key in ("stoploss", "minimal_roi"):
            continue
        # Handle boolean parameters
        if isinstance(val, bool):
            val_str = "True" if val else "False"
            updated_source = re.sub(
                rf'({re.escape(key)}\s*=\s*)(True|False)',
                f'\\g<1>{val_str}',
                updated_source,
            )
        # Handle numeric parameters
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            updated_source = re.sub(
                rf'({re.escape(key)}\s*=\s*)[-\d.]+',
                f'\\g<1>{val}',
                updated_source,
            )

    logger.info(f"apply_auto_fix_to_strategy_source: applied {action} to strategy source")

    return updated_source


# ── Sharp Peak Auto-Fix Logic ───────────────────────────────────────────────────

def apply_sharp_peak_auto_fix(
    params_dict: dict[str, Any],
    sensitivity_result: dict[str, Any],
    metrics_before: dict[str, float],
) -> tuple[dict[str, Any], RetryAttempt]:
    """Apply Sharp Peak auto-fix with ROI smoothing.

    This implements the user's specified logic:
    1. Detect sharp/overfit ROI curve
    2. Smooth/cap minimal_roi
    3. Reduce unrealistic early ROI targets
    4. Make ROI table more gradual
    5. Return updated params and retry attempt record

    Args:
        params_dict: The current parameters
        sensitivity_result: The sensitivity check result
        metrics_before: Performance metrics before the fix

    Returns:
        A tuple of (updated_params, retry_attempt)
    """
    attempt_number = 1  # This would be incremented from state.retry_count

    # Apply ROI smoothing
    updated_params = copy.deepcopy(params_dict)
    if "minimal_roi" in updated_params:
        updated_params["minimal_roi"] = smooth_minimal_roi(
            updated_params["minimal_roi"]
        )

    # Create retry attempt record
    retry_attempt = RetryAttempt(
        attempt=attempt_number,
        error_code="sharp_peak",
        action="smooth_minimal_roi",
        before=params_dict,
        after=updated_params,
        status="pending",
        metrics_before=metrics_before,
        reason="Sharp Peak detected - applying ROI smoothing",
    )

    logger.info(
        "apply_sharp_peak_auto_fix: applied ROI smoothing for Sharp Peak detection"
    )

    return updated_params, retry_attempt
