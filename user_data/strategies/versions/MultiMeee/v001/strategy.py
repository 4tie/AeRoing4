# MultiMa Strategy V2
# Author: @Mablue (Masoud Azizi)
# github: https://github.com/mablue/

from functools import reduce

import pandas as pd
import talib.abstract as ta
from freqtrade.strategy import IntParameter, IStrategy
from pandas import DataFrame


class MultiMeee(IStrategy):
    INTERFACE_VERSION: int = 3

    # --- ROI ---
    minimal_roi = {
        "0": 0.109,
        "13": 0.034,
        "38": 0.024,
        "146": 0,
    }

    # --- Stoploss ---
    stoploss = -0.245

    # --- Trailing stop ---
    trailing_stop = True
    trailing_stop_positive = 0.334
    trailing_stop_positive_offset = 0.371
    trailing_only_offset_is_reached = False

    # --- Misc ---
    max_open_trades = 2
    timeframe = "5m"
    can_short = False

    # --- Hyperopt parameters ---
    buy_ma_count = IntParameter(1, 20, default=16, space="buy")
    buy_ma_gap = IntParameter(1, 50, default=34, space="buy")
    sell_ma_count = IntParameter(1, 20, default=2, space="sell")
    sell_ma_gap = IntParameter(1, 50, default=23, space="sell")

    @staticmethod
    def _tema_column_name(period: int) -> str:
        """Return the TEMA column name for a given period."""
        return f"tema_{int(period)}"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Compute all TEMA columns needed by entry/exit logic."""
        needed_periods: set = set()

        for ma_count in range(self.buy_ma_count.value + 1):
            needed_periods.add(ma_count * self.buy_ma_gap.value)

        for ma_count in range(self.sell_ma_count.value + 1):
            needed_periods.add(ma_count * self.sell_ma_gap.value)

        new_cols = {}
        for period in needed_periods:
            if period > 1:
                col_name = self._tema_column_name(period)
                if col_name not in dataframe.columns:
                    new_cols[col_name] = ta.TEMA(dataframe, timeperiod=int(period))

        if new_cols:
            dataframe = pd.concat(
                [dataframe, DataFrame(new_cols, index=dataframe.index)], axis=1
            )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Enter long when each successive TEMA is below the previous one (downward stack)."""
        conditions = []

        for ma_count in range(1, self.buy_ma_count.value + 1):
            key_period = ma_count * self.buy_ma_gap.value
            past_key_period = (ma_count - 1) * self.buy_ma_gap.value

            if past_key_period > 1:
                key = self._tema_column_name(key_period)
                past_key = self._tema_column_name(past_key_period)

                if key in dataframe.columns and past_key in dataframe.columns:
                    conditions.append(dataframe[key] < dataframe[past_key])

        if conditions:
            dataframe.loc[reduce(lambda x, y: x & y, conditions), "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Exit long when any successive TEMA is above the previous one (upward cross)."""
        conditions = []

        for ma_count in range(1, self.sell_ma_count.value + 1):
            key_period = ma_count * self.sell_ma_gap.value
            past_key_period = (ma_count - 1) * self.sell_ma_gap.value

            if past_key_period > 1:
                key = self._tema_column_name(key_period)
                past_key = self._tema_column_name(past_key_period)

                if key in dataframe.columns and past_key in dataframe.columns:
                    conditions.append(dataframe[key] > dataframe[past_key])

        if conditions:
            dataframe.loc[reduce(lambda x, y: x | y, conditions), "exit_long"] = 1
        return dataframe
