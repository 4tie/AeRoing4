# MultiMa Strategy V2
# Author: @Mablue (Masoud Azizi)
# github: https://github.com/mablue/

# --- Do not remove these libs ---
from freqtrade.strategy import IntParameter, IStrategy
from pandas import DataFrame

# --------------------------------

# Add your lib to import here
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
from functools import reduce
import pandas as pd


class AIStrategy(IStrategy):
    # 111/2000:     18 trades. 12/4/2 Wins/Draws/Losses. Avg profit   9.72%. Median profit   3.01%. Total profit  733.01234143 USDT (  73.30%). Avg duration 2 days, 18:40:00 min. Objective: 1.67048

    INTERFACE_VERSION: int = 3
    # Buy hyperspace params:
    buy_params = {
        "buy_ma_count": 18,
        "buy_ma_gap": 95,
    }

    # Sell hyperspace params:
    sell_params = {
        "sell_ma_count": 17,
        "sell_ma_gap": 54,
    }

    # ROI table:
    minimal_roi = {
        "0": 0.192,
        "12": 0.061,
        "33": 0.017,
        "145": 0.0,
        "1553": 0.123,
        "2332": 0.076,
        "3169": 0
    }

    # Stoploss:
    stoploss = -0.336

    # Trailing stop:
    trailing_stop = False  # value loaded from strategy
    trailing_stop_positive = None  # value loaded from strategy
    trailing_stop_positive_offset = 0.0  # value loaded from strategy
    trailing_only_offset_is_reached = False  # value loaded from strategy

    # Opimal Timeframe
    timeframe = "4h"

    count_max = 20
    gap_max = 100

    buy_ma_count = IntParameter(1, count_max, default=18, space="buy")
    buy_ma_gap = IntParameter(1, gap_max, default=95, space="buy")

    sell_ma_count = IntParameter(1, count_max, default=17, space="sell")
    sell_ma_gap = IntParameter(1, gap_max, default=54, space="sell")

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        periods = set()
        for ma_count in range(1, int(self.buy_ma_count.value)):
            periods.add(ma_count * int(self.buy_ma_gap.value))
        for ma_count in range(1, int(self.sell_ma_count.value)):
            periods.add(ma_count * int(self.sell_ma_gap.value))

        periods = sorted([p for p in periods if p > 1])

        new_cols = {}
        for p in periods:
            if p not in dataframe.columns:
                new_cols[p] = ta.TEMA(dataframe, timeperiod=int(p))

        if new_cols:
            dataframe = pd.concat([dataframe, pd.DataFrame(new_cols)], axis=1)
        print(" ", metadata['pair'], end="\t\r")

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []
        # I used range(self.buy_ma_count.value) instade of self.buy_ma_count.range
        # Cuz it returns range(7,8) but we need range(8) for all modes hyperopt, backtest and etc

        for ma_count in range(self.buy_ma_count.value):
            key = ma_count*self.buy_ma_gap.value
            past_key = (ma_count-1)*self.buy_ma_gap.value
            if past_key > 1 and key in dataframe.keys() and past_key in dataframe.keys():
                conditions.append(dataframe[key] < dataframe[past_key])

        if conditions:
            dataframe.loc[reduce(lambda x, y: x & y, conditions), "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []

        for ma_count in range(self.sell_ma_count.value):
            key = ma_count*self.sell_ma_gap.value
            past_key = (ma_count-1)*self.sell_ma_gap.value
            if past_key > 1 and key in dataframe.keys() and past_key in dataframe.keys():
                conditions.append(dataframe[key] > dataframe[past_key])

        if conditions:
            dataframe.loc[reduce(lambda x, y: x | y, conditions), "exit_long"] = 1
        return dataframe
