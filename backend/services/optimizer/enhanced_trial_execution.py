"""Enhanced trial execution service with proper error handling and recovery."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from backend.core.optimizer_errors import (
    OptimizerError,
    TrialExecutionError,
    TrialValidationError,
)
from backend.models import (
    OptimizerSession,
    OptimizerTrial,
    OptimizerTrialStatus,
    RunRequest,
)
from backend.services.execution.backtest_runner import BacktestRunner
from backend.services.optimizer.session_validator import SessionValidator
from backend.services.storage.run_repository import RunRepository
from backend.services.strategy.optimizer_trial import OptimizerTrialExecutor
from backend.services.strategy.strategy_registry import StrategyRegistry
from backend.services.strategy.version_manager import VersionManager
from backend.utils import utc_now

logger = logging.getLogger(__name__)


class EnhancedTrialExecutionService:
    """Enhanced trial execution service with error handling, recovery, and validation."""

    def __init__(
        self,
        backtest_runner: BacktestRunner,
        run_repository: RunRepository,
        version_manager: VersionManager,
        trial_executor: OptimizerTrialExecutor,
        validator: SessionValidator,
        registry: StrategyRegistry | None = None,
        settings_store: Any | None = None,
        max_concurrent_trials: int = 1,
        trial_timeout_seconds: float = 3600,  # 1 hour default
    ):
        self.backtest_runner = backtest_runner
        self.run_repository = run_repository
        self.version_manager = version_manager
        self.trial_executor = trial_executor
        self.validator = validator
        self.registry = registry
        self.settings_store = settings_store
        
        # Execution limits
        self.max_concurrent_trials = max_concurrent_trials
        self.trial_timeout_seconds = trial_timeout_seconds
        
        # State tracking
        self._active_trials: dict[str, asyncio.Task] = {}
        self._trial_semaphore = asyncio.Semaphore(max_concurrent_trials)
        self._progress_callback: Callable[[str, dict], None] | None = None

    def set_progress_callback(self, callback: Callable[[str, dict], None] | None) -> None:
        """Set callback for progress updates."""
        self._progress_callback = callback

    def _emit_progress(self, session_id: str, data: dict[str, Any]) -> None:
        """Emit progress update if callback is set."""
        if self._progress_callback:
            try:
                self._progress_callback(session_id, data)
            except Exception as e:
                logger.error(f"Error in progress callback: {e}")

    @staticmethod
    def _value(value: Any) -> Any:
        return getattr(value, "value", value)

    async def validate_trial_parameters(
        self, trial_parameters: dict[str, Any], search_spaces: list[Any]
    ) -> list[str]:
        """Validate trial parameters against search spaces."""
        errors = []
        
        for param_name, param_value in trial_parameters.items():
            # Find corresponding search space
            space = next((s for s in search_spaces if s.name == param_name), None)
            if not space:
                errors.append(f"Parameter '{param_name}' not found in search spaces")
                continue

            # Type validation
            param_type = self._value(space.param_type)
            if param_type == "int":
                if not isinstance(param_value, int):
                    errors.append(f"Parameter '{param_name}' must be integer")
                elif space.min_value is not None and param_value < space.min_value:
                    errors.append(f"Parameter '{param_name}' below minimum ({space.min_value})")
                elif space.max_value is not None and param_value > space.max_value:
                    errors.append(f"Parameter '{param_name}' above maximum ({space.max_value})")

            elif param_type == "decimal":
                try:
                    float_value = float(param_value)
                    if space.min_value is not None and float_value < space.min_value:
                        errors.append(f"Parameter '{param_name}' below minimum ({space.min_value})")
                    elif space.max_value is not None and float_value > space.max_value:
                        errors.append(f"Parameter '{param_name}' above maximum ({space.max_value})")
                except (ValueError, TypeError):
                    errors.append(f"Parameter '{param_name}' must be numeric")

            elif param_type == "categorical":
                if space.choices and param_value not in space.choices:
                    errors.append(f"Parameter '{param_name}' must be one of {space.choices}")

            elif param_type == "boolean":
                if not isinstance(param_value, bool):
                    errors.append(f"Parameter '{param_name}' must be boolean")

        return errors

    async def execute_trial(
        self,
        session: OptimizerSession,
        trial_number: int,
        trial_parameters: dict[str, Any],
        strategy_source: str,
        parent_version_id: str,
    ) -> OptimizerTrial:
        """Execute a single trial with comprehensive error handling."""
        try:
            # Validate parameters
            validation_errors = await self.validate_trial_parameters(
                trial_parameters, session.config.search_spaces
            )
            if validation_errors:
                raise TrialValidationError(trial_number, validation_errors)

            # Create trial record
            trial = OptimizerTrial(
                trial_number=trial_number,
                status=OptimizerTrialStatus.RUNNING,
                parameters=trial_parameters,
                started_at=utc_now(),
            )

            # Update session with running trial
            session.trials.append(trial)
            self._emit_progress(session.session_id, {
                "type": "trial_started",
                "trial_number": trial_number,
            })

            run_id, error = await self.run_existing_trial_backtest(
                session=session,
                trial=trial,
                strategy_source=strategy_source,
                parent_version_id=parent_version_id,
            )
            if error or run_id is None:
                raise TrialExecutionError(
                    trial_number,
                    error or "Backtest did not produce a run_id",
                    recoverable=True,
                )

            # Extract metrics
            try:
                metrics = self.trial_executor.extract_trial_metrics(
                    run_id,
                    session.config.score_metric,
                    session.config.score_weights,
                )
                if metrics is None:
                    raise TrialExecutionError(
                        trial_number,
                        "Failed to extract metrics from backtest results",
                        recoverable=True,
                    )
            except Exception as e:
                raise TrialExecutionError(
                    trial_number,
                    f"Failed to extract metrics: {str(e)}",
                    recoverable=False,
                )

            # Update trial with success
            trial = trial.model_copy(
                update={
                    "status": OptimizerTrialStatus.COMPLETED,
                    "metrics": metrics,
                    "completed_at": utc_now(),
                    "run_id": run_id,
                }

            )

            self._emit_progress(session.session_id, {
                "type": "trial_completed",
                "trial_number": trial_number,
                "metrics": metrics.model_dump(mode="json") if metrics else None,
            })

            return trial

        except OptimizerError:
            # Re-raise our custom errors
            raise
        except Exception as e:
            # Wrap unexpected errors
            raise TrialExecutionError(
                trial_number,
                f"Unexpected error during trial execution: {str(e)}",
                recoverable=False,
            )

    async def _execute_backtest_with_timeout(
        self,
        strategy,
        trial_version_id: str,
        run_request: RunRequest,
    ) -> str:
        """Execute backtest with proper timeout handling."""
        return await self.backtest_runner.queue_strategy_backtest(
            strategy,
            trial_version_id,
            run_request,
        )

    async def run_existing_trial_backtest(
        self,
        session: OptimizerSession,
        trial: OptimizerTrial,
        strategy_source: str | None = None,
        parent_version_id: str | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> tuple[str | None, str | None]:
        """Run a persisted optimizer trial and return (run_id, error_message)."""
        config = session.config
        trial_version_id: str | None = None
        try:
            wait_attempts = 0
            while self.backtest_runner.is_busy() and wait_attempts < 120:
                if cancel_requested is not None and cancel_requested():
                    return None, "Cancelled"
                await asyncio.sleep(1.0)
                wait_attempts += 1
            if self.backtest_runner.is_busy():
                return None, "Backtest runner still busy after timeout"

            if self.registry is None:
                return None, "Optimizer registry is unavailable"

            strategy = self.registry.get_strategy(config.strategy_name)
            pointer = self.version_manager.get_current_pointer(config.strategy_name)
            if pointer is None:
                return None, "Strategy has no accepted version"

            parent_version_id = parent_version_id or pointer.accepted_version_id
            if strategy_source is None:
                strategy_source = self.version_manager.load_strategy_source(
                    config.strategy_name,
                    parent_version_id,
                )
            parent_params = self.version_manager.load_params(
                config.strategy_name,
                parent_version_id,
            )
            trial_params = self.trial_executor.build_trial_params(
                parent_params,
                trial.parameters,
            )
            if trial_params == parent_params:
                return None, "Trial parameters did not change any strategy values"

            trial_version = self.trial_executor.create_trial_version(
                config.strategy_name,
                parent_version_id,
                strategy_source,
                trial_params,
                trial.trial_number,
            )
            trial_version_id = trial_version.version_id

            config_file = config.config_file
            if not config_file and self.settings_store is not None:
                settings = self.settings_store.load()
                config_file = settings.default_config_file_path

            run_request = RunRequest(
                strategy_name=config.strategy_name,
                version_id=trial_version_id,
                config_file=config_file,
                timerange=config.timerange,
                timeframe=config.timeframe,
                pairs=config.pairs if config.pairs else None,
                fee_rate=config.fee_rate,
                max_open_trades=config.max_open_trades,
                dry_run_wallet=config.dry_run_wallet,
            )

            async with self._trial_semaphore:
                try:
                    run_id = await asyncio.wait_for(
                        self._execute_backtest_with_timeout(
                            strategy,
                            trial_version_id,
                            run_request,
                        ),
                        timeout=self.trial_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    active_run_id = self.backtest_runner.active_run_id
                    if active_run_id:
                        self.backtest_runner.cancel(active_run_id)
                    return None, f"Trial execution timed out after {self.trial_timeout_seconds}s"

            try:
                metadata = self.run_repository.load_metadata(run_id)
                if self._value(metadata.run_status) == "completed":
                    return run_id, None
                reason = self.trial_executor.extract_run_failure_reason(run_id)
                return None, f"Backtest {self._value(metadata.run_status)}: {reason}"
            except Exception as exc:
                return None, f"Failed to read backtest result: {exc}"
        except Exception as exc:
            return None, str(exc)
        finally:
            if trial_version_id:
                try:
                    self.version_manager.reject_version(trial_version_id, "Trial completed")
                except Exception:
                    logger.debug(
                        "Failed to cleanup optimizer trial version %s",
                        trial_version_id,
                        exc_info=True,
                    )

    async def cancel_trial(self, session_id: str, trial_number: int) -> bool:
        """Cancel a running trial."""
        trial_key = f"{session_id}:{trial_number}"
        
        if trial_key in self._active_trials:
            task = self._active_trials[trial_key]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            finally:
                del self._active_trials[trial_key]
            return True

        return False

    async def get_active_trials(self) -> list[dict[str, Any]]:
        """Get information about currently active trials."""
        active_trials = []
        
        for trial_key, task in self._active_trials.items():
            session_id, trial_number = trial_key.split(":")
            active_trials.append({
                "session_id": session_id,
                "trial_number": int(trial_number),
                "is_running": not task.done(),
            })

        return active_trials

    async def cleanup_completed_trials(self) -> int:
        """Clean up completed trial tasks."""
        completed_count = 0
        keys_to_remove = []

        for trial_key, task in self._active_trials.items():
            if task.done():
                keys_to_remove.append(trial_key)
                completed_count += 1

        for key in keys_to_remove:
            del self._active_trials[key]

        return completed_count
