"""Pair Selection step for AeRoing4.

Selects pairs from Pair Discovery results for portfolio baseline execution.
Supports AUTO_BEST_N and MANUAL selection modes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..models import AeRoing4StepStatus, PairDiscoveryResult, StepResult
from ..pair_selection import (
    PairSelectionMode,
    PairSelectionOutcome,
    PairSelectionResult,
    PairSelector,
)

if TYPE_CHECKING:
    from ...app_services import AppServices

logger = logging.getLogger(__name__)


class PairSelectionStep:
    """Pair Selection step.

    Selects pairs from Pair Discovery results for portfolio baseline execution.
    """

    def __init__(self, services: "AppServices"):
        """Initialize pair selection step with services."""
        self.services = services
        self.selector = PairSelector()

    async def execute(
        self,
        discovery_result: PairDiscoveryResult,
        selection_mode: PairSelectionMode = PairSelectionMode.AUTO_BEST_N,
        target_pair_count: int = 4,
        manually_selected_pairs: list[str] | None = None,
        allow_non_qualified_manual: bool = False,
    ) -> StepResult:
        """Execute pair selection.

        Args:
            discovery_result: Result from Pair Discovery step
            selection_mode: AUTO_BEST_N or MANUAL
            target_pair_count: Number of pairs to select for AUTO_BEST_N
            manually_selected_pairs: List of pairs for MANUAL mode
            allow_non_qualified_manual: Whether to allow non-qualified pairs in MANUAL mode

        Returns:
            StepResult with PairSelectionResult data
        """
        started_at = datetime.now(UTC)

        try:
            if selection_mode == PairSelectionMode.AUTO_BEST_N:
                selection_result = self.selector.select_auto_best_n(
                    discovery_result=discovery_result,
                    target_count=target_pair_count,
                    discovery_run_id=None,  # Will be set by orchestrator
                )
            elif selection_mode == PairSelectionMode.MANUAL:
                if not manually_selected_pairs:
                    return StepResult(
                        step_name="pair_selection",
                        status=AeRoing4StepStatus.FAILED,
                        started_at=started_at,
                        completed_at=datetime.now(UTC),
                        error="MANUAL selection mode requires manually_selected_pairs",
                    )

                selection_result = self.selector.select_manual(
                    requested_pairs=manually_selected_pairs,
                    discovery_result=discovery_result,
                    discovery_run_id=None,  # Will be set by orchestrator
                    allow_non_qualified=allow_non_qualified_manual,
                )
            else:
                return StepResult(
                    step_name="pair_selection",
                    status=AeRoing4StepStatus.FAILED,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    error=f"Unsupported selection mode: {selection_mode}",
                )

            # Determine step status based on outcome
            if selection_result.outcome in (
                PairSelectionOutcome.SELECTION_COMPLETE,
                PairSelectionOutcome.PARTIAL_SELECTION,
            ):
                step_status = AeRoing4StepStatus.PASSED
            else:
                step_status = AeRoing4StepStatus.FAILED

            completed_at = datetime.now(UTC)
            duration_seconds = (completed_at - started_at).total_seconds()

            return StepResult(
                step_name="pair_selection",
                status=step_status,
                started_at=started_at,
                completed_at=completed_at,
                data=selection_result.model_dump(mode="json"),
                error=None if step_status == AeRoing4StepStatus.PASSED else selection_result.warnings[0] if selection_result.warnings else "Pair selection failed",
            )

        except Exception as exc:
            logger.exception("Pair selection execution failed")
            return StepResult(
                step_name="pair_selection",
                status=AeRoing4StepStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error=f"Pair selection execution failed: {exc}",
            )
