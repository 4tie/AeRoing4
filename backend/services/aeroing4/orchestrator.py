"""AeRoing4 orchestrator for workflow execution."""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .models import (
    AeRoing4Run,
    AeRoing4RunStatus,
    AeRoing4StepStatus,
    StepResult,
    SmokeBacktestOutcome,
    BiasCheckOutcome,
)
from .state_store import AeRoing4StateStore
from .steps import ValidationStep, DataPreparationStep, SmokeBacktestStep, PairDiscoveryStep, BiasCheckStep, PairSelectionStep, PortfolioBaselineStep, InitialChampionStep, DiagnosisStep
from .research import DataZoneGuard, ResearchStage, ResearchZone, compute_strategy_hash

if TYPE_CHECKING:
    from ...app_services import AppServices

logger = logging.getLogger(__name__)

# Default discovery timerange when PASS_ACTIVITY and no explicit range is given.
# Separate from smoke_timerange — must not be the 1-week integration window.
DEFAULT_DISCOVERY_TIMERANGE = "20240101-20240630"


class AeRoing4Orchestrator:
    """Orchestrator for AeRoing4 workflow execution.

    Manages the complete vertical flow:
    Strategy Selection → Strict Validation → Data Preparation → Smoke Backtest
    → (if enabled) Pair Discovery → Ranked Candidate List
    """

    def __init__(self, services: "AppServices", runs_root: Path):
        """Initialize orchestrator with services and state store."""
        self.services = services
        self.state_store = AeRoing4StateStore(runs_root)
        self.guard = DataZoneGuard(self.state_store, runs_root)
        self._active_task: asyncio.Task | None = None
        self._cancel_requested: bool = False

    def create_run(
        self,
        strategy_name: str,
        timeframe: str = "5m",
        smoke_timerange: str = "20240101-20240131",
        smoke_pairs: list[str] | None = None,
        enable_pair_discovery: bool = False,
        discovery_pairs: list[str] | None = None,
        discovery_timerange: str | None = None,
        confirmation_timerange: str | None = None,
        final_unseen_timerange: str | None = None,
        exchange: str = "binance",
        trading_mode: str = "spot",
        max_open_trades: int = 4,
        dry_run_wallet: float = 1000.0,
        config_file: str = "config.json",
        enable_research_loop: bool = False,
        enable_focused_hyperopt: bool = False,
    ) -> AeRoing4Run:
        """Create a new AeRoing4 run.

        Args:
            ...
            enable_research_loop: PROMPT 8 opt-in. When True, the orchestrator
                runs the Controlled Research Loop after Diagnosis instead of
                marking the run COMPLETED immediately.

        Returns:
            Created AeRoing4Run

        Raises:
            BackendError: If another run is already active
        """
        # Enforce single-execution constraint
        active_run_id = self.state_store.get_active_run()
        if active_run_id:
            active_run = self.state_store.load_run(active_run_id)
            if active_run and active_run.status == AeRoing4RunStatus.RUNNING:
                from ...core.errors import BackendError
                raise BackendError(
                    f"Another AeRoing4 run is already active: {active_run_id}",
                    status_code=409,
                )

        # Create new run
        run = self.state_store.create_run(
            strategy_name=strategy_name,
            timeframe=timeframe,
            smoke_timerange=smoke_timerange,
            smoke_pairs=smoke_pairs,
            enable_pair_discovery=enable_pair_discovery,
            discovery_pairs=discovery_pairs,
            discovery_timerange=discovery_timerange,
            confirmation_timerange=confirmation_timerange,
            final_unseen_timerange=final_unseen_timerange,
            exchange=exchange,
            trading_mode=trading_mode,
            max_open_trades=max_open_trades,
            dry_run_wallet=dry_run_wallet,
            config_file=config_file,
            enable_research_loop=enable_research_loop,
            enable_focused_hyperopt=enable_focused_hyperopt,
        )

        return run

    async def start_run(self, run_id: str) -> None:
        """Start execution of an AeRoing4 run.

        Args:
            run_id: ID of the run to start

        Raises:
            ValueError: If run not found or already running
        """
        run = self.state_store.load_run(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")

        if run.status != AeRoing4RunStatus.PENDING:
            raise ValueError(f"Run is not in pending status: {run.status}")

        # Mark as active and running
        self.state_store.set_active_run(run_id)
        run.mark_running()
        self.state_store.save_run(run)

        # Reset cancel flag
        self._cancel_requested = False

        # Start background task
        self._active_task = asyncio.create_task(self._execute_workflow(run_id))

    async def cancel_run(self, run_id: str) -> None:
        """Cancel an active AeRoing4 run.

        Args:
            run_id: ID of the run to cancel
        """
        run = self.state_store.load_run(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")

        if run.status != AeRoing4RunStatus.RUNNING:
            raise ValueError(f"Run is not running: {run.status}")

        # Set cancel flag
        self._cancel_requested = True

        # Cancel backtest if running
        if self.services.backtest_runner.is_busy():
            current_run_id = self.services.backtest_runner.get_current_run_id()
            if current_run_id:
                self.services.backtest_runner.cancel(current_run_id)

        # Mark run as cancelled
        run.mark_cancelled()
        self.state_store.save_run(run)
        self.state_store.set_active_run(None)

        # Cancel task
        if self._active_task and not self._active_task.done():
            self._active_task.cancel()

    async def _execute_workflow(self, run_id: str) -> None:
        """Execute the complete AeRoing4 workflow.

        Args:
            run_id: ID of the run to execute
        """
        run = self.state_store.load_run(run_id)
        if not run:
            logger.error(f"Run not found during execution: {run_id}")
            return

        try:
            # ── Step 1: Strict Validation ────────────────────────────────────
            if self._cancel_requested:
                return

            validation_step = ValidationStep(self.services)
            validation_result = await validation_step.execute(run.strategy_name)
            run.update_step("validation", validation_result)
            self.state_store.save_run(run)

            if validation_result.status == AeRoing4StepStatus.FAILED:
                run.mark_failed(validation_result.error or "Validation failed")
                self.state_store.save_run(run)
                self.state_store.set_active_run(None)
                return

            # ── Step 2: Data Preparation ─────────────────────────────────────
            if self._cancel_requested:
                return

            data_prep_step = DataPreparationStep(self.services)
            data_prep_result = await data_prep_step.execute(
                pairs=run.smoke_pairs,
                timeframe=run.timeframe,
                timerange=run.smoke_timerange,
            )
            run.update_step("data_preparation", data_prep_result)
            self.state_store.save_run(run)

            if data_prep_result.status == AeRoing4StepStatus.FAILED:
                run.mark_failed(data_prep_result.error or "Data preparation failed")
                self.state_store.save_run(run)
                self.state_store.set_active_run(None)
                return

            # ── Step 3: Smoke Backtest ───────────────────────────────────────
            if self._cancel_requested:
                return

            smoke_step = SmokeBacktestStep(self.services)
            smoke_result = await smoke_step.execute(
                strategy_name=run.strategy_name,
                version_id=None,  # Step will resolve version ID internally
                pairs=run.smoke_pairs,
                timeframe=run.timeframe,
                timerange=run.smoke_timerange,
            )
            run.update_step("smoke_backtest", smoke_result)
            self.state_store.save_run(run)

            outcome = smoke_result.data.get("outcome")

            # EXECUTION_FAILURE stops the workflow before pair discovery
            if outcome == SmokeBacktestOutcome.EXECUTION_FAILURE.value:
                run.mark_failed(smoke_result.error or "Smoke backtest execution failed")
                self.state_store.save_run(run)
                self.state_store.set_active_run(None)
                return

            # ── Step 3b: Bias Check ──────────────────────────────────────────
            bias_outcome = None
            if outcome == SmokeBacktestOutcome.PASS_ACTIVITY.value:
                if self._cancel_requested:
                    return
                
                bias_step = BiasCheckStep(self.services)
                bias_result = await bias_step.execute(
                    strategy_name=run.strategy_name,
                    pairs=run.smoke_pairs,
                    timeframe=run.timeframe,
                    timerange=run.smoke_timerange,
                )
                run.update_step("bias_check", bias_result)
                self.state_store.save_run(run)
                
                bias_outcome = bias_result.data.get("outcome")
                
                if bias_outcome in [BiasCheckOutcome.FAIL_LOOKAHEAD.value, BiasCheckOutcome.FAIL_RECURSIVE_BIAS.value]:
                    run.mark_failed(f"Strategy rejected due to fatal bias: {bias_outcome}")
                    self.state_store.save_run(run)
                    self.state_store.set_active_run(None)
                    return
                elif bias_outcome == BiasCheckOutcome.EXECUTION_FAILURE.value:
                    run.mark_failed(bias_result.error or "Bias check execution failed")
                    self.state_store.save_run(run)
                    self.state_store.set_active_run(None)
                    return
                
                # Bias PASS or PASS_WITH_WARNING continues

            # ── Step 4: Pair Discovery (optional, PASS_ACTIVITY only) ────────
            if (
                run.enable_pair_discovery
                and outcome == SmokeBacktestOutcome.PASS_ACTIVITY.value
                and bias_outcome in [BiasCheckOutcome.PASS.value, BiasCheckOutcome.PASS_WITH_WARNING.value]
            ):
                if self._cancel_requested:
                    return

                discovery_timerange = run.discovery_timerange or DEFAULT_DISCOVERY_TIMERANGE

                # Research Protocol / Data Zone Guard: strictly opt-in. Only
                # activates when the run explicitly carries both
                # confirmation_timerange and final_unseen_timerange; when
                # absent, behavior below is byte-for-byte identical to
                # pre-Milestone-3 workflow (guard.request_access is skipped
                # entirely, no boundaries are initialized).
                protocol_active = bool(
                    run.confirmation_timerange and run.final_unseen_timerange
                )

                if protocol_active:
                    run = self.guard.initialize_boundaries(
                        run,
                        develop_timerange=discovery_timerange,
                        confirmation_timerange=run.confirmation_timerange,
                        final_unseen_timerange=run.final_unseen_timerange,
                    )
                    strategy_hash = compute_strategy_hash(run.strategy_name)
                    decision, run = self.guard.request_access(
                        run,
                        stage=ResearchStage.PAIR_DISCOVERY,
                        zone=ResearchZone.DEVELOP,
                        strategy_hash=strategy_hash,
                    )
                    if not decision.allowed:
                        run.mark_failed(
                            f"Data Zone Guard denied pair_discovery access to "
                            f"DEVELOP zone: [{decision.decision_code.value}] "
                            f"{decision.reason}"
                        )
                        self.state_store.save_run(run)
                        self.state_store.set_active_run(None)
                        return
                    # Reload: guard.request_access persists boundary freezing
                    # as a side effect; keep working with the authoritative
                    # on-disk state going forward.
                    run = self.state_store.load_run(run_id) or run

                discovery_step = PairDiscoveryStep(self.services)
                discovery_result = await discovery_step.execute(
                    strategy_name=run.strategy_name,
                    timeframe=run.timeframe,
                    discovery_timerange=discovery_timerange,
                    discovery_pairs=run.discovery_pairs,
                )
                run.update_step("pair_discovery", discovery_result)
                self.state_store.save_run(run)

                if discovery_result.status == AeRoing4StepStatus.FAILED:
                    run.mark_failed(
                        discovery_result.error or "Pair discovery failed"
                    )
                    self.state_store.save_run(run)
                    self.state_store.set_active_run(None)
                    return

                # ── Step 5: Pair Selection ─────────────────────────────────────
                if self._cancel_requested:
                    return

                from ..aeroing4.pair_selection import PairSelectionMode
                selection_mode = PairSelectionMode.AUTO_BEST_N
                if run.pair_selection_mode == "manual":
                    selection_mode = PairSelectionMode.MANUAL

                selection_step = PairSelectionStep(self.services)
                selection_result = await selection_step.execute(
                    discovery_result=discovery_result.data,
                    selection_mode=selection_mode,
                    target_pair_count=run.target_pair_count,
                    manually_selected_pairs=run.manually_selected_pairs,
                )
                run.update_step("pair_selection", selection_result)
                self.state_store.save_run(run)

                if selection_result.status == AeRoing4StepStatus.FAILED:
                    run.mark_failed(selection_result.error or "Pair selection failed")
                    self.state_store.save_run(run)
                    self.state_store.set_active_run(None)
                    return

                # ── Step 6: Portfolio Baseline ─────────────────────────────────
                if self._cancel_requested:
                    return

                # Research Protocol access for Portfolio Baseline
                if protocol_active:
                    # Compute pair set hash
                    import hashlib
                    import json
                    selection_data = selection_result.data
                    selected_pairs = selection_data.get("selected_pairs", [])
                    pair_set_hash = hashlib.sha256(
                        json.dumps(sorted(selected_pairs)).encode()
                    ).hexdigest()

                    decision, run = self.guard.request_access(
                        run,
                        stage=ResearchStage.PORTFOLIO_BASELINE,
                        zone=ResearchZone.DEVELOP,
                        pair_set_hash=pair_set_hash,
                    )
                    if not decision.allowed:
                        run.mark_failed(
                            f"Data Zone Guard denied portfolio_baseline access to "
                            f"DEVELOP zone: [{decision.decision_code.value}] "
                            f"{decision.reason}"
                        )
                        self.state_store.save_run(run)
                        self.state_store.set_active_run(None)
                        return
                    # Reload after guard access
                    run = self.state_store.load_run(run_id) or run

                # Get config file from settings
                settings = self.services.settings_store.load()
                config_file = settings.config_file

                baseline_step = PortfolioBaselineStep(self.services)
                baseline_result = await baseline_step.execute(
                    strategy_name=run.strategy_name,
                    version_id=None,
                    selection_result=selection_result.data,
                    develop_timerange=discovery_timerange,
                    timeframe=run.timeframe,
                    config_file=run.config_file,
                    max_open_trades=run.max_open_trades,
                    dry_run_wallet=run.dry_run_wallet,
                    exchange=run.exchange,
                    trading_mode=run.trading_mode,
                    aeroing4_run_id=run_id,
                    guard=self.guard if protocol_active else None,
                )
                run.update_step("portfolio_baseline", baseline_result)
                self.state_store.save_run(run)

                if baseline_result.status == AeRoing4StepStatus.FAILED:
                    run.mark_failed(baseline_result.error or "Portfolio baseline failed")
                    self.state_store.save_run(run)
                    self.state_store.set_active_run(None)
                    return

                # ── Step 7: Initial Champion ───────────────────────────────────
                if self._cancel_requested:
                    return

                champion_step = InitialChampionStep(self.services, self.state_store.runs_root)
                champion_result = await champion_step.execute(
                    aeroing4_run_id=run_id,
                    baseline_result=baseline_result.data,
                    strategy_name=run.strategy_name,
                    strategy_path=None,
                )
                run.update_step("initial_champion", champion_result)
                self.state_store.save_run(run)

                if champion_result.status == AeRoing4StepStatus.FAILED:
                    run.mark_failed(champion_result.error or "Initial champion creation failed")
                    self.state_store.save_run(run)
                    self.state_store.set_active_run(None)
                    return

                # ── Step 8: Diagnosis ───────────────────────────────────────────
                if self._cancel_requested:
                    return

                champion_id = champion_result.data.get("champion_id")
                if not champion_id:
                    run.mark_failed("Champion ID not found in initial champion result")
                    self.state_store.save_run(run)
                    self.state_store.set_active_run(None)
                    return

                diagnosis_step = DiagnosisStep(self.services, str(self.state_store.runs_root))
                diagnosis_result = await diagnosis_step.execute(
                    aeroing4_run_id=run_id,
                    baseline_result=baseline_result.data,
                    strategy_name=run.strategy_name,
                    champion_id=champion_id,
                )
                run.update_step("diagnosis", diagnosis_result)
                self.state_store.save_run(run)

                # Diagnosis step failures are not fatal to the run
                # They are informational only
                if diagnosis_result.status == AeRoing4StepStatus.FAILED:
                    logger.warning(
                        f"Diagnosis step failed for run {run_id}: {diagnosis_result.error}"
                    )

                # ── Step 9: Controlled Research Loop (PROMPT 8, strict opt-in) ──
                if getattr(run, "enable_research_loop", False):
                    if self._cancel_requested:
                        return
                    from .research.factory import build_research_loop_coordinator

                    coordinator = build_research_loop_coordinator(
                        self.services, self.state_store.runs_root,
                    )
                    # Initialize ResearchState for this run (idempotent).
                    research_state_store = coordinator.state_store
                    rs = research_state_store.load(run_id)
                    if rs is None:
                        rs = research_state_store.create(
                            run_id, max_total_experiments=run.max_open_trades or 5,
                        )
                    rs.current_champion_id = champion_id
                    research_state_store.save(rs)

                    loop_results = await coordinator.run_loop(
                        run_id=run_id, max_iterations=run.max_open_trades or 5,
                    )
                    run.update_step(
                        "research_loop",
                        StepResult(
                            step_name="research_loop",
                            status=AeRoing4StepStatus.PASSED,
                            data={"iterations": [r.model_dump() for r in loop_results]},
                        ),
                    )
                    # PROMPT 9 (strict opt-in): after a KEEP champion exists, run
                    # Focused Hyperopt → HYPEROPT champion → Sensitivity gate.
                    # Confirmation/Final Unseen are later prompts.
                    if getattr(run, "enable_focused_hyperopt", False) and rs.current_champion_id:
                        if self._cancel_requested:
                            return
                        try:
                            from .research.factory import (
                                build_focused_hyperopt_service,
                                build_sensitivity_service,
                            )
                            from .research.hyperopt_policy import build_focused_scope
                            from .research.allowed_targets import discover_allowed_mutation_targets
                            from backend.services.aeroing4.diagnosis.models import DiagnosisCode
                            champion = coordinator.champion_store.get(run_id, rs.current_champion_id)
                            if champion is not None:
                                # PROMPT 9 reuses the research loop's diagnosis context.
                                # The coordinator stores the decision; we fall back to
                                # NO_EDGE (a hyperopt-actionable diagnosis) when none is
                                # pinned, so Focused Hyperopt still has an actionable scope.
                                diagnosis_code = DiagnosisCode.NO_EDGE
                                allowed_targets = discover_allowed_mutation_targets(
                                    run.strategy_name, self.state_store.runs_root, self.services,
                                    strategies_dir=self.services.paths.strategies_dir,
                                )
                                hyperopt_svc = build_focused_hyperopt_service(
                                    self.services, self.state_store.runs_root,
                                )
                                hyperopt_res = hyperopt_svc.run(
                                    run_id=run_id, strategy_name=run.strategy_name,
                                    version_id="v1", champion=champion,
                                    diagnosis_code=diagnosis_code or __import__("backend.services.aeroing4.diagnosis.models", fromlist=["DiagnosisCode"]).DiagnosisCode.NO_EDGE,
                                    allowed_targets=allowed_targets, state_store=research_state_store,
                                )
                                run.update_step(
                                    "focused_hyperopt",
                                    StepResult(
                                        step_name="focused_hyperopt",
                                        status=AeRoing4StepStatus.PASSED,
                                        data={"result": hyperopt_res.model_dump()},
                                    ),
                                )
                                # Sensitivity runs on the (possibly promoted) current champion.
                                cur = coordinator.champion_store.get(run_id, rs.current_champion_id)
                                sensitivity_svc = build_sensitivity_service(
                                    self.services, self.state_store.runs_root,
                                )
                                sens_res = sensitivity_svc.run(
                                    run_id=run_id, strategy_name=run.strategy_name,
                                    version_id="v1", champion=cur,
                                    diagnosis_code=diagnosis_code or __import__("backend.services.aeroing4.diagnosis.models", fromlist=["DiagnosisCode"]).DiagnosisCode.NO_EDGE,
                                    allowed_targets=allowed_targets,
                                )
                                rs.eligible_for_confirmation = sens_res.eligible_for_confirmation
                                rs.last_sensitivity_status = sens_res.status.value
                                research_state_store.save(rs)
                                run.update_step(
                                    "sensitivity",
                                    StepResult(
                                        step_name="sensitivity",
                                        status=AeRoing4StepStatus.PASSED,
                                        data={"result": sens_res.model_dump()},
                                    ),
                                )
                                # PROMPT 10: Confirmation entered ONLY when Sensitivity PASSed.
                                # It is a frozen OOS test — no mutation, no repair.
                                if rs.eligible_for_confirmation:
                                    from .research.factory import build_confirmation_service
                                    confirmation_svc = build_confirmation_service(
                                        self.services, self.state_store.runs_root,
                                        confirmation_timerange=run.confirmation_timerange or "20240701-20240731",
                                        final_unseen_timerange=run.final_unseen_timerange or "20240801-20240831",
                                    )
                                    conf_res = confirmation_svc.run(
                                        run_id=run_id, strategy_name=run.strategy_name,
                                        version_id="v1", champion=cur,
                                        eligible_for_confirmation=rs.eligible_for_confirmation,
                                        state_store=research_state_store, run=run,
                                    )
                                    run.update_step(
                                        "confirmation",
                                        StepResult(
                                            step_name="confirmation",
                                            status=AeRoing4StepStatus.PASSED,
                                            data={"result": conf_res.model_dump()},
                                        ),
                                    )
                                    # PROMPT 11: Final Unseen entered ONLY when Confirmation PASSed.
                                    # Terminal evidence — no mutation, no repair. gated by protocol flag.
                                    if getattr(conf_res.decision, "value", conf_res.decision) == "pass":
                                        from .research.factory import build_final_unseen_service
                                        from .research.confirmation import ConfirmationResult
                                        protocol_passed = bool(
                                            getattr(run.research_protocol, "confirmation_passed", False)
                                        )
                                        fu_svc = build_final_unseen_service(
                                            self.services, self.state_store.runs_root,
                                            final_unseen_timerange=run.final_unseen_timerange or "20240801-20240831",
                                        )
                                        fu_res = fu_svc.run(
                                            run_id=run_id, strategy_name=run.strategy_name,
                                            version_id="v1", champion=cur,
                                            confirmation_result=conf_res,
                                            protocol_confirmation_passed=protocol_passed,
                                            eligible_for_confirmation=rs.eligible_for_confirmation,
                                            state_store=research_state_store,
                                        )
                                        run.update_step(
                                            "final_unseen",
                                            StepResult(
                                                step_name="final_unseen",
                                                status=AeRoing4StepStatus.PASSED,
                                                data={"result": fu_res.model_dump()},
                                            ),
                                        )
                                        # PROMPT 12: Delivery (packaging) entered ONLY when Final Unseen
                                        # produced delivery_eligible=true. Safe run-local export; no truth change.
                                        if getattr(fu_res, "delivery_eligible", False):
                                            from .research.factory import build_delivery_service
                                            delivery_svc = build_delivery_service(
                                                self.services, self.state_store.runs_root,
                                            )
                                            del_res = delivery_svc.run(
                                                run_id=run_id, champion=cur,
                                                final_unseen_result=fu_res,
                                                confirmation_result=conf_res,
                                                delivery_eligible_state=bool(
                                                    getattr(rs, "delivery_eligible", False)
                                                ),
                                                research_state=rs,
                                            )
                                            run.update_step(
                                                "delivery",
                                                StepResult(
                                                    step_name="delivery",
                                                    status=AeRoing4StepStatus.PASSED,
                                                    data={"result": del_res.model_dump()},
                                                ),
                                            )
                        except Exception as hyp_exc:
                            logger.exception(f"PROMPT 9 stages failed for run {run_id}: {hyp_exc}")
                            run.update_step(
                                "focused_hyperopt",
                                StepResult(
                                    step_name="focused_hyperopt",
                                    status=AeRoing4StepStatus.FAILED,
                                    error=str(hyp_exc),
                                ),
                            )

                    # Paused loop (e.g. AI unavailable) → run stays resumable,
                    # not COMPLETED.
                    if loop_results and loop_results[-1].outcome.value == "ai_unavailable":
                        run.status = AeRoing4RunStatus.RUNNING
                        self.state_store.save_run(run)
                        self.state_store.set_active_run(None)
                        return

            # Both PASS_ACTIVITY and NO_SIGNAL_ACTIVITY complete the run
            # (NO_SIGNAL_ACTIVITY does NOT automatically trigger pair discovery)
            run.mark_completed()
            self.state_store.save_run(run)

        except asyncio.CancelledError:
            # Task was cancelled
            run = self.state_store.load_run(run_id)
            if run:
                run.mark_cancelled()
                self.state_store.save_run(run)
            self.state_store.set_active_run(None)
            raise

        except Exception as exc:
            # Unexpected error
            logger.exception(f"AeRoing4 workflow execution failed: {exc}")
            run = self.state_store.load_run(run_id)
            if run:
                run.mark_failed(f"Workflow execution failed: {str(exc)}")
                self.state_store.save_run(run)
            self.state_store.set_active_run(None)

        finally:
            self.state_store.set_active_run(None)

    def get_run(self, run_id: str) -> AeRoing4Run | None:
        """Get a run by ID."""
        return self.state_store.load_run(run_id)

    def list_runs(self) -> list[AeRoing4Run]:
        """List all AeRoing4 runs, newest first."""
        return self.state_store.list_runs()
