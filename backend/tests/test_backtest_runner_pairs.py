from datetime import UTC, datetime
from types import SimpleNamespace

from backend.models import ParamsSchema
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
