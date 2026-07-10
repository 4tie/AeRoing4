"""Unit tests for results analysis service module."""

from pathlib import Path
import tempfile
import json

from backend.services.backtest.results_analysis_service import (
    read_json,
    compute_smart_flags,
    compute_health_report,
)
from backend.models import ParsedSummary, BacktestTrade, SmartFlag


def test_read_json_file_exists():
    """Test read_json with existing file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "test.json"
        file_path.write_text('{"key": "value"}', encoding="utf-8")
        
        result = read_json(file_path)
        assert result == {"key": "value"}


def test_read_json_file_not_exists():
    """Test read_json with non-existent file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "nonexistent.json"
        
        result = read_json(file_path)
        assert result is None


def test_read_json_file_not_exists_with_default():
    """Test read_json with non-existent file and default value."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "nonexistent.json"
        
        result = read_json(file_path, default={"default": True})
        assert result == {"default": True}


def test_read_json_invalid_json():
    """Test read_json with invalid JSON file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "invalid.json"
        file_path.write_text("{invalid json", encoding="utf-8")
        
        result = read_json(file_path)
        assert result is None


def test_compute_smart_flags_low_frequency():
    """Test compute_smart_flags with low trading frequency."""
    summary = ParsedSummary(
        run_id="test_run",
        starting_balance=1000.0,
        final_balance=1000.0,
        net_profit_currency=0.0,
        net_profit_pct=0.0,
        total_trades=10,
        trades_per_day=0.3,
        max_drawdown_pct=None,
        win_rate_pct=None,
        loss_rate_pct=None,
        max_drawdown_currency=None,
        avg_trade_duration_minutes=None,
        profit_factor=None,
        expectancy=None,
        sharpe_ratio=None,
        sortino_ratio=None,
        calmar_ratio=None,
        exit_reason_distribution=[],
    )
    trades = []
    
    flags = compute_smart_flags(summary, trades)
    
    assert len(flags) == 1
    assert flags[0].code == "LOW_FREQUENCY"
    assert flags[0].type == "warning"


def test_compute_smart_flags_high_drawdown():
    """Test compute_smart_flags with high drawdown."""
    summary = ParsedSummary(
        run_id="test_run",
        starting_balance=1000.0,
        final_balance=900.0,
        net_profit_currency=-100.0,
        net_profit_pct=-10.0,
        total_trades=10,
        trades_per_day=2.0,
        max_drawdown_pct=-20.0,
        win_rate_pct=None,
        loss_rate_pct=None,
        max_drawdown_currency=None,
        avg_trade_duration_minutes=None,
        profit_factor=None,
        expectancy=None,
        sharpe_ratio=None,
        sortino_ratio=None,
        calmar_ratio=None,
        exit_reason_distribution=[],
    )
    trades = []
    
    flags = compute_smart_flags(summary, trades)
    
    # Both HIGH_DRAWDOWN and NET_LOSS flags are generated
    assert len(flags) == 2
    assert any(f.code == "HIGH_DRAWDOWN" for f in flags)
    assert any(f.code == "NET_LOSS" for f in flags)


def test_compute_smart_flags_net_loss():
    """Test compute_smart_flags with net loss."""
    summary = ParsedSummary(
        run_id="test_run",
        starting_balance=1000.0,
        final_balance=950.0,
        net_profit_currency=-50.0,
        net_profit_pct=-5.0,
        total_trades=10,
        trades_per_day=2.0,
        max_drawdown_pct=-10.0,
        win_rate_pct=None,
        loss_rate_pct=None,
        max_drawdown_currency=None,
        avg_trade_duration_minutes=None,
        profit_factor=None,
        expectancy=None,
        sharpe_ratio=None,
        sortino_ratio=None,
        calmar_ratio=None,
        exit_reason_distribution=[],
    )
    trades = []
    
    flags = compute_smart_flags(summary, trades)
    
    assert len(flags) == 1
    assert flags[0].code == "NET_LOSS"
    assert flags[0].type == "danger"


def test_compute_smart_flags_low_win_rate():
    """Test compute_smart_flags with low win rate."""
    summary = ParsedSummary(
        run_id="test_run",
        starting_balance=1000.0,
        final_balance=1050.0,
        net_profit_currency=50.0,
        net_profit_pct=5.0,
        total_trades=20,
        trades_per_day=2.0,
        max_drawdown_pct=-10.0,
        win_rate_pct=35.0,
        loss_rate_pct=65.0,
        max_drawdown_currency=None,
        avg_trade_duration_minutes=None,
        profit_factor=None,
        expectancy=None,
        sharpe_ratio=None,
        sortino_ratio=None,
        calmar_ratio=None,
        exit_reason_distribution=[],
    )
    trades = []
    
    flags = compute_smart_flags(summary, trades)
    
    assert len(flags) == 1
    assert flags[0].code == "LOW_WIN_RATE"
    assert flags[0].type == "warning"


def test_compute_smart_flags_no_flags():
    """Test compute_smart_flags with good metrics (no flags)."""
    summary = ParsedSummary(
        run_id="test_run",
        starting_balance=1000.0,
        final_balance=1050.0,
        net_profit_currency=50.0,
        net_profit_pct=5.0,
        total_trades=20,
        trades_per_day=2.0,
        max_drawdown_pct=-10.0,
        win_rate_pct=50.0,
        loss_rate_pct=50.0,
        max_drawdown_currency=None,
        avg_trade_duration_minutes=None,
        profit_factor=None,
        expectancy=None,
        sharpe_ratio=None,
        sortino_ratio=None,
        calmar_ratio=None,
        exit_reason_distribution=[],
    )
    trades = []
    
    flags = compute_smart_flags(summary, trades)
    
    assert len(flags) == 0


