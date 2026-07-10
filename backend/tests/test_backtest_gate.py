"""Tests for backtest gate."""

import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.models.runs import ParsedSummary
from backend.services.execution.backtest_gate import (
    GATE_THRESHOLDS,
    _apply_gate_rules,
    _build_gate_command,
    _normalize_pairs_for_config,
    _resolve_config_file,
    run_backtest_gate,
)

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


def _popen_side_effect_create_raw_result(*args, **kwargs):
    cmd = args[0] if args else kwargs.get("args", [])
    for i, arg in enumerate(cmd):
        if arg == "--export-filename" and i + 1 < len(cmd):
            path = Path(cmd[i + 1])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"dummy": True}), encoding="utf-8")
            break
        if arg == "--backtest-directory" and i + 1 < len(cmd):
            run_dir = Path(cmd[i + 1])
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "raw_result.json").write_text(json.dumps({"dummy": True}), encoding="utf-8")
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


def _popen_side_effect_create_native_zip(*args, **kwargs):
    cmd = args[0] if args else kwargs.get("args", [])
    user_data_dir = Path(cmd[cmd.index("--user-data-dir") + 1])
    results_dir = user_data_dir / "backtest_results"
    results_dir.mkdir(parents=True, exist_ok=True)
    zip_name = "backtest-result-2026-06-16_21-06-52.zip"
    zip_path = results_dir / zip_name
    payload = {
        "strategy": {
            "MyStrategy": {
                "total_trades": 50,
                "profit_total_abs": 100.0,
                "profit_total": 0.1,
                "results_per_pair": [],
                "trades": [],
            },
        },
    }
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("backtest-result-2026-06-16_21-06-52.json", json.dumps(payload))
    (results_dir / ".last_result.json").write_text(
        json.dumps({"latest_backtest": zip_name}),
        encoding="utf-8",
    )
    mock = MagicMock()
    mock.returncode = 0
    mock.communicate.return_value = (
        b"Result for strategy MyStrategy\n",
        b"dumping json to backtest_results\n",
    )
    return mock


def _popen_side_effect_no_result(*args, **kwargs):
    mock = MagicMock()
    mock.returncode = 0
    mock.communicate.return_value = (b"No trades made\n", b"")
    return mock


# -------------------------------------------------------------------
# _build_gate_command
# -------------------------------------------------------------------

def test_build_gate_command_includes_all_flags():
    cmd = _build_gate_command(
        executable="freqtrade",
        user_data_dir="/tmp/user_data",
        config_file="/tmp/config.json",
        strategy_name="MyStrategy",
        run_dir=Path("/tmp/run"),
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT", "ETH/USDT"],
        max_open_trades=3,
        dry_run_wallet=5000.0,
    )
    assert cmd[0] == "freqtrade"
    assert cmd[1] == "backtesting"
    assert "--user-data-dir" in cmd
    assert "--strategy-path" in cmd
    assert "--strategy" in cmd
    assert "MyStrategy" in cmd
    assert "--backtest-directory" in cmd
    assert str(Path("/tmp/run")) in cmd
    assert "--export-filename" not in cmd
    assert "--pairs" in cmd
    assert "BTC/USDT" in cmd
    assert "ETH/USDT" in cmd


def test_build_gate_command_deduplicates_pairs():
    cmd = _build_gate_command(
        executable="freqtrade",
        user_data_dir="/tmp",
        config_file="/tmp/config.json",
        strategy_name="S",
        run_dir=Path("/tmp/r"),
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT", "BTC/USDT"],
        max_open_trades=1,
        dry_run_wallet=1000.0,
    )
    btc_count = sum(1 for c in cmd if c == "BTC/USDT")
    assert btc_count == 1


def test_normalize_pairs_for_futures_config_adds_settlement_suffix():
    pairs = _normalize_pairs_for_config(
        ["BTC/USDT", "ETH/USDT", "BTC/USDT:USDT", "BTC/USDT"],
        {"trading_mode": "futures"},
    )

    assert pairs == ["BTC/USDT:USDT", "ETH/USDT:USDT"]


def test_normalize_pairs_for_spot_config_keeps_spot_symbols():
    pairs = _normalize_pairs_for_config(
        ["BTC/USDT", "ETH/USDT", "BTC/USDT"],
        {"trading_mode": "spot"},
    )

    assert pairs == ["BTC/USDT", "ETH/USDT"]


