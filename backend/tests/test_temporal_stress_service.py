"""Unit tests for temporal stress service module."""

from datetime import date
from pathlib import Path
import tempfile
import json

from backend.services.stress.temporal_stress_service import (
    parse_date,
    fmt_date,
    split_timerange,
    generate_time_split_segments,
    generate_monte_carlo_segments,
    generate_crash_gauntlet_segments,
    extract_segment_metrics,
    consistency_score,
)


def test_parse_date():
    """Test parse_date with valid YYYYMMDD format."""
    result = parse_date("20240101")
    assert result == date(2024, 1, 1)


def test_fmt_date():
    """Test fmt_date with date object."""
    d = date(2024, 1, 1)
    result = fmt_date(d)
    assert result == "20240101"


def test_split_timerange_valid():
    """Test split_timerange with valid format."""
    start, end = split_timerange("20240101-20240131")
    assert start == date(2024, 1, 1)
    assert end == date(2024, 1, 31)


def test_split_timerange_invalid_format():
    """Test split_timerange with invalid format."""
    try:
        split_timerange("2024-01-01")
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "YYYYMMDD-YYYYMMDD" in str(e)


def test_split_timerange_invalid_length():
    """Test split_timerange with invalid date length."""
    try:
        split_timerange("202401-20240131")
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "YYYYMMDD-YYYYMMDD" in str(e)


def test_generate_time_split_segments():
    """Test generate_time_split_segments."""
    segments = generate_time_split_segments("20240101-20240131", 4)
    assert len(segments) == 4
    assert segments[0]["label"] == "Segment 1"
    assert segments[0]["start"] == "20240101"
    assert segments[-1]["label"] == "Segment 4"
    assert segments[-1]["end"] == "20240131"


def test_generate_time_split_segments_too_short():
    """Test generate_time_split_segments with too short timerange."""
    try:
        generate_time_split_segments("20240101-20240102", 4)
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "too short" in str(e)


def test_generate_monte_carlo_segments():
    """Test generate_monte_carlo_segments."""
    segments = generate_monte_carlo_segments("20240101-20240131", 5, 7)
    assert len(segments) == 5
    assert segments[0]["label"] == "Random Window 1"
    assert segments[0]["description"] == "7-day random sample"
    assert segments[-1]["label"] == "Random Window 5"


def test_generate_monte_carlo_segments_too_short():
    """Test generate_monte_carlo_segments with timerange shorter than window."""
    try:
        generate_monte_carlo_segments("20240101-20240105", 5, 7)
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "shorter than window length" in str(e)


def test_generate_crash_gauntlet_segments():
    """Test generate_crash_gauntlet_segments."""
    segments = generate_crash_gauntlet_segments()
    assert len(segments) == 6
    assert segments[0]["label"] == "COVID Crash"
    assert segments[0]["start"] == "20200215"
    assert segments[0]["end"] == "20200331"
    assert segments[-1]["label"] == "FTX Collapse"


def test_extract_segment_metrics_no_file():
    """Test extract_segment_metrics with missing file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        result = extract_segment_metrics(run_dir, "TestStrategy")
        assert result == {}


def test_extract_segment_metrics_invalid_json():
    """Test extract_segment_metrics with invalid JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        raw_path = run_dir / "raw_result.json"
        raw_path.write_text("{invalid json", encoding="utf-8")
        
        result = extract_segment_metrics(run_dir, "TestStrategy")
        assert result == {}


def test_extract_segment_metrics_valid_data():
    """Test extract_segment_metrics with valid data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        raw_path = run_dir / "raw_result.json"
        
        data = {
            "profit_total": 0.05,
            "total_trades": 3,  # Match the actual number of trades in the list
            "trades": [
                {"profit_ratio": 0.01},
                {"profit_ratio": 0.02},
                {"profit_ratio": -0.01},
            ],
            "max_drawdown": -0.10,
        }
        raw_path.write_text(json.dumps(data), encoding="utf-8")
        
        result = extract_segment_metrics(run_dir, "TestStrategy")
        assert result["net_profit_pct"] == 5.0
        assert result["total_trades"] == 3
        # Win rate is 2 wins out of 3 trades = 66.67%
        assert result["win_rate_pct"] == 66.67
        assert result["max_drawdown_pct"] == -0.10


def test_consistency_score_no_finished():
    """Test consistency_score with no finished segments."""
    results = [
        {"status": "running"},
        {"status": "queued"},
    ]
    result = consistency_score(results)
    assert result == 0.0


def test_consistency_score_all_profitable():
    """Test consistency_score with all profitable segments."""
    results = [
        {"status": "profitable"},
        {"status": "profitable"},
        {"status": "profitable"},
    ]
    result = consistency_score(results)
    assert result == 100.0


def test_consistency_score_mixed():
    """Test consistency_score with mixed results."""
    results = [
        {"status": "profitable"},
        {"status": "loss"},
        {"status": "profitable"},
        {"status": "loss"},
    ]
    result = consistency_score(results)
    assert result == 50.0


def test_consistency_score_all_loss():
    """Test consistency_score with all loss segments."""
    results = [
        {"status": "loss"},
        {"status": "loss"},
        {"status": "loss"},
    ]
    result = consistency_score(results)
    assert result == 0.0
