"""Data quality gate for validating market data before backtests."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from ...utils import get_data_file_path, detect_data_file_format

VALID_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}

# Expected candle durations in seconds
TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def _parse_timerange_bounds(timerange: str) -> tuple[datetime | None, datetime | None, list[str]]:
    warnings: list[str] = []
    start_date = None
    end_date = None

    parts = str(timerange or "").split("-", maxsplit=1)
    start_str = parts[0] if parts else ""
    end_str = parts[1] if len(parts) > 1 else ""

    if len(start_str) == 8:
        try:
            start_date = datetime.strptime(start_str, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            warnings.append(f"Could not parse timerange start date: {start_str}")
    elif start_str:
        warnings.append(f"Could not parse timerange start date: {start_str}")

    if len(end_str) == 8:
        try:
            end_date = datetime.strptime(end_str, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            warnings.append(f"Could not parse timerange end date: {end_str}")
    elif end_str:
        warnings.append(f"Could not parse timerange end date: {end_str}")

    return start_date, end_date, warnings


def _coerce_timestamp_ms(value: Any) -> int:
    timestamp = int(value)
    abs_timestamp = abs(timestamp)
    if abs_timestamp > 10**14:
        return timestamp // 1_000_000
    if abs_timestamp > 10**11:
        return timestamp
    return timestamp * 1000


def _timestamp_ms_to_datetime(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


def _date_label(value: datetime) -> str:
    return value.strftime("%Y%m%d")


def check_data_quality(
    pairs: list[str],
    timeframe: str,
    timerange: str,
    user_data_dir: str,
    exchange: str = "binance",
) -> dict:
    """Validate market data quality before backtest execution.

    Args:
        pairs: List of trading pairs (e.g., ["BTC/USDT", "ETH/USDT"])
        timeframe: Candle timeframe (e.g., "5m", "1h")
        timerange: Date range in Freqtrade format (e.g., "20240101-20240131")
        user_data_dir: Path to user_data directory
        exchange: Exchange name (default: "binance")

    Returns:
        dict with keys:
            - passed: bool - overall pass/fail status
            - errors: list[str] - error codes and messages
            - warnings: list[str] - warning messages
            - details: dict - per-pair validation results
    """
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, dict[str, Any]] = {}

    # Check 3: Timeframe is available
    if timeframe not in VALID_TIMEFRAMES:
        errors.append(f"INVALID_TIMEFRAME: '{timeframe}' is not a valid timeframe")
        return {
            "passed": False,
            "errors": errors,
            "warnings": warnings,
            "details": details,
        }

    required_start_date, required_end_date, timerange_warnings = _parse_timerange_bounds(timerange)
    warnings.extend(timerange_warnings)

    for pair in pairs:
        pair_details: dict[str, Any] = {}
        
        # Detect the file format
        data_format = detect_data_file_format(user_data_dir, pair, timeframe, exchange)
        data_file = get_data_file_path(user_data_dir, pair, timeframe, exchange, data_format)
        pair_details["data_file"] = str(data_file)
        pair_details["timeframe"] = timeframe

        # Check 1: Data file exists
        if not data_file.exists():
            errors.append(f"MISSING_DATA_FILE: {pair} - file does not exist at {data_file}")
            pair_details["exists"] = False
            details[pair] = pair_details
            continue

        pair_details["exists"] = True
        pair_details["format"] = data_format

        # Check 6: File is readable (JSON or Feather)
        try:
            if data_format == "feather":
                # Read feather file using pandas
                import pandas as pd
                df = pd.read_feather(data_file)
                
                # Convert feather DataFrame to the expected list format
                # Feather schema: date (datetime64[ms, UTC]), open, high, low, close, volume
                # Convert to: [[timestamp_ms, open, high, low, close, volume], ...]
                if df.empty:
                    errors.append(f"CORRUPT_DATA_FILE: {pair} - empty data file")
                    pair_details["readable"] = False
                    details[pair] = pair_details
                    continue
                
                # Normalize date column to handle different datetime formats
                if pd.api.types.is_integer_dtype(df["date"]):
                    # int64 ms since epoch
                    timestamps = [_coerce_timestamp_ms(value) for value in df["date"].tolist()]
                else:
                    dates = pd.to_datetime(df["date"], utc=True, errors="coerce")
                    if dates.isna().any():
                        raise ValueError("date column contains invalid timestamps")
                    timestamps = [int(value.value // 1_000_000) for value in dates]
                
                # Build the expected format: [[timestamp_ms, open, high, low, close, volume], ...]
                raw_data = [
                    [int(ts), row["open"], row["high"], row["low"], row["close"], row["volume"]]
                    for ts, (_, row) in zip(timestamps, df.iterrows())
                ]
            else:
                # Read JSON file (original format)
                raw_json = json.loads(data_file.read_text(encoding="utf-8"))
                raw_data = [
                    [_coerce_timestamp_ms(candle[0]), *candle[1:]]
                    for candle in raw_json
                ]
                
        except json.JSONDecodeError as e:
            errors.append(f"CORRUPT_DATA_FILE: {pair} - invalid JSON: {e}")
            pair_details["readable"] = False
            details[pair] = pair_details
            continue
        except Exception as e:
            errors.append(f"CORRUPT_DATA_FILE: {pair} - read error: {e}")
            pair_details["readable"] = False
            details[pair] = pair_details
            continue

        if not raw_data or not isinstance(raw_data, list):
            errors.append(f"CORRUPT_DATA_FILE: {pair} - empty or invalid data format")
            pair_details["readable"] = False
            details[pair] = pair_details
            continue

        pair_details["readable"] = True
        pair_details["candle_count"] = len(raw_data)

        # Check 2: Enough history for timerange
        if required_start_date or required_end_date:
            try:
                first_ts_ms = raw_data[0][0]
                last_ts_ms = raw_data[-1][0]
                first_date = _timestamp_ms_to_datetime(first_ts_ms)
                last_date = _timestamp_ms_to_datetime(last_ts_ms)
                pair_details["start_date"] = _date_label(first_date)
                pair_details["end_date"] = _date_label(last_date)
                coverage_failed = False

                if required_start_date and first_date > required_start_date:
                    errors.append(
                        f"INSUFFICIENT_HISTORY: {pair} - data starts at {_date_label(first_date)}, "
                        f"required {_date_label(required_start_date)}"
                    )
                    coverage_failed = True

                if required_end_date and last_date < required_end_date:
                    errors.append(
                        f"INSUFFICIENT_HISTORY: {pair} - data ends at {_date_label(last_date)}, "
                        f"required {_date_label(required_end_date)}"
                    )
                    coverage_failed = True

                pair_details["covers_timerange"] = not coverage_failed
            except (IndexError, TypeError, ValueError) as e:
                warnings.append(f"Could not verify timerange coverage for {pair}: {e}")
                pair_details["covers_timerange"] = None
        else:
            pair_details["covers_timerange"] = None

        # Check 4: No critical candle gaps
        gap_pct = _calculate_gap_percentage(raw_data, timeframe)
        pair_details["gap_pct"] = gap_pct

        if gap_pct > 0.10:  # More than 10% gaps
            errors.append(f"CRITICAL_CANDLE_GAPS: {pair} - {gap_pct:.1%} of candles have critical gaps")
            pair_details["critical_gaps"] = True
        else:
            pair_details["critical_gaps"] = False

        # Check 5: Pair format is valid
        if not _is_valid_pair_format(pair, exchange):
            errors.append(f"INVALID_PAIR_FORMAT: {pair} - format does not match exchange pattern")
            pair_details["valid_format"] = False
        else:
            pair_details["valid_format"] = True

        details[pair] = pair_details

    passed = len(errors) == 0

    return {
        "passed": passed,
        "errors": errors,
        "warnings": warnings,
        "details": details,
    }


def _calculate_gap_percentage(data: list[list], timeframe: str) -> float:
    """Calculate percentage of candles with critical gaps.

    A gap is critical if it exceeds 5x the expected candle duration.
    """
    if len(data) < 2:
        return 0.0

    expected_duration = TIMEFRAME_SECONDS.get(timeframe, 300)  # Default to 5m
    critical_threshold = expected_duration * 5

    gap_count = 0
    for i in range(1, len(data)):
        prev_ts = data[i - 1][0] / 1000  # Convert ms to seconds
        curr_ts = data[i][0] / 1000
        gap = curr_ts - prev_ts

        if gap > critical_threshold:
            gap_count += 1

    return gap_count / len(data)


def _is_valid_pair_format(pair: str, exchange: str) -> bool:
    """Validate pair format matches exchange pattern.

    Binance uses BTC/USDT or BTC_USDT format.
    """
    if exchange.lower() == "binance":
        # Accept BTC/USDT, BTC/USDT:USDT, BTC_USDT, and BTC_USDT_USDT formats.
        symbol = pair
        if ":" in pair:
            symbol, settlement = pair.split(":", maxsplit=1)
            if not settlement.isalnum():
                return False
        if "/" in symbol:
            parts = symbol.split("/")
            return len(parts) == 2 and all(part.isalnum() for part in parts)
        elif "_" in symbol:
            parts = symbol.split("_")
            return len(parts) in {2, 3} and all(part.isalnum() for part in parts)
        else:
            return False

    # For other exchanges, be lenient - just check it's not empty and has reasonable chars
    return bool(pair) and len(pair) >= 3
