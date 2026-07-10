"""Typed Research Protocol state attached to an `AeRoing4Run`.

Additive only: `AeRoing4Run.research_protocol` defaults to `None` for the
existing linear workflow, so current serialization/round-trip tests for
runs created before this milestone continue to pass unchanged (see
`docs/AEROING4_TARGET_ARCHITECTURE.md` §14.4).

Note: this is *not* the future `ResearchState` (hypotheses/iteration
counts/champion tracking) planned in Prompt 4 — that is an explicitly
separate, not-yet-implemented model. This module only tracks what the Data
Zone Guard itself needs: the frozen boundary set and the confirmation-pass
flag that gates FINAL_UNSEEN access.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from .data_zones import ResearchBoundaries
from .ledger import AccessDecisionCode, AccessLedgerEntry


class ResearchProtocolState(BaseModel):
    """Per-run Research Protocol state (boundaries + confirmation gate)."""

    boundaries: ResearchBoundaries | None = None

    # Set only by a future Confirmation execution stage (not implemented in
    # this milestone). Exposed now so the Data Zone Guard's FINAL_UNSEEN gate
    # (`CONFIRMATION_NOT_PASSED`) has something concrete to enforce against.
    confirmation_passed: bool = False
    confirmation_passed_at: datetime | None = None


class ResearchProtocolSummary(BaseModel):
    """Read-only, typed summary of a run's Research Protocol status.

    Combines the run's `ResearchProtocolState` with ledger-derived
    information (access counts, latest violation) — see §16 of Prompt 3.
    """

    run_id: str
    protocol_version: str | None
    boundaries: ResearchBoundaries | None
    boundaries_frozen: bool
    boundary_hash: str | None
    confirmation_passed: bool
    access_counts: dict[str, int]
    latest_violation: AccessLedgerEntry | None

    @classmethod
    def build(
        cls,
        *,
        run_id: str,
        state: ResearchProtocolState | None,
        ledger_entries: list[AccessLedgerEntry],
    ) -> "ResearchProtocolSummary":
        boundaries = state.boundaries if state else None
        allowed = sum(1 for e in ledger_entries if e.allowed)
        denied = sum(1 for e in ledger_entries if not e.allowed)
        violations = [e for e in ledger_entries if not e.allowed]
        latest_violation = (
            max(violations, key=lambda e: e.sequence) if violations else None
        )
        return cls(
            run_id=run_id,
            protocol_version=boundaries.protocol_version if boundaries else None,
            boundaries=boundaries,
            boundaries_frozen=bool(boundaries and boundaries.is_frozen),
            boundary_hash=boundaries.boundary_hash if boundaries else None,
            confirmation_passed=bool(state and state.confirmation_passed),
            access_counts={"allowed": allowed, "denied": denied},
            latest_violation=latest_violation,
        )
