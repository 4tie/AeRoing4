"""Tests for data quality gate."""

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd

from backend.services.execution.data_quality_gate import check_data_quality


def _create_test_data_file(tmp_path: Path, pair: str, timeframe: str, data: list) -> Path:
    """Helper to create a test data file."""
    exchange_dir = tmp_path / "data" / "binance"
    exchange_dir.mkdir(parents=True, exist_ok=True)
    
    pair_filename = pair.replace("/", "_")
    data_file = exchange_dir / f"{pair_filename}-{timeframe}.json"
    
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    
    return data_file


def _create_feather_test_data_file(tmp_path: Path, pair: str, timeframe: str, data: list) -> Path:
    """Helper to create a test feather data file."""
    exchange_dir = tmp_path / "data" / "binance"
    exchange_dir.mkdir(parents=True, exist_ok=True)
    
    pair_filename = pair.replace("/", "_")
    data_file = exchange_dir / f"{pair_filename}-{timeframe}.feather"
    
    # Convert the list format to DataFrame format
    # data is [[timestamp_ms, open, high, low, close, volume], ...]
    df_data = {
        "date": pd.to_datetime([candle[0] for candle in data], unit="ms", utc=True),
        "open": [candle[1] for candle in data],
        "high": [candle[2] for candle in data],
        "low": [candle[3] for candle in data],
        "close": [candle[4] for candle in data],
        "volume": [candle[5] for candle in data],
    }
    
    df = pd.DataFrame(df_data)
    df.to_feather(data_file)
    
    return data_file


def _generate_normal_candles(count: int, timeframe: str = "5m") -> list:
    """Generate normal candle data without gaps."""
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    timeframe_seconds = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
    }.get(timeframe, 300)
    
    candles = []
    for i in range(count):
        ts = int((base_time + timedelta(seconds=i * timeframe_seconds)).timestamp() * 1000)
        candles.append([ts, 50000.0 + i, 50010.0 + i, 49990.0 + i, 50005.0 + i, 100.0])
    
    return candles


def _generate_candles_with_gaps(count: int, timeframe: str = "5m", gap_ratio: float = 0.2) -> list:
    """Generate candle data with gaps."""
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    timeframe_seconds = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
    }.get(timeframe, 300)
    
    critical_threshold = timeframe_seconds * 5
    candles = []
    
    for i in range(count):
        # Add gap for some candles
        if i % int(1 / gap_ratio) == 0 and i > 0:
            gap = critical_threshold + 60  # Exceed critical threshold
        else:
            gap = timeframe_seconds
        
        if i == 0:
            ts = int(base_time.timestamp() * 1000)
        else:
            ts = candles[-1][0] + int(gap * 1000)
        
        candles.append([ts, 50000.0 + i, 50010.0 + i, 49990.0 + i, 50005.0 + i, 100.0])
    
    return candles


def test_data_file_exists(tmp_path):
    """Existing file passes check."""
    data = _generate_normal_candles(10000)  # Generate enough data to cover timerange
    _create_test_data_file(tmp_path, "BTC/USDT", "5m", data)
    
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is True
    assert result["errors"] == []
    assert result["details"]["BTC/USDT"]["exists"] is True


def test_missing_data_file_fails(tmp_path):
    """Missing file returns MISSING_DATA_FILE error."""
    # Don't create any data file
    
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is False
    assert len(result["errors"]) == 1
    assert "MISSING_DATA_FILE" in result["errors"][0]
    assert "BTC/USDT" in result["errors"][0]
    assert result["details"]["BTC/USDT"]["data_file"].endswith("BTC_USDT-5m.json")


def test_timerange_coverage_pass(tmp_path):
    """Data covers full timerange."""
    # Generate data through end of January
    data = _generate_normal_candles(10000, "5m")  # ~35 days of 5m candles
    _create_test_data_file(tmp_path, "BTC/USDT", "5m", data)
    
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is True
    assert result["details"]["BTC/USDT"]["covers_timerange"] is True


def test_insufficient_history_fails(tmp_path):
    """Data ends before timerange end."""
    # Generate only 1 day of data
    data = _generate_normal_candles(288, "5m")  # 1 day of 5m candles
    _create_test_data_file(tmp_path, "BTC/USDT", "5m", data)
    
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is False
    assert len(result["errors"]) == 1
    assert "INSUFFICIENT_HISTORY" in result["errors"][0]
    assert result["details"]["BTC/USDT"]["covers_timerange"] is False
    assert result["details"]["BTC/USDT"]["start_date"] == "20240101"
    assert result["details"]["BTC/USDT"]["end_date"] == "20240101"


