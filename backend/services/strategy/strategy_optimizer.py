"""Systematic strategy optimizer service.

This module runs many backtest trials with different parameter combinations,
tracks per-trial metrics, scores candidates, and stores optimizer session history.
"""

from __future__ import annotations

import logging
import asyncio
from datetime import datetime
from typing import Any, Callable

from ...core.errors import BackendError
from ...models import (
    OptimizerScoreMetric,
    OptimizerScoreWeights,
    OptimizerSession,
    OptimizerSessionConfig,
    OptimizerSessionPhase,
    OptimizerParameterMode,
    OptimizerTrial,
    OptimizerTrialMetrics,
    OptimizerTrialStatus,
    ParameterSearchSpace,
    ParamsSchema,
    RunRequest,
    StartOptimizerRequest,
    VectorBTScreeningReport,
)
from ...utils import utc_now
from ..execution.backtest_runner import BacktestRunner
from ..optimizer.enhanced_session_manager import EnhancedSessionManager
from ..optimizer.enhanced_trial_execution import EnhancedTrialExecutionService
from ..optimizer.session_validator import SessionValidator
from ..storage.optimizer_store import OptimizerStore
from ..storage.run_repository import RunRepository
from .optimizer_auto_safe import (
    apply_auto_safe_initial_spaces,
    build_auto_safe_narrowing_event,
)
from .optimizer_search_spaces import OptimizerSearchSpaceBuilder
from .optimizer_session import OptimizerSessionManager
from .optimizer_trial import OptimizerTrialExecutor
from .strategy_optimizer_search import select_parameters_for_trial
from .strategy_registry import StrategyRegistry
from .strategy_source import StrategySourceParser


