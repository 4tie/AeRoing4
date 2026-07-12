"""Loop Coordinator for the AeRoing4 Controlled Research Loop (§5).

Orchestrates one deterministic iteration (and a bounded loop) wiring the
already-built primitives together:

    Diagnosis
      → Hypothesis reuse/create
      → Proposal Generator
      → Schema + evidence validation
      → Allowed Target validation
      → Mutation Policy
      → Experiment identity
      → ExperimentStore.reserve()  (budget consumed HERE, once)
      → DEVELOP access
      → READY
      → Candidate Artifact
      → Candidate Executor
      → Metrics SSOT
      → Decision Policy
      → Persist decision
      → Hypothesis update
      → KEEP:  Champion promotion + ResearchState update + re-diagnosis
      → DROP/INCONCLUSIVE: Champion unchanged

Hard invariants (user decision 2026-07-11):
  * No candidate artifact before a SUCCESSFUL reservation.
  * No budget consumption when AI unavailable / invalid proposal / duplicate.
  * No access to non-DEVELOP (only DEVELOP_CONSUMER stage; executor gets
    develop_timerange only).
  * The AI never decides KEEP/DROP — only the DecisionPolicy does.
  * DecisionPolicy never promotes; promotion happens here, only on KEEP.
  * No new state store — the Coordinator uses the existing ResearchState.
  * After KEEP, the next proposal is built from the NEW champion's diagnosis.
  * Duplicate → returns the existing experiment reference, no new execution.
  * Restart → does not silently re-run an in-flight experiment.

The Coordinator is orchestration-only: it owns no persistence of its own
beyond calling the existing stores' atomic methods.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable, Optional, Union

from pydantic import BaseModel, Field

from ..diagnosis.models import DiagnosisCode
from ..metrics.models import CanonicalMetricsSnapshot
from .access_guard import DataZoneGuard
from .allowed_targets import AllowedMutationTarget, discover_allowed_mutation_targets
from .candidate_artifacts import CandidateArtifactResult, CandidateArtifactService
from .candidate_executor import CandidateExecutor, CandidateExecutionStatus
from .champions import (
    ArtifactReference,
    ChampionReference,
    ChampionSourceType,
    ChampionStore,
)
from .data_zones import ResearchZone
from .decision_policy import DecisionPolicy, DecisionRequest
from .experiments import (
    DuplicateExperimentDecision,
    ExperimentDecision,
    ExperimentRecord,
    ExperimentStatus,
    ExperimentStore,
    OriginalStrategyProvenance,
)
from .hypotheses import (
    HypothesisEvidenceRef,
    HypothesisRecord,
    HypothesisSource,
    HypothesisStatus,
    HypothesisStore,
)
from .identity import (
    compute_mutation_identity_hash,
    format_mutation_identity,
    mutation_identity_from_exact_change,
)
from .mutation_policy import MutationPolicy, MutationPolicyCode
from .proposal_generator import (
    ProposalGenerator,
    ProposalOutcome,
    ProposalRequest,
    ProposalResult,
)
from .research_state import ResearchState, ResearchStateStore, ResearchStatus
from .stages import ResearchStage


class LoopStage(str, Enum):
    DIAGNOSIS = "diagnosis"
    HYPOTHESIS = "hypothesis"
    PROPOSAL = "proposal"
    VALIDATION = "validation"
    MUTATION_POLICY = "mutation_policy"
    EXPERIMENT_IDENTITY = "experiment_identity"
    RESERVE = "reserve"
    DEVELOP_ACCESS = "develop_access"
    READY = "ready"
    CANDIDATE_ARTIFACT = "candidate_artifact"
    CANDIDATE_EXECUTOR = "candidate_executor"
    METRICS = "metrics"
    DECISION = "decision"
    PERSIST_DECISION = "persist_decision"
    HYPOTHESIS_UPDATE = "hypothesis_update"
    PROMOTION = "promotion"


class LoopOutcome(str, Enum):
    """Why an iteration stopped (no decision needed)."""

    AI_UNAVAILABLE = "ai_unavailable"
    PROPOSAL_SKIPPED = "proposal_skipped"
    PROPOSAL_INVALID = "proposal_invalid"
    NO_SAFE_TARGET = "no_safe_target"
    TARGET_NOT_ALLOWED = "target_not_allowed"
    VALUE_OUT_OF_RANGE = "value_out_of_range"
    ZONE_ACCESS_DENIED = "zone_access_denied"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DUPLICATE = "duplicate"
    DUPLICATE_MUTATION = "duplicate_mutation"
    RECONCILE_REQUIRED = "reconcile_required"
    EXECUTION_SYSTEM_FAILURE = "execution_system_failure"
    DECISION_KEEP = "decision_keep"
    DECISION_DROP = "decision_drop"
    DECISION_INCONCLUSIVE = "decision_inconclusive"


class LoopIterationResult(BaseModel):
    """Full typed result of one loop iteration."""

    run_id: str
    outcome: LoopOutcome
    stage_reached: LoopStage
    hypothesis_id: Optional[str] = None
    experiment_id: Optional[str] = None
    duplicate_of_experiment_id: Optional[str] = None
    proposal: Optional[ProposalResult] = None
    mutation_code: Optional[str] = None
    decision: Optional[ExperimentDecision] = None
    decision_reason: Optional[str] = None
    promoted_champion_id: Optional[str] = None
    details: str = ""


# Pluggable diagnostics + proposal so the Coordinator is testable without Ollama.
DiagnoseFn = Callable[[ChampionReference], DiagnosisCode]
ProposalCallable = Union[
    Callable[[ProposalRequest], ProposalResult],
    Callable[[ProposalRequest], Awaitable[ProposalResult]],
]


class ResearchLoopCoordinator:
    """Orchestrates the controlled research loop using existing stores only."""

    def __init__(
        self,
        *,
        runs_root: "Path",
        experiment_store: ExperimentStore,
        hypothesis_store: HypothesisStore,
        champion_store: ChampionStore,
        state_store: ResearchStateStore,
        artifact_service: CandidateArtifactService,
        executor: CandidateExecutor,
        zone_guard: DataZoneGuard,
        diagnose_fn: DiagnoseFn,
        proposal_callable: ProposalCallable,
        budget_service=None,
        strategies_dir: Path,
        develop_timerange: str,
        pairs: list[str],
        timeframe: str = "5m",
        exchange: str = "binance",
        trading_mode: str = "spot",
        dry_run_wallet: float = 1000.0,
        max_open_trades: int = 4,
        config_file: str = "config.json",
        min_sample_trades: int = 30,
    ):
        self.runs_root = runs_root
        self.strategies_dir = strategies_dir
        self.experiment_store = experiment_store
        self.hypothesis_store = hypothesis_store
        self.champion_store = champion_store
        self.state_store = state_store
        self.artifact_service = artifact_service
        self.executor = executor
        self.zone_guard = zone_guard
        self.diagnose_fn = diagnose_fn
        self.proposal_callable = proposal_callable
        self.budget_service = budget_service
        self.develop_timerange = develop_timerange
        self.pairs = pairs
        self.timeframe = timeframe
        self.exchange = exchange
        self.trading_mode = trading_mode
        self.dry_run_wallet = dry_run_wallet
        self.max_open_trades = max_open_trades
        self.config_file = config_file
        self.min_sample_trades = min_sample_trades

    # ── Public drivers ──────────────────────────────────────────────────────

    async def run_one_iteration(self, *, run_id: str) -> LoopIterationResult:
        """Execute one full deterministic iteration. Never raises for normal stops."""
        state = self.state_store.load_or_create(run_id)
        if state.current_champion_id is None:
            return self._stop(
                run_id, LoopOutcome.PROPOSAL_SKIPPED, LoopStage.DIAGNOSIS,
                details="No current champion established; baseline required first",
            )

        champion = self.champion_store.get(run_id, state.current_champion_id)
        if champion is None:
            return self._stop(
                run_id, LoopOutcome.PROPOSAL_SKIPPED, LoopStage.DIAGNOSIS,
                details="Current champion reference missing",
            )

        # §10/E: restart recovery guard. If an in-flight experiment was left in
        # RUNNING on a previous (interrupted) run, the store transitions it to
        # INTERRUPTED on reload and resume_safety_report flags reconciliation as
        # required. We must NOT silently reserve a duplicate or re-execute — the
        # operator must reconcile (mark COMPLETED/FAILED_SYSTEM) first.
        report = self.experiment_store.resume_safety_report(run_id)
        if report.must_reconcile_first:
            return self._stop(
                run_id, LoopOutcome.RECONCILE_REQUIRED, LoopStage.RESERVE,
                experiment_id=report.active_experiment_id,
                details=report.reason,
            )

        # §7: mark research ACTIVE while the loop is producing work. A PAUSED
        # run may be resumed — re-activating it here continues from where it
        # stopped (no silent re-run).
        if state.research_status in (ResearchStatus.NOT_STARTED, ResearchStatus.READY, ResearchStatus.PAUSED):
            try:
                state.transition_status(ResearchStatus.ACTIVE)
                self.state_store.save(state)
            except ValueError:
                pass

        return await self._iterate(run_id=run_id, state=state, champion=champion)

    async def run_loop(self, *, run_id: str, max_iterations: int = 10) -> list[LoopIterationResult]:
        """Run up to max_iterations, stopping on a stop outcome or budget exhaustion."""
        results: list[LoopIterationResult] = []
        for _ in range(max_iterations):
            res = await self.run_one_iteration(run_id=run_id)
            results.append(res)
            # Stop the loop on non-decision stops (no new work possible) or when
            # the experiment budget is exhausted.
            if res.outcome in (
                LoopOutcome.BUDGET_EXHAUSTED,
                LoopOutcome.AI_UNAVAILABLE,
                LoopOutcome.PROPOSAL_SKIPPED,
                LoopOutcome.NO_SAFE_TARGET,
                LoopOutcome.ZONE_ACCESS_DENIED,
                LoopOutcome.DUPLICATE_MUTATION,
                LoopOutcome.RECONCILE_REQUIRED,
            ):
                break
            # DROP/INCONCLUSIVE keep the same champion, so the loop naturally
            # re-diagnoses it; KEEP promotes and re-diagnoses the new champion.
            # Continue until max_iterations or a hard stop above.
        return results

    # ── Core iteration (exact 18-step order) ──────────────────────────────────

    async def _iterate(
        self, *, run_id: str, state: ResearchState, champion: ChampionReference
    ) -> LoopIterationResult:
        # 1. DIAGNOSIS
        diagnosis_code = self.diagnose_fn(champion)

        # 2. HYPOTHESIS reuse/create
        hyp = self._reuse_or_create_hypothesis(run_id, diagnosis_code, champion)
        hypothesis_id = hyp.hypothesis_id

        strategy_name = self._strategy_name(champion)
        proposal = None
        exact_change = None
        allowed_targets = None
        duplicate_match = None
        duplicate_identity = None
        duplicate_hash = None

        for attempt in range(2):
            context_limits = None
            if attempt == 1:
                context_limits = {
                    "excluded_mutations": self._mutation_exclusion_list(run_id, champion)
                }

            # 3. PROPOSAL GENERATOR (AI proposes ONLY — never decides)
            proposal = await self._generate_proposal(
                run_id,
                hypothesis_id,
                diagnosis_code,
                champion,
                context_limits=context_limits,
            )
            if proposal.outcome == ProposalOutcome.AI_UNAVAILABLE:
                return self._pause(
                    run_id, LoopOutcome.AI_UNAVAILABLE, LoopStage.PROPOSAL,
                    hypothesis_id=hypothesis_id, proposal=proposal,
                    pause_reason="proposal_generator_unavailable: ollama unreachable",
                )
            if proposal.outcome == ProposalOutcome.AI_PROPOSAL_SKIPPED:
                return self._stop(run_id, LoopOutcome.PROPOSAL_SKIPPED, LoopStage.PROPOSAL,
                                  hypothesis_id=hypothesis_id, proposal=proposal)
            if proposal.outcome != ProposalOutcome.ACCEPTED or proposal.exact_change is None:
                return self._stop(run_id, LoopOutcome.PROPOSAL_INVALID, LoopStage.PROPOSAL,
                                  hypothesis_id=hypothesis_id, proposal=proposal,
                                  details=proposal.rejection_reason or "Proposal not accepted")

            exact_change = proposal.exact_change

            # 4. SCHEMA + EVIDENCE VALIDATION (exact_change shape)
            if not self._exact_change_valid(exact_change):
                return self._stop(run_id, LoopOutcome.PROPOSAL_INVALID, LoopStage.VALIDATION,
                                  hypothesis_id=hypothesis_id, proposal=proposal,
                                  details="exact_change failed schema validation")

            # 5. ALLOWED TARGET VALIDATION
            allowed_targets = discover_allowed_mutation_targets(
                strategy_name, runs_root=self.runs_root,
                services=getattr(self, "services", None),
                strategies_dir=self.strategies_dir,
            )
            if not allowed_targets:
                return self._stop(run_id, LoopOutcome.NO_SAFE_TARGET, LoopStage.VALIDATION,
                                  hypothesis_id=hypothesis_id, proposal=proposal)

            duplicate_match, duplicate_identity, duplicate_hash = self._find_duplicate_mutation(
                run_id, champion, exact_change
            )
            if duplicate_match is None:
                break

        if duplicate_match is not None:
            return self._duplicate_mutation_stop(
                run_id=run_id,
                hypothesis_id=hypothesis_id,
                proposal=proposal,
                existing=duplicate_match,
                identity=duplicate_identity,
                identity_hash=duplicate_hash,
            )

        # 6. MUTATION POLICY (structural approval only; no budget yet)
        identity_hash = self._build_identity_hash(run_id, champion, exact_change)

        # 6b. DUPLICATE pre-check BEFORE mutation policy + reserve → no budget
        #     consumption on duplicate, and returns the existing reference.
        existing = self.experiment_store.find_by_identity_hash(run_id, identity_hash)
        if existing is not None:
            self.hypothesis_store.associate_experiment(run_id, hypothesis_id, existing.experiment_id)
            return LoopIterationResult(
                run_id=run_id,
                outcome=LoopOutcome.DUPLICATE,
                stage_reached=LoopStage.RESERVE,
                hypothesis_id=hypothesis_id,
                experiment_id=existing.experiment_id,
                duplicate_of_experiment_id=existing.experiment_id,
                proposal=proposal,
                details="Duplicate identity — returned existing experiment, no new execution",
            )

        mutation = MutationPolicy(
            experiment_store=self.experiment_store,
            hypothesis_store=self.hypothesis_store,
        ).evaluate(
            run_id=run_id,
            hypothesis_id=hypothesis_id,
            exact_change=exact_change.model_dump(),
            allowed_targets=allowed_targets,
            experiment_identity_hash=identity_hash,
            champion_strategy_hash=champion.strategy_artifact.artifact_hash if champion.strategy_artifact else None,
            champion_parameter_hash=champion.parameter_artifact.artifact_hash if champion.parameter_artifact else None,
        )
        if not mutation.allowed:
            return self._mutation_stop(run_id, hypothesis_id, proposal, mutation)

        # 7. EXPERIMENT IDENTITY
        # 8. RESERVE (budget consumed here, atomically, once)
        #     Duplicate check BEFORE reserve → no budget consumption on dup.
        existing = self.experiment_store.find_by_identity_hash(run_id, identity_hash)
        if existing is not None:
            self.hypothesis_store.associate_experiment(run_id, hypothesis_id, existing.experiment_id)
            return LoopIterationResult(
                run_id=run_id,
                outcome=LoopOutcome.DUPLICATE,
                stage_reached=LoopStage.RESERVE,
                hypothesis_id=hypothesis_id,
                experiment_id=existing.experiment_id,
                duplicate_of_experiment_id=existing.experiment_id,
                proposal=proposal,
                mutation_code=mutation.code.value,
                details="Duplicate identity — returned existing experiment, no new execution",
            )

        record = self._build_experiment_record(
            run_id=run_id, hypothesis_id=hypothesis_id, champion=champion,
            exact_change=exact_change, identity_hash=identity_hash,
        )
        try:
            saved, dup = self.experiment_store.reserve(record)
        except ValueError as exc:  # Budget exhausted
            return self._stop(run_id, LoopOutcome.BUDGET_EXHAUSTED, LoopStage.RESERVE,
                              hypothesis_id=hypothesis_id, proposal=proposal,
                              mutation_code=mutation.code.value, details=str(exc))

        if dup is not None:
            # Reserve itself detected a duplicate (race-safe).
            self.hypothesis_store.associate_experiment(run_id, hypothesis_id, dup.existing_experiment_id)
            return LoopIterationResult(
                run_id=run_id, outcome=LoopOutcome.DUPLICATE, stage_reached=LoopStage.RESERVE,
                hypothesis_id=hypothesis_id, experiment_id=dup.existing_experiment_id,
                duplicate_of_experiment_id=dup.existing_experiment_id, proposal=proposal,
                mutation_code=mutation.code.value,
                details="Duplicate detected inside reserve()",
            )
        experiment_id = saved.experiment_id

        # 9. DEVELOP ACCESS (only DEVELOP zone allowed for this stage)
        access_ok, access_decision = self._ensure_develop_access(run_id, experiment_id)
        if not access_ok:
            # §1/§10: protocol denial is a typed failure classification
            # (PROTOCOL_DENIED), NOT a performance DROP. The reserved experiment
            # is invalidated with an auditable reason; the champion is unchanged;
            # no candidate artifact was created and no executor was invoked.
            self.experiment_store.record_decision(
                run_id, experiment_id, ExperimentDecision.PENDING,
                result=f"PROTOCOL_DENIED:{access_decision.decision_code.value}",
            )
            try:
                self.experiment_store.transition_status(
                    run_id, experiment_id, ExperimentStatus.INVALIDATED
                )
            except Exception:
                pass
            return self._stop(run_id, LoopOutcome.ZONE_ACCESS_DENIED, LoopStage.DEVELOP_ACCESS,
                              hypothesis_id=hypothesis_id, experiment_id=experiment_id,
                              proposal=proposal, mutation_code=mutation.code.value,
                              details=f"DEVELOP access denied by DataZoneGuard: {access_decision.decision_code.value}")

        # 10. READY
        self.experiment_store.transition_status(run_id, experiment_id, ExperimentStatus.READY)

        # 11. CANDIDATE ARTIFACT (only AFTER successful reservation)
        artifact = self.artifact_service.create(
            run_id=run_id, strategy_name=strategy_name, champion=champion,
            exact_change=exact_change,
        )
        self.experiment_store.record_execution_reference(
            run_id, experiment_id,
            underlying_execution_id=artifact.candidate_dir,
        )

        # 12. CANDIDATE EXECUTOR (DEVELOP-only; champion original untouched)
        try:
            exec_result = self.executor.execute(
                run_id=run_id,
                strategy_name=strategy_name,
                version_id=self._version_id(champion),
                champion=champion,
                candidate_artifact_result=artifact,
                exact_change=exact_change,
                develop_timerange=self.develop_timerange,
                pairs=self.pairs,
                timeframe=self.timeframe,
                exchange=self.exchange,
                trading_mode=self.trading_mode,
                dry_run_wallet=self.dry_run_wallet,
                max_open_trades=self.max_open_trades,
                config_file=self.config_file,
            )
        except Exception as exc:  # noqa: BLE001 - surface as system failure, no decision
            self.experiment_store.record_decision(
                run_id, experiment_id, ExperimentDecision.INCONCLUSIVE,
                result=f"execution_system_failure: {exc}",
            )
            return self._stop(run_id, LoopOutcome.EXECUTION_SYSTEM_FAILURE, LoopStage.CANDIDATE_EXECUTOR,
                              hypothesis_id=hypothesis_id, experiment_id=experiment_id,
                              proposal=proposal, mutation_code=mutation.code.value,
                              details=f"Executor raised: {exc}")

        # 13. METRICS SSOT (executor already resolved canonical metrics)
        candidate_metrics = exec_result.metrics
        parent_metrics = champion.metrics
        exec_status = exec_result.status

        # System / parse failures are explicit SYSTEM failures, NOT a research
        # INCONCLUSIVE (§3). They must be classified distinctly so a metrics
        # subsystem or parser failure is never silently downgraded into a
        # "no edge" research verdict.
        SYSTEM_FAILURE_STATUSES = (
            CandidateExecutionStatus.EXECUTION_FAILURE,
            CandidateExecutionStatus.PARSE_FAILURE,
            CandidateExecutionStatus.SYSTEM_FAILURE,
        )
        if exec_status in SYSTEM_FAILURE_STATUSES:
            self.experiment_store.record_metrics(
                run_id, experiment_id,
                metrics_after=None,
                metrics_availability_reason=(
                    f"system_failure:{exec_status.value}:"
                    f"{exec_result.failure_classification or 'unknown'}"
                ),
            )
            self.experiment_store.transition_status(run_id, experiment_id, ExperimentStatus.RUNNING)
            self.experiment_store.transition_status(run_id, experiment_id, ExperimentStatus.FAILED_SYSTEM)
            self.experiment_store.record_decision(
                run_id, experiment_id, ExperimentDecision.PENDING,
                result=f"system_failure:{exec_status.value}:{exec_result.failure_classification or 'unknown'}",
            )
            return self._stop(run_id, LoopOutcome.EXECUTION_SYSTEM_FAILURE, LoopStage.CANDIDATE_EXECUTOR,
                              hypothesis_id=hypothesis_id, experiment_id=experiment_id,
                              proposal=proposal, mutation_code=mutation.code.value,
                              details=f"Candidate execution/system failure ({exec_status.value}): "
                                      f"{exec_result.failure_classification}")

        # NO_TRADES: a real execution completed but produced zero trades →
        # insufficient sample. This is a valid execution with insufficient
        # evidence → INCONCLUSIVE (research), with a typed availability reason.
        if exec_status == CandidateExecutionStatus.NO_TRADES:
            candidate_metrics = None  # no trade-level metrics to compare

        # 14. DECISION POLICY (returns a verdict; does NOT promote)
        if candidate_metrics is None or parent_metrics is None:
            decision = ExperimentDecision.INCONCLUSIVE
            decision_reason = (
                "missing_critical_evidence: parent or candidate metrics unavailable"
                if parent_metrics is None
                else f"valid_execution_but_insufficient_comparison: {exec_status.value}"
            )
            availability_reason = (
                "valid_execution_but_metrics_unavailable"
                if parent_metrics is not None
                else "parent_metrics_unavailable"
            )
        else:
            dres = DecisionPolicy.decide(DecisionRequest(
                diagnosis_code=diagnosis_code,
                parent_metrics=parent_metrics,
                candidate_metrics=candidate_metrics,
                min_sample_trades=self.min_sample_trades,
            ))
            decision = dres.decision
            decision_reason = dres.reason
            availability_reason = None

        # Persist metrics (after) with a typed availability reason when absent
        # (never a bare None — see ExperimentRecord.metrics_availability_reason).
        self.experiment_store.record_metrics(
            run_id, experiment_id,
            metrics_after=candidate_metrics,
            metrics_availability_reason=availability_reason,
        )

        # 15. PERSIST DECISION
        self.experiment_store.record_decision(
            run_id, experiment_id, decision, result=decision_reason,
        )
        # Valid status lifecycle: READY → RUNNING → COMPLETED.
        self.experiment_store.transition_status(run_id, experiment_id, ExperimentStatus.RUNNING)
        self.experiment_store.transition_status(run_id, experiment_id, ExperimentStatus.COMPLETED)

        # §7: update ResearchState coordination fields.
        self._record_decision_state(run_id, experiment_id=experiment_id, decision=decision)

        # 16. HYPOTHESIS UPDATE
        self._update_hypothesis_after_decision(run_id, hypothesis_id, decision, experiment_id)

        # 17. KEEP → Champion promotion + ResearchState update (re-diagnosis next)
        if decision == ExperimentDecision.KEEP and candidate_metrics is not None:
            new_champion = self._promote(
                run_id=run_id, parent_champion=champion, experiment_id=experiment_id,
                artifact=artifact, metrics=candidate_metrics,
            )
            return LoopIterationResult(
                run_id=run_id, outcome=LoopOutcome.DECISION_KEEP,
                stage_reached=LoopStage.PROMOTION, hypothesis_id=hypothesis_id,
                experiment_id=experiment_id, proposal=proposal,
                mutation_code=mutation.code.value, decision=decision,
                decision_reason=decision_reason,
                promoted_champion_id=new_champion.champion_id,
                details="KEEP: champion promoted; next iteration diagnoses the new champion",
            )

        # 18. DROP / INCONCLUSIVE → Champion unchanged
        return LoopIterationResult(
            run_id=run_id,
            outcome=(
                LoopOutcome.DECISION_DROP if decision == ExperimentDecision.DROP
                else LoopOutcome.DECISION_INCONCLUSIVE
            ),
            stage_reached=LoopStage.HYPOTHESIS_UPDATE,
            hypothesis_id=hypothesis_id, experiment_id=experiment_id,
            proposal=proposal, mutation_code=mutation.code.value,
            decision=decision, decision_reason=decision_reason,
            details="Champion unchanged (DROP/INCONCLUSIVE)",
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _stop(self, run_id, outcome, stage, *, hypothesis_id=None, experiment_id=None,
              proposal=None, mutation_code=None, details="") -> LoopIterationResult:
        return LoopIterationResult(
            run_id=run_id, outcome=outcome, stage_reached=stage,
            hypothesis_id=hypothesis_id, experiment_id=experiment_id,
            proposal=proposal, mutation_code=mutation_code, details=details,
        )

    def _pause(self, run_id, outcome, stage, *, hypothesis_id=None, experiment_id=None,
               proposal=None, mutation_code=None, details="", pause_reason="") -> LoopIterationResult:
        """§7: safe pause (e.g. AI unavailable) — NOT a failure. Research stays
        pausable (ACTIVE → PAUSED) so it can be resumed, never FAILED."""
        state = self.state_store.load(run_id)
        if state is not None:
            if state.research_status not in (ResearchStatus.ACTIVE,):
                try:
                    state.transition_status(ResearchStatus.ACTIVE)
                except ValueError:
                    pass
            try:
                state.transition_status(ResearchStatus.PAUSED)
            except ValueError:
                pass
            state.pause_reason = pause_reason or (details or outcome.value)
            self.state_store.save(state)
        return LoopIterationResult(
            run_id=run_id, outcome=outcome, stage_reached=stage,
            hypothesis_id=hypothesis_id, experiment_id=experiment_id,
            proposal=proposal, mutation_code=mutation_code,
            details=details or pause_reason,
        )

    def _record_decision_state(self, run_id, *, experiment_id, decision) -> None:
        """§7: bump iteration + record the latest decision id. Also ensure the
        research status is ACTIVE while the loop is producing decisions."""
        state = self.state_store.load(run_id)
        if state is None:
            return
        if state.research_status != ResearchStatus.ACTIVE:
            try:
                state.transition_status(ResearchStatus.ACTIVE)
            except ValueError:
                pass
        state.current_iteration += 1
        state.last_decision_id = experiment_id
        state.touch()
        self.state_store.save(state)

    def _mutation_stop(self, run_id, hypothesis_id, proposal, mutation) -> LoopIterationResult:
        code = mutation.code
        if code == MutationPolicyCode.NO_SAFE_MUTATION_TARGET:
            outcome = LoopOutcome.NO_SAFE_TARGET
        elif code == MutationPolicyCode.TARGET_UNKNOWN:
            outcome = LoopOutcome.TARGET_NOT_ALLOWED
        elif code == MutationPolicyCode.VALUE_OUTSIDE_ALLOWED_RANGE:
            outcome = LoopOutcome.VALUE_OUT_OF_RANGE
        elif code == MutationPolicyCode.EXPERIMENT_DUPLICATE:
            outcome = LoopOutcome.DUPLICATE
        else:
            outcome = LoopOutcome.TARGET_NOT_ALLOWED
        return LoopIterationResult(
            run_id=run_id, outcome=outcome, stage_reached=LoopStage.MUTATION_POLICY,
            hypothesis_id=hypothesis_id, proposal=proposal,
            mutation_code=code.value, details=mutation.reason,
        )

    def _duplicate_mutation_stop(
        self, *, run_id, hypothesis_id, proposal, existing, identity, identity_hash
    ) -> LoopIterationResult:
        existing_id = existing.experiment_id if existing is not None else None
        details = (
            "DUPLICATE_MUTATION: exact mutation already tested for parent lineage; "
            f"identity={identity}; mutation_identity_hash={identity_hash}"
        )
        if existing_id:
            self.hypothesis_store.associate_experiment(run_id, hypothesis_id, existing_id)
            details += f"; duplicate_of_experiment_id={existing_id}"
        return LoopIterationResult(
            run_id=run_id,
            outcome=LoopOutcome.DUPLICATE_MUTATION,
            stage_reached=LoopStage.VALIDATION,
            hypothesis_id=hypothesis_id,
            experiment_id=existing_id,
            duplicate_of_experiment_id=existing_id,
            proposal=proposal,
            mutation_code="DUPLICATE_MUTATION",
            details=details,
        )

    def _strategy_name(self, champion: ChampionReference) -> str:
        # The strategy name is encoded in the artifact's original_source_path filename.
        path = champion.strategy_artifact.original_source_path if champion.strategy_artifact else ""
        name = Path(path).stem
        return name or "AIStrategy"

    def _version_id(self, champion: ChampionReference) -> str:
        # ArtifactReference carries no version_id; default to a stable marker.
        # Real versioning lives in the trusted VersionManager, keyed by the
        # champion's original source hash when needed by the executor.
        return "v1"

    def _exact_change_valid(self, exact_change) -> bool:
        if not isinstance(exact_change, dict) and not hasattr(exact_change, "target"):
            return False
        target = getattr(exact_change, "target", None)
        return bool(target)

    def _build_identity_hash(self, run_id, champion, exact_change) -> str:
        lineage_id = self._parent_lineage_id(run_id, champion.champion_id)
        identity = mutation_identity_from_exact_change(
            parent_lineage_id=lineage_id,
            exact_change=exact_change,
        )
        return compute_mutation_identity_hash(identity)

    def _find_duplicate_mutation(self, run_id, champion, exact_change):
        lineage_id = self._parent_lineage_id(run_id, champion.champion_id)
        identity = mutation_identity_from_exact_change(
            parent_lineage_id=lineage_id,
            exact_change=exact_change,
        )
        identity_hash = compute_mutation_identity_hash(identity)
        for experiment in self.experiment_store.list_for_run(run_id):
            if experiment.exact_change is None:
                continue
            parent_id = experiment.parent_champion_id or ""
            experiment_lineage_id = self._parent_lineage_id(run_id, parent_id)
            existing_identity = mutation_identity_from_exact_change(
                parent_lineage_id=experiment_lineage_id,
                exact_change=experiment.exact_change,
            )
            if compute_mutation_identity_hash(existing_identity) == identity_hash:
                return experiment, identity, identity_hash
        return None, identity, identity_hash

    def _mutation_exclusion_list(self, run_id, champion) -> list[str]:
        lineage_id = self._parent_lineage_id(run_id, champion.champion_id)
        exclusions = []
        seen = set()
        for experiment in self.experiment_store.list_for_run(run_id):
            if experiment.exact_change is None:
                continue
            parent_id = experiment.parent_champion_id or ""
            if self._parent_lineage_id(run_id, parent_id) != lineage_id:
                continue
            identity = mutation_identity_from_exact_change(
                parent_lineage_id=lineage_id,
                exact_change=experiment.exact_change,
            )
            identity_hash = compute_mutation_identity_hash(identity)
            if identity_hash in seen:
                continue
            seen.add(identity_hash)
            exclusions.append(format_mutation_identity(identity))
        return exclusions

    def _parent_lineage_id(self, run_id, champion_id: str | None) -> str:
        current_id = champion_id or ""
        seen = set()
        while current_id and current_id not in seen:
            seen.add(current_id)
            champion = self.champion_store.get(run_id, current_id)
            if champion is None or not champion.parent_champion_id:
                return current_id
            current_id = champion.parent_champion_id
        return current_id or ""

    def _build_experiment_record(self, *, run_id, hypothesis_id, champion, exact_change, identity_hash) -> ExperimentRecord:
        strategy_artifact = champion.strategy_artifact
        return ExperimentRecord(
            run_id=run_id,
            hypothesis_id=hypothesis_id,
            parent_champion_id=champion.champion_id,
            original_strategy_provenance=OriginalStrategyProvenance(
                logical_name=self._strategy_name(champion),
                path_reference=strategy_artifact.original_source_path if strategy_artifact else None,
                path_hash=strategy_artifact.artifact_hash if strategy_artifact else None,
                source_hash=strategy_artifact.original_source_hash if strategy_artifact else None,
                version_id=self._version_id(champion),
            ),
            dataset_zone="develop",
            concrete_timerange=self.develop_timerange,
            pair_set=list(self.pairs),
            experiment_identity_hash=identity_hash,
            exact_change=exact_change,
            metrics_before=champion.metrics,
        )

    def _reuse_or_create_hypothesis(self, run_id, diagnosis_code, champion) -> HypothesisRecord:
        # §6: deterministic compatible-hypothesis reuse (no embedding/AI match).
        # Reuse an ACTIVE/APPROVED/PROPOSED hypothesis with the same diagnosis
        # + target scope + overlapping evidence refs; never reuse terminal ones.
        evidence_refs = self._evidence_refs(champion)
        reused = self.hypothesis_store.select_compatible_hypothesis(
            run_id,
            diagnosis_code=diagnosis_code.value,
            target_scope=getattr(self, "target_scope", None),
            evidence_refs=evidence_refs,
        )
        if reused is not None:
            return reused
        hyp = HypothesisRecord(
            run_id=run_id,
            diagnosis_code=diagnosis_code.value,
            hypothesis_text=f"Resolve {diagnosis_code.value} via parameter mutation",
            target_scope=getattr(self, "target_scope", None),
            evidence_refs=[HypothesisEvidenceRef(ref_path=r) for r in evidence_refs],
            source=HypothesisSource.DETERMINISTIC_DIAGNOSIS,
            status=HypothesisStatus.ACTIVE,
        )
        return self.hypothesis_store.create(hyp)

    def _evidence_refs(self, champion=None) -> list[str]:
        """Deterministic evidence-ref identity for reuse matching (v1)."""
        if champion is None or champion.metrics is None:
            return []
        return ["champion.metrics"]

    def _update_hypothesis_after_decision(self, run_id, hypothesis_id, decision, experiment_id):
        self.hypothesis_store.associate_experiment(run_id, hypothesis_id, experiment_id)
        new_status = {
            ExperimentDecision.KEEP: HypothesisStatus.SUPPORTED,
            ExperimentDecision.DROP: HypothesisStatus.REJECTED,
            ExperimentDecision.INCONCLUSIVE: HypothesisStatus.EXHAUSTED,
        }.get(decision, HypothesisStatus.EXHAUSTED)
        try:
            self.hypothesis_store.transition_status(run_id, hypothesis_id, new_status)
        except Exception:
            # Non-fatal: association already recorded; status may be terminal.
            pass

    def _ensure_develop_access(self, run_id, experiment_id) -> "tuple[bool, object]":
        # The zone guard only reads `.research_protocol` off the run object.
        # If boundaries aren't initialized, can_access returns allowed=True
        # (legacy/uninitialized run). Either way, the Coordinator only ever
        # passes develop_timerange to the executor, so the DEVELOP-only
        # invariant holds regardless of guard state.
        decision, _ = self.zone_guard.request_access(
            _RunShim(run_id), ResearchStage.RESEARCH_EXPERIMENT, ResearchZone.DEVELOP,
            experiment_id=experiment_id,
        )
        if decision.allowed:
            self.experiment_store.record_access_ledger_entry(
                run_id, experiment_id,
                access_ledger_entry_id=decision.decision_code.value,
                concrete_timerange=self.develop_timerange,
            )
            return True, decision
        return False, decision

    def _promote(self, *, run_id, parent_champion, experiment_id, artifact, metrics) -> ChampionReference:
        new_champion = ChampionReference(
            run_id=run_id,
            parent_champion_id=parent_champion.champion_id,
            source_type=ChampionSourceType.RESEARCH_EXPERIMENT,
            source_experiment_id=experiment_id,
            strategy_artifact=ArtifactReference(
                artifact_path=artifact.strategy_artifact.artifact_path,
                artifact_hash=artifact.strategy_artifact.artifact_hash,
                original_source_path=parent_champion.strategy_artifact.original_source_path
                if parent_champion.strategy_artifact else "",
                original_source_hash=parent_champion.strategy_artifact.original_source_hash
                if parent_champion.strategy_artifact else "",
            ),
            parameter_artifact=ArtifactReference(
                artifact_path=artifact.parameter_artifact.artifact_path,
                artifact_hash=artifact.parameter_artifact.artifact_hash,
                original_source_path=parent_champion.parameter_artifact.original_source_path
                if parent_champion.parameter_artifact else "",
                original_source_hash=parent_champion.parameter_artifact.original_source_hash
                if parent_champion.parameter_artifact else "",
            ),
            metrics=metrics,
        )
        promoted = self.champion_store.promote(
            run_id=run_id, candidate=new_champion,
            current_champion_id=parent_champion.champion_id,
            require_metrics=True,
        )
        # Update ResearchState with NEW champion (next iteration re-diagnoses it)
        state = self.state_store.load(run_id)
        if state is not None:
            state.current_champion_id = promoted.champion_id
            state.current_champion_strategy_hash = promoted.strategy_artifact.artifact_hash
            state.current_champion_parameter_hash = promoted.parameter_artifact.artifact_hash
            # Research status is ACTIVE while the loop is running; keep it so.
            self.state_store.save(state)
        return promoted

    async def _generate_proposal(
        self, run_id, hypothesis_id, diagnosis_code, champion, *, context_limits=None
    ) -> ProposalResult:
        allowed_targets = discover_allowed_mutation_targets(
            self._strategy_name(champion), runs_root=self.runs_root,
            strategies_dir=self.strategies_dir,
        )
        request = ProposalRequest(
            run_id=run_id,
            hypothesis_id=hypothesis_id,
            diagnosis_code=diagnosis_code.value,
            champion_metrics=champion.metrics,
            allowed_targets=allowed_targets,
            context_limits=context_limits,
        )
        result = self.proposal_callable(request)
        if hasattr(result, "__await__"):
            result = await result
        return result


# Local shim to avoid a hard dependency on the full AeRoing4Run model in the
# Coordinator — the zone guard only reads `.research_protocol` off the run
# object, and boundaries may be uninitialized (legacy run) which the guard
# treats as allowed.
class _RunShim:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.research_protocol = None
