"""Research Data Zones — zone enum + immutable boundary model.

AeRoing4 v1 supports exactly three active research zones (see
`docs/AEROING4_RESEARCH_PROTOCOL.md`):

  DEVELOP        research, diagnosis, controlled experimentation
  CONFIRMATION   evaluate a locked champion on data unused for research
  FINAL_UNSEEN   final independent evaluation, single-use, terminal

`RESEARCH_PROTOCOL_VERSION` is the single authoritative version string for
this protocol contract, following the same pattern as
`scoring.RANKING_POLICY_VERSION` and `metrics.provenance.METRICS_VERSION`.
Do not scatter version strings elsewhere.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field

# ── Versioning ────────────────────────────────────────────────────────────────

# Single authoritative Research Protocol version. Bump only when zone
# semantics, permission rules, or boundary validation change in a way that
# could change previously-frozen decisions.
RESEARCH_PROTOCOL_VERSION = "1.0.0"

# Single authoritative version of the deterministic boundary-derivation
# policy (see `derive_boundaries`). Bumping this must never retroactively
# change already-persisted boundaries for existing runs (see
# `access_guard.BoundaryManager.initialize_boundaries`).
BOUNDARY_DERIVATION_POLICY_VERSION = "1.0.0"


class ResearchZone(str, Enum):
    """The three active AeRoing4 v1 research data zones."""

    DEVELOP = "develop"
    CONFIRMATION = "confirmation"
    FINAL_UNSEEN = "final_unseen"


class BoundarySource(str, Enum):
    """How a run's concrete research boundaries were established."""

    EXPLICIT = "explicit"
    """Caller supplied develop/confirmation/final_unseen timeranges directly."""

    DERIVED = "derived"
    """Deterministically split from a single larger `research_timerange`
    via `derive_boundaries`, then persisted as concrete values."""


class ResearchBoundaries(BaseModel):
    """Concrete, persisted research-zone boundaries for one AeRoing4 run.

    Resolved boundaries are always explicit concrete values — even when
    `boundary_source == DERIVED`, the derivation happens once and the
    result is what gets persisted here. Nothing re-derives dynamically.
    """

    develop_timerange: str
    confirmation_timerange: str
    final_unseen_timerange: str

    protocol_version: str = RESEARCH_PROTOCOL_VERSION
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    frozen_at: datetime | None = None

    boundary_source: BoundarySource
    boundary_hash: str

    # Present only when boundary_source == DERIVED; kept so a later call with
    # the *same* original input can be recognised as idempotent without
    # recomputing (see `access_guard.BoundaryManager.initialize_boundaries`).
    derivation_source_timerange: str | None = None
    derivation_policy_version: str | None = None

    @property
    def is_frozen(self) -> bool:
        return self.frozen_at is not None

    def frozen_copy(self, *, at: datetime | None = None) -> "ResearchBoundaries":
        """Return a copy with `frozen_at` set, idempotent if already frozen."""
        if self.is_frozen:
            return self
        return self.model_copy(update={"frozen_at": at or datetime.now(UTC)})


# ── Parsing & validation ──────────────────────────────────────────────────────

def _parse_zone_timerange(value: str, *, zone_label: str) -> tuple[datetime, datetime]:
    """Parse a `YYYYMMDD-YYYYMMDD` zone timerange into (start, end).

    Zone boundaries must be explicit and finite (no open-ended `-` ranges,
    unlike the more permissive `smoke_timerange`/`discovery_timerange`
    strings elsewhere) — ordering and overlap checks require concrete dates.
    """
    from .errors import BoundaryErrorCode, BoundaryValidationError

    if not isinstance(value, str) or "-" not in value:
        raise BoundaryValidationError(
            f"{zone_label} timerange '{value}' must be in 'YYYYMMDD-YYYYMMDD' format",
            code=BoundaryErrorCode.INVALID_FORMAT,
        )
    start_str, _, end_str = value.partition("-")
    if not start_str or not end_str or len(start_str) != 8 or len(end_str) != 8:
        raise BoundaryValidationError(
            f"{zone_label} timerange '{value}' must have explicit 8-digit "
            "YYYYMMDD start and end dates",
            code=BoundaryErrorCode.INVALID_FORMAT,
        )
    try:
        start = datetime.strptime(start_str, "%Y%m%d").replace(tzinfo=UTC)
        end = datetime.strptime(end_str, "%Y%m%d").replace(tzinfo=UTC)
    except ValueError as exc:
        raise BoundaryValidationError(
            f"{zone_label} timerange '{value}' is not a valid calendar date",
            code=BoundaryErrorCode.INVALID_FORMAT,
        ) from exc

    if end <= start:
        raise BoundaryValidationError(
            f"{zone_label} timerange '{value}' is reversed or has zero duration",
            code=BoundaryErrorCode.REVERSED_OR_ZERO_DURATION,
        )
    return start, end


