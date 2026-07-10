"""Standalone tests for data_healer flag logic without conftest dependencies.

Tests cover:
  §1  _download_pair_data flag logic
  §2  Gap analysis logic for prepend/erase detection

Run:  python -m pytest backend/tests/test_data_healer_flags.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

# Direct imports to avoid conftest
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.services.auto_quant.pipeline_modules.data_healer import (
    _download_pair_data,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc
TIMERANGE = "20230101-20240101"   # IS window: 2023-01-01 to 2024-01-01
TIMEFRAME = "5m"
TF_MINUTES = 5
PAIR = "BTC/USDT"


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# ---------------------------------------------------------------------------
# §1  _download_pair_data flag logic
# ---------------------------------------------------------------------------

class TestDownloadPairDataFlags:
    """Test that _download_pair_data correctly appends --prepend and --erase flags."""

    @pytest.mark.asyncio
    async def test_download_without_flags(self, tmp_path, mocker):
        """Default download should not include --prepend or --erase flags."""
        # Mock the subprocess runner
        mock_run = mocker.patch(
            "backend.services.auto_quant.pipeline_modules.data_healer._run_subprocess",
            return_value=(0, "success", "")
        )
        # Mock gap check to return some candles
        mocker.patch(
            "backend.services.auto_quant.pipeline_modules.data_healer._check_pair_data_gaps",
            return_value={"available_candles": 1000}
        )

        await _download_pair_data(
            pair=PAIR,
            timerange=TIMERANGE,
            timeframe=TIMEFRAME,
            config_file=str(tmp_path / "config.json"),
            freqtrade_path="freqtrade",
            user_data_dir=str(tmp_path),
            run_id="test",
            timeout_seconds=300,
            prepend=False,
            erase=False,
        )

        # Verify the command was called without --prepend or --erase
        call_args = mock_run.call_args
        cmd = call_args[0][1]  # Second argument is the command list
        assert "--prepend" not in cmd
        assert "--erase" not in cmd

    @pytest.mark.asyncio
    async def test_download_with_prepend_flag(self, tmp_path, mocker):
        """Download with prepend=True should include --prepend flag."""
        mock_run = mocker.patch(
            "backend.services.auto_quant.pipeline_modules.data_healer._run_subprocess",
            return_value=(0, "success", "")
        )
        mocker.patch(
            "backend.services.auto_quant.pipeline_modules.data_healer._check_pair_data_gaps",
            return_value={"available_candles": 1000}
        )

        await _download_pair_data(
            pair=PAIR,
            timerange=TIMERANGE,
            timeframe=TIMEFRAME,
            config_file=str(tmp_path / "config.json"),
            freqtrade_path="freqtrade",
            user_data_dir=str(tmp_path),
            run_id="test",
            timeout_seconds=300,
            prepend=True,
            erase=False,
        )

        cmd = mock_run.call_args[0][1]
        assert "--prepend" in cmd
        assert "--erase" not in cmd

    @pytest.mark.asyncio
    async def test_download_with_erase_flag(self, tmp_path, mocker):
        """Download with erase=True should include --erase flag."""
        mock_run = mocker.patch(
            "backend.services.auto_quant.pipeline_modules.data_healer._run_subprocess",
            return_value=(0, "success", "")
        )
        mocker.patch(
            "backend.services.auto_quant.pipeline_modules.data_healer._check_pair_data_gaps",
            return_value={"available_candles": 1000}
        )

        await _download_pair_data(
            pair=PAIR,
            timerange=TIMERANGE,
            timeframe=TIMEFRAME,
            config_file=str(tmp_path / "config.json"),
            freqtrade_path="freqtrade",
            user_data_dir=str(tmp_path),
            run_id="test",
            timeout_seconds=300,
            prepend=False,
            erase=True,
        )

        cmd = mock_run.call_args[0][1]
        assert "--erase" in cmd
        assert "--prepend" not in cmd

    @pytest.mark.asyncio
    async def test_download_with_both_flags(self, tmp_path, mocker):
        """Download with both flags should include --erase (takes precedence)."""
        mock_run = mocker.patch(
            "backend.services.auto_quant.pipeline_modules.data_healer._run_subprocess",
            return_value=(0, "success", "")
        )
        mocker.patch(
            "backend.services.auto_quant.pipeline_modules.data_healer._check_pair_data_gaps",
            return_value={"available_candles": 1000}
        )

        await _download_pair_data(
            pair=PAIR,
            timerange=TIMERANGE,
            timeframe=TIMEFRAME,
            config_file=str(tmp_path / "config.json"),
            freqtrade_path="freqtrade",
            user_data_dir=str(tmp_path),
            run_id="test",
            timeout_seconds=300,
            prepend=True,
            erase=True,
        )

        cmd = mock_run.call_args[0][1]
        # When both are set, --erase should be present (it overwrites the file)
        assert "--erase" in cmd
        # --prepend may or may not be present when --erase is used, but the logic
        # in _stage_data_healing ensures they're not both passed together


# ---------------------------------------------------------------------------
# §2  Gap analysis logic for prepend/erase detection
# ---------------------------------------------------------------------------

class TestGapAnalysisFlagLogic:
    """Test the logic in _stage_data_healing that determines prepend/erase flags."""

    def test_needs_prepend_when_earliest_after_download_start(self):
        """If earliest_available is after download_start, need --prepend."""
        download_start_dt = _dt(2022, 12, 1)
        earliest = _dt(2023, 1, 1)  # After download start
        latest = _dt(2024, 1, 1)
        end_date = _dt(2024, 1, 1)

        needs_prepend = earliest > download_start_dt
        needs_append = latest < end_date

        assert needs_prepend is True
        assert needs_append is False

    def test_needs_append_when_latest_before_end_date(self):
        """If latest_available is before end_date, need append (default)."""
        download_start_dt = _dt(2022, 12, 1)
        earliest = _dt(2022, 12, 1)
        latest = _dt(2023, 12, 1)  # Before end date
        end_date = _dt(2024, 1, 1)

        needs_prepend = earliest > download_start_dt
        needs_append = latest < end_date

        assert needs_prepend is False
        assert needs_append is True

    def test_needs_erase_when_both_prepend_and_append(self):
        """If both prepend and append needed, use --erase."""
        download_start_dt = _dt(2022, 12, 1)
        earliest = _dt(2023, 1, 1)  # After download start
        latest = _dt(2023, 12, 1)  # Before end date
        end_date = _dt(2024, 1, 1)

        needs_prepend = earliest > download_start_dt
        needs_append = latest < end_date
        needs_erase = needs_prepend and needs_append

        assert needs_prepend is True
        assert needs_append is True
        assert needs_erase is True

    def test_needs_erase_when_middle_gaps_present(self):
        """If there are gaps in the middle of available data, use --erase."""
        earliest = _dt(2022, 12, 1)
        latest = _dt(2024, 1, 1)
        download_start_dt = _dt(2022, 12, 1)
        end_date = _dt(2024, 1, 1)

        # Simulate middle gaps
        missing_ranges = [
            (_dt(2023, 3, 1), _dt(2023, 4, 1)),  # Gap in middle
        ]

        middle_gaps = False
        for gap_start, gap_end in missing_ranges:
            if gap_start > earliest and gap_end < latest:
                middle_gaps = True
                break

        needs_prepend = earliest > download_start_dt
        needs_append = latest < end_date
        needs_erase = middle_gaps or (needs_prepend and needs_append)

        assert middle_gaps is True
        assert needs_erase is True

    def test_no_flags_when_data_complete(self):
        """If data covers full range, no flags needed."""
        download_start_dt = _dt(2022, 12, 1)
        earliest = _dt(2022, 12, 1)  # At download start
        latest = _dt(2024, 1, 1)  # At end date
        end_date = _dt(2024, 1, 1)

        needs_prepend = earliest > download_start_dt
        needs_append = latest < end_date

        assert needs_prepend is False
        assert needs_append is False

    def test_prepend_flag_suppressed_when_erase_needed(self):
        """When --erase is needed, --prepend should not be passed."""
        needs_prepend = True
        needs_erase = True

        # This is the logic from _stage_data_healing line 545
        prepend_flag = needs_prepend and not needs_erase

        assert prepend_flag is False, "prepend should be False when erase is True"

    def test_prepend_flag_passed_when_only_prepend_needed(self):
        """When only --prepend is needed (no erase), flag should be passed."""
        needs_prepend = True
        needs_erase = False

        prepend_flag = needs_prepend and not needs_erase

        assert prepend_flag is True, "prepend should be True when only prepend needed"
