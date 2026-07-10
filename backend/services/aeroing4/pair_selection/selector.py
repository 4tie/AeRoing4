"""Pair Selection logic for AeRoing4.

This module implements AUTO_BEST_N and MANUAL selection modes for
selecting pairs from Pair Discovery results.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from .models import (
    ManualPairValidationError,
    PairSelectionMode,
    PairSelectionOutcome,
    PairSelectionResult,
    PAIR_SELECTION_POLICY_VERSION,
)
from ..models import PairCandidateStatus

if TYPE_CHECKING:
    from ..models import PairDiscoveryResult, PairEvaluationRecord


class PairSelector:
    """Selects pairs from Pair Discovery results for portfolio baseline."""

    def __init__(self):
        self.policy_version = PAIR_SELECTION_POLICY_VERSION

    def select_auto_best_n(
        self,
        discovery_result: PairDiscoveryResult,
        target_count: int = 4,
        discovery_run_id: str | None = None,
    ) -> PairSelectionResult:
        """Select top N VALID_CANDIDATE pairs from discovery results.

        Rules:
        - Only select VALID_CANDIDATE pairs
        - Preserve deterministic ranking order
        - Never select DATA_UNAVAILABLE, EXECUTION_FAILURE, ZERO_TRADES, INSUFFICIENT_TRADES
        - If fewer qualified pairs exist than requested, return PARTIAL_SELECTION
        - If no qualified pairs exist, return INSUFFICIENT_QUALIFIED_PAIRS

        Args:
            discovery_result: Result from Pair Discovery step
            target_count: Number of pairs to select (default 4)
            discovery_run_id: Optional run_id for traceability

        Returns:
            PairSelectionResult with selected pairs and outcome
        """
        # Filter to only VALID_CANDIDATE pairs, preserving ranking order
        qualified_pairs = [
            record for record in discovery_result.ranked_pairs
            if record.status == PairCandidateStatus.VALID_CANDIDATE
        ]

        # Take top N
        selected = qualified_pairs[:target_count]
        selected_pairs = [record.pair for record in selected]

        # Determine outcome
        if len(selected_pairs) == 0:
            outcome = PairSelectionOutcome.INSUFFICIENT_QUALIFIED_PAIRS
            warnings = ["No VALID_CANDIDATE pairs available for selection"]
        elif len(selected_pairs) < target_count:
            outcome = PairSelectionOutcome.PARTIAL_SELECTION
            warnings = [
                f"Requested {target_count} pairs but only {len(selected_pairs)} "
                f"VALID_CANDIDATE pairs available"
            ]
        else:
            outcome = PairSelectionOutcome.SELECTION_COMPLETE
            warnings = []

        # Create ranking snapshot for reproducibility
        ranking_snapshot = [
            {
                "pair": record.pair,
                "status": record.status.value,
                "rank": record.rank,
                "rank_score": record.rank_score,
            }
            for record in discovery_result.ranked_pairs
        ]

        # Compute selection hash
        selection_hash = self._compute_selection_hash(
            mode=PairSelectionMode.AUTO_BEST_N,
            target_count=target_count,
            ranking_snapshot=ranking_snapshot,
        )

        return PairSelectionResult(
            selection_mode=PairSelectionMode.AUTO_BEST_N,
            selection_policy_version=self.policy_version,
            outcome=outcome,
            requested_target_count=target_count,
            selected_pairs=selected_pairs,
            warnings=warnings,
            discovery_run_reference=discovery_run_id,
            discovery_ranking_snapshot=ranking_snapshot,
            selection_hash=selection_hash,
        )

    def select_manual(
        self,
        requested_pairs: list[str],
        discovery_result: PairDiscoveryResult,
        discovery_run_id: str | None = None,
        allow_non_qualified: bool = False,
    ) -> PairSelectionResult:
        """Validate and select manually specified pairs.

        Rules:
        - Each requested pair must exist in discovery results
        - Each requested pair must be technically usable (not DATA_UNAVAILABLE or EXECUTION_FAILURE)
        - If allow_non_qualified is False, only VALID_CANDIDATE pairs are accepted
        - If allow_non_qualified is True, technically usable pairs are accepted with warnings
        - Preserve warnings for pairs that were not VALID_CANDIDATE

        Args:
            requested_pairs: List of pairs manually requested
            discovery_result: Result from Pair Discovery step
            discovery_run_id: Optional run_id for traceability
            allow_non_qualified: Whether to accept technically usable but non-qualified pairs

        Returns:
            PairSelectionResult with selected pairs and validation errors
        """
        # Build lookup map for discovery results
        discovery_map = {record.pair: record for record in discovery_result.all_evaluations}

        selected_pairs: list[str] = []
        rejected_pairs: dict[str, str] = {}
        warnings: list[str] = []

        for pair in requested_pairs:
            record = discovery_map.get(pair)

            if record is None:
                # Pair not in discovery results
                rejected_pairs[pair] = "Pair not found in discovery results"
                warnings.append(f"Pair {pair} not found in discovery results")
                continue

            # Check if technically usable
            if record.status in (
                PairCandidateStatus.DATA_UNAVAILABLE,
                PairCandidateStatus.EXECUTION_FAILURE,
            ):
                rejected_pairs[pair] = f"Pair has status {record.status.value}"
                warnings.append(f"Pair {pair} has status {record.status.value} and was rejected")
                continue

            # Check if qualified
            if record.status != PairCandidateStatus.VALID_CANDIDATE:
                if allow_non_qualified:
                    # Accept with warning
                    selected_pairs.append(pair)
                    warnings.append(
                        f"Pair {pair} was not a VALID_CANDIDATE (status: {record.status.value}) "
                        f"but was accepted as technically usable"
                    )
                else:
                    rejected_pairs[pair] = f"Pair has status {record.status.value}"
                    warnings.append(f"Pair {pair} has status {record.status.value} and was rejected")
                continue

            # Pair is valid and qualified
            selected_pairs.append(pair)

        # Determine outcome
        if len(selected_pairs) == 0:
            outcome = PairSelectionOutcome.INVALID_SELECTION
        elif len(rejected_pairs) > 0:
            outcome = PairSelectionOutcome.PARTIAL_SELECTION
        else:
            outcome = PairSelectionOutcome.SELECTION_COMPLETE

        # Create ranking snapshot
        ranking_snapshot = [
            {
                "pair": record.pair,
                "status": record.status.value,
                "rank": record.rank,
                "rank_score": record.rank_score,
            }
            for record in discovery_result.all_evaluations
        ]

        # Compute selection hash
        selection_hash = self._compute_selection_hash(
            mode=PairSelectionMode.MANUAL,
            requested_pairs=requested_pairs,
            ranking_snapshot=ranking_snapshot,
            allow_non_qualified=allow_non_qualified,
        )

        return PairSelectionResult(
            selection_mode=PairSelectionMode.MANUAL,
            selection_policy_version=self.policy_version,
            outcome=outcome,
            selected_pairs=selected_pairs,
            rejected_manual_pairs=rejected_pairs,
            warnings=warnings,
            discovery_run_reference=discovery_run_id,
            discovery_ranking_snapshot=ranking_snapshot,
            selection_hash=selection_hash,
        )

    def _compute_selection_hash(self, **kwargs) -> str:
        """Compute deterministic hash of selection inputs for idempotency."""
        # Sort keys for deterministic serialization
        sorted_data = json.dumps(kwargs, sort_keys=True)
        return hashlib.sha256(sorted_data.encode()).hexdigest()
