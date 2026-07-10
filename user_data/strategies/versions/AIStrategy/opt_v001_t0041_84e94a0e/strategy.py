from freqtrade.strategy import IntParameter, IStrategy
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
from functools import reduce
import pandas as pd

class AIStrategy(IStrategy):
    INTERFACE_VERSION: int = 3
    buy_params = {'buy_ma_count': 14, 'buy_ma_gap': 70}
    sell_params = {'sell_ma_count': 8, 'sell_ma_gap': 39}
    minimal_roi = {'0': 0.192, '1553': 0.123, '2332': 0.076, '3169': 0.0, '12': 0.061, '33': 0.017, '145': 0.0}
    stoploss = -0.336
    trailing_stop = False
    trailing_stop_positive = None
    trailing_stop_positive_offset = 0.0
    trailing_only_offset_is_reached = False
    timeframe = '4h'
    count_max = 20
    gap_max = 100
    buy_ma_count = IntParameter(1, count_max, default=7, space='buy')
    buy_ma_gap = IntParameter(1, gap_max, default=7, space='buy')
    sell_ma_count = IntParameter(1, count_max, default=7, space='sell')
    sell_ma_gap = IntParameter(1, gap_max, default=94, space='sell')

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
        print(' ', metadata['pair'], end='\t\r')
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []
        for ma_count in range(self.buy_ma_count.value):
            key = ma_count * self.buy_ma_gap.value
            past_key = (ma_count - 1) * self.buy_ma_gap.value
            if past_key > 1 and key in dataframe.keys() and (past_key in dataframe.keys()):
                conditions.append(dataframe[key] < dataframe[past_key])
        if conditions:
            dataframe.loc[reduce(lambda x, y: x & y, conditions), 'enter_long'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []
        for ma_count in range(self.sell_ma_count.value):
            key = ma_count * self.sell_ma_gap.value
            past_key = (ma_count - 1) * self.sell_ma_gap.value
            if past_key > 1 and key in dataframe.keys() and (past_key in dataframe.keys()):
                conditions.append(dataframe[key] > dataframe[past_key])
        if conditions:
            dataframe.loc[reduce(lambda x, y: x | y, conditions), 'exit_long'] = 1
        return dataframe