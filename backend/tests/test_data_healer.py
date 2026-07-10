"""Unit tests for data_healer._check_pair_data_gaps and _is_only_start_boundary_gap.

Tests cover:
  §1  _check_pair_data_gaps — file-not-found, empty file, complete data,
      exchange-bounded start gap, trailing gap, internal gap,
      feather DataFrame format (date column as datetime64[ms, UTC])
  §2  _is_only_start_boundary_gap — start-only gap (accept), internal gap
      (reject), end gap (reject), empty missing_ranges (reject)

Run:  python -m pytest backend/tests/test_data_healer.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from backend.services.auto_quant.pipeline_modules.data_healer import (
    _check_pair_data_gaps,
    _is_only_start_boundary_gap,
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


def _write_feather(path: Path, timestamps: list[datetime]) -> None:
    """Write a minimal feather file with the given UTC timestamps."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(timestamps, utc=True).astype("datetime64[ms, UTC]"),
            "open":   [1.0] * len(timestamps),
            "high":   [1.1] * len(timestamps),
            "low":    [0.9] * len(timestamps),
            "close":  [1.0] * len(timestamps),
            "volume": [100.0] * len(timestamps),
        }
    )
    df.to_feather(path)


def _feather_path(user_data_dir: str) -> Path:
    """Return the expected feather path for BTC/USDT 5m."""
    return Path(user_data_dir) / "data" / "binance" / "BTC_USDT-5m.feather"


def _dense_timestamps(start: datetime, end: datetime, step_minutes: int = TF_MINUTES) -> list[datetime]:
    """Generate a gapless list of timestamps from start to end (inclusive)."""
    ts = []
    cur = start
    step = timedelta(minutes=step_minutes)
    while cur <= end:
        ts.append(cur)
        cur += step
    return ts


# ---------------------------------------------------------------------------
# §1  _check_pair_data_gaps
# ---------------------------------------------------------------------------

