"""WebSocket message validation and fixtures for AutoQuant tests."""

from __future__ import annotations

from typing import Any, TypedDict


class SnapshotMessage(TypedDict):
    """WebSocket snapshot message schema."""

    type: str
    stage: int
    status: str
    message: str
    progress: int
    data: dict[str, Any]


class StageMessage(TypedDict):
    """WebSocket stage update message schema."""

    type: str
    stage: int
    status: str
    message: str
    progress: int
    data: dict[str, Any]


class KeepaliveMessage(TypedDict):
    """WebSocket keepalive message schema."""

    type: str


class FinalMessage(TypedDict):
    """WebSocket final message schema."""

    type: str
    stage: int
    status: str
    message: str
    progress: int
    data: dict[str, Any]


MESSAGE_SCHEMA = {
    "snapshot": {
        "type": str,
        "stage": int,
        "status": str,
        "message": str,
        "progress": int,
        "data": dict,
    },
    "stage": {
        "type": str,
        "stage": int,
        "status": str,
        "message": str,
        "progress": int,
        "data": dict,
    },
    "keepalive": {
        "type": str,
    },
    "final": {
        "type": str,
        "stage": int,
        "status": str,
        "message": str,
        "progress": int,
        "data": dict,
    },
}


def validate_websocket_message(msg: dict[str, Any]) -> bool:
    """
    Validate WebSocket message against expected schema.

    Args:
        msg: Message to validate

    Returns:
        True if valid, False otherwise

    Raises:
        ValueError: If message type is unknown
        TypeError: If field type is incorrect
        KeyError: If required field is missing
    """
    if "type" not in msg:
        raise KeyError("Missing required field: type")

    msg_type = msg.get("type")
    if msg_type not in MESSAGE_SCHEMA:
        raise ValueError(f"Unknown message type: {msg_type}")

    schema = MESSAGE_SCHEMA[msg_type]

    for field, expected_type in schema.items():
        if field not in msg:
            raise KeyError(f"Missing required field: {field}")

        actual_value = msg[field]
        if expected_type == dict and not isinstance(actual_value, dict):
            raise TypeError(
                f"Field '{field}' should be dict, got {type(actual_value).__name__}"
            )
        elif field == "progress" and not isinstance(actual_value, expected_type):
            raise ValueError(
                f"Progress must be int in range [0, 100], got {actual_value}"
            )
        elif expected_type != dict and not isinstance(actual_value, expected_type):
            raise TypeError(
                f"Field '{field}' should be {expected_type.__name__}, "
                f"got {type(actual_value).__name__}"
            )

    # Additional validation for specific message types
    if msg_type in ("snapshot", "stage", "final"):
        progress = msg.get("progress")
        if not isinstance(progress, int) or not (0 <= progress <= 100):
            raise ValueError(f"Progress must be int in range [0, 100], got {progress}")

        stage = msg.get("stage")
        if not isinstance(stage, int) or not (0 <= stage <= 7):
            raise ValueError(f"Stage must be int in range [0, 7], got {stage}")

    return True


def create_snapshot_message(stage: int = 0, progress: int = 0) -> dict[str, Any]:
    """Create a valid snapshot message."""
    return {
        "type": "snapshot",
        "stage": stage,
        "status": "pending",
        "message": "Pipeline initialized",
        "progress": progress,
        "data": {
            "run_id": "test-run-id",
            "current_stage": stage,
            "status": "pending",
            "stages": [],
        },
    }


def create_stage_message(
    stage: int, status: str = "running", progress: int = 0, message: str = ""
) -> dict[str, Any]:
    """Create a valid stage update message."""
    return {
        "type": "stage",
        "stage": stage,
        "status": status,
        "message": message or f"Stage {stage} {status}",
        "progress": progress,
        "data": {
            "run_id": "test-run-id",
            "current_stage": stage,
            "status": status,
        },
    }


def create_keepalive_message() -> dict[str, Any]:
    """Create a valid keepalive message."""
    return {"type": "keepalive"}


def create_final_message(
    status: str = "completed", progress: int = 100
) -> dict[str, Any]:
    """Create a valid final message."""
    return {
        "type": "final",
        "stage": 7,
        "status": status,
        "message": f"Pipeline {status}",
        "progress": progress,
        "data": {
            "run_id": "test-run-id",
            "status": status,
            "stages": [{"index": i, "status": "passed"} for i in range(1, 8)],
        },
    }
