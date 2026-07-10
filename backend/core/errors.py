"""Backend-neutral exceptions shared by service code.

The desktop app calls backend services directly, so service errors should not be
named after removed route handlers.  `BackendError` keeps the same `message` and
`status_code` fields that older route code used, which lets existing callers
keep the same control-flow decisions without importing server-specific code.
"""

from __future__ import annotations


class BackendError(Exception):
    """Represent a user-facing backend failure.

    Args:
        message: Plain-English explanation that can be shown to the caller.
        status_code: Existing numeric error category kept for compatibility
            with code that used HTTP-like status semantics before the server layer
            was removed.
    """

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
