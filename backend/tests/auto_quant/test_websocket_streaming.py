"""WebSocket streaming tests for real-time pipeline updates.

Tests WebSocket message delivery, format validation, and streaming behavior.
"""

from __future__ import annotations

import pytest

from .fixtures.websocket import (
    create_final_message,
    create_keepalive_message,
    create_snapshot_message,
    create_stage_message,
    validate_websocket_message,
)


class TestWebSocketMessageValidation:
    """Test WebSocket message format validation."""

    def test_validate_snapshot_message(self):
        """Verify snapshot message format is valid."""
        msg = create_snapshot_message(stage=0, progress=0)
        assert validate_websocket_message(msg)

    def test_validate_stage_message(self):
        """Verify stage message format is valid."""
        msg = create_stage_message(stage=1, status="running", progress=15)
        assert validate_websocket_message(msg)

    def test_validate_keepalive_message(self):
        """Verify keepalive message format is valid."""
        msg = create_keepalive_message()
        assert validate_websocket_message(msg)

    def test_validate_final_message(self):
        """Verify final message format is valid."""
        msg = create_final_message(status="completed", progress=100)
        assert validate_websocket_message(msg)

    def test_message_missing_type_field(self):
        """Verify message without type field raises error."""
        msg = {"stage": 1, "status": "running"}
        with pytest.raises(KeyError):
            validate_websocket_message(msg)

    def test_message_invalid_type(self):
        """Verify message with unknown type raises error."""
        msg = {"type": "unknown_type"}
        with pytest.raises(ValueError):
            validate_websocket_message(msg)

    def test_stage_message_missing_required_fields(self):
        """Verify stage message without required fields raises error."""
        msg = {"type": "stage", "stage": 1}  # Missing other fields
        with pytest.raises(KeyError):
            validate_websocket_message(msg)


class TestWebSocketProgressValidation:
    """Test WebSocket progress field validation."""

    def test_progress_zero(self):
        """Verify progress can be zero."""
        msg = create_snapshot_message(progress=0)
        assert validate_websocket_message(msg)
        assert msg["progress"] == 0

    def test_progress_100(self):
        """Verify progress can be 100."""
        msg = create_final_message(progress=100)
        assert validate_websocket_message(msg)
        assert msg["progress"] == 100

    def test_progress_mid_range(self):
        """Verify progress can be mid-range."""
        msg = create_stage_message(stage=2, progress=50)
        assert validate_websocket_message(msg)
        assert msg["progress"] == 50

    def test_progress_invalid_negative(self):
        """Verify negative progress raises error."""
        msg = create_snapshot_message(progress=0)
        msg["progress"] = -1
        with pytest.raises(ValueError):
            validate_websocket_message(msg)

    def test_progress_invalid_over_100(self):
        """Verify progress over 100 raises error."""
        msg = create_snapshot_message(progress=0)
        msg["progress"] = 101
        with pytest.raises(ValueError):
            validate_websocket_message(msg)

    def test_progress_not_integer(self):
        """Verify non-integer progress raises error."""
        msg = create_snapshot_message(progress=0)
        msg["progress"] = 50.5
        with pytest.raises(ValueError):
            validate_websocket_message(msg)


class TestWebSocketStageValidation:
    """Test WebSocket stage field validation."""

    def test_stage_zero(self):
        """Verify stage can be zero."""
        msg = create_snapshot_message(stage=0)
        assert validate_websocket_message(msg)

    def test_stage_one_through_seven(self):
        """Verify all stages 1-7 are valid."""
        for stage in range(1, 8):
            msg = create_stage_message(stage=stage, progress=50)
            assert validate_websocket_message(msg)

    def test_stage_invalid_negative(self):
        """Verify negative stage raises error."""
        msg = create_snapshot_message(stage=0)
        msg["stage"] = -1
        with pytest.raises(ValueError):
            validate_websocket_message(msg)

    def test_stage_invalid_over_seven(self):
        """Verify stage over 7 raises error."""
        msg = create_snapshot_message(stage=0)
        msg["stage"] = 8
        with pytest.raises(ValueError):
            validate_websocket_message(msg)


