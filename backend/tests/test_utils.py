"""Tests for backend utility functions."""

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

from backend.utils import get_data_file_path, detect_data_file_format


def test_get_data_file_path_json_format():
    """Test get_data_file_path with default JSON format."""
    result = get_data_file_path("/tmp/user_data", "BTC/USDT", "5m", "binance")
    expected = Path("/tmp/user_data/data/binance/BTC_USDT-5m.json")
    assert result == expected


def test_get_data_file_path_feather_format():
    """Test get_data_file_path with feather format."""
    result = get_data_file_path("/tmp/user_data", "BTC/USDT", "5m", "binance", "feather")
    expected = Path("/tmp/user_data/data/binance/BTC_USDT-5m.feather")
    assert result == expected


def test_get_data_file_path_pair_normalization():
    """Test that pair names are normalized (slashes to underscores)."""
    result = get_data_file_path("/tmp/user_data", "BTC/USDT", "5m", "binance")
    assert "BTC_USDT" in str(result)


def test_get_data_file_path_futures_pair_normalization():
    """Test that futures settlement suffixes are normalized for filenames."""
    result = get_data_file_path("/tmp/user_data", "BTC/USDT:USDT", "5m", "binance")
    expected = Path("/tmp/user_data/data/binance/BTC_USDT_USDT-5m.json")
    assert result == expected


def test_detect_data_file_format_prefers_feather(tmp_path):
    """Test that detect_data_file_format prefers feather over JSON."""
    # Create both JSON and feather files
    exchange_dir = tmp_path / "data" / "binance"
    exchange_dir.mkdir(parents=True, exist_ok=True)
    
    # Create JSON file
    json_file = exchange_dir / "BTC_USDT-5m.json"
    json_file.write_text("[]", encoding="utf-8")
    
    # Create feather file
    feather_file = exchange_dir / "BTC_USDT-5m.feather"
    df = pd.DataFrame(
        columns=["date", "open", "high", "low", "close", "volume"]
    ).astype({"date": "datetime64[ns, UTC]"})
    df.to_feather(feather_file)
    
    # Should detect feather (preferred format)
    result = detect_data_file_format(str(tmp_path), "BTC/USDT", "5m", "binance")
    assert result == "feather"


def test_detect_data_file_format_json_only(tmp_path):
    """Test detection when only JSON file exists."""
    exchange_dir = tmp_path / "data" / "binance"
    exchange_dir.mkdir(parents=True, exist_ok=True)
    
    # Create only JSON file
    json_file = exchange_dir / "BTC_USDT-5m.json"
    json_file.write_text("[]", encoding="utf-8")
    
    result = detect_data_file_format(str(tmp_path), "BTC/USDT", "5m", "binance")
    assert result == "json"


def test_detect_data_file_format_feather_only(tmp_path):
    """Test detection when only feather file exists."""
    exchange_dir = tmp_path / "data" / "binance"
    exchange_dir.mkdir(parents=True, exist_ok=True)
    
    # Create only feather file
    feather_file = exchange_dir / "BTC_USDT-5m.feather"
    df = pd.DataFrame(
        columns=["date", "open", "high", "low", "close", "volume"]
    ).astype({"date": "datetime64[ns, UTC]"})
    df.to_feather(feather_file)
    
    result = detect_data_file_format(str(tmp_path), "BTC/USDT", "5m", "binance")
    assert result == "feather"


def test_detect_data_file_format_none_exists(tmp_path):
    """Test detection defaults to JSON when no files exist."""
    # Don't create any files
    result = detect_data_file_format(str(tmp_path), "BTC/USDT", "5m", "binance")
    assert result == "json"


def test_detect_data_file_format_different_exchange(tmp_path):
    """Test detection works with different exchange names."""
    exchange_dir = tmp_path / "data" / "kraken"
    exchange_dir.mkdir(parents=True, exist_ok=True)
    
    # Create JSON file for kraken
    json_file = exchange_dir / "BTC_USDT-5m.json"
    json_file.write_text("[]", encoding="utf-8")
    
    result = detect_data_file_format(str(tmp_path), "BTC/USDT", "5m", "kraken")
    assert result == "json"


def test_detect_data_file_format_futures_pair(tmp_path):
    """Test detection for Freqtrade futures pair filenames."""
    exchange_dir = tmp_path / "data" / "binance"
    exchange_dir.mkdir(parents=True, exist_ok=True)

    feather_file = exchange_dir / "BTC_USDT_USDT-5m.feather"
    df = pd.DataFrame(
        columns=["date", "open", "high", "low", "close", "volume"]
    ).astype({"date": "datetime64[ns, UTC]"})
    df.to_feather(feather_file)

    result = detect_data_file_format(str(tmp_path), "BTC/USDT:USDT", "5m", "binance")
    assert result == "feather"
