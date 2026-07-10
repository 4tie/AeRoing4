"""OOS Isolation Tests - Verify OOS never leaks into optimization.

This test suite verifies that Out-of-Sample (OOS) data is properly isolated
from optimization inputs (hyperopt, sensitivity, parameter selection).
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from backend.services.auto_quant.pipeline_modules.oos_guard import (
    check_timerange_overlap,
    extract_pure_is_range,
    parse_timerange,
    validate_oos_isolation,
)


class MockState:
    """Mock PipelineState for testing."""
    def __init__(self):
        self.in_sample_range = "20230101-20231201"
        self.out_sample_range = "20231201-20240601"
        self.validation_notes = []


def test_parse_timerange_valid():
    """Test parsing valid timerange strings."""
    start, end = parse_timerange("20230101-20231201")
    assert start == datetime(2023, 1, 1)
    assert end == datetime(2023, 12, 1)


def test_parse_timerange_invalid():
    """Test parsing invalid timerange strings."""
    start, end = parse_timerange("invalid")
    assert start is None
    assert end is None


def test_check_timerange_overlap_no_overlap():
    """Check non-overlapping timeranges."""
    result = check_timerange_overlap("20230101-20231201", "20240101-20240601")
    assert result["has_overlap"] is False
    assert result["overlap_days"] == 0


def test_check_timerange_overlap_with_overlap():
    """Check overlapping timeranges."""
    result = check_timerange_overlap("20230101-20231201", "20231101-20240601")
    assert result["has_overlap"] is True
    assert result["overlap_days"] > 0


def test_check_timerange_overlap_adjacent():
    """Check adjacent timeranges (no gap, no overlap)."""
    result = check_timerange_overlap("20230101-20231201", "20231201-20240601")
    assert result["has_overlap"] is False
    assert result["overlap_days"] == 0


def test_validate_oos_isolation_properly_separated():
    """Test validation with properly separated IS and OOS ranges."""
    state = MockState()
    state.in_sample_range = "20230101-20231201"
    state.out_sample_range = "20240101-20240601"
    
    is_isolated, warnings = validate_oos_isolation("test_run", state, "test_context")
    
    assert is_isolated is True
    assert len(warnings) == 0


def test_validate_oos_isolation_overlapping():
    """Test validation with overlapping IS and OOS ranges."""
    state = MockState()
    state.in_sample_range = "20230101-20231201"
    state.out_sample_range = "20231101-20240601"
    
    is_isolated, warnings = validate_oos_isolation("test_run", state, "test_context")
    
    assert is_isolated is False
    assert len(warnings) > 0
    assert "CONTAMINATION" in warnings[0]


def test_validate_oos_isolation_oos_before_is():
    """Test validation when OOS starts before IS ends."""
    state = MockState()
    state.in_sample_range = "20230101-20231201"
    state.out_sample_range = "20231101-20231130"
    
    is_isolated, warnings = validate_oos_isolation("test_run", state, "test_context")
    
    assert is_isolated is False
    assert len(warnings) > 0


def test_extract_pure_is_range():
    """Test extraction of pure IS range."""
    state = MockState()
    state.in_sample_range = "20230101-20231201"
    
    pure_range = extract_pure_is_range(state)
    
    assert pure_range == "20230101-20231201"


def test_validate_oos_isolation_missing_ranges():
    """Test validation when IS or OOS range is missing."""
    state = MockState()
    state.in_sample_range = ""
    state.out_sample_range = "20240101-20240601"
    
    is_isolated, warnings = validate_oos_isolation("test_run", state, "test_context")
    
    assert is_isolated is False
    assert len(warnings) > 0


def test_validate_oos_isolation_adds_notes_to_state():
    """Test that validation notes are added to state."""
    state = MockState()
    state.in_sample_range = "20230101-20231201"
    state.out_sample_range = "20231101-20240601"
    
    initial_note_count = len(state.validation_notes)
    
    from backend.services.auto_quant.pipeline_modules.oos_guard import log_oos_contamination_warning
    log_oos_contamination_warning("test_run", state, "test_context")
    
    assert len(state.validation_notes) > initial_note_count


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
