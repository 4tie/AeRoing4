"""OOS Isolation Guard for AutoQuant robustness-first workflow.

This module ensures that Out-of-Sample (OOS) data never contaminates optimization
inputs. It provides validation and warning functions to check timerange separation.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .logging import _rlog


def parse_timerange(timerange: str) -> tuple[datetime | None, datetime | None]:
    """Parse a timerange string (YYYYMMDD-YYYYMMDD) into datetime objects.
    
    Args:
        timerange: Timerange string in format YYYYMMDD-YYYYMMDD
        
    Returns:
        Tuple of (start_date, end_date) as datetime objects, or (None, None) if parsing fails
    """
    try:
        parts = timerange.split("-")
        if len(parts) != 2:
            return None, None
        
        start_str, end_str = parts
        start = datetime.strptime(start_str, "%Y%m%d")
        end = datetime.strptime(end_str, "%Y%m%d")
        return start, end
    except Exception:
        return None, None


def check_timerange_overlap(is_range: str, oos_range: str) -> dict[str, Any]:
    """Check if IS and OOS timeranges overlap.
    
    Args:
        is_range: In-sample timerange (YYYYMMDD-YYYYMMDD)
        oos_range: Out-of-sample timerange (YYYYMMDD-YYYYMMDD)
        
    Returns:
        Dict with overlap information:
        - has_overlap: bool - whether ranges overlap
        - overlap_days: int - number of overlapping days
        - is_start, is_end: datetime objects for IS range
        - oos_start, oos_end: datetime objects for OOS range
    """
    is_start, is_end = parse_timerange(is_range)
    oos_start, oos_end = parse_timerange(oos_range)
    
    if is_start is None or is_end is None or oos_start is None or oos_end is None:
        return {
            "has_overlap": False,
            "overlap_days": 0,
            "is_start": is_start,
            "is_end": is_end,
            "oos_start": oos_start,
            "oos_end": oos_end,
            "parse_error": True,
        }
    
    # Check for overlap
    has_overlap = not (is_end <= oos_start or oos_end <= is_start)
    
    # Calculate overlap days
    overlap_days = 0
    if has_overlap:
        overlap_start = max(is_start, oos_start)
        overlap_end = min(is_end, oos_end)
        overlap_days = max(0, (overlap_end - overlap_start).days)
    
    return {
        "has_overlap": has_overlap,
        "overlap_days": overlap_days,
        "is_start": is_start,
        "is_end": is_end,
        "oos_start": oos_start,
        "oos_end": oos_end,
        "parse_error": False,
    }


def validate_oos_isolation(
    run_id: str,
    state: Any,
    context: str = "hyperopt",
) -> tuple[bool, list[str]]:
    """Validate that OOS data is isolated from optimization inputs.
    
    Checks that the OOS range does not overlap with the IS range and logs
    warnings if contamination is detected.
    
    Args:
        run_id: Pipeline run identifier
        state: PipelineState instance
        context: Context string for logging (e.g., "hyperopt", "sensitivity")
        
    Returns:
        Tuple of (is_isolated, warnings) where:
        - is_isolated: bool - True if OOS is properly isolated
        - warnings: list of warning messages
    """
    warnings = []
    
    is_range = state.in_sample_range
    oos_range = state.out_sample_range
    
    if not is_range or not oos_range:
        warnings.append(f"{context}: Missing IS or OOS range, cannot validate isolation")
        return False, warnings
    
    overlap_info = check_timerange_overlap(is_range, oos_range)
    
    if overlap_info.get("parse_error"):
        warnings.append(f"{context}: Failed to parse timeranges for isolation check")
        return False, warnings
    
    if overlap_info["has_overlap"]:
        overlap_days = overlap_info["overlap_days"]
        warning_msg = (
            f"{context}: OOS CONTAMINATION DETECTED - IS and OOS ranges overlap by "
            f"{overlap_days} days. IS={is_range}, OOS={oos_range}. "
            f"This may lead to overfitting. Results should be interpreted with caution."
        )
        warnings.append(warning_msg)
        _rlog(run_id, 0, logging.WARNING, warning_msg)
        return False, warnings
    
    # Check for proper separation (OOS should start after IS ends)
    is_end = overlap_info["is_end"]
    oos_start = overlap_info["oos_start"]
    
    if is_end and oos_start:
        separation_days = (oos_start - is_end).days
        if separation_days < 0:
            warning_msg = (
                f"{context}: OOS starts before IS ends by {abs(separation_days)} days. "
                f"IS={is_range}, OOS={oos_range}. This is a data leakage risk."
            )
            warnings.append(warning_msg)
            _rlog(run_id, 0, logging.WARNING, warning_msg)
            return False, warnings
        elif separation_days == 0:
            warning_msg = (
                f"{context}: OOS starts immediately after IS ends (no gap). "
                f"IS={is_range}, OOS={oos_range}. Consider adding a buffer period."
            )
            warnings.append(warning_msg)
            _rlog(run_id, 0, logging.INFO, warning_msg)
            # Still return True as this is not a critical issue
    
    return True, warnings


def extract_pure_is_range(state: Any) -> str:
    """Extract the pure IS range for hyperopt, ensuring no OOS contamination.
    
    Args:
        state: PipelineState instance
        
    Returns:
        IS timerange string (YYYYMMDD-YYYYMMDD)
    """
    # For now, just return the IS range
    # In a full implementation, this could add a buffer or trim the range
    return state.in_sample_range


def log_oos_contamination_warning(run_id: str, state: Any, context: str) -> None:
    """Log OOS contamination warning and add to validation notes.
    
    Args:
        run_id: Pipeline run identifier
        state: PipelineState instance
        context: Context string for logging
    """
    is_isolated, warnings = validate_oos_isolation(run_id, state, context)
    
    if not is_isolated:
        # Add warnings to validation notes
        state.validation_notes.extend(warnings)


__all__ = [
    "parse_timerange",
    "check_timerange_overlap",
    "validate_oos_isolation",
    "extract_pure_is_range",
    "log_oos_contamination_warning",
]