def test_data_start_after_timerange_start_fails(tmp_path):
    """Data starting after timerange start is rejected before backtesting."""
    one_day_ms = 24 * 60 * 60 * 1000
    data = [
        [candle[0] + one_day_ms, *candle[1:]]
        for candle in _generate_normal_candles(1000, "5m")
    ]
    _create_test_data_file(tmp_path, "BTC/USDT", "5m", data)

    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240103",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )

    assert result["passed"] is False
    assert len(result["errors"]) == 1
    assert "INSUFFICIENT_HISTORY" in result["errors"][0]
    assert "data starts at 20240102" in result["errors"][0]
    assert result["details"]["BTC/USDT"]["covers_timerange"] is False


def test_valid_timeframe_pass(tmp_path):
    """Valid timeframe passes."""
    data = _generate_normal_candles(1000, "1h")  # Generate enough data to cover timerange
    _create_test_data_file(tmp_path, "BTC/USDT", "1h", data)
    
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="1h",
        timerange="20240101-20240105",  # Shorter timerange to match generated data
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is True


def test_invalid_timeframe_fails(tmp_path):
    """Invalid timeframe returns error."""
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="3m",  # Invalid timeframe
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is False
    assert len(result["errors"]) == 1
    assert "INVALID_TIMEFRAME" in result["errors"][0]
    assert "3m" in result["errors"][0]


def test_no_critical_gaps_pass(tmp_path):
    """Normal data with minor gaps passes."""
    # Generate data with normal spacing (no critical gaps)
    data = _generate_normal_candles(10000, "5m")
    _create_test_data_file(tmp_path, "BTC/USDT", "5m", data)
    
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is True
    assert result["details"]["BTC/USDT"]["critical_gaps"] is False
    assert result["details"]["BTC/USDT"]["gap_pct"] < 0.10


def test_critical_gaps_fail(tmp_path):
    """>10% gap rate returns CRITICAL_CANDLE_GAPS."""
    # Generate data with 20% gaps (exceeds 10% threshold)
    data = _generate_candles_with_gaps(10000, "5m", gap_ratio=0.2)
    _create_test_data_file(tmp_path, "BTC/USDT", "5m", data)
    
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is False
    assert len(result["errors"]) == 1
    assert "CRITICAL_CANDLE_GAPS" in result["errors"][0]
    assert result["details"]["BTC/USDT"]["critical_gaps"] is True
    assert result["details"]["BTC/USDT"]["gap_pct"] > 0.10


