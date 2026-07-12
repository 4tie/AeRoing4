"""Smoke backtest step for AeRoing4."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ....core.errors import BackendError
from ....models.contracts import RunRequest
from ....models.base import RunStatus
from ....services.backtest.backtest_service import extract_freqtrade_error
from ....services.execution.backtest_runner import BacktestRunner
from ....services.storage.run_repository import RunRepository
from ..models import (
    StepResult,
    SmokeBacktestResult,
    SmokeBacktestOutcome,
    AeRoing4StepStatus,
)

if TYPE_CHECKING:
    from ...app_services import AppServices


class SmokeBacktestStep:
    """Smoke backtest step.

    Runs the selected strategy against smoke pairs to verify execution.
    Classifies outcome as:
    - PASS_ACTIVITY: Freqtrade completed successfully with trades
    - NO_SIGNAL_ACTIVITY: Freqtrade completed successfully with zero trades
    - EXECUTION_FAILURE: Freqtrade or strategy runtime failed
    """

    def __init__(self, services: "AppServices"):
        """Initialize smoke backtest step with services."""
        self.services = services

    async def execute(
        self,
        strategy_name: str,
        version_id: str,
        pairs: list[str],
        timeframe: str,
        timerange: str,
        max_open_trades: int = 1,
        dry_run_wallet: float = 1000.0,
        config_file: str | None = None,
    ) -> StepResult:
        """Execute smoke backtest step.

        Args:
            strategy_name: Name of the strategy
            version_id: Strategy version ID
            pairs: List of smoke pairs
            timeframe: Candle timeframe
            timerange: Date range
            max_open_trades: Maximum open trades
            dry_run_wallet: Dry run wallet amount
            config_file: Optional config file override

        Returns:
            StepResult with smoke backtest outcome
        """
        started_at = datetime.now(UTC)

        try:
            # Check for version_id first
            if version_id is None:
                pointer = self.services.version_manager.get_current_pointer(strategy_name)
                if not pointer:
                    return StepResult(
                        step_name="smoke_backtest",
                        status=AeRoing4StepStatus.FAILED,
                        started_at=started_at,
                        completed_at=datetime.now(UTC),
                        error="Strategy has no accepted version",
                        data={
                            "outcome": SmokeBacktestOutcome.EXECUTION_FAILURE.value,
                            "backtest_run_id": None,
                            "total_trades": 0,
                            "trades_per_pair": {},
                            "net_profit": None,
                            "profit_factor": None,
                            "max_drawdown": None,
                            "execution_error": "Strategy has no accepted version",
                        },
                    )
                version_id = pointer.accepted_version_id

            # Resolve config file
            settings = self.services.settings_store.load()
            config_file = config_file or settings.default_config_file_path

            # Get strategy record
            strategy = self.services.registry.get_strategy(strategy_name)

            # Create run request
            run_request = RunRequest(
                strategy_name=strategy_name,
                version_id=version_id,
                config_file=config_file,
                timerange=timerange,
                timeframe=timeframe,
                pairs=pairs,
                max_open_trades=max_open_trades,
                dry_run_wallet=dry_run_wallet,
            )

            # Run backtest (synchronous, wrap in thread)
            run_id = await asyncio.to_thread(
                self.services.backtest_runner.run_backtest,
                strategy,
                version_id,
                run_request,
            )

            # Load backtest results
            metadata = self.services.run_repository.load_metadata(run_id)

            # Classify outcome
            outcome = self._classify_outcome(metadata, run_id)

            # Extract additional metrics
            detail = self.services.run_repository.load_detail(run_id)
            total_trades = self._total_trades_from_detail(detail)
            trades_per_pair = {
                pair_result.pair: pair_result.total_trades
                for pair_result in detail.pair_results
            }
            net_profit = detail.parsed_summary.net_profit_pct if detail.parsed_summary else None
            profit_factor = detail.parsed_summary.profit_factor if detail.parsed_summary else None
            max_drawdown = detail.parsed_summary.max_drawdown_pct if detail.parsed_summary else None
            execution_error = (
                self._extract_execution_error(run_id)
                if outcome == SmokeBacktestOutcome.EXECUTION_FAILURE
                else None
            )
            artifact_details = self._artifact_details(run_id, detail)

            return StepResult(
                step_name="smoke_backtest",
                status=AeRoing4StepStatus.PASSED
                if outcome != SmokeBacktestOutcome.EXECUTION_FAILURE
                else AeRoing4StepStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error=execution_error,
                data={
                    "outcome": outcome.value,
                    "backtest_run_id": run_id,
                    "total_trades": total_trades,
                    "trades_per_pair": trades_per_pair,
                    "net_profit": net_profit,
                    "profit_factor": profit_factor,
                    "max_drawdown": max_drawdown,
                    "execution_error": execution_error,
                    **artifact_details,
                },
            )

        except BackendError as exc:
            return StepResult(
                step_name="smoke_backtest",
                status=AeRoing4StepStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error=f"Backtest execution failed: {exc.message}",
                data={
                    "outcome": SmokeBacktestOutcome.EXECUTION_FAILURE.value,
                    "backtest_run_id": None,
                    "total_trades": 0,
                    "trades_per_pair": {},
                    "net_profit": None,
                    "profit_factor": None,
                    "max_drawdown": None,
                    "execution_error": exc.message,
                },
            )
        except Exception as exc:
            return StepResult(
                step_name="smoke_backtest",
                status=AeRoing4StepStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error=f"Smoke backtest step failed: {str(exc)}",
                data={
                    "outcome": SmokeBacktestOutcome.EXECUTION_FAILURE.value,
                    "backtest_run_id": None,
                    "total_trades": 0,
                    "trades_per_pair": {},
                    "net_profit": None,
                    "profit_factor": None,
                    "max_drawdown": None,
                    "execution_error": str(exc),
                },
            )

    def _classify_outcome(
        self, metadata, run_id: str
    ) -> SmokeBacktestOutcome:
        """Classify backtest outcome based on results.

        Args:
            metadata: Backtest run metadata
            run_id: Backtest run ID

        Returns:
            SmokeBacktestOutcome classification
        """
        # Check for execution failure
        if metadata.run_status == RunStatus.FAILED:
            return SmokeBacktestOutcome.EXECUTION_FAILURE

        if metadata.run_status == RunStatus.CANCELLED:
            return SmokeBacktestOutcome.EXECUTION_FAILURE

        # Load detail to check trade count
        try:
            detail = self.services.run_repository.load_detail(run_id)
            total_trades = self._total_trades_from_detail(detail)

            if total_trades > 0:
                return SmokeBacktestOutcome.PASS_ACTIVITY
            else:
                return SmokeBacktestOutcome.NO_SIGNAL_ACTIVITY

        except Exception:
            # If we can't load details, assume execution failure
            return SmokeBacktestOutcome.EXECUTION_FAILURE

    def _extract_execution_error(self, run_id: str) -> str | None:
        """Extract a concise Freqtrade error from the run artifacts."""
        try:
            run_dir = self.services.run_repository.find_run_dir(run_id)
        except Exception:
            return None
        if not isinstance(run_dir, (str, bytes)):
            try:
                run_dir = str(run_dir)
            except Exception:
                return None
        try:
            return extract_freqtrade_error(Path(run_dir))
        except Exception:
            return None

    def _total_trades_from_detail(self, detail) -> int:
        parsed_summary = getattr(detail, "parsed_summary", None)
        if parsed_summary is not None:
            raw_total = getattr(parsed_summary, "total_trades", None)
            if raw_total is not None:
                try:
                    return int(raw_total)
                except (TypeError, ValueError):
                    pass
        trades = getattr(detail, "trades", None)
        if isinstance(trades, list):
            return len(trades)
        return 0

    def _artifact_details(self, run_id: str, detail) -> dict:
        artifacts = getattr(detail, "artifacts", {}) or {}
        if not isinstance(artifacts, dict):
            artifacts = {}

        command = getattr(detail, "freqtrade_command", None)
        if not isinstance(command, str):
            command = None

        run_dir: Path | None = None
        try:
            found = self.services.run_repository.find_run_dir(run_id)
            if isinstance(found, Path):
                run_dir = found
            elif isinstance(found, (str, bytes)):
                run_dir = Path(found)
        except Exception:
            run_dir = None

        logs_path = artifacts.get("logs.txt")
        log_excerpt = None
        if isinstance(logs_path, str):
            log_excerpt = self._tail_text(Path(logs_path))
        if log_excerpt is None and run_dir is not None:
            log_excerpt = self._tail_text(run_dir / "logs.txt")

        output_result_path = artifacts.get("raw_result.json")
        output_zip_path = artifacts.get("freqtrade_native_result.zip")
        if not output_zip_path:
            output_zip_path = next(
                (
                    path
                    for name, path in artifacts.items()
                    if isinstance(name, str)
                    and name.lower().endswith(".zip")
                    and isinstance(path, str)
                ),
                None,
            )

        return {
            "run_dir": str(run_dir) if run_dir is not None else None,
            "freqtrade_command": command,
            "strategy_path_argument": self._extract_strategy_path_argument(command),
            "output_result_path": output_result_path,
            "output_zip_path": output_zip_path,
            "log_excerpt": log_excerpt,
            "artifacts": artifacts,
        }

    def _tail_text(self, path: Path) -> str | None:
        try:
            if not path.exists() or not path.is_file():
                return None
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            return None
        if not text:
            return None
        return text[-4000:]

    def _extract_strategy_path_argument(self, command: str | None) -> str | None:
        if not command or "--strategy-path" not in command:
            return None
        tail = command.split("--strategy-path", 1)[1].lstrip()
        if not tail:
            return None
        if tail[0] == '"':
            end = tail.find('"', 1)
            return tail[1:end] if end != -1 else tail[1:]
        return tail.split(maxsplit=1)[0]