class StrategyOptimizerService:
    """Runs systematic multi-trial parameter optimization for a strategy."""

    def __init__(
        self,
        optimizer_store: OptimizerStore,
        backtest_runner: BacktestRunner,
        run_repository: RunRepository,
        registry: StrategyRegistry,
        settings_store: SettingsStore,
        version_manager: Any,
        source_parser: StrategySourceParser,
        vectorbt_screener: Any | None = None,
    ) -> None:
        """Store all optimizer dependencies and in-memory task state."""
        self.optimizer_store = optimizer_store
        self.backtest_runner = backtest_runner
        self.run_repository = run_repository
        self.registry = registry
        self.settings_store = settings_store
        self.version_manager = version_manager
        self._source_parser = source_parser
        self.vectorbt_screener = vectorbt_screener
        self._active_task: asyncio.Task | None = None
        self._active_session_id: str | None = None
        self._cancel_requested: bool = False
        self._progress_callback: Callable[[dict], None] | None = None
        self._log_callback: Callable[[str], None] | None = None
        self._session_cleanup_enabled: bool = True
         
        # Initialize helper modules
        self.session_manager = OptimizerSessionManager(
            optimizer_store, registry, version_manager
        )
        self.enhanced_session_manager = EnhancedSessionManager(
            optimizer_store, registry, version_manager
        )
        self.session_validator = SessionValidator()
        self.trial_executor = OptimizerTrialExecutor(
            backtest_runner, run_repository, version_manager
        )
        self.trial_execution_service = EnhancedTrialExecutionService(
            backtest_runner=backtest_runner,
            run_repository=run_repository,
            version_manager=version_manager,
            trial_executor=self.trial_executor,
            validator=self.session_validator,
            registry=registry,
            settings_store=settings_store,
        )
        self.search_space_builder = OptimizerSearchSpaceBuilder(
            registry, source_parser
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def set_log_callback(self, callback: Callable[[str], None] | None) -> None:
        """Register an external log sink (e.g. the SSE broadcaster)."""
        self._log_callback = callback

    def is_running(self) -> bool:
        """Tell callers whether an optimizer session worker is currently running."""
        return self._active_task is not None and not self._active_task.done()

    def get_active_session_id(self) -> str | None:
        """Return the active session id so callers can resume polling."""
        return self._active_session_id if self.is_running() else None

    def build_search_spaces_from_strategy(
        self, strategy_name: str
    ) -> list[ParameterSearchSpace]:
        """Extract parameter definitions from the strategy and build default search spaces."""
        return self.search_space_builder.build_search_spaces_from_strategy(strategy_name)

    async def start_session(self, request: StartOptimizerRequest) -> OptimizerSession:
        """Create a new optimizer session record and start its async execution loop."""
        if self.is_running():
            raise BackendError("An optimizer session is already running.", status_code=409)

        if request.parameter_mode == OptimizerParameterMode.AUTO_SAFE:
            request = request.model_copy(
                update={
                    "search_spaces": apply_auto_safe_initial_spaces(
                        request.search_spaces
                    )
                }
            )

        session = self.session_manager.create_session(request)
        self._cancel_requested = False
        self._active_session_id = session.session_id
        self._active_task = asyncio.create_task(self._run_session(session.session_id))
        return session

    async def cancel_session(self, session_id: str) -> OptimizerSession:
        """Request cancellation, stop active backtests when possible, and persist terminal state."""
        session = self.session_manager.load_session(session_id)
        if session is None:
            raise BackendError(f"Optimizer session '{session_id}' not found.", status_code=404)
        if session.phase not in {OptimizerSessionPhase.RUNNING, OptimizerSessionPhase.IDLE}:
            return session
        self._cancel_requested = True
        # Also cancel the active backtest if it's for this session
        if self._active_session_id == session_id and self.backtest_runner.is_busy():
            run_id = self.backtest_runner.active_run_id
            if run_id:
                try:
                    self.backtest_runner.cancel(run_id)
                except Exception as exc:
                    self._emit_log(f"Warning: Failed to cancel backtest {run_id}: {exc}")
        # Wait briefly for the task to notice the cancellation
        if self._active_task and not self._active_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._active_task), timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._emit_log("Cancellation request sent, but task did not complete within timeout")
        # Reload and mark cancelled if still running
        session = self.session_manager.load_session(session_id)
        if session and session.phase == OptimizerSessionPhase.RUNNING:
            session = self.session_manager.mark_session_cancelled(session_id)
            self._emit_log(f"Session {session_id} marked as cancelled")
        return session

    def start_session_sync(
        self,
        request: StartOptimizerRequest,
        progress_callback: Any | None = None,
        log_callback: Any | None = None,
    ) -> OptimizerSession:
        """Synchronous wrapper for start_session - runs async method in event loop.

        This method runs the session to completion synchronously, blocking until
        all trials are complete. It uses asyncio.run() to execute both the
        session startup and the full trial execution loop.
        """
        # Store callbacks for use in _emit_log and progress emission
        self._progress_callback = progress_callback
        self._log_callback = log_callback
        
        # Run the full session asynchronously - setup and execution
        async def run_full_session() -> OptimizerSession:
            session = await self.start_session(request)
            # Wait for the session execution task to complete
            if self._active_task:
                await self._active_task
            return session

        return asyncio.run(run_full_session())

    def cancel_session_sync(self, session_id: str) -> OptimizerSession:
        """Synchronous wrapper for cancel_session - runs async method in event loop."""
        return asyncio.run(self.cancel_session(session_id))

    async def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """Clean up old completed sessions to free disk space."""
        if not self._session_cleanup_enabled:
            return 0
            
        from datetime import UTC, datetime
        
        cleaned_count = 0
        cutoff_time = datetime.now(tz=UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        try:
            sessions = self.optimizer_store.list_sessions()
            for session_summary in sessions:
                if session_summary.phase in {
                    OptimizerSessionPhase.COMPLETED,
                    OptimizerSessionPhase.FAILED,
                    OptimizerSessionPhase.CANCELLED,
                }:
                    if session_summary.completed_at:
                        session_age = (cutoff_time - session_summary.completed_at).total_seconds()
                        if session_age > max_age_hours * 3600:
                            try:
                                if self.optimizer_store.delete_session(session_summary.session_id):
                                    cleaned_count += 1
                                    if self._log_callback:
                                        self._log_callback(f"Cleaned up old session: {session_summary.session_id}")
                            except Exception as e:
                                if self._log_callback:
                                    self._log_callback(f"Failed to cleanup session {session_summary.session_id}: {e}")
        except Exception as e:
            if self._log_callback:
                self._log_callback(f"Session cleanup failed: {e}")

        return cleaned_count

    def _emit_log(self, message: str) -> None:
        """Emit a log message via the session manager's callback if set."""
        if self._log_callback is not None:
            try:
                self._log_callback(message)
            except Exception:
                pass  # Ignore callback errors to avoid disrupting execution

    def _format_metric(self, value: Any, decimals: int = 2, suffix: str = "") -> str:
        """Format optional metric values for log output."""
        if value is None:
            return "n/a"
        try:
            return f"{float(value):.{decimals}f}{suffix}"
        except (TypeError, ValueError):
            return f"{value}{suffix}"

    # ── Internal execution loop ───────────────────────────────────────────────

    async def _run_session(self, session_id: str) -> None:
        """Execute trial-by-trial optimization until completion, failure, or cancellation."""
        session = self.session_manager.load_session(session_id)
        if session is None:
            return
        try:
            session = self.session_manager.mark_session_running(session_id)
            self._emit_log(f"[Session] Starting optimizer session {session_id}")
            if session.config.parameter_mode == OptimizerParameterMode.AUTO_SAFE:
                safe_enabled = [s for s in session.config.search_spaces if s.enabled]
                self._emit_log(
                    "[Auto Safe] Enabled "
                    f"{len(safe_enabled)} conservative buy/sell parameter(s) "
                    "before trial selection."
                )

            screened_candidates = await self._run_vectorbt_screening(session)

            for trial_number in range(1, session.config.total_trials + 1):
                if self._cancel_requested:
                    session = self.session_manager.mark_session_cancelled(session_id)
                    self._emit_log(f"[Session] Session cancelled at trial {trial_number}")
                    return

                session = self.session_manager.load_session(session_id)
                if session is None:
                    return
                session = self._maybe_apply_auto_safe_narrowing(
                    session, trial_number
                )
                enabled_spaces = [s for s in session.config.search_spaces if s.enabled]
                if not enabled_spaces:
                    if session.config.parameter_mode == OptimizerParameterMode.AUTO_SAFE:
                        raise BackendError(
                            "Auto Safe found no enabled optimizable buy/sell parameters.",
                            status_code=400,
                        )
                    raise BackendError(
                        "No enabled parameter search spaces defined.",
                        status_code=400,
                    )

                params = self._select_parameters_for_trial(
                    session,
                    enabled_spaces,
                    trial_number,
                    screened_candidates,
                )
                trial = OptimizerTrial(
                    trial_number=trial_number,
                    status=OptimizerTrialStatus.RUNNING,
                    parameters=params,
                    started_at=utc_now(),
                )
                session = self.session_manager.load_session(session_id)
                trials = list(session.trials) + [trial]
                session = session.model_copy(update={"trials": trials})
                self.session_manager.save_session(session)
                self._emit_log(f"[Trial #{trial_number}] Starting with parameters: {params}")

                # Run the backtest for this trial
                run_id, error = await self._run_trial_backtest(session, trial)
                session = self.session_manager.load_session(session_id)

                if error or run_id is None:
                    self._emit_log(f"[Trial #{trial_number}] Failed: {error or 'Backtest did not produce a run_id'}")
                    trial = trial.model_copy(
                        update={
                            "status": OptimizerTrialStatus.FAILED,
                            "completed_at": utc_now(),
                            "error": error or "Backtest did not produce a run_id",
                        }
                    )
                    session = self._update_trial(session, trial)
                    session = session.model_copy(
                        update={"failed_trials": session.failed_trials + 1}
                    )
                    self.session_manager.save_session(session)
                    continue

                # Parse metrics from the completed run
                metrics = self.trial_executor.extract_trial_metrics(run_id, session.config.score_metric, session.config.score_weights)
                if metrics is None:
                    self._emit_log(f"[Trial #{trial_number}] Failed: Metrics could not be extracted")
                    trial = trial.model_copy(
                        update={
                            "status": OptimizerTrialStatus.FAILED,
                            "completed_at": utc_now(),
                            "run_id": run_id,
                            "error": "Run completed but metrics could not be extracted.",
                        }
                    )
                    session = self._update_trial(session, trial)
                    session = session.model_copy(
                        update={"failed_trials": session.failed_trials + 1}
                    )
                    self.session_manager.save_session(session)
                    continue

                score = metrics.score
                trial = trial.model_copy(
                    update={
                        "status": OptimizerTrialStatus.COMPLETED,
                        "completed_at": utc_now(),
                        "run_id": run_id,
                        "metrics": metrics,
                    }
                )
                session = self._update_trial(session, trial)
                session = session.model_copy(
                    update={"completed_trials": session.completed_trials + 1}
                )
                self._emit_log(
                    "[Trial #"
                    f"{trial_number}] Completed - Score: {self._format_metric(score)}, "
                    f"Profit: {self._format_metric(metrics.net_profit_pct, suffix='%')}, "
                    f"Trades: {metrics.total_trades if metrics.total_trades is not None else 'n/a'}"
                )

                # Update best trial
                if score is not None:
                    current_best = session.best_metrics
                    if current_best is None or current_best.score is None or score > current_best.score:
                        self._emit_log(
                            f"[Trial #{trial_number}] NEW BEST SCORE: {self._format_metric(score)}"
                        )
                        # Mark all previous best trials as not best
                        updated_trials = [
                            t.model_copy(update={"is_best": False}) for t in session.trials
                        ]
                        # Mark this trial as best
                        updated_trials = [
                            t.model_copy(update={"is_best": True}) if t.trial_number == trial_number else t
                            for t in updated_trials
                        ]
                        session = session.model_copy(
                            update={
                                "trials": updated_trials,
                                "best_trial_number": trial_number,
                                "best_metrics": metrics,
                            }
                        )

                # Update elapsed/ETA
                session = self._update_timing(session)
                self.session_manager.save_session(session)
                
                # Emit progress update
                if self._progress_callback is not None:
                    try:
                        progress_data = {
                            "trial_number": trial_number,
                            "total": session.config.total_trials,
                            "result": {
                                "status": "completed" if trial.status == OptimizerTrialStatus.COMPLETED else "failed",
                                "score": trial.metrics.score if trial.metrics else None,
                                "profit_pct": trial.metrics.net_profit_pct if trial.metrics else None,
                                "win_rate_pct": trial.metrics.win_rate_pct if trial.metrics else None,
                                "max_drawdown_pct": trial.metrics.max_drawdown_pct if trial.metrics else None,
                                "total_trades": trial.metrics.total_trades if trial.metrics else None,
                                "profit_factor": trial.metrics.profit_factor if trial.metrics else None,
                                "sharpe_ratio": trial.metrics.sharpe_ratio if trial.metrics else None,
                            }
                        }
                        self._progress_callback(progress_data)
                    except Exception:
                        pass  # Ignore callback errors to avoid disrupting execution

            # All trials done
            session = self.session_manager.mark_session_completed(session_id)
            self._emit_log(f"[Session] Completed - {session.completed_trials} trials successful, {session.failed_trials} failed")

        except Exception as exc:
            self._emit_log(f"[Session] Failed with error: {exc}")
            session = self.session_manager.mark_session_failed(session_id, str(exc))
        finally:
            self._active_task = None
            self._active_session_id = None
            self._cancel_requested = False

    async def _run_trial_backtest(
        self, session: OptimizerSession, trial: OptimizerTrial
    ) -> tuple[str | None, str | None]:
        """Run a single trial backtest with trial parameters injected. Returns (run_id, error_message)."""
        return await self.trial_execution_service.run_existing_trial_backtest(
            session=session,
            trial=trial,
            cancel_requested=lambda: self._cancel_requested,
        )

    def _select_parameters_for_trial(
        self,
        session: OptimizerSession,
        spaces: list[ParameterSearchSpace],
        trial_number: int,
        screened_candidates: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Choose the next trial parameter set from the configured search strategy."""
        if screened_candidates:
            enabled_names = {space.name for space in spaces if space.enabled}
            while screened_candidates:
                candidate = screened_candidates.pop(0)
                filtered = {
                    name: value
                    for name, value in candidate.items()
                    if name in enabled_names
                }
                if filtered:
                    return filtered
        return select_parameters_for_trial(session, spaces, trial_number)

    async def _run_vectorbt_screening(
        self,
        session: OptimizerSession,
    ) -> list[dict[str, Any]]:
        """Run the optional VectorBT pre-screen and persist its report."""
        if not session.config.enable_vectorbt_screening:
            report = VectorBTScreeningReport(
                status="skipped",
                started_at=utc_now(),
                completed_at=utc_now(),
                skipped_reason="disabled",
            )
            latest = session.model_copy(update={"vectorbt_screening": report})
            self.session_manager.save_session(latest)
            self._emit_log("[VectorBT] Skipped pre-screening: disabled")
            return []

        enabled_spaces = [s for s in session.config.search_spaces if s.enabled]
        if not enabled_spaces:
            report = VectorBTScreeningReport(
                status="skipped",
                started_at=utc_now(),
                completed_at=utc_now(),
                skipped_reason="no_enabled_spaces",
            )
            latest = session.model_copy(update={"vectorbt_screening": report})
            self.session_manager.save_session(latest)
            self._emit_log("[VectorBT] Skipped pre-screening: no enabled search spaces")
            return []

        if self.vectorbt_screener is None:
            report = VectorBTScreeningReport(
                status="skipped",
                started_at=utc_now(),
                completed_at=utc_now(),
                skipped_reason="vectorbt_service_unavailable",
            )
            session = session.model_copy(update={"vectorbt_screening": report})
            self.session_manager.save_session(session)
            self._emit_log("[VectorBT] Skipped pre-screening: service unavailable")
            return []

        running_report = VectorBTScreeningReport(
            status="running",
            started_at=utc_now(),
        )
        latest = session.model_copy(update={"vectorbt_screening": running_report})
        self.session_manager.save_session(latest)
        self._emit_log(
            "[VectorBT] Starting parameter pre-screening "
            f"({session.config.vectorbt_candidate_count} candidates, "
            f"keep ratio {session.config.vectorbt_keep_ratio:.0%})"
        )
        outcome = await self.vectorbt_screener.screen_parameter_spaces(
            session=session,
            spaces=enabled_spaces,
            score_fn=self.trial_executor.compute_score,
        )
        latest = self.session_manager.load_session(session.session_id) or session
        latest = latest.model_copy(update={"vectorbt_screening": outcome.report})
        self.session_manager.save_session(latest)

        report = outcome.report
        if report.status in {"completed", "partial"}:
            self._emit_log(
                "[VectorBT] "
                f"{report.status}: evaluated {report.evaluated_count}, "
                f"selected {report.selected_count}, "
                f"reduced {self._format_metric(report.reduction_pct, suffix='%')}"
            )
            return list(outcome.selected_parameters)

        reason = report.skipped_reason or report.error or "unknown"
        self._emit_log(f"[VectorBT] Skipped pre-screening: {reason}")
        return []

    def _maybe_apply_auto_safe_narrowing(
        self,
        session: OptimizerSession,
        next_trial_number: int,
    ) -> OptimizerSession:
        """Persist visible Auto Safe narrowing before the next trial is selected."""
        updated_spaces, event = build_auto_safe_narrowing_event(
            session, next_trial_number
        )
        if event is None:
            return session

        config = session.config.model_copy(update={"search_spaces": updated_spaces})
        updates: dict[str, Any] = {
            "config": config,
            "auto_lock_events": list(session.auto_lock_events) + [event],
        }
        if event.grid_epoch_after is not None:
            updates["grid_epoch"] = event.grid_epoch_after
        if event.grid_epoch_start_trial is not None:
            updates["grid_epoch_start_trial"] = event.grid_epoch_start_trial

        session = session.model_copy(update=updates)
        self.session_manager.save_session(session)

        locked_text = ", ".join(event.locked_params)
        grid_text = ""
        if event.grid_epoch_before is not None and event.grid_epoch_after is not None:
            grid_text = (
                f" Grid epoch {event.grid_epoch_before}->{event.grid_epoch_after}."
            )
        self._emit_log(
            "[Auto Safe] "
            f"Before trial #{next_trial_number}, {event.reason.replace('_', ' ')} "
            f"triggered narrowing. Locked: {locked_text}. "
            f"Enabled {event.before_enabled_count}->{event.after_enabled_count}."
            f"{grid_text}"
        )
        return session

    def _update_trial(self, session: OptimizerSession, trial: OptimizerTrial) -> OptimizerSession:
        """Update one trial entry inside a session and persist the session."""
        trials = [t if t.trial_number != trial.trial_number else trial for t in session.trials]
        return session.model_copy(update={"trials": trials})

    def _update_timing(self, session: OptimizerSession) -> OptimizerSession:
        """Recalculate elapsed time and ETA shown in optimizer progress."""
        if session.started_at is None:
            return session
        now = utc_now()
        elapsed = (now - session.started_at).total_seconds()
        completed = session.completed_trials + session.failed_trials
        total = session.total_trials
        eta: float | None = None
        if completed > 0 and total > completed:
            avg_per_trial = elapsed / completed
            eta = avg_per_trial * (total - completed)
        return session.model_copy(update={"elapsed_seconds": elapsed, "eta_seconds": eta})