def test_valid_pair_format_pass(tmp_path):
    """Correctly formatted pair passes."""
    data = _generate_normal_candles(10000)
    _create_test_data_file(tmp_path, "BTC/USDT", "5m", data)
    
    # Test slash format
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    assert result["passed"] is True
    assert result["details"]["BTC/USDT"]["valid_format"] is True
    
    # Test underscore format
    data_file = tmp_path / "data" / "binance" / "BTC_USDT-5m.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")
    
    result = check_data_quality(
        pairs=["BTC_USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    assert result["passed"] is True
    assert result["details"]["BTC_USDT"]["valid_format"] is True


def test_invalid_pair_format_fails(tmp_path):
    """Malformed pair returns INVALID_PAIR_FORMAT."""
    data = _generate_normal_candles(10000)
    _create_test_data_file(tmp_path, "BTC-USDT", "5m", data)  # Invalid format
    
    result = check_data_quality(
        pairs=["BTC-USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is False
    assert len(result["errors"]) == 1
    assert "INVALID_PAIR_FORMAT" in result["errors"][0]
    assert result["details"]["BTC-USDT"]["valid_format"] is False


def test_corrupt_json_fails(tmp_path):
    """Malformed JSON returns CORRUPT_DATA_FILE."""
    exchange_dir = tmp_path / "data" / "binance"
    exchange_dir.mkdir(parents=True, exist_ok=True)
    
    data_file = exchange_dir / "BTC_USDT-5m.json"
    data_file.write_text("{ invalid json", encoding="utf-8")
    
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is False
    assert len(result["errors"]) == 1
    assert "CORRUPT_DATA_FILE" in result["errors"][0]
    assert result["details"]["BTC/USDT"]["readable"] is False


def test_empty_json_fails(tmp_path):
    """Empty array returns CORRUPT_DATA_FILE."""
    exchange_dir = tmp_path / "data" / "binance"
    exchange_dir.mkdir(parents=True, exist_ok=True)
    
    data_file = exchange_dir / "BTC_USDT-5m.json"
    data_file.write_text("[]", encoding="utf-8")
    
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is False
    assert len(result["errors"]) == 1
    assert "CORRUPT_DATA_FILE" in result["errors"][0]
    assert result["details"]["BTC/USDT"]["readable"] is False


# ---------------------------------------------------------------------------
# Feather format tests
# ---------------------------------------------------------------------------

def test_feather_file_exists_pass(tmp_path):
    """Existing feather file passes check."""
    data = _generate_normal_candles(10000)  # Generate enough data to cover timerange
    _create_feather_test_data_file(tmp_path, "BTC/USDT", "5m", data)
    
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is True
    assert result["errors"] == []
    assert result["details"]["BTC/USDT"]["exists"] is True
    assert result["details"]["BTC/USDT"]["format"] == "feather"


def test_feather_missing_data_file_fails(tmp_path):
    """Missing feather file returns MISSING_DATA_FILE error (falls back to JSON)."""
    # Don't create any data file
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is False
    assert len(result["errors"]) == 1
    assert "MISSING_DATA_FILE" in result["errors"][0]
    assert "BTC/USDT" in result["errors"][0]


def test_feather_timerange_coverage_pass(tmp_path):
    """Feather data covers full timerange."""
    # Generate data through end of January
    data = _generate_normal_candles(10000, "5m")  # ~35 days of 5m candles
    _create_feather_test_data_file(tmp_path, "BTC/USDT", "5m", data)
    
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is True
    assert result["details"]["BTC/USDT"]["covers_timerange"] is True


def test_feather_insufficient_history_fails(tmp_path):
    """Feather data ends before timerange end."""
    # Generate only 1 day of data
    data = _generate_normal_candles(288, "5m")  # 1 day of 5m candles
    _create_feather_test_data_file(tmp_path, "BTC/USDT", "5m", data)
    
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is False
    assert len(result["errors"]) == 1
    assert "INSUFFICIENT_HISTORY" in result["errors"][0]
    assert result["details"]["BTC/USDT"]["covers_timerange"] is False


def test_feather_no_critical_gaps_pass(tmp_path):
    """Feather data with normal spacing passes."""
    data = _generate_normal_candles(10000, "5m")
    _create_feather_test_data_file(tmp_path, "BTC/USDT", "5m", data)
    
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is True
    assert result["details"]["BTC/USDT"]["critical_gaps"] is False
    assert result["details"]["BTC/USDT"]["gap_pct"] < 0.10


def test_feather_critical_gaps_fail(tmp_path):
    """Feather data with >10% gap rate returns CRITICAL_CANDLE_GAPS."""
    data = _generate_candles_with_gaps(10000, "5m", gap_ratio=0.2)
    _create_feather_test_data_file(tmp_path, "BTC/USDT", "5m", data)
    
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is False
    assert len(result["errors"]) == 1
    assert "CRITICAL_CANDLE_GAPS" in result["errors"][0]
    assert result["details"]["BTC/USDT"]["critical_gaps"] is True
    assert result["details"]["BTC/USDT"]["gap_pct"] > 0.10


def test_feather_empty_data_fails(tmp_path):
    """Empty feather file returns CORRUPT_DATA_FILE."""
    exchange_dir = tmp_path / "data" / "binance"
    exchange_dir.mkdir(parents=True, exist_ok=True)
    
    data_file = exchange_dir / "BTC_USDT-5m.feather"
    # Write an empty DataFrame with the correct schema
    df = pd.DataFrame(
        columns=["date", "open", "high", "low", "close", "volume"]
    ).astype({"date": "datetime64[ns, UTC]"})
    df.to_feather(data_file)
    
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is False
    assert len(result["errors"]) == 1
    assert "CORRUPT_DATA_FILE" in result["errors"][0]
    assert result["details"]["BTC/USDT"]["readable"] is False


def test_format_detection_prefers_feather(tmp_path):
    """When both formats exist, feather is preferred."""
    data = _generate_normal_candles(10000, "5m")
    # Create both JSON and feather files
    _create_test_data_file(tmp_path, "BTC/USDT", "5m", data)
    _create_feather_test_data_file(tmp_path, "BTC/USDT", "5m", data)
    
    result = check_data_quality(
        pairs=["BTC/USDT"],
        timeframe="5m",
        timerange="20240101-20240131",
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    
    assert result["passed"] is True
    assert result["details"]["BTC/USDT"]["format"] == "feather"