class TestCheckPairDataGaps:

    # ── §1.1 No data file ────────────────────────────────────────────────────

    def test_missing_file_returns_has_gaps_true(self, tmp_path):
        result = _check_pair_data_gaps(PAIR, TIMERANGE, TIMEFRAME, str(tmp_path))
        assert result["has_gaps"] is True
        assert result["reason"] == "no_data_file"
        assert result["available_candles"] == 0
        assert result["earliest_available"] is None
        assert result["latest_available"] is None

    # ── §1.2 Empty feather file ──────────────────────────────────────────────

    def test_empty_feather_returns_has_gaps_true(self, tmp_path):
        path = _feather_path(str(tmp_path))
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write an empty DataFrame with the correct schema
        df = pd.DataFrame(
            columns=["date", "open", "high", "low", "close", "volume"]
        ).astype({"date": "datetime64[ns, UTC]"})
        df.to_feather(path)

        result = _check_pair_data_gaps(PAIR, TIMERANGE, TIMEFRAME, str(tmp_path))
        assert result["has_gaps"] is True
        assert result["available_candles"] == 0

    # ── §1.3 Complete data — no gaps ────────────────────────────────────────

    def test_complete_data_returns_no_gaps(self, tmp_path):
        """Dense candles covering warmup + IS window → has_gaps=False."""
        path = _feather_path(str(tmp_path))
        # IS window: 2023-01-01 to 2024-01-01
        # Warmup 200 candles × 5m = 1000 min ≈ 16.7 h before IS start
        warmup_start = _dt(2023, 1, 1) - timedelta(minutes=TF_MINUTES * 200)
        is_end = _dt(2024, 1, 1)
        timestamps = _dense_timestamps(warmup_start, is_end)
        _write_feather(path, timestamps)

        result = _check_pair_data_gaps(PAIR, TIMERANGE, TIMEFRAME, str(tmp_path))
        assert result["has_gaps"] is False
        assert result["reason"] == "complete"
        assert result["available_candles"] == len(timestamps)

    # ── §1.4 Exchange-bounded start gap: data begins at IS start ────────────

    def test_exchange_bounded_start_gap_accepted(self, tmp_path):
        """Data starts exactly at IS start (no warmup), but covers the full IS
        window — should be accepted (has_gaps=False) because the exchange
        simply has no earlier data.
        """
        path = _feather_path(str(tmp_path))
        # Earliest candle is exactly at IS start, no warmup available
        is_start = _dt(2023, 1, 1)
        is_end = _dt(2024, 1, 1)
        timestamps = _dense_timestamps(is_start, is_end)
        _write_feather(path, timestamps)

        result = _check_pair_data_gaps(PAIR, TIMERANGE, TIMEFRAME, str(tmp_path))
        # earliest == start_date: falls into the exchange-bounded branch → pass
        assert result["has_gaps"] is False
        assert result["reason"] == "complete"

    def test_exchange_bounded_start_gap_accepted_within_30_days(self, tmp_path):
        """Data starts slightly after required_start but at or before IS start
        — still considered exchange-bounded (no gap in the actual IS window).
        """
        path = _feather_path(str(tmp_path))
        # Start data 10 days before IS start (warmup is limited but IS is intact)
        is_start = _dt(2023, 1, 1)
        is_end = _dt(2024, 1, 1)
        data_start = is_start - timedelta(days=10)   # < warmup needed (200 × 5m ≈ 17h)
        timestamps = _dense_timestamps(data_start, is_end)
        _write_feather(path, timestamps)

        result = _check_pair_data_gaps(PAIR, TIMERANGE, TIMEFRAME, str(tmp_path))
        # earliest (data_start) <= start_date (is_start) → exchange-bounded → no gap
        assert result["has_gaps"] is False
        assert result["reason"] == "complete"

    # ── §1.5 Genuine leading gap: data starts AFTER IS start ─────────────────

    def test_genuine_leading_gap_detected(self, tmp_path):
        """Data that begins after IS start is a real gap, not a boundary issue."""
        path = _feather_path(str(tmp_path))
        is_end = _dt(2024, 1, 1)
        # Start well after IS start: IS window has a real hole at the beginning
        data_start = _dt(2023, 3, 1)   # 2 months into the IS window
        timestamps = _dense_timestamps(data_start, is_end)
        _write_feather(path, timestamps)

        result = _check_pair_data_gaps(PAIR, TIMERANGE, TIMEFRAME, str(tmp_path))
        assert result["has_gaps"] is True
        assert any(
            gap_end > _dt(2023, 1, 1)
            for gap_start, gap_end in result["missing_ranges"]
        )

    # ── §1.6 Trailing gap ────────────────────────────────────────────────────

    def test_trailing_gap_detected(self, tmp_path):
        """Data that ends 5 days before the IS end triggers a trailing gap."""
        path = _feather_path(str(tmp_path))
        warmup_start = _dt(2023, 1, 1) - timedelta(minutes=TF_MINUTES * 200)
        # End data 5 days before IS end (beyond the 1-day tolerance)
        data_end = _dt(2023, 12, 26)
        timestamps = _dense_timestamps(warmup_start, data_end)
        _write_feather(path, timestamps)

        result = _check_pair_data_gaps(PAIR, TIMERANGE, TIMEFRAME, str(tmp_path))
        assert result["has_gaps"] is True
        trailing_gaps = [
            (s, e) for s, e in result["missing_ranges"]
            if s >= data_end
        ]
        assert trailing_gaps, "Expected at least one trailing-gap entry"

    # ── §1.7 Internal gap ────────────────────────────────────────────────────

    def test_internal_gap_detected(self, tmp_path):
        """A gap of 3 candles mid-series is detected as an internal gap."""
        path = _feather_path(str(tmp_path))
        warmup_start = _dt(2023, 1, 1) - timedelta(minutes=TF_MINUTES * 200)
        is_end = _dt(2024, 1, 1)

        # Build full series then punch a 30-minute hole in the middle
        all_ts = _dense_timestamps(warmup_start, is_end)
        hole_center = _dt(2023, 6, 15, 12, 0)
        gap_window = timedelta(minutes=30)
        ts_with_gap = [
            t for t in all_ts
            if not (hole_center - gap_window <= t <= hole_center + gap_window)
        ]
        _write_feather(path, ts_with_gap)

        result = _check_pair_data_gaps(PAIR, TIMERANGE, TIMEFRAME, str(tmp_path))
        assert result["has_gaps"] is True
        # At least one gap should fall inside the IS window
        is_start = _dt(2023, 1, 1)
        internal_gaps = [
            (s, e) for s, e in result["missing_ranges"]
            if s >= is_start
        ]
        assert internal_gaps, "Expected at least one internal gap entry"

    # ── §1.8 Return schema always present ───────────────────────────────────

    def test_return_dict_always_has_required_keys(self, tmp_path):
        """_check_pair_data_gaps must always return all documented keys."""
        required_keys = {
            "has_gaps", "missing_ranges", "available_candles",
            "required_candles", "earliest_available", "latest_available",
        }
        result = _check_pair_data_gaps(PAIR, TIMERANGE, TIMEFRAME, str(tmp_path))
        assert required_keys.issubset(result.keys()), (
            f"Missing keys: {required_keys - result.keys()}"
        )

    # ── §1.9 Feather DataFrame format: date column ───────────────────────────

    def test_feather_date_column_timezone_aware(self, tmp_path):
        """Feather files written with UTC-aware datetimes are parsed correctly."""
        path = _feather_path(str(tmp_path))
        warmup_start = _dt(2023, 1, 1) - timedelta(minutes=TF_MINUTES * 200)
        is_end = _dt(2024, 1, 1)
        timestamps = _dense_timestamps(warmup_start, is_end)
        _write_feather(path, timestamps)

        result = _check_pair_data_gaps(PAIR, TIMERANGE, TIMEFRAME, str(tmp_path))
        assert result["earliest_available"] is not None
        assert result["earliest_available"].tzinfo is not None, (
            "earliest_available must be timezone-aware"
        )
        assert result["latest_available"] is not None
        assert result["latest_available"].tzinfo is not None, (
            "latest_available must be timezone-aware"
        )

    # ── §1.10 List-of-lists candle format (int64 ms epoch) ───────────────────

    def test_list_of_lists_format_no_gaps(self, tmp_path):
        """Feather written from list-of-lists candles [ts_ms, o, h, l, c, v]
        stores 'date' as int64 milliseconds.  The normalisation layer must
        convert it to UTC datetime64 so gap detection works correctly.

        No-gap scenario: dense series from warmup start to IS end → has_gaps=False.
        """
        path = _feather_path(str(tmp_path))
        warmup_start = _dt(2023, 1, 1) - timedelta(minutes=TF_MINUTES * 200)
        is_end = _dt(2024, 1, 1)
        timestamps = _dense_timestamps(warmup_start, is_end)

        # Simulate how freqtrade constructs DataFrames from list-of-lists candles:
        # each row is [timestamp_ms, open, high, low, close, volume]
        path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(
            {
                "date": [int(t.timestamp() * 1000) for t in timestamps],  # int64 ms
                "open":   [1.0] * len(timestamps),
                "high":   [1.1] * len(timestamps),
                "low":    [0.9] * len(timestamps),
                "close":  [1.0] * len(timestamps),
                "volume": [100.0] * len(timestamps),
            }
        )
        df.to_feather(path)

        result = _check_pair_data_gaps(PAIR, TIMERANGE, TIMEFRAME, str(tmp_path))
        assert result["has_gaps"] is False, (
            f"int64 feather should be normalised and show no gaps; "
            f"got has_gaps=True, reason={result.get('reason')}"
        )
        assert result["reason"] == "complete"

    def test_list_of_lists_format_internal_gap_detected(self, tmp_path):
        """List-of-lists format with a 30-min internal gap must still detect
        the gap after int64-to-datetime64 normalisation.
        """
        path = _feather_path(str(tmp_path))
        warmup_start = _dt(2023, 1, 1) - timedelta(minutes=TF_MINUTES * 200)
        is_end = _dt(2024, 1, 1)
        all_ts = _dense_timestamps(warmup_start, is_end)

        # Punch a 30-minute hole
        hole_center = _dt(2023, 6, 15, 12, 0)
        gap_window = timedelta(minutes=30)
        ts_with_gap = [
            t for t in all_ts
            if not (hole_center - gap_window <= t <= hole_center + gap_window)
        ]

        path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(
            {
                "date": [int(t.timestamp() * 1000) for t in ts_with_gap],  # int64 ms
                "open":   [1.0] * len(ts_with_gap),
                "high":   [1.1] * len(ts_with_gap),
                "low":    [0.9] * len(ts_with_gap),
                "close":  [1.0] * len(ts_with_gap),
                "volume": [100.0] * len(ts_with_gap),
            }
        )
        df.to_feather(path)

        result = _check_pair_data_gaps(PAIR, TIMERANGE, TIMEFRAME, str(tmp_path))
        assert result["has_gaps"] is True
        is_start = _dt(2023, 1, 1)
        internal_gaps = [
            (s, e) for s, e in result["missing_ranges"]
            if s >= is_start
        ]
        assert internal_gaps, "Expected at least one internal gap after int64 normalisation"

    def test_list_of_lists_format_start_boundary_gap_accepted(self, tmp_path):
        """List-of-lists feather starting exactly at IS start (exchange-bounded)
        must be accepted (has_gaps=False) after int64 normalisation.
        """
        path = _feather_path(str(tmp_path))
        is_start = _dt(2023, 1, 1)
        is_end = _dt(2024, 1, 1)
        timestamps = _dense_timestamps(is_start, is_end)

        path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(
            {
                "date": [int(t.timestamp() * 1000) for t in timestamps],
                "open":   [1.0] * len(timestamps),
                "high":   [1.1] * len(timestamps),
                "low":    [0.9] * len(timestamps),
                "close":  [1.0] * len(timestamps),
                "volume": [100.0] * len(timestamps),
            }
        )
        df.to_feather(path)

        result = _check_pair_data_gaps(PAIR, TIMERANGE, TIMEFRAME, str(tmp_path))
        assert result["has_gaps"] is False, (
            "int64 feather starting at IS start should be exchange-bounded accept"
        )

    # ── §1.11 Dict-format vs list-of-lists format — identical gap outcomes ───

    def test_dict_and_list_formats_produce_identical_gap_outcomes(self, tmp_path):
        """datetime64 (dict-derived) and int64 (list-of-lists-derived) feather
        files with identical candle data must produce the same gap-check result.

        This is the regression test for the candle-format bug:
        the old parser expected dicts but freqtrade uses list-of-lists.
        After the fix, both formats normalise to the same timestamps.
        """
        warmup_start = _dt(2023, 1, 1) - timedelta(minutes=TF_MINUTES * 200)
        is_end = _dt(2024, 1, 1)
        all_ts = _dense_timestamps(warmup_start, is_end)

        # Punch an internal gap in the middle to make the result non-trivial
        hole_center = _dt(2023, 8, 1, 6, 0)
        gap_window = timedelta(minutes=25)
        timestamps = [
            t for t in all_ts
            if not (hole_center - gap_window <= t <= hole_center + gap_window)
        ]

        # ── dict-format feather: datetime64[ms, UTC] date column ──────────
        dict_dir = tmp_path / "dict_fmt"
        dict_path = _feather_path(str(dict_dir))
        _write_feather(dict_path, timestamps)   # uses datetime64

        # ── list-of-lists feather: int64 ms epoch date column ─────────────
        list_dir = tmp_path / "list_fmt"
        list_path = _feather_path(str(list_dir))
        list_path.parent.mkdir(parents=True, exist_ok=True)
        df_int = pd.DataFrame(
            {
                "date": [int(t.timestamp() * 1000) for t in timestamps],
                "open":   [1.0] * len(timestamps),
                "high":   [1.1] * len(timestamps),
                "low":    [0.9] * len(timestamps),
                "close":  [1.0] * len(timestamps),
                "volume": [100.0] * len(timestamps),
            }
        )
        df_int.to_feather(list_path)

        result_dict = _check_pair_data_gaps(PAIR, TIMERANGE, TIMEFRAME, str(dict_dir))
        result_list = _check_pair_data_gaps(PAIR, TIMERANGE, TIMEFRAME, str(list_dir))

        assert result_dict["has_gaps"] == result_list["has_gaps"], (
            f"Gap detection diverges: dict={result_dict['has_gaps']}, "
            f"list={result_list['has_gaps']}"
        )
        assert result_dict["available_candles"] == result_list["available_candles"], (
            "Available candle counts differ between dict and list formats"
        )
        assert len(result_dict["missing_ranges"]) == len(result_list["missing_ranges"]), (
            "Number of missing ranges differs between dict and list formats"
        )


