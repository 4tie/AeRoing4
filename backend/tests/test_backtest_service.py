"""Unit tests for backtest service module."""

from pathlib import Path
import tempfile
import py_compile

from backend.services.backtest.backtest_service import preflight_strategy, extract_freqtrade_error


def test_preflight_strategy_missing_file():
    """Test preflight_strategy with missing strategy file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        errors = preflight_strategy(tmpdir, "NonExistentStrategy")
        assert len(errors) == 1
        assert "Strategy file not found" in errors[0]


def test_preflight_strategy_syntax_error():
    """Test preflight_strategy with syntax error in strategy file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        strat_path = Path(tmpdir) / "TestStrategy.py"
        strat_path.write_text("def broken_syntax(\n", encoding="utf-8")
        
        errors = preflight_strategy(tmpdir, "TestStrategy")
        assert len(errors) == 1
        assert "Syntax error" in errors[0]


def test_preflight_strategy_valid_python():
    """Test preflight_strategy with valid Python file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        strat_path = Path(tmpdir) / "TestStrategy.py"
        strat_path.write_text("class TestStrategy:\n    pass\n", encoding="utf-8")
        
        errors = preflight_strategy(tmpdir, "TestStrategy")
        assert len(errors) == 0


def test_preflight_strategy_invalid_json():
    """Test preflight_strategy with invalid JSON companion file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        strat_path = Path(tmpdir) / "TestStrategy.py"
        strat_path.write_text("class TestStrategy:\n    pass\n", encoding="utf-8")
        
        json_path = Path(tmpdir) / "TestStrategy.json"
        json_path.write_text("{invalid json", encoding="utf-8")
        
        errors = preflight_strategy(tmpdir, "TestStrategy")
        assert len(errors) == 1
        assert "Invalid JSON" in errors[0]


def test_preflight_strategy_valid_json():
    """Test preflight_strategy with valid JSON companion file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        strat_path = Path(tmpdir) / "TestStrategy.py"
        strat_path.write_text("class TestStrategy:\n    pass\n", encoding="utf-8")
        
        json_path = Path(tmpdir) / "TestStrategy.json"
        json_path.write_text('{"key": "value"}', encoding="utf-8")
        
        errors = preflight_strategy(tmpdir, "TestStrategy")
        assert len(errors) == 0


def test_extract_freqtrade_error_no_log_file():
    """Test extract_freqtrade_error when log file doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        result = extract_freqtrade_error(run_dir)
        assert result is None


def test_extract_freqtrade_error_no_error_lines():
    """Test extract_freqtrade_error when log has no ERROR lines."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        log_path = run_dir / "logs.txt"
        log_path.write_text("INFO - Some info message\nDEBUG - Debug message\n", encoding="utf-8")
        
        result = extract_freqtrade_error(run_dir)
        assert result is None


def test_extract_freqtrade_error_with_error():
    """Test extract_freqtrade_error when log has ERROR line."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        log_path = run_dir / "logs.txt"
        log_path.write_text("INFO - Some info\n2024-01-01 10:00:00 - ERROR - Test error message\n", encoding="utf-8")
        
        result = extract_freqtrade_error(run_dir)
        assert result == "Test error message"


def test_extract_freqtrade_error_alternative_format():
    """Test extract_freqtrade_error with alternative ERROR format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        log_path = run_dir / "logs.txt"
        log_path.write_text("ERROR - Alternative error format\n", encoding="utf-8")
        
        result = extract_freqtrade_error(run_dir)
        # The function only strips " - ERROR - " prefix, not "ERROR - " at start
        assert result == "ERROR - Alternative error format"
