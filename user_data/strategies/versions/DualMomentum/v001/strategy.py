from freqtrade.strategy import IntParameter, DecimalParameter, IStrategy
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib


class DualMomentum(IStrategy):
    can_short: bool = True

    INTERFACE_VERSION: int = 3

    minimal_roi = {
        "0": 0.02,
        "30": 0.01,
        "60": 0.005,
        "120": 0,
    }

    stoploss = -0.03
    timeframe = "15m"
    process_only_new_candles = True
    startup_candle_count = 100

    # --- Hyperoptable parameters ---

    # EMA periods
    ema_fast = IntParameter(5, 15, default=8, space="buy", optimize=True)
    ema_slow = IntParameter(20, 50, default=21, space="buy", optimize=True)

    # RSI thresholds for long entries
    rsi_long_min = IntParameter(45, 60, default=50, space="buy", optimize=True)
    rsi_long_max = IntParameter(60, 75, default=65, space="buy", optimize=True)

    # RSI thresholds for short entries
    rsi_short_min = IntParameter(25, 40, default=35, space="sell", optimize=True)
    rsi_short_max = IntParameter(40, 55, default=50, space="sell", optimize=True)

    # RSI exit thresholds
    rsi_long_exit = IntParameter(35, 50, default=45, space="sell", optimize=True)
    rsi_short_exit = IntParameter(50, 65, default=55, space="buy", optimize=True)

    # Volume filter
    volume_mult = DecimalParameter(0.8, 2.0, default=1.0, space="buy", optimize=False)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=self.ema_fast.value)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=self.ema_slow.value)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["volume_median"] = (
            dataframe["volume"].rolling(window=20, min_periods=1).median()
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # LONG: uptrend (fast > slow) + RSI in bullish range
        dataframe.loc[
            (
                (dataframe["ema_fast"] > dataframe["ema_slow"])
                & (dataframe["rsi"] > self.rsi_long_min.value)
                & (dataframe["rsi"] < self.rsi_long_max.value)
                & (dataframe["volume"] > dataframe["volume_median"] * self.volume_mult.value)
            ),
            "enter_long",
        ] = 1

        # SHORT: downtrend (fast < slow) + RSI in bearish range
        dataframe.loc[
            (
                (dataframe["ema_fast"] < dataframe["ema_slow"])
                & (dataframe["rsi"] > self.rsi_short_min.value)
                & (dataframe["rsi"] < self.rsi_short_max.value)
                & (dataframe["volume"] > dataframe["volume_median"] * self.volume_mult.value)
            ),
            "enter_short",
        ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # EXIT LONG: trend reversed (fast < slow) OR RSI dropped too far
        dataframe.loc[
            (
                qtpylib.crossed_below(dataframe["ema_fast"], dataframe["ema_slow"])
                | (dataframe["rsi"] < self.rsi_long_exit.value)
            ),
            "exit_long",
        ] = 1

        # EXIT SHORT: trend reversed (fast > slow) OR RSI rose too far
        dataframe.loc[
            (
                qtpylib.crossed_above(dataframe["ema_fast"], dataframe["ema_slow"])
                | (dataframe["rsi"] > self.rsi_short_exit.value)
            ),
            "exit_short",
        ] = 1

        return dataframe
