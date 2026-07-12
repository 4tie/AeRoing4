from datetime import UTC, datetime
from types import SimpleNamespace
from zipfile import ZipFile

from backend.models import ParamsSchema
from backend.services.execution import backtest_runner as backtest_runner_module
from backend.services.execution.backtest_runner import BacktestRunner


def _params(**buy_params):
    return ParamsSchema(
        strategy_name="AIStrategy",
        version_id="v001",
        extracted_at=datetime.now(tz=UTC),
        pair_list=None,
        buy_params=buy_params,
        sell_params={},
        protection_params={},
        roi_table={"0": 0.1},
        stoploss=-0.1,
        trailing_stop=False,
        trailing_stop_positive=None,
        trailing_stop_positive_offset=None,
        trailing_only_offset_is_reached=False,
        custom_params={},
    )


def test_accepted_run_materializes_live_source_with_stored_params(tmp_path):
    live_strategy = tmp_path / "AIStrategy.py"
    live_strategy.write_text(
        "class AIStrategy:\n"
        "    buy_params = {'buy_ma_count': 12}\n",
        encoding="utf-8",
    )
    stored_params = _params(buy_ma_count=18)

    class FakeVersionManager:
        def __init__(self):
            self.calls = []

        def get_current_pointer(self, strategy_name):
            return SimpleNamespace(accepted_version_id="v001")

        def materialize_strategy_source(
            self,
            strategy_name,
            version_id,
            source=None,
            params=None,
        ):
            self.calls.append(
                {
                    "strategy_name": strategy_name,
                    "version_id": version_id,
                    "source": source,
                    "params": params,
                }
            )
            return f"buy_ma_count={params.buy_params['buy_ma_count']}"

    runner = BacktestRunner.__new__(BacktestRunner)
    runner.version_manager = FakeVersionManager()

    source = runner._materialize_strategy_source_for_run(
        strategy_name="AIStrategy",
        resolved_version_id="v001",
        params=stored_params,
        strategy_path=str(live_strategy),
    )

    assert source == "buy_ma_count=18"
    call = runner.version_manager.calls[0]
    assert call["source"] == live_strategy.read_text(encoding="utf-8")
    assert call["params"] is stored_params


def test_normalize_futures_pairs_adds_settlement_suffix():
    runner = BacktestRunner.__new__(BacktestRunner)

    pairs = runner._normalize_pairs_for_config(
        ["ADA/USDT", "ETH/USDT", "BTC/USDT:USDT", "ADA/USDT"],
        {"trading_mode": "futures"},
    )

    assert pairs == ["ADA/USDT:USDT", "ETH/USDT:USDT", "BTC/USDT:USDT"]


def test_normalize_spot_pairs_leaves_symbols_unchanged():
    runner = BacktestRunner.__new__(BacktestRunner)

    pairs = runner._normalize_pairs_for_config(
        ["ADA/USDT", "ETH/USDT"],
        {"trading_mode": "spot"},
    )

    assert pairs == ["ADA/USDT", "ETH/USDT"]


def test_build_command_uses_local_freqtrade_and_backtest_directory(tmp_path, monkeypatch):
    runner = BacktestRunner.__new__(BacktestRunner)
    runner.settings_store = SimpleNamespace(root_dir=tmp_path)
    monkeypatch.setattr(
        backtest_runner_module.shutil,
        "which",
        lambda name: "C:\\Windows\\py.exe" if name == "py" else None,
    )

    local_freqtrade = tmp_path / "4t" / "Scripts" / "freqtrade.exe"
    local_freqtrade.parent.mkdir(parents=True)
    local_freqtrade.write_text("", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    command = runner._build_command(
        "py -m freqtrade",
        str(tmp_path / "user_data"),
        str(run_dir / "freqtrade_execution_config.json"),
        "MultiMa",
        run_dir,
        "20240101-20240108",
        "4h",
        ["BTC/USDT", "BTC/USDT"],
        1,
        1000.0,
    )

    assert command[0] == str(local_freqtrade)
    assert "--backtest-directory" in command
    assert str(run_dir) in command
    assert "--export-filename" not in command
    assert command[command.index("--pairs") + 1:] == ["BTC/USDT"]


def test_execution_config_uses_requested_pairs_and_local_binance_metadata():
    runner = BacktestRunner.__new__(BacktestRunner)

    payload = runner._build_execution_config_payload(
        config_payload={
            "trading_mode": "spot",
            "margin_mode": "isolated",
            "exchange": {
                "name": "binance",
                "pair_whitelist": ["ETH/USDT"],
                "ccxt_async_config": {"aiohttp_trust_env": True},
            },
        },
        pairs=["BTC/USDT"],
        timeframe="4h",
        max_open_trades=1,
        dry_run_wallet=1000.0,
        market_base_url="http://127.0.0.1:12345",
    )

    assert payload["timeframe"] == "4h"
    assert payload["max_open_trades"] == 1
    assert payload["dry_run_wallet"] == 1000.0
    assert payload["trading_mode"] == "spot"
    assert payload["margin_mode"] == ""
    assert payload["pairlists"] == [{"method": "StaticPairList"}]
    assert payload["exchange"]["pair_whitelist"] == ["BTC/USDT"]
    assert payload["exchange"]["skip_pair_validation"] is True
    assert (
        payload["exchange"]["ccxt_config"]["urls"]["api"]["public"]
        == "http://127.0.0.1:12345/api/v3"
    )
    assert payload["exchange"]["ccxt_async_config"]["aiohttp_trust_env"] is False


def test_collect_latest_freqtrade_result_reads_run_directory_zip(tmp_path):
    runner = BacktestRunner.__new__(BacktestRunner)
    runner.run_repository = SimpleNamespace(backtest_results_root=tmp_path / "backtest_results")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    zip_path = run_dir / "freqtrade-backtest.zip"
    with ZipFile(zip_path, "w") as archive:
        archive.writestr("strategy.json", '{"strategy": {"MultiMa": {"trades": []}}}')
    (run_dir / "progress.json").write_text('{"phase": "finalizing"}', encoding="utf-8")
    (run_dir / "MultiMa.json").write_text('{"strategy_name": "MultiMa"}', encoding="utf-8")

    runner._collect_latest_freqtrade_result(run_dir)

    assert (run_dir / "raw_result.json").read_text(encoding="utf-8") == (
        '{"strategy": {"MultiMa": {"trades": []}}}'
    )
    assert (run_dir / "freqtrade_native_result.zip").exists()
