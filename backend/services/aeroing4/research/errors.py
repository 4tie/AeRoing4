"""Typed error hierarchy for the AeRoing4 Research Protocol.

Boundary and access-control problems must never fail silently (no silent
overwrite, no silent re-derivation, no bare booleans). These exceptions are
raised for programming/API misuse and invariant violations; day-to-day
"can this stage access this data right now?" questions are answered by
`AccessDecision` (see `ledger.py`), not by raising.
"""

from __future__ import annotations

from enum import Enum


class BoundaryErrorCode(str, Enum):
    """Typed reasons a research-boundary operation was rejected."""

    INVALID_FORMAT = "invalid_format"
    REVERSED_OR_ZERO_DURATION = "reversed_or_zero_duration"
    OVERLAPPING_OR_OUT_OF_ORDER = "overlapping_or_out_of_order"
    AMBIGUOUS_INPUT = "ambiguous_input"
    UNSUPPORTED_DERIVATION_POLICY = "unsupported_derivation_policy"
    SOURCE_RANGE_TOO_SHORT = "source_range_too_short"
    BOUNDARIES_FROZEN = "boundaries_frozen"
    PROTOCOL_VERSION_MISMATCH = "protocol_version_mismatch"


class ResearchProtocolError(Exception):
    """Base class for all Research Protocol errors."""

    def __init__(self, message: str, *, code: BoundaryErrorCode):
        super().__init__(message)
        self.message = message
        self.code = code

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class BoundaryValidationError(ResearchProtocolError):
    """Raised when a candidate set of research boundaries is invalid.

    Covers: malformed timerange syntax, reversed/zero-duration zones,
    overlapping or out-of-order zones, and unsupported/ambiguous input.
    """


class BoundaryFrozenError(ResearchProtocolError):
    """Raised when code attempts to change boundaries after they froze.

    Boundaries freeze the moment the first protected DEVELOP access is
    granted (see `access_guard.py`). Any later attempt to persist a
    *different* set of boundaries for the same run must raise this instead
    of silently overwriting or silently re-deriving.
    """

    def __init__(self, message: str, *, run_id: str):
        super().__init__(message, code=BoundaryErrorCode.BOUNDARIES_FROZEN)
        self.run_id = run_id


class LedgerIntegrityError(Exception):
    """Raised when the Access Ledger file exists but cannot be read or parsed.

    Fail-closed: callers must treat this as a denial rather than assuming an
    empty ledger. Returning an empty list on corruption would silently erase
    audit history and could allow a second FINAL_UNSEEN access to appear
    un-consumed.
    """

    def __init__(self, message: str, *, run_id: str, cause: Exception | None = None):
        super().__init__(message)
        self.message = message
        self.run_id = run_id
        self.cause = cause

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message
