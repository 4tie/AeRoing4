"""Comprehensive error types for optimizer operations."""

from __future__ import annotations

from enum import Enum
from typing import Any


class OptimizerErrorCode(str, Enum):
    """Standardized error codes for optimizer operations."""
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_ALREADY_RUNNING = "SESSION_ALREADY_RUNNING"
    SESSION_CORRUPTED = "SESSION_CORRUPTED"
    TRIAL_EXECUTION_FAILED = "TRIAL_EXECUTION_FAILED"
    TRIAL_VALIDATION_FAILED = "TRIAL_VALIDATION_FAILED"
    STRATEGY_NOT_FOUND = "STRATEGY_NOT_FOUND"
    VERSION_NOT_FOUND = "VERSION_NOT_FOUND"
    INVALID_PARAMETERS = "INVALID_PARAMETERS"
    RESOURCE_LOCKED = "RESOURCE_LOCKED"
    TIMEOUT_EXPIRED = "TIMEOUT_EXPIRED"
    BACKTEST_RUNNER_BUSY = "BACKTEST_RUNNER_BUSY"
    STORAGE_ERROR = "STORAGE_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class OptimizerError(Exception):
    """Base class for optimizer-specific errors."""

    def __init__(
        self,
        message: str,
        code: OptimizerErrorCode,
        details: dict[str, Any] | None = None,
        recoverable: bool = False,
    ):
        self.message = message
        self.code = code
        self.details = details or {}
        self.recoverable = recoverable
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary for API responses."""
        return {
            "error": self.code.value,
            "message": self.message,
            "details": self.details,
            "recoverable": self.recoverable,
        }


class SessionNotFoundError(OptimizerError):
    """Raised when an optimizer session cannot be found."""

    def __init__(self, session_id: str, details: dict[str, Any] | None = None):
        super().__init__(
            f"Optimizer session '{session_id}' not found",
            OptimizerErrorCode.SESSION_NOT_FOUND,
            {"session_id": session_id, **(details or {})},
            recoverable=False,
        )


class SessionAlreadyRunningError(OptimizerError):
    """Raised when trying to start a session while another is running."""

    def __init__(self, active_session_id: str | None = None):
        details = {}
        if active_session_id:
            details["active_session_id"] = active_session_id
        super().__init__(
            "An optimizer session is already running",
            OptimizerErrorCode.SESSION_ALREADY_RUNNING,
            details,
            recoverable=True,
        )


class SessionCorruptedError(OptimizerError):
    """Raised when session data is corrupted or invalid."""

    def __init__(self, session_id: str, reason: str):
        super().__init__(
            f"Session '{session_id}' data is corrupted: {reason}",
            OptimizerErrorCode.SESSION_CORRUPTED,
            {"session_id": session_id, "reason": reason},
            recoverable=False,
        )


class TrialExecutionError(OptimizerError):
    """Raised when trial execution fails."""

    def __init__(
        self,
        trial_number: int,
        reason: str,
        recoverable: bool = True,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            f"Trial #{trial_number} execution failed: {reason}",
            OptimizerErrorCode.TRIAL_EXECUTION_FAILED,
            {"trial_number": trial_number, "reason": reason, **(details or {})},
            recoverable,
        )


class TrialValidationError(OptimizerError):
    """Raised when trial parameters are invalid."""

    def __init__(self, trial_number: int, validation_errors: list[str]):
        super().__init__(
            f"Trial #{trial_number} validation failed",
            OptimizerErrorCode.TRIAL_VALIDATION_FAILED,
            {"trial_number": trial_number, "validation_errors": validation_errors},
            recoverable=False,
        )


class ResourceTimeoutError(OptimizerError):
    """Raised when an operation times out."""

    def __init__(self, resource: str, timeout_seconds: float):
        super().__init__(
            f"Resource '{resource}' operation timed out after {timeout_seconds}s",
            OptimizerErrorCode.TIMEOUT_EXPIRED,
            {"resource": resource, "timeout_seconds": timeout_seconds},
            recoverable=True,
        )