def validate_boundary_set(
    develop_timerange: str,
    confirmation_timerange: str,
    final_unseen_timerange: str,
) -> None:
    """Validate a candidate set of the three zone boundaries.

    Raises `BoundaryValidationError` (never returns a bare bool) covering:
      * syntactically invalid ranges
      * reversed or zero-duration ranges
      * overlapping zones
      * zones out of order (CONFIRMATION must follow DEVELOP,
        FINAL_UNSEEN must follow CONFIRMATION)
    """
    from .errors import BoundaryErrorCode, BoundaryValidationError

    d_start, d_end = _parse_zone_timerange(develop_timerange, zone_label="DEVELOP")
    c_start, c_end = _parse_zone_timerange(confirmation_timerange, zone_label="CONFIRMATION")
    f_start, f_end = _parse_zone_timerange(final_unseen_timerange, zone_label="FINAL_UNSEEN")

    if c_start <= d_end:
        raise BoundaryValidationError(
            "CONFIRMATION zone must start strictly after DEVELOP ends "
            f"(develop ends {d_end.date()}, confirmation starts {c_start.date()})",
            code=BoundaryErrorCode.OVERLAPPING_OR_OUT_OF_ORDER,
        )
    if f_start <= c_end:
        raise BoundaryValidationError(
            "FINAL_UNSEEN zone must start strictly after CONFIRMATION ends "
            f"(confirmation ends {c_end.date()}, final_unseen starts {f_start.date()})",
            code=BoundaryErrorCode.OVERLAPPING_OR_OUT_OF_ORDER,
        )


def compute_boundary_hash(
    develop_timerange: str,
    confirmation_timerange: str,
    final_unseen_timerange: str,
    protocol_version: str,
) -> str:
    """Deterministic fingerprint of a boundary set (stable across processes)."""
    canonical = (
        f"{protocol_version}|{develop_timerange}|{confirmation_timerange}|"
        f"{final_unseen_timerange}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def derive_boundaries(
    research_timerange: str,
    policy_version: str = BOUNDARY_DERIVATION_POLICY_VERSION,
) -> tuple[str, str, str]:
    """Deterministically split one larger range into (develop, confirmation, final_unseen).

    Policy v1.0.0: 70% DEVELOP / 15% CONFIRMATION / 15% FINAL_UNSEEN by day
    count, each zone separated by a one-day gap so zones never touch.
    Pure and deterministic: identical input + policy_version always produces
    identical output. Bumping `BOUNDARY_DERIVATION_POLICY_VERSION` (or
    changing the split ratios) must never be applied retroactively — callers
    persist the result once and never recompute for an existing run.
    """
    from .errors import BoundaryErrorCode, BoundaryValidationError

    if policy_version != BOUNDARY_DERIVATION_POLICY_VERSION:
        raise BoundaryValidationError(
            f"Unsupported boundary derivation policy version: {policy_version}",
            code=BoundaryErrorCode.UNSUPPORTED_DERIVATION_POLICY,
        )

    start, end = _parse_zone_timerange(research_timerange, zone_label="research_timerange")
    total_days = (end - start).days

    # Need at least 1 day per zone + 2 one-day gaps = 5 days minimum.
    if total_days < 5:
        raise BoundaryValidationError(
            f"research_timerange '{research_timerange}' spans only {total_days} "
            "day(s); at least 5 are required to derive three non-empty, "
            "non-overlapping zones",
            code=BoundaryErrorCode.SOURCE_RANGE_TOO_SHORT,
        )

    from datetime import timedelta

    develop_days = max(1, round(total_days * 0.70))
    confirmation_days = max(1, round(total_days * 0.15))
    # Reserve at least 1 day + the two 1-day gaps for final_unseen.
    while develop_days + confirmation_days > total_days - 3:
        if develop_days > confirmation_days:
            develop_days -= 1
        else:
            confirmation_days -= 1

    develop_end = start + timedelta(days=develop_days - 1)
    confirmation_start = develop_end + timedelta(days=2)  # 1-day gap
    confirmation_end = confirmation_start + timedelta(days=confirmation_days - 1)
    final_unseen_start = confirmation_end + timedelta(days=2)  # 1-day gap
    final_unseen_end = end

    def fmt(dt: datetime) -> str:
        return dt.strftime("%Y%m%d")

    return (
        f"{fmt(start)}-{fmt(develop_end)}",
        f"{fmt(confirmation_start)}-{fmt(confirmation_end)}",
        f"{fmt(final_unseen_start)}-{fmt(final_unseen_end)}",
    )
