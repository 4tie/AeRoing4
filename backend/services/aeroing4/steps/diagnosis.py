"""Diagnosis step for AeRoing4.

Deterministic diagnosis of the Initial Champion using measured evidence.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from ..diagnosis import DiagnosisEngine, DiagnosisInput, DiagnosisOutcome
from ..diagnosis.persistence import DiagnosisStore
from ..metrics import METRICS_VERSION
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

            # Compute baseline input hash for idempotency
            baseline_input_hash = baseline.input_hash if baseline.input_hash else self._compute_baseline_input_hash(baseline)

            # Compute canonical metrics hash for idempotency
            canonical_metrics_hash = ""
            if baseline.canonical_metrics:
                canonical_metrics_hash = self._compute_metrics_hash(baseline.canonical_metrics)

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
                baseline_input_hash=baseline_input_hash,
                canonical_metrics_hash=canonical_metrics_hash,
                pair_discovery_result_id=baseline_result.get("pair_discovery_id"),
                pair_discovery_valid_candidates_count=baseline_result.get(
                    "valid_candidates_count"
                ),
                timeframe=baseline.timeframe,
                develop_timerange=baseline.develop_timerange,
                champion_reference=champion_reference,
                metrics_version=METRICS_VERSION,
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

    def _compute_baseline_input_hash(self, baseline: PortfolioBaselineResult) -> str:
        """Compute hash of baseline input for idempotency.

        Args:
            baseline: Portfolio baseline result

        Returns:
            SHA-256 hash of baseline input
        """
        input_dict = {
            "selected_pairs": sorted(baseline.selected_pairs),
            "strategy_name": baseline.strategy_name,
            "strategy_hash": baseline.strategy_hash,
            "parameter_hash": baseline.parameter_hash,
            "timeframe": baseline.timeframe,
            "develop_timerange": baseline.develop_timerange,
            "max_open_trades": baseline.max_open_trades,
            "exchange": baseline.exchange,
            "trading_mode": baseline.trading_mode,
        }
        input_json = json.dumps(input_dict, sort_keys=True)
        return hashlib.sha256(input_json.encode()).hexdigest()

    def _compute_metrics_hash(self, canonical_metrics: dict) -> str:
        """Compute hash of canonical metrics for idempotency.

        Args:
            canonical_metrics: Canonical metrics snapshot dict

        Returns:
            SHA-256 hash of metrics
        """
        # Extract key metrics for identity
        metrics_dict = {
            "total_trades": canonical_metrics.get("total_trades"),
            "profit_factor": canonical_metrics.get("profit_factor"),
            "expectancy": canonical_metrics.get("expectancy"),
            "max_drawdown_pct": canonical_metrics.get("max_drawdown_pct"),
            "win_rate": canonical_metrics.get("win_rate"),
            "calmar": canonical_metrics.get("calmar"),
            "sortino": canonical_metrics.get("sortino"),
        }
        metrics_json = json.dumps(metrics_dict, sort_keys=True)
        return hashlib.sha256(metrics_json.encode()).hexdigest()
