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

TREND_PULLBACK_FAMILY = "trend_pullback_continuation"
TREND_PULLBACK_CLASS_NAME = "TrendPullbackContinuation"

MEAN_REVERSION_FAMILY = "mean_reversion_exhaustion"
MEAN_REVERSION_CLASS_NAME = "MeanReversionExhaustion"


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

DEFAULT_TREND_PULLBACK_PARAMS: dict[str, Any] = {
    "ema_fast_period": 9,
    "ema_slow_period": 21,
    "adx_period": 14,
    "adx_min": 20,
    "rsi_period": 14,
    "rsi_pullback_min": 25,
    "rsi_pullback_max": 55,
    "atr_period": 14,
}

STRICT_TREND_PULLBACK_PARAMS: dict[str, Any] = {
    "ema_fast_period": 9,
    "ema_slow_period": 21,
    "adx_period": 14,
    "adx_min": 20,
    "rsi_period": 14,
    "rsi_pullback_min": 27,
    "rsi_pullback_max": 52,
    "atr_period": 14,
}

DEFAULT_MEAN_REVERSION_PARAMS: dict[str, Any] = {
    "bb_period": 20,
    "bb_stddev": 2.0,
    "rsi_period": 14,
    "rsi_oversold": 30,
    "rsi_recovery_min": 35,
    "ema_guard_period": 50,
    "atr_period": 14,
    "adx_period": 14,
    "adx_max": 40,
}


def write_strategy_from_spec(spec: dict[str, Any], output_dir: Path) -> StrategyTemplateResult:
    """Write deterministic strategy artifacts for a supported StrategySpec."""

    family = str(spec.get("family", "")).strip().lower()
    if family == VOLATILITY_COMPRESSION_FAMILY:
        if str(spec.get("variant", "")).strip().lower() in {"strict_v2", "v2"}:
            return write_volatility_compression_breakout_v2(output_dir)
        return write_volatility_compression_breakout(output_dir)
    elif family == TREND_PULLBACK_FAMILY:
        if str(spec.get("variant", "")).strip().lower() in {"strict_v2", "v2"}:
            return write_trend_pullback_continuation_v2(output_dir)
        return write_trend_pullback_continuation(output_dir)
    elif family == MEAN_REVERSION_FAMILY:
        return write_mean_reversion_exhaustion(output_dir)
    else:
        raise ValueError(f"unsupported deterministic strategy family: {family}")


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


