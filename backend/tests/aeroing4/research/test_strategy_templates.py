from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pandas as pd

from backend.services.aeroing4.research.strategy_templates import (
    DEFAULT_VOLATILITY_COMPRESSION_PARAMS,
    VOLATILITY_COMPRESSION_CLASS_NAME,
    VOLATILITY_COMPRESSION_FAMILY,
    write_strategy_from_spec,
)


def _load_generated_strategy(strategy_path: Path):
    spec = importlib.util.spec_from_file_location(strategy_path.stem, strategy_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return getattr(module, strategy_path.stem)


def _deterministic_candles(rows: int = 320) -> pd.DataFrame:
    close = []
    for index in range(rows):
        base = 100 + index * 0.018
        compression = math.sin(index / 5) * 0.05
        value = base + compression
        if index > rows - 25:
            value += (index - (rows - 25)) * 0.22
        close.append(value)

    frame = pd.DataFrame({"close": close})
    frame["open"] = frame["close"].shift(1).fillna(frame["close"])
    frame["high"] = frame[["open", "close"]].max(axis=1) + 0.12
    frame["low"] = frame[["open", "close"]].min(axis=1) - 0.12
    frame["volume"] = 1000.0
    frame.loc[rows - 20 :, "volume"] = 1800.0
    return frame


def test_strategy_spec_routes_to_volatility_compression_template(tmp_path: Path):
    result = write_strategy_from_spec(
        {"family": VOLATILITY_COMPRESSION_FAMILY},
        tmp_path,
    )

    assert result.family == VOLATILITY_COMPRESSION_FAMILY
    assert result.strategy_name == VOLATILITY_COMPRESSION_CLASS_NAME
    assert tuple(DEFAULT_VOLATILITY_COMPRESSION_PARAMS) == result.parameters


def test_generated_py_and_json_exist_with_matching_strategy_name(tmp_path: Path):
    result = write_strategy_from_spec({"family": VOLATILITY_COMPRESSION_FAMILY}, tmp_path)

    assert result.strategy_path.exists()
    assert result.sidecar_path.exists()
    assert result.strategy_path.name == f"{VOLATILITY_COMPRESSION_CLASS_NAME}.py"
    assert result.sidecar_path.name == f"{VOLATILITY_COMPRESSION_CLASS_NAME}.json"
    assert f"class {VOLATILITY_COMPRESSION_CLASS_NAME}" in result.strategy_path.read_text(encoding="utf-8")

    sidecar = json.loads(result.sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["strategy_name"] == VOLATILITY_COMPRESSION_CLASS_NAME


def test_generated_sidecar_contains_runtime_params_shape(tmp_path: Path):
    result = write_strategy_from_spec({"family": VOLATILITY_COMPRESSION_FAMILY}, tmp_path)
    sidecar = json.loads(result.sidecar_path.read_text(encoding="utf-8"))

    assert set(sidecar["params"]) == {"buy", "sell", "roi", "stoploss", "trailing"}
    assert sidecar["params"]["buy"] == DEFAULT_VOLATILITY_COMPRESSION_PARAMS
    assert sidecar["params"]["sell"] == {}
    assert sidecar["params"]["stoploss"]["stoploss"] == -0.12
    assert sidecar["params"]["roi"]["0"] == 0.06
    assert sidecar["params"]["trailing"]["trailing_stop"] is False

    for name, value in DEFAULT_VOLATILITY_COMPRESSION_PARAMS.items():
        assert sidecar["parameters"][name]["current"] == value
        assert sidecar["parameters"][name]["default"] == value


def test_generated_code_has_no_future_looking_shift(tmp_path: Path):
    result = write_strategy_from_spec({"family": VOLATILITY_COMPRESSION_FAMILY}, tmp_path)
    source = result.strategy_path.read_text(encoding="utf-8")

    assert "shift(-" not in source
    assert ".shift(1)" in source


def test_generated_strategy_imports_and_compiles_successfully(tmp_path: Path):
    result = write_strategy_from_spec({"family": VOLATILITY_COMPRESSION_FAMILY}, tmp_path)

    strategy_class = _load_generated_strategy(result.strategy_path)
    assert strategy_class.__name__ == VOLATILITY_COMPRESSION_CLASS_NAME


def test_generated_indicators_and_signal_columns_are_populated(tmp_path: Path):
    result = write_strategy_from_spec({"family": VOLATILITY_COMPRESSION_FAMILY}, tmp_path)
    strategy_class = _load_generated_strategy(result.strategy_path)
    strategy = strategy_class(config={})
    dataframe = _deterministic_candles()

    dataframe = strategy.populate_indicators(dataframe, {"pair": "LTC/USDT"})
    required_columns = {
        "bb_middle",
        "bb_upper",
        "bb_lower",
        "bb_width",
        "atr",
        "ema_trend",
        "volume_mean",
        "relative_volume",
        "range_high",
        "breakout_level",
        "breakout_extension_atr",
        "atr_stop_level",
    }
    assert required_columns.issubset(dataframe.columns)
    assert dataframe[list(required_columns)].tail(20).notna().all().all()

    dataframe = strategy.populate_entry_trend(dataframe, {"pair": "LTC/USDT"})
    dataframe = strategy.populate_exit_trend(dataframe, {"pair": "LTC/USDT"})
    assert "enter_long" in dataframe.columns
    assert "exit_long" in dataframe.columns


def test_unknown_strategy_spec_family_is_rejected(tmp_path: Path):
    try:
        write_strategy_from_spec({"family": "plain_ma_count_gap"}, tmp_path)
    except ValueError as exc:
        assert "unsupported deterministic strategy family" in str(exc)
    else:
        raise AssertionError("unsupported family was not rejected")