def test_resolve_config_file_prefers_user_data_dir_for_relative_default(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("{}", encoding="utf-8")

    resolved = _resolve_config_file("config.json", str(tmp_path))

    assert resolved == str(config_file)


# -------------------------------------------------------------------
# _apply_gate_rules
# -------------------------------------------------------------------

def test_apply_gate_rules_all_pass():
    metrics = {
        "total_trades": 50,
        "win_rate_pct": 55.0,
        "profit_factor": 1.5,
        "max_drawdown_pct": 15.0,
        "expectancy": 2.0,
        "sharpe_ratio": 1.2,
    }
    assert _apply_gate_rules(metrics) == []


def test_apply_gate_rules_min_trades():
    metrics = {
        "total_trades": 3,
        "win_rate_pct": 55.0,
        "profit_factor": 1.5,
        "max_drawdown_pct": 15.0,
        "expectancy": 2.0,
        "sharpe_ratio": 1.2,
    }
    assert _apply_gate_rules(metrics) == ["MIN_TRADES"]


def test_apply_gate_rules_win_rate():
    metrics = {
        "total_trades": 50,
        "win_rate_pct": 25.0,
        "profit_factor": 1.5,
        "max_drawdown_pct": 15.0,
        "expectancy": 2.0,
        "sharpe_ratio": 1.2,
    }
    assert _apply_gate_rules(metrics) == ["MIN_WIN_RATE"]


def test_apply_gate_rules_profit_factor():
    metrics = {
        "total_trades": 50,
        "win_rate_pct": 55.0,
        "profit_factor": 1.01,
        "max_drawdown_pct": 15.0,
        "expectancy": 2.0,
        "sharpe_ratio": 1.2,
    }
    assert _apply_gate_rules(metrics) == ["MIN_PROFIT_FACTOR"]


def test_apply_gate_rules_drawdown():
    metrics = {
        "total_trades": 50,
        "win_rate_pct": 55.0,
        "profit_factor": 1.5,
        "max_drawdown_pct": 45.0,
        "expectancy": 2.0,
        "sharpe_ratio": 1.2,
    }
    assert _apply_gate_rules(metrics) == ["MAX_DRAWDOWN"]


def test_apply_gate_rules_expectancy():
    metrics = {
        "total_trades": 50,
        "win_rate_pct": 55.0,
        "profit_factor": 1.5,
        "max_drawdown_pct": 15.0,
        "expectancy": -5.0,
        "sharpe_ratio": 1.2,
    }
    assert _apply_gate_rules(metrics) == ["POSITIVE_EXPECTANCY"]


def test_apply_gate_rules_sharpe():
    metrics = {
        "total_trades": 50,
        "win_rate_pct": 55.0,
        "profit_factor": 1.5,
        "max_drawdown_pct": 15.0,
        "expectancy": 2.0,
        "sharpe_ratio": 0.1,
    }
    assert _apply_gate_rules(metrics) == ["MIN_SHARPE"]


def test_apply_gate_rules_multiple():
    metrics = {
        "total_trades": 3,
        "win_rate_pct": 25.0,
        "profit_factor": 1.01,
        "max_drawdown_pct": 45.0,
        "expectancy": -5.0,
        "sharpe_ratio": 0.1,
    }
    failures = _apply_gate_rules(metrics)
    assert "MIN_TRADES" in failures
    assert "MIN_WIN_RATE" in failures
    assert "MIN_PROFIT_FACTOR" in failures
    assert "MAX_DRAWDOWN" in failures
    assert "POSITIVE_EXPECTANCY" in failures
    assert "MIN_SHARPE" in failures
    assert len(failures) == 6


def test_apply_gate_rules_skips_none():
    metrics = {
        "total_trades": 50,
        "win_rate_pct": 55.0,
        "profit_factor": None,
        "max_drawdown_pct": 15.0,
        "expectancy": 2.0,
        "sharpe_ratio": None,
    }
    failures = _apply_gate_rules(metrics)
    assert "MIN_PROFIT_FACTOR" not in failures
    assert "MIN_SHARPE" not in failures
    assert failures == []


# -------------------------------------------------------------------
# run_backtest_gate — integration with mocks
# -------------------------------------------------------------------

@patch("backend.services.execution.backtest_gate.check_data_quality")
def test_data_quality_fails_early(mock_dq, tmp_path):
    mock_dq.return_value = {
        "passed": False,
        "errors": ["MISSING_DATA_FILE: BTC/USDT"],
        "warnings": [],
        "details": {},
    }
    result = run_backtest_gate(
        strategy_path="/nonexistent/strategy.py",
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT"],
        max_open_trades=1,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    assert result.gate_status == "data_quality_failed"
    assert "MISSING_DATA_FILE" in str(result.errors)


@patch("backend.services.execution.backtest_gate.check_data_quality")
@patch("backend.services.execution.backtest_gate.ResultParser.parse_run_artifacts")
@patch("backend.services.execution.backtest_gate.subprocess.Popen")
def test_gate_passes_all_thresholds(mock_popen, mock_parse, mock_dq, tmp_path):
    mock_dq.return_value = {"passed": True, "errors": [], "warnings": [], "details": {}}
    mock_popen.side_effect = _popen_side_effect_create_raw_result
    mock_parse.return_value = (_good_summary(), [])

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_backtest_gate(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT"],
        max_open_trades=1,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    assert result.gate_status == "passed"
    assert result.failures == []
    assert result.run_id is not None
    assert result.metrics["total_trades"] == 50
    assert result.metrics["profit_factor"] == 1.5


@patch("backend.services.execution.backtest_gate.check_data_quality")
@patch("backend.services.execution.backtest_gate.ResultParser.parse_run_artifacts")
@patch("backend.services.execution.backtest_gate.subprocess.Popen")
def test_gate_collects_native_freqtrade_zip_when_raw_result_missing(
    mock_popen,
    mock_parse,
    mock_dq,
    tmp_path,
):
    mock_dq.return_value = {"passed": True, "errors": [], "warnings": [], "details": {}}
    mock_popen.side_effect = _popen_side_effect_create_native_zip
    mock_parse.return_value = (_good_summary(), [])

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_backtest_gate(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT"],
        max_open_trades=1,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )

    parse_run_dir = mock_parse.call_args.args[0]
    assert result.gate_status == "passed"
    assert (parse_run_dir / "raw_result.json").exists()
    assert (parse_run_dir / "freqtrade_native_result.zip").exists()
    assert result.details["raw_result_path"] == str(parse_run_dir / "raw_result.json")
    assert result.details["result_source"].endswith(".zip")


@patch("backend.services.execution.backtest_gate.check_data_quality")
@patch("backend.services.execution.backtest_gate.subprocess.Popen")
def test_gate_reports_clear_error_when_no_result_artifact_found(mock_popen, mock_dq, tmp_path):
    mock_dq.return_value = {"passed": True, "errors": [], "warnings": [], "details": {}}
    mock_popen.side_effect = _popen_side_effect_no_result

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_backtest_gate(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT"],
        max_open_trades=1,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )

    assert result.gate_status == "backtest_failed"
    assert "native result archive" in result.errors[0]
    assert result.details["expected_result"].endswith("raw_result.json")
    assert result.details["last_result_pointer"].endswith(".last_result.json")


@patch("backend.services.execution.backtest_gate.check_data_quality")
@patch("backend.services.execution.backtest_gate.ResultParser.parse_run_artifacts")
@patch("backend.services.execution.backtest_gate.subprocess.Popen")
def test_gate_resolves_relative_config_file_under_user_data(mock_popen, mock_parse, mock_dq, tmp_path):
    mock_dq.return_value = {"passed": True, "errors": [], "warnings": [], "details": {}}
    mock_popen.side_effect = _popen_side_effect_create_raw_result
    mock_parse.return_value = (_good_summary(), [])

    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_backtest_gate(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT"],
        max_open_trades=1,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )

    command = mock_popen.call_args.args[0]
    config_arg_index = command.index("--config") + 1
    assert result.gate_status == "passed"
    assert command[config_arg_index] == str(tmp_path / "config.json")


@patch("backend.services.execution.backtest_gate.check_data_quality")
@patch("backend.services.execution.backtest_gate.ResultParser.parse_run_artifacts")
@patch("backend.services.execution.backtest_gate.subprocess.Popen")
def test_gate_uses_futures_pairs_when_config_is_futures(mock_popen, mock_parse, mock_dq, tmp_path):
    mock_dq.return_value = {"passed": True, "errors": [], "warnings": [], "details": {}}
    mock_popen.side_effect = _popen_side_effect_create_raw_result
    mock_parse.return_value = (_good_summary(), [])

    (tmp_path / "config.json").write_text(
        json.dumps({"trading_mode": "futures"}),
        encoding="utf-8",
    )
    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_backtest_gate(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT", "ETH/USDT"],
        max_open_trades=1,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )

    command = mock_popen.call_args.args[0]
    config_idx = command.index("--config")
    pairs_idx = command.index("--pairs")
    gate_config = Path(command[config_idx + 1])
    gate_config_payload = json.loads(gate_config.read_text(encoding="utf-8"))
    assert result.gate_status == "passed"
    assert gate_config.name == "candidate_config.json"
    assert gate_config_payload["exchange"]["pair_whitelist"] == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert command[pairs_idx + 1:pairs_idx + 3] == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert mock_dq.call_args.kwargs["pairs"] == ["BTC/USDT:USDT", "ETH/USDT:USDT"]


@patch("backend.services.execution.backtest_gate.check_data_quality")
@patch("backend.services.execution.backtest_gate.ResultParser.parse_run_artifacts")
@patch("backend.services.execution.backtest_gate.subprocess.Popen")
def test_gate_fails_min_trades(mock_popen, mock_parse, mock_dq, tmp_path):
    mock_dq.return_value = {"passed": True, "errors": [], "warnings": [], "details": {}}
    mock_popen.side_effect = _popen_side_effect_create_raw_result
    mock_parse.return_value = (_good_summary(total_trades=3), [])

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_backtest_gate(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT"],
        max_open_trades=1,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    assert result.gate_status == "failed"
    assert result.failures == ["MIN_TRADES"]


@patch("backend.services.execution.backtest_gate.check_data_quality")
@patch("backend.services.execution.backtest_gate.ResultParser.parse_run_artifacts")
@patch("backend.services.execution.backtest_gate.subprocess.Popen")
def test_gate_fails_win_rate(mock_popen, mock_parse, mock_dq, tmp_path):
    mock_dq.return_value = {"passed": True, "errors": [], "warnings": [], "details": {}}
    mock_popen.side_effect = _popen_side_effect_create_raw_result
    mock_parse.return_value = (_good_summary(win_rate_pct=25.0), [])

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_backtest_gate(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT"],
        max_open_trades=1,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    assert result.gate_status == "failed"
    assert result.failures == ["MIN_WIN_RATE"]


@patch("backend.services.execution.backtest_gate.check_data_quality")
@patch("backend.services.execution.backtest_gate.ResultParser.parse_run_artifacts")
@patch("backend.services.execution.backtest_gate.subprocess.Popen")
def test_gate_fails_profit_factor(mock_popen, mock_parse, mock_dq, tmp_path):
    mock_dq.return_value = {"passed": True, "errors": [], "warnings": [], "details": {}}
    mock_popen.side_effect = _popen_side_effect_create_raw_result
    mock_parse.return_value = (_good_summary(profit_factor=1.01), [])

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_backtest_gate(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT"],
        max_open_trades=1,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    assert result.gate_status == "failed"
    assert result.failures == ["MIN_PROFIT_FACTOR"]


@patch("backend.services.execution.backtest_gate.check_data_quality")
@patch("backend.services.execution.backtest_gate.ResultParser.parse_run_artifacts")
@patch("backend.services.execution.backtest_gate.subprocess.Popen")
def test_gate_fails_drawdown(mock_popen, mock_parse, mock_dq, tmp_path):
    mock_dq.return_value = {"passed": True, "errors": [], "warnings": [], "details": {}}
    mock_popen.side_effect = _popen_side_effect_create_raw_result
    mock_parse.return_value = (_good_summary(max_drawdown_pct=45.0), [])

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_backtest_gate(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT"],
        max_open_trades=1,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    assert result.gate_status == "failed"
    assert result.failures == ["MAX_DRAWDOWN"]


@patch("backend.services.execution.backtest_gate.check_data_quality")
@patch("backend.services.execution.backtest_gate.ResultParser.parse_run_artifacts")
@patch("backend.services.execution.backtest_gate.subprocess.Popen")
def test_gate_fails_expectancy(mock_popen, mock_parse, mock_dq, tmp_path):
    mock_dq.return_value = {"passed": True, "errors": [], "warnings": [], "details": {}}
    mock_popen.side_effect = _popen_side_effect_create_raw_result
    mock_parse.return_value = (_good_summary(expectancy=-5.0), [])

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_backtest_gate(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT"],
        max_open_trades=1,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    assert result.gate_status == "failed"
    assert result.failures == ["POSITIVE_EXPECTANCY"]


@patch("backend.services.execution.backtest_gate.check_data_quality")
@patch("backend.services.execution.backtest_gate.ResultParser.parse_run_artifacts")
@patch("backend.services.execution.backtest_gate.subprocess.Popen")
def test_gate_fails_sharpe(mock_popen, mock_parse, mock_dq, tmp_path):
    mock_dq.return_value = {"passed": True, "errors": [], "warnings": [], "details": {}}
    mock_popen.side_effect = _popen_side_effect_create_raw_result
    mock_parse.return_value = (_good_summary(sharpe_ratio=0.1), [])

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_backtest_gate(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT"],
        max_open_trades=1,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    assert result.gate_status == "failed"
    assert result.failures == ["MIN_SHARPE"]


@patch("backend.services.execution.backtest_gate.check_data_quality")
@patch("backend.services.execution.backtest_gate.ResultParser.parse_run_artifacts")
@patch("backend.services.execution.backtest_gate.subprocess.Popen")
def test_gate_reports_multiple_failures(mock_popen, mock_parse, mock_dq, tmp_path):
    mock_dq.return_value = {"passed": True, "errors": [], "warnings": [], "details": {}}
    mock_popen.side_effect = _popen_side_effect_create_raw_result
    mock_parse.return_value = (_good_summary(
        total_trades=3,
        win_rate_pct=25.0,
        profit_factor=1.01,
        max_drawdown_pct=45.0,
        expectancy=-5.0,
        sharpe_ratio=0.1,
    ), [])

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_backtest_gate(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT"],
        max_open_trades=1,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    assert result.gate_status == "failed"
    assert len(result.failures) == 6
    for code in ["MIN_TRADES", "MIN_WIN_RATE", "MIN_PROFIT_FACTOR", "MAX_DRAWDOWN", "POSITIVE_EXPECTANCY", "MIN_SHARPE"]:
        assert code in result.failures


@patch("backend.services.execution.backtest_gate.check_data_quality")
@patch("backend.services.execution.backtest_gate.ResultParser.parse_run_artifacts")
@patch("backend.services.execution.backtest_gate.subprocess.Popen")
def test_gate_skips_none_metrics_with_warning(mock_popen, mock_parse, mock_dq, tmp_path):
    mock_dq.return_value = {"passed": True, "errors": [], "warnings": [], "details": {}}
    mock_popen.side_effect = _popen_side_effect_create_raw_result
    mock_parse.return_value = (_good_summary(
        profit_factor=None,
        sharpe_ratio=None,
    ), [])

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_backtest_gate(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT"],
        max_open_trades=1,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    assert result.gate_status == "passed"
    assert result.failures == []
    assert any("profit_factor" in w for w in result.warnings)
    assert any("sharpe_ratio" in w for w in result.warnings)
    assert result.metrics["profit_factor"] is None
    assert result.metrics["sharpe_ratio"] is None


@patch("backend.services.execution.backtest_gate.check_data_quality")
@patch("backend.services.execution.backtest_gate.subprocess.Popen")
def test_backtest_crash_returns_backtest_failed(mock_popen, mock_dq, tmp_path):
    mock_dq.return_value = {"passed": True, "errors": [], "warnings": [], "details": {}}
    mock_popen.side_effect = _popen_side_effect_failure

    strategy_file = tmp_path / "strategies" / "MyStrategy.py"
    strategy_file.parent.mkdir(parents=True)
    strategy_file.write_text(_VALID_SOURCE, encoding="utf-8")

    result = run_backtest_gate(
        strategy_path=str(strategy_file),
        strategy_name="MyStrategy",
        config_file="/tmp/config.json",
        timerange="20240101-20240131",
        timeframe="5m",
        pairs=["BTC/USDT"],
        max_open_trades=1,
        dry_run_wallet=1000.0,
        user_data_dir=str(tmp_path),
        exchange="binance",
    )
    assert result.gate_status == "backtest_failed"
    assert any("exit" in e.lower() for e in result.errors)
    assert "error" in result.errors
    assert result.details["stderr_tail"] == ["error"]