class TestWebSocketMessageTypes:
    """Test different WebSocket message types."""

    def test_snapshot_has_all_fields(self):
        """Verify snapshot message has all required fields."""
        msg = create_snapshot_message()
        required_fields = {"type", "stage", "status", "message", "progress", "data"}
        assert set(msg.keys()) >= required_fields

    def test_stage_has_all_fields(self):
        """Verify stage message has all required fields."""
        msg = create_stage_message(stage=1)
        required_fields = {"type", "stage", "status", "message", "progress", "data"}
        assert set(msg.keys()) >= required_fields

    def test_keepalive_minimal_fields(self):
        """Verify keepalive message has minimal required fields."""
        msg = create_keepalive_message()
        required_fields = {"type"}
        assert set(msg.keys()) >= required_fields

    def test_final_has_all_fields(self):
        """Verify final message has all required fields."""
        msg = create_final_message()
        required_fields = {"type", "stage", "status", "message", "progress", "data"}
        assert set(msg.keys()) >= required_fields


class TestWebSocketDataField:
    """Test WebSocket data field content."""

    def test_data_field_is_dict(self):
        """Verify data field is always a dictionary."""
        for factory in [
            create_snapshot_message,
            lambda: create_stage_message(stage=1),
            create_final_message,
        ]:
            msg = factory()
            assert isinstance(msg["data"], dict)

    def test_data_contains_run_id(self):
        """Verify data field contains run_id."""
        for factory in [
            create_snapshot_message,
            lambda: create_stage_message(stage=1),
            create_final_message,
        ]:
            msg = factory()
            assert "run_id" in msg["data"]

    def test_snapshot_data_contains_stages(self):
        """Verify snapshot data contains stages list."""
        msg = create_snapshot_message()
        assert isinstance(msg["data"].get("stages"), list)


class TestWebSocketStatusValues:
    """Test valid status values in WebSocket messages."""

    def test_snapshot_status_pending(self):
        """Verify snapshot can have pending status."""
        msg = create_snapshot_message()
        assert msg["status"] == "pending"

    def test_stage_status_running(self):
        """Verify stage message can have running status."""
        msg = create_stage_message(stage=1, status="running")
        assert msg["status"] == "running"

    def test_stage_status_passed(self):
        """Verify stage message can have passed status."""
        msg = create_stage_message(stage=1, status="passed")
        assert msg["status"] == "passed"

    def test_final_status_completed(self):
        """Verify final message can have completed status."""
        msg = create_final_message(status="completed")
        assert msg["status"] == "completed"

    def test_final_status_failed(self):
        """Verify final message can have failed status."""
        msg = create_final_message(status="failed")
        assert msg["status"] == "failed"

    def test_final_status_cancelled(self):
        """Verify final message can have cancelled status."""
        msg = create_final_message(status="cancelled")
        assert msg["status"] == "cancelled"


class TestWebSocketMessageSequence:
    """Test expected message sequences."""

    def test_message_sequence_happy_path(self):
        """Verify expected message sequence for happy path."""
        messages = [
            create_snapshot_message(stage=0, progress=0),
            create_stage_message(stage=1, status="running", progress=15),
            create_stage_message(stage=1, status="passed", progress=30),
            create_keepalive_message(),
            create_stage_message(stage=2, status="running", progress=45),
            create_stage_message(stage=2, status="passed", progress=60),
            create_keepalive_message(),
            create_final_message(status="completed", progress=100),
        ]

        # All messages should be valid
        for msg in messages:
            assert validate_websocket_message(msg)

    def test_snapshot_first(self):
        """Verify snapshot is always first."""
        msg = create_snapshot_message()
        assert msg["type"] == "snapshot"

    def test_keepalive_anytime(self):
        """Verify keepalive can appear anywhere."""
        keepalive = create_keepalive_message()
        assert keepalive["type"] == "keepalive"

    def test_final_last(self):
        """Verify final message ends sequence."""
        msg = create_final_message()
        assert msg["type"] == "final"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
