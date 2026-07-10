"""Smoke data preparation step for AeRoing4."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ....core.errors import BackendError
from ....models.contracts import DownloadDataRequest
from ....services.execution.backtest_runner import BacktestRunner
from ....services.execution.data_download_runner import DataDownloadRunner
from ....utils import detect_data_file_format, get_data_file_path
from ..models import StepResult, DataPreparationResult, AeRoing4StepStatus

if TYPE_CHECKING:
    from ...app_services import AppServices


class DataPreparationStep:
    """Smoke data preparation step.

    Checks data availability for smoke pairs and downloads missing data
    using existing data download infrastructure.
    """

    def __init__(self, services: "AppServices"):
        """Initialize data preparation step with services."""
        self.services = services

    async def execute(
        self,
        pairs: list[str],
        timeframe: str,
        timerange: str,
        exchange: str = "binance",
    ) -> StepResult:
        """Execute data preparation step.

        Args:
            pairs: List of smoke pairs to prepare
            timeframe: Candle timeframe
            timerange: Date range for data
            exchange: Exchange name (default: binance)

        Returns:
            StepResult with data preparation outcome
        """
        started_at = datetime.now(UTC)

        try:
            settings = self.services.settings_store.load()
            user_data_dir = Path(settings.user_data_directory_path)

            # Check initial data availability
            pairs_ready = {}
            missing_pairs = []

            for pair in pairs:
                has_data = self._check_pair_data(
                    user_data_dir, pair, timeframe, timerange, exchange
                )
                pairs_ready[pair] = has_data
                if not has_data:
                    missing_pairs.append(pair)

            # Download missing data if needed
            download_errors = {}
            pairs_downloaded = []

            if missing_pairs:
                try:
                    download_request = DownloadDataRequest(
                        config_file=settings.default_config_file_path,
                        timerange=timerange,
                        timeframes=[timeframe],
                        pairs=missing_pairs,
                        prepend=False,
                    )

                    download_id = await asyncio.to_thread(
                        self.services.data_download_runner.run_download,
                        download_request,
                    )

                    # Track which pairs were downloaded
                    pairs_downloaded = missing_pairs.copy()

                except BackendError as exc:
                    # Mark download errors for each missing pair
                    for pair in missing_pairs:
                        download_errors[pair] = str(exc)
                except Exception as exc:
                    for pair in missing_pairs:
                        download_errors[pair] = str(exc)

            # Re-check coverage after download
            final_pairs_ready = {}
            for pair in pairs:
                has_data = self._check_pair_data(
                    user_data_dir, pair, timeframe, timerange, exchange
                )
                final_pairs_ready[pair] = has_data

            # Determine if coverage check passed
            # At least one pair must have usable data
            coverage_check_passed = any(final_pairs_ready.values())

            if not coverage_check_passed:
                return StepResult(
                    step_name="data_preparation",
                    status=AeRoing4StepStatus.FAILED,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    error="No smoke pair has usable data after preparation",
                    data={
                        "pairs_ready": final_pairs_ready,
                        "missing_pairs_downloaded": pairs_downloaded,
                        "download_errors": download_errors,
                        "coverage_check_passed": False,
                    },
                )

            return StepResult(
                step_name="data_preparation",
                status=AeRoing4StepStatus.PASSED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                data={
                    "pairs_ready": final_pairs_ready,
                    "missing_pairs_downloaded": pairs_downloaded,
                    "download_errors": download_errors,
                    "coverage_check_passed": True,
                },
            )

        except Exception as exc:
            return StepResult(
                step_name="data_preparation",
                status=AeRoing4StepStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error=f"Data preparation step failed: {str(exc)}",
                data={
                    "pairs_ready": {},
                    "missing_pairs_downloaded": [],
                    "download_errors": {},
                    "coverage_check_passed": False,
                },
            )

    def _check_pair_data(
        self,
        user_data_dir: Path,
        pair: str,
        timeframe: str,
        timerange: str,
        exchange: str = "binance",
    ) -> bool:
        """Check if a pair has required data for the timerange.

        Reuses BacktestRunner's data checking logic.
        """
        try:
            # Check if data file exists
            data_format = detect_data_file_format(user_data_dir, pair, timeframe, exchange)
            data_file = get_data_file_path(user_data_dir, pair, timeframe, exchange, data_format)

            if not data_file.exists():
                return False

            # Check if data covers the timerange
            # Use BacktestRunner's logic for consistency
            return self.services.backtest_runner._check_data_covers_timerange(
                pairs=[pair],
                timeframe=timeframe,
                user_data_dir=str(user_data_dir),
                timerange=timerange,
                exchange=exchange,
            )

        except Exception:
            # If check fails, assume data is not ready
            return False