def write_trend_pullback_continuation(output_dir: Path) -> StrategyTemplateResult:
    """Write the deterministic trend pullback continuation template."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    strategy_name = TREND_PULLBACK_CLASS_NAME
    strategy_path = output_dir / f"{strategy_name}.py"
    sidecar_path = output_dir / f"{strategy_name}.json"

    strategy_path.write_text(_trend_pullback_strategy_source(), encoding="utf-8")
    sidecar_path.write_text(
        json.dumps(_trend_pullback_sidecar(), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return StrategyTemplateResult(
        family=TREND_PULLBACK_FAMILY,
        strategy_name=strategy_name,
        strategy_path=strategy_path,
        sidecar_path=sidecar_path,
        parameters=tuple(DEFAULT_TREND_PULLBACK_PARAMS),
    )


def write_trend_pullback_continuation_v2(output_dir: Path) -> StrategyTemplateResult:
    """Write a stricter deterministic v2 of the trend pullback template for DEVELOP audit."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    strategy_name = f"{TREND_PULLBACK_CLASS_NAME}V2"
    strategy_path = output_dir / f"{strategy_name}.py"
    sidecar_path = output_dir / f"{strategy_name}.json"

    strategy_path.write_text(_trend_pullback_v2_strategy_source(), encoding="utf-8")
    sidecar_path.write_text(
        json.dumps(
            _trend_pullback_sidecar(
                strategy_name=strategy_name,
                params=STRICT_TREND_PULLBACK_PARAMS,
            ),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return StrategyTemplateResult(
        family=TREND_PULLBACK_FAMILY,
        strategy_name=strategy_name,
        strategy_path=strategy_path,
        sidecar_path=sidecar_path,
        parameters=tuple(STRICT_TREND_PULLBACK_PARAMS),
    )


def write_mean_reversion_exhaustion(output_dir: Path) -> StrategyTemplateResult:
    """Write the deterministic mean reversion exhaustion template."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    strategy_name = MEAN_REVERSION_CLASS_NAME
    strategy_path = output_dir / f"{strategy_name}.py"
    sidecar_path = output_dir / f"{strategy_name}.json"

    strategy_path.write_text(_mean_reversion_strategy_source(), encoding="utf-8")
    sidecar_path.write_text(
        json.dumps(_mean_reversion_sidecar(), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return StrategyTemplateResult(
        family=MEAN_REVERSION_FAMILY,
        strategy_name=strategy_name,
        strategy_path=strategy_path,
        sidecar_path=sidecar_path,
        parameters=tuple(DEFAULT_MEAN_REVERSION_PARAMS),
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


def _trend_pullback_sidecar(
    *,
    strategy_name: str = TREND_PULLBACK_CLASS_NAME,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = params or DEFAULT_TREND_PULLBACK_PARAMS
    return {
        "strategy_name": strategy_name,
        "family": TREND_PULLBACK_FAMILY,
        "params": {
            "buy": dict(params),
            "sell": {},
            "roi": {"0": 0.08, "240": 0.03, "720": 0.0},
            "stoploss": {"stoploss": -0.10},
            "trailing": {
                "trailing_stop": False,
                "trailing_stop_positive_offset": 0.0,
                "trailing_only_offset_is_reached": False,
            },
        },
        "parameters": {
            "ema_fast_period": _tracking_parameter("ema_fast_period", params["ema_fast_period"], "int", 5, 20),
            "ema_slow_period": _tracking_parameter("ema_slow_period", params["ema_slow_period"], "int", 15, 50),
            "adx_period": _tracking_parameter("adx_period", params["adx_period"], "int", 7, 30),
            "adx_min": _tracking_parameter("adx_min", params["adx_min"], "int", 10, 40),
            "rsi_period": _tracking_parameter("rsi_period", params["rsi_period"], "int", 7, 30),
            "rsi_pullback_min": _tracking_parameter("rsi_pullback_min", params["rsi_pullback_min"], "int", 20, 40),
            "rsi_pullback_max": _tracking_parameter("rsi_pullback_max", params["rsi_pullback_max"], "int", 45, 70),
            "atr_period": _tracking_parameter("atr_period", params["atr_period"], "int", 7, 30),
        },
    }


def _mean_reversion_sidecar() -> dict[str, Any]:
    params = DEFAULT_MEAN_REVERSION_PARAMS
    return {
        "strategy_name": MEAN_REVERSION_CLASS_NAME,
        "family": MEAN_REVERSION_FAMILY,
        "params": {
            "buy": dict(params),
            "sell": {},
            "roi": {"0": 0.06, "180": 0.04, "480": 0.0},
            "stoploss": {"stoploss": -0.08},
            "trailing": {
                "trailing_stop": False,
                "trailing_stop_positive_offset": 0.0,
                "trailing_only_offset_is_reached": False,
            },
        },
        "parameters": {
            "bb_period": _tracking_parameter("bb_period", params["bb_period"], "int", 10, 30),
            "bb_stddev": _tracking_parameter("bb_stddev", params["bb_stddev"], "float", 1.5, 3.0),
            "rsi_period": _tracking_parameter("rsi_period", params["rsi_period"], "int", 7, 30),
            "rsi_oversold": _tracking_parameter("rsi_oversold", params["rsi_oversold"], "int", 20, 40),
            "rsi_recovery_min": _tracking_parameter("rsi_recovery_min", params["rsi_recovery_min"], "int", 30, 50),
            "ema_guard_period": _tracking_parameter("ema_guard_period", params["ema_guard_period"], "int", 20, 100),
            "atr_period": _tracking_parameter("atr_period", params["atr_period"], "int", 7, 30),
            "adx_period": _tracking_parameter("adx_period", params["adx_period"], "int", 7, 30),
            "adx_max": _tracking_parameter("adx_max", params["adx_max"], "int", 25, 60),
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


def _trend_pullback_strategy_source() -> str:
    return '''from freqtrade.strategy import DecimalParameter, IntParameter, IStrategy
from pandas import DataFrame
import talib.abstract as ta


class TrendPullbackContinuation(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "5m"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 240

    minimal_roi = {
        "0": 0.08,
        "240": 0.03,
        "720": 0.0,
    }
    stoploss = -0.10
    trailing_stop = False
    trailing_stop_positive_offset = 0.0
    trailing_only_offset_is_reached = False

    buy_params = {
        "ema_fast_period": 9,
        "ema_slow_period": 21,
        "adx_period": 14,
        "adx_min": 20,
        "rsi_period": 14,
        "rsi_pullback_min": 25,
        "rsi_pullback_max": 55,
        "atr_period": 14,
    }
    sell_params = {}

    ema_fast_period = IntParameter(5, 20, default=9, space="buy", optimize=True)
    ema_slow_period = IntParameter(15, 50, default=21, space="buy", optimize=True)
    adx_period = IntParameter(7, 30, default=14, space="buy", optimize=True)
    adx_min = IntParameter(10, 40, default=20, space="buy", optimize=True)
    rsi_period = IntParameter(7, 30, default=14, space="buy", optimize=True)
    rsi_pullback_min = IntParameter(20, 40, default=25, space="buy", optimize=True)
    rsi_pullback_max = IntParameter(45, 70, default=55, space="buy", optimize=True)
    atr_period = IntParameter(7, 30, default=14, space="buy", optimize=True)

    atr_stop_mult = 2.0
    volume_window = 30
    relative_volume_min = 1.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ema_fast_period = int(self.ema_fast_period.value)
        ema_slow_period = int(self.ema_slow_period.value)
        adx_period = int(self.adx_period.value)
        rsi_period = int(self.rsi_period.value)
        atr_period = int(self.atr_period.value)

        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=ema_fast_period)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=ema_slow_period)
        dataframe["ema_slow_slope"] = dataframe["ema_slow"] - dataframe["ema_slow"].shift(12)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=adx_period)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=rsi_period)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=atr_period)
        
        dataframe["volume_mean"] = dataframe["volume"].rolling(
            self.volume_window, min_periods=self.volume_window
        ).mean()
        dataframe["relative_volume"] = dataframe["volume"] / dataframe["volume_mean"]
        
        dataframe["pullback_high"] = dataframe["high"].rolling(
            ema_fast_period, min_periods=ema_fast_period
        ).max().shift(1)
        
        dataframe["atr_stop_level"] = dataframe["close"] - (dataframe["atr"] * self.atr_stop_mult)
        
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        above_regime = dataframe["close"] > dataframe["ema_slow"]
        fast_above_slow = dataframe["ema_fast"] > dataframe["ema_slow"]
        positive_slope = dataframe["ema_slow_slope"] > 0
        strong_trend = dataframe["adx"] >= int(self.adx_min.value)
        rsi_pullback = dataframe["rsi"].between(
            int(self.rsi_pullback_min.value),
            int(self.rsi_pullback_max.value)
        )
        reclaimed_fast = dataframe["close"] > dataframe["ema_fast"]
        reclaimed_pullback = dataframe["close"] > dataframe["pullback_high"]
        volume_ok = dataframe["relative_volume"] >= self.relative_volume_min
        atr_ready = dataframe["atr"].notna() & (dataframe["atr"] > 0)

        dataframe.loc[
            above_regime
            & fast_above_slow
            & positive_slope
            & strong_trend
            & rsi_pullback
            & (reclaimed_fast | reclaimed_pullback)
            & volume_ok
            & atr_ready,
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        lost_fast = dataframe["close"] < dataframe["ema_fast"]
        lost_regime = dataframe["close"] < dataframe["ema_slow"]
        atr_stop = dataframe["close"] < dataframe["atr_stop_level"]
        rsi_overextended = dataframe["rsi"] > 70
        rsi_overextended_weak = (
            (dataframe["rsi"] > 70)
            & (dataframe["close"] < dataframe["close"].shift(3))
        )

        dataframe.loc[
            lost_fast | lost_regime | atr_stop | rsi_overextended_weak,
            "exit_long",
        ] = 1
        return dataframe
'''


def _trend_pullback_v2_strategy_source() -> str:
    return '''from freqtrade.strategy import DecimalParameter, IntParameter, IStrategy
from pandas import DataFrame
import talib.abstract as ta


class TrendPullbackContinuationV2(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "5m"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 240

    minimal_roi = {
        "0": 0.08,
        "240": 0.03,
        "720": 0.0,
    }
    stoploss = -0.10
    trailing_stop = False
    trailing_stop_positive_offset = 0.0
    trailing_only_offset_is_reached = False

    buy_params = {
        "ema_fast_period": 9,
        "ema_slow_period": 21,
        "adx_period": 14,
        "adx_min": 20,
        "rsi_period": 14,
        "rsi_pullback_min": 27,
        "rsi_pullback_max": 52,
        "atr_period": 14,
    }
    sell_params = {}

    ema_fast_period = IntParameter(5, 20, default=9, space="buy", optimize=True)
    ema_slow_period = IntParameter(15, 50, default=21, space="buy", optimize=True)
    adx_period = IntParameter(7, 30, default=14, space="buy", optimize=True)
    adx_min = IntParameter(15, 50, default=20, space="buy", optimize=True)
    rsi_period = IntParameter(7, 30, default=14, space="buy", optimize=True)
    rsi_pullback_min = IntParameter(25, 40, default=27, space="buy", optimize=True)
    rsi_pullback_max = IntParameter(40, 60, default=52, space="buy", optimize=True)
    atr_period = IntParameter(7, 30, default=14, space="buy", optimize=True)

    atr_stop_mult = 2.0
    volume_window = 30
    relative_volume_min = 1.15

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ema_fast_period = int(self.ema_fast_period.value)
        ema_slow_period = int(self.ema_slow_period.value)
        adx_period = int(self.adx_period.value)
        rsi_period = int(self.rsi_period.value)
        atr_period = int(self.atr_period.value)

        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=ema_fast_period)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=ema_slow_period)
        dataframe["ema_slow_slope"] = dataframe["ema_slow"] - dataframe["ema_slow"].shift(12)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=adx_period)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=rsi_period)
        dataframe["rsi_slope"] = dataframe["rsi"] - dataframe["rsi"].shift(3)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=atr_period)
        
        dataframe["volume_mean"] = dataframe["volume"].rolling(
            self.volume_window, min_periods=self.volume_window
        ).mean()
        dataframe["relative_volume"] = dataframe["volume"] / dataframe["volume_mean"]
        
        dataframe["pullback_high"] = dataframe["high"].rolling(
            ema_fast_period, min_periods=ema_fast_period
        ).max().shift(1)
        
        dataframe["atr_stop_level"] = dataframe["close"] - (dataframe["atr"] * self.atr_stop_mult)
        
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        above_regime = dataframe["close"] > dataframe["ema_slow"]
        fast_above_slow = dataframe["ema_fast"] > dataframe["ema_slow"]
        positive_slope = dataframe["ema_slow_slope"] > 0
        strong_trend = dataframe["adx"] >= int(self.adx_min.value)
        rsi_pullback = dataframe["rsi"].between(
            int(self.rsi_pullback_min.value),
            int(self.rsi_pullback_max.value)
        )
        rsi_recovering = dataframe["rsi_slope"] > 0
        reclaimed_fast = dataframe["close"] > dataframe["ema_fast"]
        reclaimed_pullback = dataframe["close"] > dataframe["pullback_high"]
        volume_ok = dataframe["relative_volume"] >= self.relative_volume_min
        atr_ready = dataframe["atr"].notna() & (dataframe["atr"] > 0)

        dataframe.loc[
            above_regime
            & fast_above_slow
            & positive_slope
            & strong_trend
            & rsi_pullback
            & (rsi_recovering | reclaimed_pullback)
            & (reclaimed_fast | reclaimed_pullback)
            & volume_ok
            & atr_ready,
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        lost_fast = dataframe["close"] < dataframe["ema_fast"]
        lost_regime = dataframe["close"] < dataframe["ema_slow"]
        atr_stop = dataframe["close"] < dataframe["atr_stop_level"]
        rsi_overextended = dataframe["rsi"] > 70
        rsi_overextended_weak = (
            (dataframe["rsi"] > 70)
            & (dataframe["close"] < dataframe["close"].shift(3))
        )

        dataframe.loc[
            lost_fast | lost_regime | atr_stop | rsi_overextended_weak,
            "exit_long",
        ] = 1
        return dataframe
'''


def _mean_reversion_strategy_source() -> str:
    return """from freqtrade.strategy import DecimalParameter, IntParameter, IStrategy
from pandas import DataFrame
import talib.abstract as ta


class MeanReversionExhaustion(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "5m"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 240

    minimal_roi = {
        "0": 0.06,
        "180": 0.04,
        "480": 0.0,
    }
    stoploss = -0.08
    trailing_stop = False
    trailing_stop_positive_offset = 0.0
    trailing_only_offset_is_reached = False

    buy_params = {
        "bb_period": 20,
        "bb_stddev": 2.0,
        "rsi_period": 14,
        "rsi_oversold": 30,
        "rsi_recovery_min": 35,
        "ema_guard_period": 50,
        "atr_period": 14,
        "adx_period": 14,
        "adx_max": 40,
    }
    sell_params = {}

    bb_period = IntParameter(10, 30, default=20, space="buy", optimize=True)
    bb_stddev = DecimalParameter(1.5, 3.0, default=2.0, decimals=1, space="buy", optimize=True)
    rsi_period = IntParameter(7, 30, default=14, space="buy", optimize=True)
    rsi_oversold = IntParameter(20, 40, default=30, space="buy", optimize=True)
    rsi_recovery_min = IntParameter(30, 50, default=35, space="buy", optimize=True)
    ema_guard_period = IntParameter(20, 100, default=50, space="buy", optimize=True)
    atr_period = IntParameter(7, 30, default=14, space="buy", optimize=True)
    adx_period = IntParameter(7, 30, default=14, space="buy", optimize=True)
    adx_max = IntParameter(25, 60, default=40, space="buy", optimize=True)

    atr_stop_mult = 1.5
    bb_mid_exit_pct = 0.5
    rsi_normalization_level = 55
    volume_window = 20
    relative_volume_min = 1.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        bb_period = int(self.bb_period.value)
        bb_stddev = float(self.bb_stddev.value)
        rsi_period = int(self.rsi_period.value)
        ema_guard_period = int(self.ema_guard_period.value)
        atr_period = int(self.atr_period.value)
        adx_period = int(self.adx_period.value)

        dataframe["bb_middle"] = ta.SMA(dataframe, timeperiod=bb_period)
        bb_std = ta.STDDEV(dataframe, timeperiod=bb_period, nbdev=1.0)
        dataframe["bb_upper"] = dataframe["bb_middle"] + (bb_std * bb_stddev)
        dataframe["bb_lower"] = dataframe["bb_middle"] - (bb_std * bb_stddev)
        
        dataframe["bb_width"] = (dataframe["bb_upper"] - dataframe["bb_lower"]) / dataframe["bb_middle"]
        dataframe["close_bb_lower_dist"] = (dataframe["close"] - dataframe["bb_lower"]) / dataframe["bb_lower"]
        
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=rsi_period)
        dataframe["rsi_slope"] = dataframe["rsi"] - dataframe["rsi"].shift(3)
        
        dataframe["ema_guard"] = ta.EMA(dataframe, timeperiod=ema_guard_period)
        dataframe["price_vs_ema"] = (dataframe["close"] - dataframe["ema_guard"]) / dataframe["ema_guard"]
        
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=atr_period)
        dataframe["atr_stop_level"] = dataframe["close"] - (dataframe["atr"] * self.atr_stop_mult)
        
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=adx_period)
        
        dataframe["volume_mean"] = dataframe["volume"].rolling(
            self.volume_window, min_periods=self.volume_window
        ).mean()
        dataframe["relative_volume"] = dataframe["volume"] / dataframe["volume_mean"]
        
        dataframe["lower_bb_touch"] = dataframe["close"] <= dataframe["bb_lower"]
        dataframe["near_lower_bb"] = dataframe["close_bb_lower_dist"] <= 0.02
        
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        near_lower_bb = dataframe["near_lower_bb"]
        touched_lower_bb = dataframe["lower_bb_touch"]
        
        rsi_oversold = dataframe["rsi"] <= int(self.rsi_oversold.value)
        rsi_recovering = dataframe["rsi_slope"] > 0
        rsi_above_recovery = dataframe["rsi"] >= int(self.rsi_recovery_min.value)
        
        not_strong_bearish = dataframe["price_vs_ema"] > -0.05
        not_severe_downtrend = dataframe["adx"] <= int(self.adx_max.value)
        
        atr_ready = dataframe["atr"].notna() & (dataframe["atr"] > 0)
        volume_ok = dataframe["relative_volume"] >= self.relative_volume_min
        
        stabilization = (
            (dataframe["close"] > dataframe["close"].shift(1))
            | (dataframe["close"] > dataframe["open"])
        )

        dataframe.loc[
            (near_lower_bb | touched_lower_bb)
            & rsi_oversold
            & (rsi_recovering | rsi_above_recovery)
            & not_strong_bearish
            & not_severe_downtrend
            & atr_ready
            & volume_ok
            & stabilization,
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        near_bb_mid = (
            (dataframe["close"] >= dataframe["bb_middle"])
            | (dataframe["close_bb_lower_dist"] >= self.bb_mid_exit_pct)
        )
        
        rsi_normalized = dataframe["rsi"] >= self.rsi_normalization_level
        
        atr_stop = dataframe["close"] < dataframe["atr_stop_level"]
        
        continued_fall = (
            (dataframe["close"] < dataframe["close"].shift(1))
            & (dataframe["close"] < dataframe["open"])
            & (dataframe["close"] < dataframe["bb_lower"])
        )

        dataframe.loc[
            near_bb_mid | rsi_normalized | atr_stop | continued_fall,
            "exit_long",
        ] = 1
        return dataframe
"""