def test_compute_health_report_winner_take_all_red():
    """Test compute_health_report with winner-take-all trap (yellow severity)."""
    summary = ParsedSummary(
        run_id="test_run",
        starting_balance=1000.0,
        final_balance=1050.0,
        net_profit_currency=50.0,
        net_profit_pct=5.0,
        total_trades=10,
        trades_per_day=2.0,
        max_drawdown_pct=-10.0,
        win_rate_pct=50.0,
        loss_rate_pct=50.0,
        max_drawdown_currency=None,
        avg_trade_duration_minutes=None,
        profit_factor=None,
        expectancy=None,
        sharpe_ratio=None,
        sortino_ratio=None,
        calmar_ratio=None,
        exit_reason_distribution=[],
    )
    trades = [
        BacktestTrade(pair="BTC/USDT", profit_abs=100.0),
        BacktestTrade(pair="ETH/USDT", profit_abs=50.0),
        BacktestTrade(pair="SOL/USDT", profit_abs=-60.0),  # Worst loss is 60% of gross profit
    ]
    
    report = compute_health_report(summary, trades)
    
    # Winner-take-all triggers yellow severity
    assert report.overall_severity == "yellow"
    winner_check = next(c for c in report.checks if c.code == "WINNER_TAKE_ALL")
    assert winner_check.severity == "yellow"


def test_compute_health_report_consistency_ratio_red():
    """Test compute_health_report with poor consistency ratio."""
    summary = ParsedSummary(
        run_id="test_run",
        starting_balance=1000.0,
        final_balance=1000.0,
        net_profit_currency=0.0,
        net_profit_pct=0.0,
        total_trades=10,
        trades_per_day=2.0,
        max_drawdown_pct=-10.0,
        win_rate_pct=30.0,
        loss_rate_pct=70.0,
        max_drawdown_currency=None,
        avg_trade_duration_minutes=None,
        profit_factor=None,
        expectancy=None,
        sharpe_ratio=None,
        sortino_ratio=None,
        calmar_ratio=None,
        exit_reason_distribution=[],
    )
    trades = [
        BacktestTrade(pair="BTC/USDT", profit_abs=10.0),
        BacktestTrade(pair="ETH/USDT", profit_abs=10.0),
        BacktestTrade(pair="SOL/USDT", profit_abs=10.0),
        BacktestTrade(pair="XRP/USDT", profit_abs=-50.0),
    ]
    
    report = compute_health_report(summary, trades)
    
    consistency_check = next(c for c in report.checks if c.code == "CONSISTENCY_RATIO")
    assert consistency_check.severity == "red"


def test_compute_health_report_drawdown_warning_red():
    """Test compute_health_report with dangerous drawdown."""
    summary = ParsedSummary(
        run_id="test_run",
        starting_balance=1000.0,
        final_balance=700.0,
        net_profit_currency=-300.0,
        net_profit_pct=-30.0,
        total_trades=10,
        trades_per_day=2.0,
        max_drawdown_pct=-30.0,
        win_rate_pct=50.0,
        loss_rate_pct=50.0,
        max_drawdown_currency=None,
        avg_trade_duration_minutes=None,
        profit_factor=None,
        expectancy=None,
        sharpe_ratio=None,
        sortino_ratio=None,
        calmar_ratio=None,
        exit_reason_distribution=[],
    )
    trades = []
    
    report = compute_health_report(summary, trades)
    
    dd_check = next(c for c in report.checks if c.code == "DRAWDOWN_WARNING")
    assert dd_check.severity == "red"


def test_compute_health_report_risk_of_ruin_red():
    """Test compute_health_report with high risk of ruin."""
    summary = ParsedSummary(
        run_id="test_run",
        starting_balance=1000.0,
        final_balance=1050.0,
        net_profit_currency=50.0,
        net_profit_pct=5.0,
        total_trades=10,
        trades_per_day=2.0,
        max_drawdown_pct=-10.0,
        win_rate_pct=50.0,
        loss_rate_pct=50.0,
        max_drawdown_currency=None,
        avg_trade_duration_minutes=None,
        profit_factor=None,
        expectancy=None,
        sharpe_ratio=None,
        sortino_ratio=None,
        calmar_ratio=None,
        exit_reason_distribution=[],
    )
    trades = [
        BacktestTrade(pair="BTC/USDT", profit_abs=-200.0),  # 20% loss per trade
        BacktestTrade(pair="ETH/USDT", profit_abs=-200.0),
    ]
    
    report = compute_health_report(summary, trades)
    
    ruin_check = next(c for c in report.checks if c.code == "RISK_OF_RUIN")
    assert ruin_check.severity == "yellow"


def test_compute_health_report_all_green():
    """Test compute_health_report with healthy metrics."""
    summary = ParsedSummary(
        run_id="test_run",
        starting_balance=1000.0,
        final_balance=1100.0,
        net_profit_currency=100.0,
        net_profit_pct=10.0,
        total_trades=10,
        trades_per_day=2.0,
        max_drawdown_pct=-5.0,
        win_rate_pct=60.0,
        loss_rate_pct=40.0,
        max_drawdown_currency=None,
        avg_trade_duration_minutes=None,
        profit_factor=None,
        expectancy=None,
        sharpe_ratio=None,
        sortino_ratio=None,
        calmar_ratio=None,
        exit_reason_distribution=[],
    )
    trades = [
        BacktestTrade(pair="BTC/USDT", profit_abs=100.0),
        BacktestTrade(pair="ETH/USDT", profit_abs=50.0),
        BacktestTrade(pair="SOL/USDT", profit_abs=-10.0),
    ]
    
    report = compute_health_report(summary, trades)
    
    assert report.overall_severity == "green"
