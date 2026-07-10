"""Tests for run_portfolio_backtest()."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.models.runs import ParsedSummary, PairResult
from backend.models.base import PairClassification
from backend.services.execution.pair_sweep_runner import run_portfolio_backtest

_VALID_SOURCE = "class MyStrategy(IStrategy):\n    pass\n"


def _good_summary(**overrides) -> ParsedSummary:
    base = {
        "run_id": "test",
        "starting_balance": 1000.0,
        "final_balance": 1100.0,
        "net_profit_currency": 100.0,
        "net_profit_pct": 10.0,
        "total_trades": 50,
        "trades_per_day": 2.0,
        "win_rate_pct": 55.0,
        "loss_rate_pct": 45.0,
        "max_drawdown_pct": 15.0,
        "max_drawdown_currency": 50.0,
        "avg_trade_duration_minutes": 120.0,
        "profit_factor": 1.5,
        "expectancy": 2.0,
        "sharpe_ratio": 1.2,
        "sortino_ratio": 1.5,
        "calmar_ratio": 2.0,
        "exit_reason_distribution": [],
    }
    base.update(overrides)
    return ParsedSummary(**base)


def _good_pair_results() -> list[PairResult]:
    return [
        PairResult(
            pair="BTC/USDT",
            net_profit_currency=60.0,
            net_profit_pct=6.0,
            total_trades=25,
            win_count=15,
            loss_count=10,
            win_rate_pct=60.0,
            avg_trade_result_pct=0.4,
            avg_trade_duration_minutes=120.0,
            pair_classification=None,
            classification_rationale=None,
        ),
        PairResult(
            pair="ETH/USDT",
            net_profit_currency=40.0,
            net_profit_pct=4.0,
            total_trades=25,
            win_count=12,
            loss_count=13,
            win_rate_pct=48.0,
            avg_trade_result_pct=0.3,
            avg_trade_duration_minutes=90.0,
            pair_classification=None,
            classification_rationale=None,
        ),
    ]


def _popen_side_effect_create_raw_result(*args, **kwargs):
    cmd = args[0] if args else kwargs.get("args", [])
    for i, arg in enumerate(cmd):
        if arg == "--export-filename" and i + 1 < len(cmd):
            path = Path(cmd[i + 1])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"dummy": True}), encoding="utf-8")
            break
    mock = MagicMock()
    mock.returncode = 0
    mock.communicate.return_value = (b"", b"")
    return mock


def _popen_side_effect_failure(*args, **kwargs):
    mock = MagicMock()
    mock.returncode = 1
    mock.communicate.return_value = (b"", b"error")
    return mock


# -------------------------------------------------------------------
# Input validation
# -------------------------------------------------------------------


def test_empty_pairs_raises_value_error(tmp_path):
    strategy_file = tmp_path / "strategy.py"
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")
    try:
        run_portfolio_backtest(
            strategy_path=str(strategy_file),
            strategy_name="MyStrategy",
            config_file="/tmp/config.json",
            timerange="20240101-20240131",
            timeframe="5m",
            pairs=[],
            max_open_trades=5,
            dry_run_wallet=1000.0,
            user_data_dir=str(tmp_path),
            exchange="binance",
        )
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "pairs" in str(e).lower()


def test_max_open_trades_zero_raises_value_error(tmp_path):
    strategy_file = tmp_path / "strategy.py"
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")
    try:
        run_portfolio_backtest(
            strategy_path=str(strategy_file),
            strategy_name="MyStrategy",
            config_file="/tmp/config.json",
            timerange="20240101-20240131",
            timeframe="5m",
            pairs=["BTC/USDT"],
            max_open_trades=0,
            dry_run_wallet=1000.0,
            user_data_dir=str(tmp_path),
            exchange="binance",
        )
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "max_open_trades" in str(e).lower()


# -------------------------------------------------------------------
# Portfolio pass/fail
# -------------------------------------------------------------------


@patch("backend.services.execution.pair_sweep.portfolio_backtest.ResultParser.parse_run_artifacts")
@patch("backend.services.execution.pair_sweep.portfolio_backtest.subprocess.Popen")
def test_portfolio_passes_all_thresholds(mock_popen, mock_parse, tmp_path):
    mock_popen.side_effect = _popen_side_effect_create_raw_result
    mock_parse.return_value = (_good_summary(), _good_pair_results())

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_portfolio_backtest(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT", "ETH/USDT"],
        max_open_trades=5,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )

    assert result["status"] == "passed"
    assert result["failure_reasons"] == []
    assert result["run_id"] is not None
    assert result["portfolio_summary"]["total_trades"] == 50
    assert result["portfolio_summary"]["profit_factor"] == 1.5
    assert len(result["per_pair_metrics"]) == 2
    assert result["config_used"]["pairs_count"] == 2
    assert result["config_used"]["max_open_trades"] == 5


@patch("backend.services.execution.pair_sweep.portfolio_backtest.ResultParser.parse_run_artifacts")
@patch("backend.services.execution.pair_sweep.portfolio_backtest.subprocess.Popen")
def test_portfolio_fails_drawdown(mock_popen, mock_parse, tmp_path):
    mock_popen.side_effect = _popen_side_effect_create_raw_result
    mock_parse.return_value = (
        _good_summary(max_drawdown_pct=45.0),
        _good_pair_results(),
    )

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_portfolio_backtest(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT", "ETH/USDT"],
        max_open_trades=5,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )

    assert result["status"] == "failed"
    assert "MAX_DRAWDOWN" in result["failure_reasons"]


@patch("backend.services.execution.pair_sweep.portfolio_backtest.ResultParser.parse_run_artifacts")
@patch("backend.services.execution.pair_sweep.portfolio_backtest.subprocess.Popen")
def test_portfolio_fails_low_trades(mock_popen, mock_parse, tmp_path):
    mock_popen.side_effect = _popen_side_effect_create_raw_result
    mock_parse.return_value = (
        _good_summary(total_trades=3),
        _good_pair_results(),
    )

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_portfolio_backtest(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT", "ETH/USDT"],
        max_open_trades=5,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )

    assert result["status"] == "failed"
    assert "MIN_TRADES" in result["failure_reasons"]


# -------------------------------------------------------------------
# max_open_trades passed correctly
# -------------------------------------------------------------------


@patch("backend.services.execution.pair_sweep.portfolio_backtest.subprocess.Popen")
def test_max_open_trades_in_command(mock_popen, tmp_path):
    captured_cmds = []

    def capture_popen(*args, **kwargs):
        captured_cmds.append(args[0] if args else kwargs.get("args", []))
        mock = MagicMock()
        mock.returncode = 0
        mock.communicate.return_value = (b"{}", b"")
        return mock

    mock_popen.side_effect = capture_popen

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    run_portfolio_backtest(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT", "ETH/USDT"],
        max_open_trades=3,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )

    assert len(captured_cmds) >= 1
    cmd = captured_cmds[0]
    max_idx = cmd.index("--max-open-trades")
    assert cmd[max_idx + 1] == "3"


# -------------------------------------------------------------------
# All pairs passed into one joint backtest
# -------------------------------------------------------------------


@patch("backend.services.execution.pair_sweep.portfolio_backtest.subprocess.Popen")
def test_all_pairs_in_one_command(mock_popen, tmp_path):
    captured_cmds = []

    def capture_popen(*args, **kwargs):
        captured_cmds.append(args[0] if args else kwargs.get("args", []))
        mock = MagicMock()
        mock.returncode = 0
        mock.communicate.return_value = (b"{}", b"")
        return mock

    mock_popen.side_effect = capture_popen

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    test_pairs = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    run_portfolio_backtest(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=test_pairs,
        max_open_trades=5,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )

    assert len(captured_cmds) >= 1
    cmd = captured_cmds[0]
    pairs_idx = cmd.index("--pairs")
    cmd_pairs = cmd[pairs_idx + 1:]
    for p in test_pairs:
        assert p in cmd_pairs


# -------------------------------------------------------------------
# Backtest failure
# -------------------------------------------------------------------


@patch("backend.services.execution.pair_sweep.portfolio_backtest.subprocess.Popen")
def test_backtest_crash_returns_backtest_failed(mock_popen, tmp_path):
    mock_popen.side_effect = _popen_side_effect_failure

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_portfolio_backtest(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT", "ETH/USDT"],
        max_open_trades=5,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )

    assert result["status"] == "backtest_failed"
    assert len(result["failure_reasons"]) >= 1


# -------------------------------------------------------------------
# Missing strategy file
# -------------------------------------------------------------------


def test_missing_strategy_file(tmp_path):
    result = run_portfolio_backtest(
        strategy_path="/nonexistent/strategy.py",
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT"],
        max_open_trades=5,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )

    assert result["status"] == "backtest_failed"
    assert any("not found" in r.lower() for r in result["failure_reasons"])


# -------------------------------------------------------------------
# No PairSelectorService writes (not applicable — standalone function)
# -------------------------------------------------------------------


def test_standalone_function_has_no_side_effects_on_pair_selector():
    """run_portfolio_backtest is a standalone function — it cannot write to PairSelectorService."""
    import inspect
    source = inspect.getsource(run_portfolio_backtest)
    assert "pair_selector" not in source
    assert "PairSelectorService" not in source