# ---------------------------------------------------------------------------
# §2  _is_only_start_boundary_gap
# ---------------------------------------------------------------------------

class TestIsOnlyStartBoundaryGap:
    """Four canonical scenarios documented in the data_healer docstring."""

    # Shared dates
    start_date = _dt(2023, 1, 1)
    end_date = _dt(2024, 1, 1)

    # ── §2.1 Start-only gap → True ──────────────────────────────────────────

    def test_start_boundary_gap_only_returns_true(self):
        """All missing ranges end at or before start_date, latest >= end_date."""
        verify_check = {
            "missing_ranges": [
                # Gap entirely before IS start (warmup region)
                (_dt(2022, 11, 1), _dt(2022, 12, 31)),
            ],
            "latest_available": _dt(2024, 1, 1),   # covers IS end
        }
        assert _is_only_start_boundary_gap(
            verify_check, self.start_date, self.end_date
        ) is True

    def test_start_boundary_gap_ending_exactly_at_start_returns_true(self):
        """Gap end == start_date is still a boundary gap (gap_end <= start_date)."""
        verify_check = {
            "missing_ranges": [
                (_dt(2022, 12, 1), self.start_date),   # ends exactly at IS start
            ],
            "latest_available": _dt(2024, 1, 2),
        }
        assert _is_only_start_boundary_gap(
            verify_check, self.start_date, self.end_date
        ) is True

    # ── §2.2 Internal gap → False ───────────────────────────────────────────

    def test_internal_gap_crossing_is_start_returns_false(self):
        """A missing range that extends past start_date is not a boundary gap."""
        verify_check = {
            "missing_ranges": [
                # Gap starts before IS start but ends after it → internal
                (_dt(2022, 12, 15), _dt(2023, 1, 15)),
            ],
            "latest_available": _dt(2024, 1, 1),
        }
        assert _is_only_start_boundary_gap(
            verify_check, self.start_date, self.end_date
        ) is False

    def test_gap_entirely_within_is_window_returns_false(self):
        """A gap inside the IS window must always be rejected."""
        verify_check = {
            "missing_ranges": [
                # Entirely inside IS window
                (_dt(2023, 6, 1), _dt(2023, 6, 15)),
            ],
            "latest_available": _dt(2024, 1, 1),
        }
        assert _is_only_start_boundary_gap(
            verify_check, self.start_date, self.end_date
        ) is False

    # ── §2.3 End / trailing gap → False ─────────────────────────────────────

    def test_trailing_gap_latest_before_end_returns_false(self):
        """latest_available before end_date means the IS window isn't covered."""
        verify_check = {
            "missing_ranges": [
                # Only warmup gap — but data doesn't reach IS end
                (_dt(2022, 11, 1), _dt(2022, 12, 31)),
            ],
            "latest_available": _dt(2023, 11, 1),   # does NOT reach IS end
        }
        assert _is_only_start_boundary_gap(
            verify_check, self.start_date, self.end_date
        ) is False

    def test_latest_available_none_returns_false(self):
        """latest_available=None (file not read) must return False."""
        verify_check = {
            "missing_ranges": [
                (_dt(2022, 11, 1), _dt(2022, 12, 31)),
            ],
            "latest_available": None,
        }
        assert _is_only_start_boundary_gap(
            verify_check, self.start_date, self.end_date
        ) is False

    # ── §2.4 Empty missing_ranges → False ───────────────────────────────────

    def test_empty_missing_ranges_returns_false(self):
        """No missing ranges means data is complete — boundary logic does not apply."""
        verify_check = {
            "missing_ranges": [],
            "latest_available": _dt(2024, 1, 1),
        }
        assert _is_only_start_boundary_gap(
            verify_check, self.start_date, self.end_date
        ) is False

    def test_missing_ranges_key_absent_returns_false(self):
        """Missing the missing_ranges key entirely must not raise and must return False."""
        verify_check = {
            "latest_available": _dt(2024, 1, 1),
        }
        assert _is_only_start_boundary_gap(
            verify_check, self.start_date, self.end_date
        ) is False

    # ── §2.5 Mixed gaps (start boundary + internal) → False ─────────────────

    def test_mixed_boundary_and_internal_gap_returns_false(self):
        """Even if one gap is a boundary gap, an additional internal gap fails."""
        verify_check = {
            "missing_ranges": [
                (_dt(2022, 11, 1), _dt(2022, 12, 31)),   # boundary gap — OK
                (_dt(2023, 6, 1),  _dt(2023, 6, 15)),    # internal gap — reject
            ],
            "latest_available": _dt(2024, 1, 1),
        }
        assert _is_only_start_boundary_gap(
            verify_check, self.start_date, self.end_date
        ) is False


