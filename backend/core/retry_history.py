"""Retry history data structures and management utilities.

This module provides:
- RetryAttempt dataclass for structured retry history entries
- Helper functions for creating and managing retry attempts
- Validation and serialization utilities
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .error_taxonomy import AutoFixAction, ErrorCode


@dataclass
class RetryAttempt:
    """A single retry attempt with detailed before/after metrics.

    Attributes:
        attempt: The attempt number (1-based)
        error_code: The error code that triggered this retry
        action: The auto-fix action taken (if any)
        before: Parameter values before the fix
        after: Parameter values after the fix
        status: The result status (improved, declined, failed, pending)
        metrics_before: Performance metrics before the fix
        metrics_after: Performance metrics after the fix
        timestamp: When this attempt was made
        accepted: Whether the fix was accepted by the user (or auto-accepted in auto mode)
        reason: Human-readable reason for the attempt
    """

    attempt: int
    error_code: ErrorCode
    action: AutoFixAction | None = None
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending, improved, declined, failed
    metrics_before: dict[str, float] = field(default_factory=dict)
    metrics_after: dict[str, float] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    accepted: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "attempt": self.attempt,
            "error_code": self.error_code,
            "action": self.action,
            "before": self.before,
            "after": self.after,
            "status": self.status,
            "metrics_before": self.metrics_before,
            "metrics_after": self.metrics_after,
            "timestamp": self.timestamp,
            "accepted": self.accepted,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetryAttempt":
        """Create from dictionary (for deserialization)."""
        return cls(
            attempt=data.get("attempt", 0),
            error_code=data.get("error_code", "optimization_failed"),
            action=data.get("action"),
            before=data.get("before", {}),
            after=data.get("after", {}),
            status=data.get("status", "pending"),
            metrics_before=data.get("metrics_before", {}),
            metrics_after=data.get("metrics_after", {}),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            accepted=data.get("accepted", False),
            reason=data.get("reason", ""),
        )


def create_retry_attempt(
    attempt_number: int,
    error_code: ErrorCode,
    action: AutoFixAction | None = None,
    before_params: dict[str, Any] | None = None,
    after_params: dict[str, Any] | None = None,
    metrics_before: dict[str, float] | None = None,
    metrics_after: dict[str, float] | None = None,
    reason: str = "",
) -> RetryAttempt:
    """Create a new retry attempt with the given parameters.

    Args:
        attempt_number: The attempt number (1-based)
        error_code: The error code that triggered this retry
        action: The auto-fix action taken (if any)
        before_params: Parameter values before the fix
        after_params: Parameter values after the fix
        metrics_before: Performance metrics before the fix
        metrics_after: Performance metrics after the fix
        reason: Human-readable reason for the attempt

    Returns:
        A new RetryAttempt instance
    """
    return RetryAttempt(
        attempt=attempt_number,
        error_code=error_code,
        action=action,
        before=before_params or {},
        after=after_params or {},
        metrics_before=metrics_before or {},
        metrics_after=metrics_after or {},
        reason=reason,
    )


def update_retry_attempt_status(
    attempt: RetryAttempt,
    status: str,
    metrics_after: dict[str, float] | None = None,
    accepted: bool = False,
) -> RetryAttempt:
    """Update the status and metrics of a retry attempt.

    Args:
        attempt: The retry attempt to update
        status: The new status (improved, declined, failed)
        metrics_after: The metrics after the fix (if available)
        accepted: Whether the fix was accepted

    Returns:
        The updated retry attempt
    """
    attempt.status = status
    if metrics_after:
        attempt.metrics_after = metrics_after
    attempt.accepted = accepted
    return attempt


def calculate_improvement(
    metrics_before: dict[str, float],
    metrics_after: dict[str, float],
) -> dict[str, float]:
    """Calculate the improvement percentage for each metric.

    Args:
        metrics_before: Metrics before the fix
        metrics_after: Metrics after the fix

    Returns:
        A dict of metric names to improvement percentages
    """
    improvements = {}
    for key in metrics_before:
        if key in metrics_after:
            before_val = metrics_before[key]
            after_val = metrics_after[key]
            if before_val != 0:
                improvements[key] = ((after_val - before_val) / abs(before_val)) * 100
            else:
                improvements[key] = 0.0
    return improvements


def is_improvement_significant(
    metrics_before: dict[str, float],
    metrics_after: dict[str, float],
    threshold: float = 5.0,
) -> bool:
    """Check if the improvement is significant (above threshold).

    Args:
        metrics_before: Metrics before the fix
        metrics_after: Metrics after the fix
        threshold: The minimum improvement percentage to consider significant

    Returns:
        True if improvement is significant, False otherwise
    """
    improvements = calculate_improvement(metrics_before, metrics_after)
    for metric, improvement in improvements.items():
        # For drawdown, negative improvement is good (lower is better)
        if "drawdown" in metric.lower():
            if improvement < -threshold:
                return True
        # For other metrics, positive improvement is good
        elif improvement > threshold:
            return True
    return False


def serialize_retry_history(history: list[RetryAttempt]) -> list[dict]:
    """Serialize a list of retry attempts to dictionaries.

    Args:
        history: List of retry attempts

    Returns:
        List of dictionaries
    """
    return [attempt.to_dict() for attempt in history]


def deserialize_retry_history(data: list[dict]) -> list[RetryAttempt]:
    """Deserialize a list of dictionaries to retry attempts.

    Args:
        data: List of dictionaries

    Returns:
        List of retry attempts
    """
    return [RetryAttempt.from_dict(item) for item in data]
