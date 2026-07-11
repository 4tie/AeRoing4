"""Deterministic StrategySpec-to-artifact templates for DEVELOP research.

This module intentionally contains fixed templates only. It does not ask an AI
to write strategy code, and it does not mutate existing strategy families.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VOLATILITY_COMPRESSION_FAMILY = "volatility_compression_breakout"
VOLATILITY_COMPRESSION_CLASS_NAME = "VolatilityCompressionBreakout"
VOLATILITY_COMPRESSION_V2_CLASS_NAME = "VolatilityCompressionBreakoutV2"


@dataclass(frozen=True)
class StrategyTemplateResult:
    family: str
    strategy_name: str
    strategy_path: Path
    sidecar_path: Path
    parameters: tuple[str, ...]


DEFAULT_VOLATILITY_COMPRESSION_PARAMS: dict[str, Any] = {
    "bb_period": 20,
    "bb_stddev": 2.0,
    "bb_width_max": 0.08,
    "breakout_lookback": 24,
    "ema_trend_period": 96,
    "volume_window": 30,
    "relative_volume_min": 1.25,
    "atr_period": 14,
}

STRICT_VOLATILITY_COMPRESSION_PARAMS: dict[str, Any] = {
    "bb_period": 20,
    "bb_stddev": 2.0,
    "bb_width_max": 0.035,
    "breakout_lookback": 48,
    "ema_trend_period": 144,
    "volume_window": 48,
    "relative_volume_min": 1.6,
    "atr_period": 14,
}


def write_strategy_from_spec(spec: dict[str, Any], output_dir: Path) -> StrategyTemplateResult:
    """Write deterministic strategy artifacts for a supported StrategySpec."""

    family = str(spec.get("family", "")).strip().lower()
    if family != VOLATILITY_COMPRESSION_FAMILY:
        raise ValueError(f"unsupported deterministic strategy family: {family}")
    if str(spec.get("variant", "")).strip().lower() in {"strict_v2", "v2"}:
        return write_volatility_compression_breakout_v2(output_dir)
    return write_volatility_compression_breakout(output_dir)


def write_volatility_compression_breakout(output_dir: Path) -> StrategyTemplateResult:
    """Write the accepted B1 volatility-compression breakout template."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    strategy_name = VOLATILITY_COMPRESSION_CLASS_NAME
    strategy_path = output_dir / f"{strategy_name}.py"
    sidecar_path = output_dir / f"{strategy_name}.json"

    strategy_path.write_text(_volatility_compression_strategy_source(), encoding="utf-8")
    sidecar_path.write_text(
        json.dumps(_volatility_compression_sidecar(), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return StrategyTemplateResult(
        family=VOLATILITY_COMPRESSION_FAMILY,
        strategy_name=strategy_name,
        strategy_path=strategy_path,
        sidecar_path=sidecar_path,
        parameters=tuple(DEFAULT_VOLATILITY_COMPRESSION_PARAMS),
    )


def write_volatility_compression_breakout_v2(output_dir: Path) -> StrategyTemplateResult:
    """Write a stricter deterministic v2 of the B2 template for DEVELOP audit."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    strategy_name = VOLATILITY_COMPRESSION_V2_CLASS_NAME
    strategy_path = output_dir / f"{strategy_name}.py"
    sidecar_path = output_dir / f"{strategy_name}.json"

    strategy_path.write_text(_volatility_compression_v2_strategy_source(), encoding="utf-8")
    sidecar_path.write_text(
        json.dumps(
            _volatility_compression_sidecar(
                strategy_name=strategy_name,
                params=STRICT_VOLATILITY_COMPRESSION_PARAMS,
            ),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return StrategyTemplateResult(
        family=VOLATILITY_COMPRESSION_FAMILY,
        strategy_name=strategy_name,
        strategy_path=strategy_path,
        sidecar_path=sidecar_path,
        parameters=tuple(STRICT_VOLATILITY_COMPRESSION_PARAMS),
    )


def _tracking_parameter(name: str, value: Any, kind: str, minimum: Any, maximum: Any) -> dict[str, Any]:
    return {
        "type": kind,
        "editable": True,
        "current": value,
        "default": value,
        "min": minimum,
        "max": maximum,
    }


def _volatility_compression_sidecar(
    *,
    strategy_name: str = VOLATILITY_COMPRESSION_CLASS_NAME,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = params or DEFAULT_VOLATILITY_COMPRESSION_PARAMS
    return {
        "strategy_name": strategy_name,
        "family": VOLATILITY_COMPRESSION_FAMILY,
        "params": {
            "buy": dict(params),
            "sell": {},
            "roi": {"0": 0.06, "120": 0.025, "360": 0.0},
            "stoploss": {"stoploss": -0.12},
            "trailing": {
                "trailing_stop": False,
                "trailing_stop_positive_offset": 0.0,
                "trailing_only_offset_is_reached": False,
            },
        },
        "parameters": {
            "bb_period": _tracking_parameter("bb_period", params["bb_period"], "int", 10, 40),
            "bb_stddev": _tracking_parameter("bb_stddev", params["bb_stddev"], "float", 1.5, 3.0),
            "bb_width_max": _tracking_parameter("bb_width_max", params["bb_width_max"], "float", 0.02, 0.20),
            "breakout_lookback": _tracking_parameter(
                "breakout_lookback", params["breakout_lookback"], "int", 8, 72
            ),
            "ema_trend_period": _tracking_parameter(
                "ema_trend_period", params["ema_trend_period"], "int", 40, 240
            ),
            "volume_window": _tracking_parameter("volume_window", params["volume_window"], "int", 10, 80),
            "relative_volume_min": _tracking_parameter(
                "relative_volume_min", params["relative_volume_min"], "float", 1.0, 3.0
            ),
            "atr_period": _tracking_parameter("atr_period", params["atr_period"], "int", 7, 40),
        },
    }


def _volatility_compression_strategy_source() -> str:
    return '''from freqtrade.strategy import DecimalParameter, IntParameter, IStrategy
from pandas import DataFrame
import talib.abstract as ta


class VolatilityCompressionBreakout(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "5m"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 240

    minimal_roi = {
        "0": 0.06,
        "120": 0.025,
        "360": 0.0,
    }
    stoploss = -0.12
    trailing_stop = False
    trailing_stop_positive_offset = 0.0
    trailing_only_offset_is_reached = False

    buy_params = {
        "bb_period": 20,
        "bb_stddev": 2.0,
        "bb_width_max": 0.08,
        "breakout_lookback": 24,
        "ema_trend_period": 96,
        "volume_window": 30,
        "relative_volume_min": 1.25,
        "atr_period": 14,
    }
    sell_params = {}

    bb_period = IntParameter(10, 40, default=20, space="buy", optimize=True)
    bb_stddev = DecimalParameter(1.5, 3.0, default=2.0, decimals=2, space="buy", optimize=True)
    bb_width_max = DecimalParameter(0.02, 0.20, default=0.08, decimals=3, space="buy", optimize=True)
    breakout_lookback = IntParameter(8, 72, default=24, space="buy", optimize=True)
    ema_trend_period = IntParameter(40, 240, default=96, space="buy", optimize=True)
    volume_window = IntParameter(10, 80, default=30, space="buy", optimize=True)
    relative_volume_min = DecimalParameter(1.0, 3.0, default=1.25, decimals=2, space="buy", optimize=True)
    atr_period = IntParameter(7, 40, default=14, space="buy", optimize=True)

    atr_stop_mult = 2.0
    atr_extension_max = 1.8

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        bb_period = int(self.bb_period.value)
        bb_stddev = float(self.bb_stddev.value)
        breakout_lookback = int(self.breakout_lookback.value)
        ema_period = int(self.ema_trend_period.value)
        volume_window = int(self.volume_window.value)
        atr_period = int(self.atr_period.value)

        middle = dataframe["close"].rolling(bb_period, min_periods=bb_period).mean()
        std = dataframe["close"].rolling(bb_period, min_periods=bb_period).std(ddof=0)
        dataframe["bb_middle"] = middle
        dataframe["bb_upper"] = middle + (std * bb_stddev)
        dataframe["bb_lower"] = middle - (std * bb_stddev)
        dataframe["bb_width"] = (dataframe["bb_upper"] - dataframe["bb_lower"]) / dataframe["bb_middle"]

        dataframe["atr"] = ta.ATR(dataframe, timeperiod=atr_period)
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=ema_period)
        dataframe["volume_mean"] = dataframe["volume"].rolling(volume_window, min_periods=volume_window).mean()
        dataframe["relative_volume"] = dataframe["volume"] / dataframe["volume_mean"]
        dataframe["range_high"] = dataframe["high"].rolling(
            breakout_lookback, min_periods=breakout_lookback
        ).max().shift(1)
        dataframe["breakout_level"] = dataframe[["bb_upper", "range_high"]].max(axis=1)
        dataframe["breakout_extension_atr"] = (
            (dataframe["close"] - dataframe["breakout_level"]) / dataframe["atr"]
        )
        dataframe["atr_stop_level"] = dataframe["breakout_level"] - (dataframe["atr"] * self.atr_stop_mult)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        compression = dataframe["bb_width"] <= float(self.bb_width_max.value)
        breakout = (
            (dataframe["close"] > dataframe["bb_upper"])
            | (dataframe["close"] > dataframe["range_high"])
        )
        volume_confirmed = dataframe["relative_volume"] >= float(self.relative_volume_min.value)
        trend_aligned = dataframe["close"] > dataframe["ema_trend"]
        atr_ready = dataframe["atr"].notna() & (dataframe["atr"] > 0)
        extension_ok = dataframe["breakout_extension_atr"].between(0, self.atr_extension_max)

        dataframe.loc[
            compression
            & breakout
            & volume_confirmed
            & trend_aligned
            & atr_ready
            & extension_ok,
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        lost_breakout = dataframe["close"] < dataframe["breakout_level"]
        lost_trend = dataframe["close"] < dataframe["ema_trend"]
        atr_stop = dataframe["close"] < dataframe["atr_stop_level"]
        weak_breakout = (
            (dataframe["close"] < dataframe["bb_middle"])
            & (dataframe["relative_volume"] < 1.0)
        )

        dataframe.loc[
            lost_breakout | lost_trend | atr_stop | weak_breakout,
            "exit_long",
        ] = 1
        return dataframe
'''


def _volatility_compression_v2_strategy_source() -> str:
    return '''from freqtrade.strategy import DecimalParameter, IntParameter, IStrategy
from pandas import DataFrame
import talib.abstract as ta


class VolatilityCompressionBreakoutV2(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "5m"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 360

    minimal_roi = {
        "0": 0.04,
        "180": 0.018,
        "480": 0.0,
    }
    stoploss = -0.08
    trailing_stop = False
    trailing_stop_positive_offset = 0.0
    trailing_only_offset_is_reached = False

    buy_params = {
        "bb_period": 20,
        "bb_stddev": 2.0,
        "bb_width_max": 0.035,
        "breakout_lookback": 48,
        "ema_trend_period": 144,
        "volume_window": 48,
        "relative_volume_min": 1.6,
        "atr_period": 14,
    }
    sell_params = {}

    bb_period = IntParameter(10, 40, default=20, space="buy", optimize=True)
    bb_stddev = DecimalParameter(1.5, 3.0, default=2.0, decimals=2, space="buy", optimize=True)
    bb_width_max = DecimalParameter(0.015, 0.12, default=0.035, decimals=3, space="buy", optimize=True)
    breakout_lookback = IntParameter(24, 96, default=48, space="buy", optimize=True)
    ema_trend_period = IntParameter(80, 240, default=144, space="buy", optimize=True)
    volume_window = IntParameter(24, 96, default=48, space="buy", optimize=True)
    relative_volume_min = DecimalParameter(1.2, 3.5, default=1.6, decimals=2, space="buy", optimize=True)
    atr_period = IntParameter(7, 40, default=14, space="buy", optimize=True)

    atr_stop_mult = 1.6
    atr_extension_max = 1.1

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        bb_period = int(self.bb_period.value)
        bb_stddev = float(self.bb_stddev.value)
        breakout_lookback = int(self.breakout_lookback.value)
        ema_period = int(self.ema_trend_period.value)
        volume_window = int(self.volume_window.value)
        atr_period = int(self.atr_period.value)

        middle = dataframe["close"].rolling(bb_period, min_periods=bb_period).mean()
        std = dataframe["close"].rolling(bb_period, min_periods=bb_period).std(ddof=0)
        dataframe["bb_middle"] = middle
        dataframe["bb_upper"] = middle + (std * bb_stddev)
        dataframe["bb_lower"] = middle - (std * bb_stddev)
        dataframe["bb_width"] = (dataframe["bb_upper"] - dataframe["bb_lower"]) / dataframe["bb_middle"]
        dataframe["prior_bb_upper"] = dataframe["bb_upper"].shift(1)
        dataframe["prior_bb_width"] = dataframe["bb_width"].shift(1)
        dataframe["compressed_recent"] = (
            dataframe["prior_bb_width"].rolling(breakout_lookback, min_periods=breakout_lookback).min()
            <= float(self.bb_width_max.value)
        )

        dataframe["atr"] = ta.ATR(dataframe, timeperiod=atr_period)
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=ema_period)
        dataframe["ema_trend_slope"] = dataframe["ema_trend"] - dataframe["ema_trend"].shift(12)
        dataframe["volume_mean"] = dataframe["volume"].rolling(volume_window, min_periods=volume_window).mean()
        dataframe["relative_volume"] = dataframe["volume"] / dataframe["volume_mean"]
        dataframe["range_high"] = dataframe["high"].rolling(
            breakout_lookback, min_periods=breakout_lookback
        ).max().shift(1)
        dataframe["breakout_level"] = dataframe[["prior_bb_upper", "range_high"]].max(axis=1)
        dataframe["prior_breakout_level"] = dataframe["breakout_level"].shift(1)
        dataframe["breakout_extension_atr"] = (
            (dataframe["close"] - dataframe["breakout_level"]) / dataframe["atr"]
        )
        dataframe["atr_stop_level"] = dataframe["breakout_level"] - (dataframe["atr"] * self.atr_stop_mult)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        fresh_breakout = (
            (dataframe["close"] > dataframe["breakout_level"])
            & (dataframe["close"].shift(1) <= dataframe["prior_breakout_level"])
        )
        volume_confirmed = dataframe["relative_volume"] >= float(self.relative_volume_min.value)
        trend_aligned = (
            (dataframe["close"] > dataframe["ema_trend"])
            & (dataframe["ema_trend_slope"] > 0)
        )
        atr_ready = dataframe["atr"].notna() & (dataframe["atr"] > 0)
        extension_ok = dataframe["breakout_extension_atr"].between(0.05, self.atr_extension_max)

        dataframe.loc[
            dataframe["compressed_recent"]
            & fresh_breakout
            & volume_confirmed
            & trend_aligned
            & atr_ready
            & extension_ok,
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        failed_breakout = dataframe["close"] < dataframe["breakout_level"]
        lost_trend = dataframe["close"] < dataframe["ema_trend"]
        atr_stop = dataframe["close"] < dataframe["atr_stop_level"]
        momentum_failed = (
            (dataframe["close"] < dataframe["bb_middle"])
            | (
                (dataframe["close"] < dataframe["close"].shift(3))
                & (dataframe["relative_volume"] < 1.0)
            )
        )

        dataframe.loc[
            failed_breakout | lost_trend | atr_stop | momentum_failed,
            "exit_long",
        ] = 1
        return dataframe
'''