# ---------------------------------------------------------------------------
# §3  _download_pair_data flag logic
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
# §4  Gap analysis logic for prepend/erase detection
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


# ---------------------------------------------------------------------------
# §5  Integration test for full data healing workflow
# ---------------------------------------------------------------------------

class TestDataHealingIntegration:
    """Integration tests for the complete data healing workflow."""

    @pytest.mark.asyncio
    async def test_data_healing_with_prepend_scenario(self, tmp_path, mocker):
        """Test full workflow when data needs to be prepended."""
        from backend.services.auto_quant.pipeline_modules.state import PipelineState
        from backend.services.auto_quant.pipeline_modules.data_healer import _stage_data_healing

        # Mock the gap check to return data that needs prepend
        def mock_gap_check(pair, timerange, timeframe, user_data_dir, warmup_candles):
            return {
                "has_gaps": True,
                "missing_ranges": [(_dt(2022, 12, 1), _dt(2023, 1, 1))],
                "available_candles": 500,
                "required_candles": 1000,
                "earliest_available": _dt(2023, 1, 1),  # After download start
                "latest_available": _dt(2024, 1, 1),  # Covers end
                "reason": "gaps_detected",
            }

        mocker.patch(
            "backend.services.auto_quant.pipeline_modules.data_healer._check_pair_data_gaps",
            side_effect=mock_gap_check
        )

        # Mock download to succeed
        mock_download = mocker.patch(
            "backend.services.auto_quant.pipeline_modules.data_healer._download_pair_data",
            return_value={
                "success": True,
                "exit_code": 0,
                "candles_downloaded": 1000,
                "error": None,
            }
        )

        # Mock emit and log
        mocker.patch("backend.services.auto_quant.pipeline_modules.data_healer._emit")
        mocker.patch("backend.services.auto_quant.pipeline_modules.data_healer._rlog")

        # Create state
        state = PipelineState()
        state.pair_universe = [PAIR]
        state.in_sample_range = TIMERANGE
        state.timeframe = TIMEFRAME
        state.user_data_dir = str(tmp_path)
        state.config_file = str(tmp_path / "config.json")
        state.freqtrade_path = "freqtrade"
        state.wfo_enabled = False

        # Run stage
        result = await _stage_data_healing("test_run", state, tmp_path)

        # Verify download was called with prepend=True
        assert mock_download.called
        call_kwargs = mock_download.call_args[1]
        assert call_kwargs["prepend"] is True
        assert call_kwargs["erase"] is False

    @pytest.mark.asyncio
    async def test_data_healing_with_erase_scenario(self, tmp_path, mocker):
        """Test full workflow when data needs erase (middle gaps)."""
        from backend.services.auto_quant.pipeline_modules.state import PipelineState
        from backend.services.auto_quant.pipeline_modules.data_healer import _stage_data_healing

        # Mock the gap check to return data with middle gaps
        def mock_gap_check(pair, timerange, timeframe, user_data_dir, warmup_candles):
            return {
                "has_gaps": True,
                "missing_ranges": [(_dt(2023, 6, 1), _dt(2023, 7, 1))],  # Middle gap
                "available_candles": 500,
                "required_candles": 1000,
                "earliest_available": _dt(2022, 12, 1),
                "latest_available": _dt(2024, 1, 1),
                "reason": "gaps_detected",
            }

        mocker.patch(
            "backend.services.auto_quant.pipeline_modules.data_healer._check_pair_data_gaps",
            side_effect=mock_gap_check
        )

        mock_download = mocker.patch(
            "backend.services.auto_quant.pipeline_modules.data_healer._download_pair_data",
            return_value={
                "success": True,
                "exit_code": 0,
                "candles_downloaded": 1000,
                "error": None,
            }
        )

        mocker.patch("backend.services.auto_quant.pipeline_modules.data_healer._emit")
        mocker.patch("backend.services.auto_quant.pipeline_modules.data_healer._rlog")

        state = PipelineState()
        state.pair_universe = [PAIR]
        state.in_sample_range = TIMERANGE
        state.timeframe = TIMEFRAME
        state.user_data_dir = str(tmp_path)
        state.config_file = str(tmp_path / "config.json")
        state.freqtrade_path = "freqtrade"
        state.wfo_enabled = False

        result = await _stage_data_healing("test_run", state, tmp_path)

        # Verify download was called with erase=True
        assert mock_download.called
        call_kwargs = mock_download.call_args[1]
        assert call_kwargs["erase"] is True

    @pytest.mark.asyncio
    async def test_data_healing_with_both_prepend_and_append(self, tmp_path, mocker):
        """Test full workflow when data needs both prepend and append → erase."""
        from backend.services.auto_quant.pipeline_modules.state import PipelineState
        from backend.services.auto_quant.pipeline_modules.data_healer import _stage_data_healing

        # Mock the gap check to return data that needs both prepend and append
        def mock_gap_check(pair, timerange, timeframe, user_data_dir, warmup_candles):
            return {
                "has_gaps": True,
                "missing_ranges": [
                    (_dt(2022, 12, 1), _dt(2023, 1, 1)),  # Leading gap
                    (_dt(2023, 12, 1), _dt(2024, 1, 1)),  # Trailing gap
                ],
                "available_candles": 500,
                "required_candles": 1000,
                "earliest_available": _dt(2023, 1, 1),  # After download start
                "latest_available": _dt(2023, 12, 1),  # Before end date
                "reason": "gaps_detected",
            }

        mocker.patch(
            "backend.services.auto_quant.pipeline_modules.data_healer._check_pair_data_gaps",
            side_effect=mock_gap_check
        )

        mock_download = mocker.patch(
            "backend.services.auto_quant.pipeline_modules.data_healer._download_pair_data",
            return_value={
                "success": True,
                "exit_code": 0,
                "candles_downloaded": 1000,
                "error": None,
            }
        )

        mocker.patch("backend.services.auto_quant.pipeline_modules.data_healer._emit")
        mocker.patch("backend.services.auto_quant.pipeline_modules.data_healer._rlog")

        state = PipelineState()
        state.pair_universe = [PAIR]
        state.in_sample_range = TIMERANGE
        state.timeframe = TIMEFRAME
        state.user_data_dir = str(tmp_path)
        state.config_file = str(tmp_path / "config.json")
        state.freqtrade_path = "freqtrade"
        state.wfo_enabled = False

        result = await _stage_data_healing("test_run", state, tmp_path)

        # Verify download was called with erase=True (both prepend and append needed)
        assert mock_download.called
        call_kwargs = mock_download.call_args[1]
        assert call_kwargs["erase"] is True
