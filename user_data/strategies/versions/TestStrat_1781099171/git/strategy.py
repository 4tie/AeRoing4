from freqtrade.strategy import CategoricalParameter, IStrategy
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib

class TestStrat_1781099171(IStrategy):
    INTERFACE_VERSION: int = 3
    minimal_roi = {'0': 0.1, '30': 0.05, '60': 0.02, '120': 0.0}
    stoploss = -0.05
    timeframe = '5m'
    trailing_stop = False
    entry_logic = CategoricalParameter(['macd_cross', 'rsi_oversold', 'bb_breakout'], default='macd_cross', space='buy', optimize=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe['bb_lowerband'] = bollinger['lower']
        dataframe['bb_middleband'] = bollinger['mid']
        dataframe['bb_upperband'] = bollinger['upper']
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        logic = self.entry_logic.value
        if logic == 'macd_cross':
            dataframe.loc[qtpylib.crossed_above(dataframe['macd'], dataframe['macdsignal']) & (dataframe['volume'] > 0), 'enter_long'] = 1
        elif logic == 'rsi_oversold':
            dataframe.loc[(dataframe['rsi'] < 30) & (dataframe['volume'] > 0), 'enter_long'] = 1
        elif logic == 'bb_breakout':
            dataframe.loc[(dataframe['close'] < dataframe['bb_lowerband']) & (dataframe['volume'] > 0), 'enter_long'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe