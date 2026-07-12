from __future__ import annotations

import importlib.util
import json
import math
import tempfile
from pathlib import Path

import pandas as pd

from backend.services.aeroing4.research.strategy_templates import (
    DEFAULT_BREAKOUT_RETEST_PARAMS,
    DEFAULT_MEAN_REVERSION_PARAMS,
    DEFAULT_TREND_PULLBACK_PARAMS,
    DEFAULT_VOLATILITY_COMPRESSION_PARAMS,
    BREAKOUT_RETEST_CLASS_NAME,
    BREAKOUT_RETEST_FAMILY,
    MEAN_REVERSION_CLASS_NAME,
    MEAN_REVERSION_FAMILY,
    TREND_PULLBACK_CLASS_NAME,
    TREND_PULLBACK_FAMILY,
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


def test_strategy_spec_routes_to_trend_pullback_template(tmp_path: Path):
    result = write_strategy_from_spec(
        {"family": TREND_PULLBACK_FAMILY},
        tmp_path,
    )

    assert result.family == TREND_PULLBACK_FAMILY
    assert result.strategy_name == TREND_PULLBACK_CLASS_NAME
    assert tuple(DEFAULT_TREND_PULLBACK_PARAMS) == result.parameters


def test_trend_pullback_py_and_json_exist_with_matching_strategy_name(tmp_path: Path):
    result = write_strategy_from_spec({"family": TREND_PULLBACK_FAMILY}, tmp_path)

    assert result.strategy_path.exists()
    assert result.sidecar_path.exists()
    assert result.strategy_path.name == f"{TREND_PULLBACK_CLASS_NAME}.py"
    assert result.sidecar_path.name == f"{TREND_PULLBACK_CLASS_NAME}.json"
    assert f"class {TREND_PULLBACK_CLASS_NAME}" in result.strategy_path.read_text(encoding="utf-8")

    sidecar = json.loads(result.sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["strategy_name"] == TREND_PULLBACK_CLASS_NAME


def test_trend_pullback_sidecar_contains_runtime_params_shape(tmp_path: Path):
    result = write_strategy_from_spec({"family": TREND_PULLBACK_FAMILY}, tmp_path)
    sidecar = json.loads(result.sidecar_path.read_text(encoding="utf-8"))

    assert set(sidecar["params"]) == {"buy", "sell", "roi", "stoploss", "trailing"}
    assert sidecar["params"]["buy"] == DEFAULT_TREND_PULLBACK_PARAMS
    assert sidecar["params"]["sell"] == {}
    assert sidecar["params"]["stoploss"]["stoploss"] == -0.10
    assert sidecar["params"]["roi"]["0"] == 0.08
    assert sidecar["params"]["trailing"]["trailing_stop"] is False

    for name, value in DEFAULT_TREND_PULLBACK_PARAMS.items():
        assert sidecar["parameters"][name]["current"] == value
        assert sidecar["parameters"][name]["default"] == value


def test_trend_pullback_code_has_no_future_looking_shift(tmp_path: Path):
    result = write_strategy_from_spec({"family": TREND_PULLBACK_FAMILY}, tmp_path)
    source = result.strategy_path.read_text(encoding="utf-8")

    assert "shift(-" not in source
    assert ".shift(1)" in source


def test_trend_pullback_strategy_imports_and_compiles_successfully(tmp_path: Path):
    result = write_strategy_from_spec({"family": TREND_PULLBACK_FAMILY}, tmp_path)

    strategy_class = _load_generated_strategy(result.strategy_path)
    assert strategy_class.__name__ == TREND_PULLBACK_CLASS_NAME


def test_trend_pullback_indicators_and_signal_columns_are_populated(tmp_path: Path):
    result = write_strategy_from_spec({"family": TREND_PULLBACK_FAMILY}, tmp_path)
    strategy_class = _load_generated_strategy(result.strategy_path)
    strategy = strategy_class(config={})
    dataframe = _deterministic_candles()

    dataframe = strategy.populate_indicators(dataframe, {"pair": "LTC/USDT"})
    required_columns = {
        "ema_fast",
        "ema_slow",
        "ema_slow_slope",
        "adx",
        "rsi",
        "atr",
        "volume_mean",
        "relative_volume",
        "pullback_high",
        "atr_stop_level",
    }
    assert required_columns.issubset(dataframe.columns)
    assert dataframe[list(required_columns)].tail(20).notna().all().all()

    dataframe = strategy.populate_entry_trend(dataframe, {"pair": "LTC/USDT"})
    dataframe = strategy.populate_exit_trend(dataframe, {"pair": "LTC/USDT"})
    assert "enter_long" in dataframe.columns
    assert "exit_long" in dataframe.columns


def test_strategy_spec_routes_to_mean_reversion_template(tmp_path: Path):
    result = write_strategy_from_spec({"family": MEAN_REVERSION_FAMILY}, tmp_path)
    assert result.strategy_name == MEAN_REVERSION_CLASS_NAME
    assert result.family == MEAN_REVERSION_FAMILY


def test_mean_reversion_py_and_json_exist_with_matching_strategy_name(tmp_path: Path):
    result = write_strategy_from_spec({"family": MEAN_REVERSION_FAMILY}, tmp_path)
    assert result.strategy_path.exists()
    assert result.sidecar_path.exists()
    assert result.strategy_path.stem == MEAN_REVERSION_CLASS_NAME
    assert result.sidecar_path.stem == MEAN_REVERSION_CLASS_NAME


def test_mean_reversion_sidecar_contains_runtime_params_shape(tmp_path: Path):
    result = write_strategy_from_spec({"family": MEAN_REVERSION_FAMILY}, tmp_path)
    sidecar = json.loads(result.sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["strategy_name"] == MEAN_REVERSION_CLASS_NAME
    assert sidecar["family"] == MEAN_REVERSION_FAMILY
    assert set(sidecar["params"]) == {"buy", "sell", "roi", "stoploss", "trailing"}
    for name, value in DEFAULT_MEAN_REVERSION_PARAMS.items():
        assert sidecar["parameters"][name]["current"] == value


def test_mean_reversion_code_has_no_future_looking_shift(tmp_path: Path):
    result = write_strategy_from_spec({"family": MEAN_REVERSION_FAMILY}, tmp_path)
    source = result.strategy_path.read_text(encoding="utf-8")
    assert ".shift(-1)" not in source
    assert ".shift(-" not in source
    assert ".shift(1)" in source


def test_mean_reversion_strategy_imports_and_compiles_successfully(tmp_path: Path):
    result = write_strategy_from_spec({"family": MEAN_REVERSION_FAMILY}, tmp_path)
    strategy_class = _load_generated_strategy(result.strategy_path)
    assert strategy_class.__name__ == MEAN_REVERSION_CLASS_NAME


def test_mean_reversion_indicators_and_signal_columns_are_populated(tmp_path: Path):
    result = write_strategy_from_spec({"family": MEAN_REVERSION_FAMILY}, tmp_path)
    strategy_class = _load_generated_strategy(result.strategy_path)
    strategy = strategy_class(config={})
    dataframe = _deterministic_candles()

    dataframe = strategy.populate_indicators(dataframe, {"pair": "LTC/USDT"})
    required_columns = {
        "bb_middle",
        "bb_upper",
        "bb_lower",
        "bb_width",
        "close_bb_lower_dist",
        "rsi",
        "rsi_slope",
        "ema_guard",
        "price_vs_ema",
        "atr",
        "atr_stop_level",
        "adx",
        "volume_mean",
        "relative_volume",
        "lower_bb_touch",
        "near_lower_bb",
    }
    assert required_columns.issubset(dataframe.columns)
    assert dataframe[list(required_columns)].tail(20).notna().all().all()

    dataframe = strategy.populate_entry_trend(dataframe, {"pair": "LTC/USDT"})
    dataframe = strategy.populate_exit_trend(dataframe, {"pair": "LTC/USDT"})
    assert "enter_long" in dataframe.columns
    assert "exit_long" in dataframe.columns
    # Note: synthetic test data may not produce entries; real smoke test verifies trades


def test_trend_pullback_continuation_rejection_archive_exists():
    """B4: verify TrendPullbackContinuation rejection archive was created."""
    rejection_path = Path(r'l:\M4tie\Documents\AeRoing4\backend\tests\aeroing4\research\rejected_families\trend_pullback_continuation_rejection.json')
    assert rejection_path.exists()
    rejection_data = json.loads(rejection_path.read_text(encoding="utf-8"))
    assert rejection_data["family"] == "trend_pullback_continuation"
    assert rejection_data["status"] == "mechanically_verified_but_rejected"
    assert "rejection_reasons" in rejection_data
    assert len(rejection_data["rejection_reasons"]) > 0
    assert "original_metrics" in rejection_data
    assert "v2_metrics" in rejection_data
    assert rejection_data["eligibility"]["focused_hyperopt"] is False
    assert rejection_data["eligibility"]["confirmation"] is False
    assert rejection_data["template_preserved"] is True


def test_breakout_retest_confirmation_routing():
    """B5: verify breakout_retest_confirmation family routes to deterministic template."""
    spec = {"family": BREAKOUT_RETEST_FAMILY}
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact = write_strategy_from_spec(spec, Path(tmpdir))
        assert artifact.family == BREAKOUT_RETEST_FAMILY
        assert artifact.strategy_name == BREAKOUT_RETEST_CLASS_NAME


def test_breakout_retest_confirmation_files_exist():
    """B5: verify generated .py and .json files exist."""
    spec = {"family": BREAKOUT_RETEST_FAMILY}
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact = write_strategy_from_spec(spec, Path(tmpdir))
        assert artifact.strategy_path.exists()
        assert artifact.sidecar_path.exists()
        assert artifact.strategy_path.suffix == ".py"
        assert artifact.sidecar_path.suffix == ".json"


def test_breakout_retest_confirmation_naming_consistency():
    """B5: verify class name, filename, and sidecar name match."""
    spec = {"family": BREAKOUT_RETEST_FAMILY}
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact = write_strategy_from_spec(spec, Path(tmpdir))
        assert artifact.strategy_path.stem == BREAKOUT_RETEST_CLASS_NAME
        assert artifact.sidecar_path.stem == BREAKOUT_RETEST_CLASS_NAME


def test_breakout_retest_confirmation_sidecar_runtime_params():
    """B5: verify sidecar contains runtime params.* shape."""
    spec = {"family": BREAKOUT_RETEST_FAMILY}
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact = write_strategy_from_spec(spec, Path(tmpdir))
        sidecar = json.loads(artifact.sidecar_path.read_text(encoding="utf-8"))
        assert "params" in sidecar
        assert "buy" in sidecar["params"]
        assert "sell" in sidecar["params"]
        assert "roi" in sidecar["params"]
        assert "stoploss" in sidecar["params"]
        assert "trailing" in sidecar["params"]
        # Verify buy params match DEFAULT_BREAKOUT_RETEST_PARAMS
        for param_name in DEFAULT_BREAKOUT_RETEST_PARAMS:
            assert param_name in sidecar["params"]["buy"]


def test_breakout_retest_confirmation_no_future_looking():
    """B5: verify generated code has no future-looking shift(-1)."""
    spec = {"family": BREAKOUT_RETEST_FAMILY}
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact = write_strategy_from_spec(spec, Path(tmpdir))
        source = artifact.strategy_path.read_text(encoding="utf-8")
        assert "shift(-1)" not in source


def test_breakout_retest_confirmation_imports_compiles():
    """B5: verify generated strategy imports and compiles."""
    spec = {"family": BREAKOUT_RETEST_FAMILY}
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact = write_strategy_from_spec(spec, Path(tmpdir))
        strategy_class = _load_generated_strategy(artifact.strategy_path)
        assert strategy_class is not None
        assert hasattr(strategy_class, "INTERFACE_VERSION")


def test_breakout_retest_confirmation_indicators_and_signal_columns_are_populated():
    """B5: verify indicator/feature columns are populated and entry/exit columns generated."""
    spec = {"family": BREAKOUT_RETEST_FAMILY}
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact = write_strategy_from_spec(spec, Path(tmpdir))
        strategy_class = _load_generated_strategy(artifact.strategy_path)
        strategy = strategy_class(config={})

        dataframe = _deterministic_candles()
        dataframe = strategy.populate_indicators(dataframe, {"pair": "LTC/USDT"})

        required_columns = [
            "resistance_high",
            "breakout_level",
            "breakout_detected",
            "retest_upper",
            "retest_lower",
            "in_retest_zone",
            "held_above_breakout",
            "volume_mean",
            "relative_volume",
            "atr",
            "atr_mean",
            "atr_expansion_ratio",
            "ema_guard",
            "price_above_ema",
            "atr_tp_level",
            "breakout_fail_level",
        ]
        for col in required_columns:
            assert col in dataframe.columns, f"Missing column: {col}"

        # Ensure columns are populated (not all NaN)
        assert dataframe[list(required_columns)].tail(20).notna().all().all()

        dataframe = strategy.populate_entry_trend(dataframe, {"pair": "LTC/USDT"})
        dataframe = strategy.populate_exit_trend(dataframe, {"pair": "LTC/USDT"})
        assert "enter_long" in dataframe.columns
        assert "exit_long" in dataframe.columns
        # Note: synthetic test data may not produce entries; real smoke test verifies trades


def test_breakout_retest_confirmation_rejection_archive_exists():
    """B5: verify MeanReversionExhaustion rejection archive was created."""
    rejection_path = Path(r'l:\M4tie\Documents\AeRoing4\backend\tests\aeroing4\research\rejected_families\mean_reversion_exhaustion_rejection.json')
    assert rejection_path.exists()
    rejection_data = json.loads(rejection_path.read_text(encoding="utf-8"))
    assert rejection_data["family"] == "mean_reversion_exhaustion"
    assert rejection_data["status"] == "mechanically_verified_but_rejected_pair_dependent"
    assert "rejection_reasons" in rejection_data
    assert len(rejection_data["rejection_reasons"]) > 0
    assert "true_baseline_metrics" in rejection_data
    assert "corrected_pair_level_metrics" in rejection_data
    assert rejection_data["eligibility"]["focused_hyperopt"] is False
    assert rejection_data["eligibility"]["confirmation"] is False
