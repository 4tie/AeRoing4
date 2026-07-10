import talib.abstract as ta
import pandas as pd
from freqtrade.strategy import IStrategy

class MeanReversion_v1(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = '5m'
    minimal_roi = {'0': 0.154, '23': 0.12, '72': 0.023, '190': 0.004}
    stoploss = -0.24
    max_open_trades = 3

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['ema2000'] = ta.EMA(dataframe, timeperiod=2000)
        return dataframe

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe.loc[(dataframe['rsi'] < 22) & (dataframe['close'] > dataframe['ema2000']), 'enter_long'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe['exit_long'] = 0
        return dataframe