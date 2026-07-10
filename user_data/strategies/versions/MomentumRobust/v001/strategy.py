from freqtrade.strategy import IntParameter, DecimalParameter, IStrategy
from pandas import DataFrame
import talib.abstract as ta


class MomentumRobust(IStrategy):
    INTERFACE_VERSION: int = 3

    minimal_roi = {
        "0": 0.02,
        "4": 0.015,
        "8": 0.01,
        "16": 0.005,
        "32": 0,
    }

    stoploss = -0.03
    timeframe = "1h"
    trailing_stop = False
    process_only_new_candles = True
    startup_candle_count = 30

    rsi_oversold = IntParameter(25, 40, default=35, space="buy", optimize=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["rsi"] < self.rsi_oversold.value)
            ),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["rsi"] > 60)
            ),
            "exit_long",
        ] = 1
        return dataframe
