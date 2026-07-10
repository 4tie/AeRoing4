"""PairSweepRunner orchestrates sequential backtest iterations for a pair sweep session."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from ....core.errors import BackendError
from ....models import (
    DownloadDataRequest,
    RunRequest,
    StartPairSweepRequest,
    SweepIterationMetrics,
    SweepIterationRecord,
    SweepIterationStatus,
    SweepPhase,
    SweepSession,
    SweepSessionConfig,
)
from ....utils import utc_now
from ....settings_store import SettingsStore
from ..backtest_runner import BacktestRunner
from ..data_download_runner import DataDownloadRunner
from ...storage.pair_sweep_store import PairSweepStore
from ...storage.run_repository import RunRepository
from ...pairs.pair_selector import PairSelectorService
from ...strategy.strategy_registry import StrategyRegistry
from ...strategy.version_manager import VersionManager
from .individual_sweep import run_individual_pair_sweep as _run_individual_pair_sweep


class PairSweepRunner:
    """Orchestrates sequential backtest iterations for a pair sweep session."""

    def __init__(
        self,
        sweep_store: PairSweepStore,
        backtest_runner: BacktestRunner,
        run_repository: RunRepository,
        registry: StrategyRegistry,
        settings_store: SettingsStore,
        version_manager: VersionManager,
        pair_selector: PairSelectorService,
        data_download_runner: DataDownloadRunner,
    ) -> None:
        """__init__ implements function-level backend logic."""
        self.sweep_store = sweep_store
        self.backtest_runner = backtest_runner
        self.run_repository = run_repository
        self.registry = registry
        self.settings_store = settings_store
        self.version_manager = version_manager
        self.pair_selector = pair_selector
        self.data_download_runner = data_download_runner
        self._active_task: asyncio.Task | None = None
        self._active_session_id: str | None = None
        self._cancel_requested: bool = False

    # ── Public API ────────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        """is_running implements function-level backend logic."""
        return self._active_task is not None and not self._active_task.done()

    def get_active_session_id(self) -> str | None:
        """get_active_session_id implements function-level backend logic."""
        return self._active_session_id if self.is_running() else None

    async def start_session(self, request: StartPairSweepRequest) -> SweepSession:
        """start_session implements function-level backend logic."""
        if self.is_running():
            raise BackendError("A sweep session is already running.", status_code=409)
        if self.backtest_runner.is_busy():
            raise BackendError("Backtest runner is busy.", status_code=409)

        # Get current pair selector state for pair_pool and locked_pairs
        pair_state = self.pair_selector.get_state()

        # Ensure max_open_trades is at least the number of locked pairs
        effective_max_open_trades = max(request.max_open_trades, len(pair_state.locked_pairs))

        # Use selected pairs as pool if available, otherwise available pairs
        pair_pool = list(pair_state.selected_pairs) if pair_state.selected_pairs else list(pair_state.available_pairs)

        # Download data for all pairs in the pool if requested
        if request.download_data_first and pair_pool:
            await self._download_data_for_pairs(
                request.config_file,
                request.timerange,
                request.timeframe,
                pair_pool,
            )

        session_id = str(uuid.uuid4())
        config = SweepSessionConfig(
            strategy_name=request.strategy_name,
            config_file=request.config_file,
            timerange=request.timerange,
            timeframe=request.timeframe,
            fee_rate=request.fee_rate,
            max_open_trades=effective_max_open_trades,
            dry_run_wallet=request.dry_run_wallet,
            iteration_count=request.iteration_count,
            pair_pool=pair_pool,
            locked_pairs=list(pair_state.locked_pairs),
        )
        session = SweepSession(
            session_id=session_id,
            strategy_name=request.strategy_name,
            config=config,
            phase=SweepPhase.RUNNING,
            created_at=utc_now(),
            total_iterations=request.iteration_count,
        )
        self.sweep_store.save_session(session)
        self._cancel_requested = False
        self._active_session_id = session_id
        self._active_task = asyncio.create_task(self._run_sweep(session_id))
        return session

    async def cancel_session(self, session_id: str) -> SweepSession:
        """cancel_session implements function-level backend logic."""
        session = self.sweep_store.load_session(session_id)
        if session is None:
            raise BackendError(f"Sweep session '{session_id}' not found.", status_code=404)
        if session.phase not in {SweepPhase.RUNNING}:
            return session
        self._cancel_requested = True
        # Also cancel the active backtest if it's for this session
        if self._active_session_id == session_id and self.backtest_runner.is_busy():
            run_id = self.backtest_runner.active_run_id
            if run_id:
                await self.backtest_runner.cancel(run_id)
        # Wait briefly for the task to notice the cancellation
        if self._active_task and not self._active_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._active_task), timeout=3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        # Reload and mark cancelled if still running
        session = self.sweep_store.load_session(session_id)
        if session and session.phase == SweepPhase.RUNNING:
            session = session.model_copy(
                update={
                    "phase": SweepPhase.CANCELLED,
                    "completed_at": utc_now(),
                    "stop_reason": "Cancelled by user",
                }
            )
            self.sweep_store.save_session(session)
        return session

    def recover_interrupted_sessions(self) -> None:
        """recover_interrupted_sessions implements function-level backend logic."""
        for session in self.sweep_store.list_running_sessions():
            session = session.model_copy(
                update={
                    "phase": SweepPhase.FAILED,
                    "stop_reason": "Interrupted by server restart",
                    "completed_at": utc_now(),
                }
            )
            self.sweep_store.save_session(session)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _download_data_for_pairs(
        self,
        config_file: str,
        timerange: str,
        timeframe: str,
        pairs: list[str],
    ) -> None:
        """Download data for all pairs in the pool before starting the sweep."""
        download_request = DownloadDataRequest(
            config_file=config_file,
            timerange=timerange,
            timeframes=[timeframe],
            pairs=pairs,
            prepend=False,
        )
        try:
            download_id = await self.data_download_runner.queue_download(download_request)
            # Wait for download to complete
            while self.data_download_runner.is_busy():
                await asyncio.sleep(1.0)
            status = self.data_download_runner.current_status()
            if status.get("status") == "failed":
                raise BackendError(
                    f"Data download failed: {status.get('error', 'Unknown error')}",
                    status_code=500,
                )
        except Exception as exc:
            raise BackendError(
                f"Failed to download data for pairs: {exc}",
                status_code=500,
            )

    async def _run_sweep(self, session_id: str) -> None:
        """_run_sweep implements function-level backend logic."""
        session = self.sweep_store.load_session(session_id)
        if session is None:
            return
        try:
            config = session.config
            pool = list(config.pair_pool)
            locked_set = set(config.locked_pairs)
            max_open_trades = config.max_open_trades
            total_iterations = session.total_iterations

            # Resolve strategy and version once — they don't change across iterations
            strategy = self.registry.get_strategy(config.strategy_name)
            pointer = self.version_manager.get_current_pointer(config.strategy_name)
            if pointer is None:
                raise BackendError(
                    f"Strategy '{config.strategy_name}' has no accepted version.",
                    status_code=400,
                )
            version_id = pointer.accepted_version_id

            # Use default config file if none provided
            config_file = config.config_file
            if not config_file:
                settings = self.settings_store.load()
                config_file = settings.default_config_file_path

            previous_pairs: list[str] | None = None

            for i in range(1, total_iterations + 1):
                # ── Cancel check ──────────────────────────────────────────
                if self._cancel_requested:
                    session = self.sweep_store.load_session(session_id)
                    session = session.model_copy(
                        update={
                            "phase": SweepPhase.CANCELLED,
                            "completed_at": utc_now(),
                            "stop_reason": "Cancelled by user",
                        }
                    )
                    self.sweep_store.save_session(session)
                    return

                # ── Wait for runner to be free ────────────────────────────
                while self.backtest_runner.is_busy():
                    if self._cancel_requested:
                        session = self.sweep_store.load_session(session_id)
                        session = session.model_copy(
                            update={
                                "phase": SweepPhase.CANCELLED,
                                "completed_at": utc_now(),
                                "stop_reason": "Cancelled by user",
                            }
                        )
                        self.sweep_store.save_session(session)
                        return
                    await asyncio.sleep(1.0)

                # ── Sample pairs ──────────────────────────────────────────
                sampled_pairs, warning = self._sample_pairs(
                    pool, locked_set, max_open_trades, previous_pairs
                )
                previous_pairs = sampled_pairs

                # ── Build RunRequest ──────────────────────────────────────
                run_request = RunRequest(
                    strategy_name=config.strategy_name,
                    version_id=version_id,
                    config_file=config_file,
                    timerange=config.timerange,
                    timeframe=config.timeframe,
                    pairs=sampled_pairs,
                    fee_rate=config.fee_rate,
                    max_open_trades=config.max_open_trades,
                    dry_run_wallet=config.dry_run_wallet,
                )

                # ── Queue backtest ────────────────────────────────────────
                run_id: str | None = None
                error: str | None = None
                started_at = utc_now()
                try:
                    run_id = await self.backtest_runner.queue_strategy_backtest(
                        strategy, version_id, run_request
                    )
                except Exception as exc:
                    error = str(exc)

                # ── Create iteration record ───────────────────────────────
                record = SweepIterationRecord(
                    iteration_number=i,
                    status=SweepIterationStatus.RUNNING if run_id else SweepIterationStatus.FAILED,
                    pairs=sampled_pairs,
                    run_id=run_id,
                    started_at=started_at,
                    warning=warning,
                    error=error,
                )
                session = self.sweep_store.load_session(session_id)
                session = session.model_copy(
                    update={"iterations": list(session.iterations) + [record]}
                )
                self.sweep_store.save_session(session)

                if run_id is None:
                    # Queue failed — count as failed iteration
                    session = self.sweep_store.load_session(session_id)
                    session = session.model_copy(
                        update={"failed_iterations": session.failed_iterations + 1}
                    )
                    session = self._update_timing(session)
                    self.sweep_store.save_session(session)
                    continue

                # ── Poll until terminal ───────────────────────────────────
                terminal_status: str | None = None
                poll_error: str | None = None
                poll_started_at = utc_now()
                missing_metadata_count = 0
                while True:
                    await asyncio.sleep(2.0)
                    if self._cancel_requested:
                        # Cancel the active backtest and mark session cancelled
                        try:
                            await self.backtest_runner.cancel(run_id)
                        except Exception:
                            pass
                        session = self.sweep_store.load_session(session_id)
                        # Update the in-progress record to cancelled
                        updated_iterations = [
                            rec.model_copy(
                                update={
                                    "status": SweepIterationStatus.CANCELLED,
                                    "completed_at": utc_now(),
                                }
                            )
                            if rec.iteration_number == i
                            else rec
                            for rec in session.iterations
                        ]
                        session = session.model_copy(
                            update={
                                "phase": SweepPhase.CANCELLED,
                                "completed_at": utc_now(),
                                "stop_reason": "Cancelled by user",
                                "iterations": updated_iterations,
                            }
                        )
                        self.sweep_store.save_session(session)
                        return
                    try:
                        metadata = self.run_repository.load_metadata(run_id)
                        missing_metadata_count = 0
                    except Exception as exc:
                        # Avoid hanging forever if the run metadata never materializes.
                        missing_metadata_count += 1
                        elapsed = (utc_now() - poll_started_at).total_seconds()
                        runner_idle = not self.backtest_runner.is_busy()
                        if elapsed > 45 or (runner_idle and missing_metadata_count >= 3):
                            terminal_status = "failed"
                            poll_error = f"Unable to read run metadata for '{run_id}': {exc}"
                            break
                        continue
                    if metadata.run_status in {"completed", "failed", "cancelled"}:
                        terminal_status = metadata.run_status
                        break
                    # Guard against indefinite non-terminal states.
                    elapsed = (utc_now() - poll_started_at).total_seconds()
                    if elapsed > 45:
                        terminal_status = "failed"
                        poll_error = (
                            f"Run '{run_id}' stayed non-terminal for {int(elapsed)}s "
                            f"(latest status: {metadata.run_status})."
                        )
                        break

                completed_at = utc_now()

                # ── Process result ────────────────────────────────────────
                session = self.sweep_store.load_session(session_id)
                if terminal_status == "completed":
                    metrics = self._extract_iteration_metrics(run_id)
                    updated_record = record.model_copy(
                        update={
                            "status": SweepIterationStatus.COMPLETED,
                            "completed_at": completed_at,
                            "metrics": metrics,
                        }
                    )
                    updated_iterations = [
                        updated_record if rec.iteration_number == i else rec
                        for rec in session.iterations
                    ]
                    session = session.model_copy(
                        update={
                            "iterations": updated_iterations,
                            "completed_iterations": session.completed_iterations + 1,
                        }
                    )
                else:
                    if poll_error is None:
                        poll_error = f"Backtest {terminal_status}"
                    updated_record = record.model_copy(
                        update={
                            "status": SweepIterationStatus.FAILED,
                            "completed_at": completed_at,
                            "error": poll_error,
                        }
                    )
                    updated_iterations = [
                        updated_record if rec.iteration_number == i else rec
                        for rec in session.iterations
                    ]
                    session = session.model_copy(
                        update={
                            "iterations": updated_iterations,
                            "failed_iterations": session.failed_iterations + 1,
                        }
                    )

                session = self._update_timing(session)
                self.sweep_store.save_session(session)

            # ── All iterations done ───────────────────────────────────────
            session = self.sweep_store.load_session(session_id)
            session = session.model_copy(
                update={
                    "phase": SweepPhase.COMPLETED,
                    "completed_at": utc_now(),
                }
            )
            self.sweep_store.save_session(session)

        except Exception as exc:
            session = self.sweep_store.load_session(session_id)
            if session:
                session = session.model_copy(
                    update={
                        "phase": SweepPhase.FAILED,
                        "completed_at": utc_now(),
                        "stop_reason": str(exc),
                    }
                )
                self.sweep_store.save_session(session)
        finally:
            self._active_task = None
            self._active_session_id = None
            self._cancel_requested = False

    def _update_timing(self, session: SweepSession) -> SweepSession:
        """_update_timing implements function-level backend logic."""
        if session.started_at is None:
            return session
        now = utc_now()
        elapsed = (now - session.started_at).total_seconds()
        completed = session.completed_iterations
        total = session.total_iterations
        eta: float | None = None
        if completed > 0 and total > completed:
            avg_per_iter = elapsed / completed
            eta = avg_per_iter * (total - completed)
        return session.model_copy(update={"elapsed_seconds": elapsed, "eta_seconds": eta})

    def _sample_pairs(
        self,
        pool: list[str],
        locked: set[str],
        max_open_trades: int,
        previous_subset: list[str] | None,
    ) -> tuple[list[str], str | None]:
        """_sample_pairs implements function-level backend logic."""
        warning: str | None = None

        # If pool is smaller than max_open_trades, use all pairs and warn
        if len(pool) < max_open_trades:
            result = list(dict.fromkeys(pool))  # deduplicated, preserving order
            warning = (
                f"Pair pool ({len(pool)}) is smaller than max_open_trades "
                f"({max_open_trades}); using all available pairs."
            )
            return result, warning

        def _do_sample() -> list[str]:
            # Start with locked pairs (deduplicated, preserving insertion order)
            """_do_sample implements function-level backend logic."""
            locked_in_pool = list(dict.fromkeys(p for p in pool if p in locked))
            remaining_slots = max_open_trades - len(locked_in_pool)

            if remaining_slots <= 0:
                # More locked pairs than slots — just return the first max_open_trades locked pairs
                return locked_in_pool[:max_open_trades]

            unlocked_pool = [p for p in pool if p not in locked]
            sampled_unlocked = random.sample(unlocked_pool, min(remaining_slots, len(unlocked_pool)))
            return locked_in_pool + sampled_unlocked

        import random

        result = _do_sample()

        # If result equals previous_subset, make one re-sample attempt
        if previous_subset is not None and sorted(result) == sorted(previous_subset):
            result = _do_sample()

        return result, warning

    def _extract_iteration_metrics(self, run_id: str) -> SweepIterationMetrics | None:
        """_extract_iteration_metrics implements function-level backend logic."""
        try:
            detail = self.run_repository.load_detail(run_id)
            summary = detail.parsed_summary
            if summary is None:
                return None
            return SweepIterationMetrics(
                net_profit_pct=summary.net_profit_pct,
                total_trades=summary.total_trades,
                win_rate_pct=summary.win_rate_pct,
                max_drawdown_pct=summary.max_drawdown_pct,
                profit_factor=summary.profit_factor,
            )
        except Exception:
            return None

    async def run_individual_pair_sweep(
        self,
        pairs: list[str],
        strategy_name: str,
        config_file: str,
        timerange: str,
        timeframe: str,
        fee_rate: float = 0.001,
        dry_run_wallet: float = 1000.0,
    ) -> list[dict]:
        """Test one strategy against each pair individually with max_open_trades=1.

        Runs a separate backtest for each pair with max_open_trades=1,
        collects per-pair metrics, scores, and returns results sorted descending.

        Returns a list of dicts, each with:
            pair, status, rejection_reason, score,
            total_trades, profit_factor, win_rate, max_drawdown, expectancy, profit_total
        """
        return await _run_individual_pair_sweep(
            backtest_runner=self.backtest_runner,
            run_repository=self.run_repository,
            registry=self.registry,
            version_manager=self.version_manager,
            settings_store=self.settings_store,
            pairs=pairs,
            strategy_name=strategy_name,
            config_file=config_file,
            timerange=timerange,
            timeframe=timeframe,
            fee_rate=fee_rate,
            dry_run_wallet=dry_run_wallet,
        )
