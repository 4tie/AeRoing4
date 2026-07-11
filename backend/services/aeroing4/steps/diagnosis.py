"""Diagnosis step for AeRoing4.

Deterministic diagnosis of the Initial Champion using measured evidence.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..diagnosis import DiagnosisEngine, DiagnosisInput, DiagnosisOutcome
from ..diagnosis.persistence import DiagnosisStore
from ..models import AeRoing4StepStatus, StepResult
from ..portfolio_baseline.models import PortfolioBaselineResult
from ..research.champions import ChampionStore

if TYPE_CHECKING:
    from ...app_services import AppServices

logger = logging.getLogger(__name__)


class DiagnosisStep:
    """Step for running deterministic diagnosis on the Initial Champion."""

    def __init__(self, services: "AppServices", runs_root: str):
        """Initialize the diagnosis step.

        Args:
            services: AppServices instance
            runs_root: Path to the runs directory
        """
        self.services = services
        self.runs_root = runs_root
        self.engine = DiagnosisEngine(runs_root)
        self.store = DiagnosisStore(runs_root)
        self.champion_store = ChampionStore(runs_root)

    async def execute(
        self,
        aeroing4_run_id: str,
        baseline_result: dict,
        strategy_name: str,
        champion_id: str,
    ) -> StepResult:
        """Execute diagnosis on the Initial Champion.

        Args:
            aeroing4_run_id: AeRoing4 run ID
            baseline_result: Portfolio baseline result data
            strategy_name: Strategy name
            champion_id: Champion ID

        Returns:
            StepResult with diagnosis outcome
        """
        try:
            # Load portfolio baseline result
            baseline = PortfolioBaselineResult.model_validate(baseline_result)

            # Load champion reference
            champion_reference = self.champion_store.get_champion(champion_id)

            if not champion_reference:
                return StepResult(
                    status=AeRoing4StepStatus.FAILED,
                    error=f"Champion not found: {champion_id}",
                )

            # Create diagnosis input
            diagnosis_input = DiagnosisInput(
                run_id=aeroing4_run_id,
                champion_id=champion_id,
                champion_strategy_hash=champion_reference.strategy_artifact.artifact_hash
                if champion_reference.strategy_artifact
                else "",
                champion_parameter_hash=champion_reference.parameter_artifact.artifact_hash
                if champion_reference.parameter_artifact
                else "",
                baseline_result_id=baseline_result.get("baseline_id", ""),
                baseline_result=baseline,
                pair_discovery_result_id=baseline_result.get("pair_discovery_id"),
                pair_discovery_valid_candidates_count=baseline_result.get(
                    "valid_candidates_count"
                ),
                timeframe=baseline.timeframe,
                develop_timerange=baseline.develop_timerange,
                champion_reference=champion_reference,
            )

            # Run diagnosis
            diagnosis_result = self.engine.diagnose(diagnosis_input)

            # Save diagnosis result
            self.store.save(diagnosis_result)

            # Check for integrity errors
            if diagnosis_result.outcome == DiagnosisOutcome.INTEGRITY_ERROR:
                return StepResult(
                    status=AeRoing4StepStatus.FAILED,
                    error=diagnosis_result.error_message or "Champion integrity check failed",
                )

            # Check for system failures
            if diagnosis_result.outcome == DiagnosisOutcome.SYSTEM_FAILURE:
                return StepResult(
                    status=AeRoing4StepStatus.FAILED,
                    error=diagnosis_result.error_message or "Diagnosis system failure",
                )

            # Insufficient evidence or no actionable findings are not failures
            # They are valid outcomes that should be recorded
            logger.info(
                f"Diagnosis completed for run {aeroing4_run_id}, "
                f"champion {champion_id}: {diagnosis_result.outcome.value}"
            )

            return StepResult(
                status=AeRoing4StepStatus.COMPLETED,
                data={
                    "diagnosis_id": diagnosis_result.diagnosis_id,
                    "outcome": diagnosis_result.outcome.value,
                    "primary_diagnosis": (
                        diagnosis_result.primary_diagnosis.model_dump(mode="json")
                        if diagnosis_result.primary_diagnosis
                        else None
                    ),
                    "evidence_quality": diagnosis_result.evidence_quality.value,
                    "secondary_findings_count": len(diagnosis_result.secondary_findings),
                    "informational_findings_count": len(
                        diagnosis_result.informational_findings
                    ),
                },
            )

        except Exception as exc:
            logger.exception(f"Diagnosis step failed: {exc}")
            return StepResult(
                status=AeRoing4StepStatus.FAILED,
                error=f"Diagnosis step failed: {str(exc)}",
            )
