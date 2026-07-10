"""Initial Champion creation step for AeRoing4.

Creates the initial champion from portfolio baseline results,
referencing immutable artifacts and baseline metrics.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..models import AeRoing4StepStatus, StepResult
from ..portfolio_baseline import PortfolioBaselineResult
from ..research import (
    ArtifactReference,
    ChampionReference,
    ChampionSourceType,
    ChampionStore,
)

if TYPE_CHECKING:
    from ...app_services import AppServices

logger = logging.getLogger(__name__)


class InitialChampionStep:
    """Initial Champion creation step.

    Creates the initial champion from portfolio baseline results.
    """

    def __init__(self, services: "AppServices", runs_root: Path):
        """Initialize initial champion step with services."""
        self.services = services
        self.runs_root = runs_root
        self.champion_store = ChampionStore(runs_root)

    async def execute(
        self,
        aeroing4_run_id: str,
        baseline_result: PortfolioBaselineResult,
        strategy_name: str,
        strategy_path: str | None = None,
    ) -> StepResult:
        """Execute initial champion creation.

        Args:
            aeroing4_run_id: AeRoing4 run ID
            baseline_result: Portfolio baseline result
            strategy_name: Strategy name
            strategy_path: Optional strategy file path

        Returns:
            StepResult with champion reference data
        """
        started_at = datetime.now(UTC)

        try:
            # Validate baseline result
            if baseline_result.status.value != "pass_baseline_created":
                return StepResult(
                    step_name="initial_champion",
                    status=AeRoing4StepStatus.FAILED,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    error=f"Cannot create champion from failed baseline: {baseline_result.status.value}",
                )

            if not baseline_result.backtest_run_id:
                return StepResult(
                    step_name="initial_champion",
                    status=AeRoing4StepStatus.FAILED,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    error="Baseline result has no backtest_run_id",
                )

            # Load backtest run directory for artifacts
            backtest_run_dir = self.services.run_repository.find_run_dir(baseline_result.backtest_run_id)
            if not backtest_run_dir.exists():
                return StepResult(
                    step_name="initial_champion",
                    status=AeRoing4StepStatus.FAILED,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    error=f"Backtest run directory not found: {baseline_result.backtest_run_id}",
                )

            # Create strategy artifact reference
            strategy_artifact = self._create_strategy_artifact_reference(
                backtest_run_dir=backtest_run_dir,
                strategy_name=strategy_name,
                strategy_path=strategy_path,
            )

            # Create parameter artifact reference
            parameter_artifact = self._create_parameter_artifact_reference(
                backtest_run_dir=backtest_run_dir,
            )

            # Create canonical metrics snapshot
            from ..metrics.models import CanonicalMetricsSnapshot
            canonical_metrics = None
            if baseline_result.canonical_metrics:
                try:
                    canonical_metrics = CanonicalMetricsSnapshot.model_validate(baseline_result.canonical_metrics)
                except Exception as e:
                    logger.warning(f"Failed to validate canonical metrics: {e}")

            # Create champion reference
            champion = ChampionReference(
                run_id=aeroing4_run_id,
                parent_champion_id=None,  # First champion has no parent
                source_type=ChampionSourceType.BASELINE,
                source_experiment_id=None,
                strategy_artifact=strategy_artifact,
                parameter_artifact=parameter_artifact,
                metrics=canonical_metrics,
            )

            # Register champion via ChampionStore
            registered_champion = self.champion_store.register(champion)

            # Update ResearchState with champion pointer
            from ..research.research_state import ResearchStateStore
            research_state_store = ResearchStateStore(self.runs_root)
            research_state = research_state_store.load()
            if research_state:
                research_state.current_champion_id = registered_champion.champion_id
                research_state_store.save(research_state)

            completed_at = datetime.now(UTC)
            duration_seconds = (completed_at - started_at).total_seconds()

            return StepResult(
                step_name="initial_champion",
                status=AeRoing4StepStatus.PASSED,
                started_at=started_at,
                completed_at=completed_at,
                data={
                    "champion_id": registered_champion.champion_id,
                    "run_id": registered_champion.run_id,
                    "source_type": registered_champion.source_type.value,
                    "strategy_artifact": registered_champion.strategy_artifact.model_dump(mode="json") if registered_champion.strategy_artifact else None,
                    "parameter_artifact": registered_champion.parameter_artifact.model_dump(mode="json") if registered_champion.parameter_artifact else None,
                    "metrics_present": registered_champion.metrics is not None,
                    "created_at": registered_champion.created_at.isoformat(),
                },
            )

        except Exception as exc:
            logger.exception("Initial champion creation failed")
            return StepResult(
                step_name="initial_champion",
                status=AeRoing4StepStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error=f"Initial champion creation failed: {exc}",
            )

    def _create_strategy_artifact_reference(
        self,
        backtest_run_dir: Path,
        strategy_name: str,
        strategy_path: str | None,
    ) -> ArtifactReference:
        """Create artifact reference for strategy file.

        Args:
            backtest_run_dir: Backtest run directory
            strategy_name: Strategy name
            strategy_path: Original strategy file path

        Returns:
            ArtifactReference for strategy
        """
        # The strategy snapshot is stored as strategy.py in the run directory
        artifact_path = f"{strategy_name}.py"
        artifact_file = backtest_run_dir / artifact_path

        if not artifact_file.exists():
            raise FileNotFoundError(f"Strategy artifact not found: {artifact_file}")

        # Compute hash of run-local copy
        artifact_content = artifact_file.read_text(encoding="utf-8")
        artifact_hash = hashlib.sha256(artifact_content.encode()).hexdigest()

        # Compute hash of original source if available
        original_source_hash = ""
        if strategy_path and Path(strategy_path).exists():
            original_content = Path(strategy_path).read_text(encoding="utf-8")
            original_source_hash = hashlib.sha256(original_content.encode()).hexdigest()

        return ArtifactReference(
            artifact_path=artifact_path,
            artifact_hash=artifact_hash,
            original_source_path=str(strategy_path) if strategy_path else "",
            original_source_hash=original_source_hash,
        )

    def _create_parameter_artifact_reference(
        self,
        backtest_run_dir: Path,
    ) -> ArtifactReference:
        """Create artifact reference for parameter file.

        Args:
            backtest_run_dir: Backtest run directory

        Returns:
            ArtifactReference for parameters
        """
        # Parameters are stored as params.json in the run directory
        artifact_path = "params.json"
        artifact_file = backtest_run_dir / artifact_path

        if not artifact_file.exists():
            raise FileNotFoundError(f"Parameter artifact not found: {artifact_file}")

        # Compute hash of run-local copy
        artifact_content = artifact_file.read_text(encoding="utf-8")
        artifact_hash = hashlib.sha256(artifact_content.encode()).hexdigest()

        # Original source is the params.json from the version manager
        # For now, use the same hash since params.json is the canonical source
        original_source_hash = artifact_hash

        return ArtifactReference(
            artifact_path=artifact_path,
            artifact_hash=artifact_hash,
            original_source_path=artifact_path,
            original_source_hash=original_source_hash,
        )
