"""Pair Selection models and policy for AeRoing4.

This module defines the data models and policy for selecting pairs from
Pair Discovery results for portfolio baseline execution.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# Policy version for pair selection
PAIR_SELECTION_POLICY_VERSION = "1.0.0"


class PairSelectionMode(str, Enum):
    """Selection mode for pair selection."""
    AUTO_BEST_N = "auto_best_n"
    MANUAL = "manual"


class PairSelectionOutcome(str, Enum):
    """Outcome of pair selection."""
    SELECTION_COMPLETE = "selection_complete"
    PARTIAL_SELECTION = "partial_selection"
    INSUFFICIENT_QUALIFIED_PAIRS = "insufficient_qualified_pairs"
    SELECTION_FAILED = "selection_failed"
    INVALID_SELECTION = "invalid_selection"


class PairSelectionResult(BaseModel):
    """Result of the pair selection step."""

    selection_mode: PairSelectionMode
    selection_policy_version: str = PAIR_SELECTION_POLICY_VERSION
    outcome: PairSelectionOutcome

    # Requested vs actual
    requested_target_count: int | None = None  # For AUTO_BEST_N
    selected_pairs: list[str] = Field(default_factory=list)
    rejected_manual_pairs: dict[str, str] = Field(default_factory=dict)  # pair -> reason

    # Warnings and evidence
    warnings: list[str] = Field(default_factory=list)

    # Traceability
    discovery_run_reference: str | None = None  # run_id of the discovery step
    discovery_ranking_snapshot: list[dict] = Field(default_factory=list)  # snapshot of ranked pairs at selection time

    # Reproducibility
    selected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    selection_hash: str = ""  # hash of selection inputs for idempotency

    # Freeze tracking
    frozen_at: datetime | None = None  # When selection became immutable (baseline start)


class ManualPairValidationError(BaseModel):
    """Validation error for a manually selected pair."""
    pair: str
    reason: str
    is_usable: bool  # Whether the pair is technically usable even if not qualified
    was_qualified: bool | None = None  # Whether it was a VALID_CANDIDATE in discovery
