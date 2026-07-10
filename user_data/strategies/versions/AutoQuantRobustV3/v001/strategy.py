from freqtrade.strategy import IntParameter, IStrategy
from pandas import DataFrame
import talib.abstract as ta
from functools import reduce


class AutoQuantRobustV3(IStrategy):
    INTERFACE_VERSION: int = 3

    # ROI Table - based on MultiMa success
    minimal_roi = {
        "0": 0.08,
        "240": 0.04,
        "720": 0.02,
        "1440": 0,
    }

    # Stoploss - wider to allow room for volatility
    stoploss = -0.15

    # Timeframe - 4h like MultiMa
    timeframe = "4h"

    # Trailing stop
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True

    # Process only new candles
    process_only_new_candles = True
    startup_candle_count = 200

    # ── Tunable Parameters for Optimizer ──
    
    # TEMA parameters
    buy_ma_count = IntParameter(2, 8, default=3, space="buy", optimize=True)
    buy_ma_gap = IntParameter(5, 20, default=10, space="buy", optimize=True)
    
    sell_ma_count = IntParameter(2, 8, default=4, space="sell", optimize=True)
    sell_ma_gap = IntParameter(10, 30, default=20, space="sell", optimize=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Compute only needed TEMA periods to save memory
        needed_periods = set()
        
        # Buy side periods
        for ma_count in range(self.buy_ma_count.value + 1):
            needed_periods.add(ma_count * self.buy_ma_gap.value)
        
        # Sell side periods
        for ma_count in range(self.sell_ma_count.value + 1):
            needed_periods.add(ma_count * self.sell_ma_gap.value)
        
        # Compute TEMA indicators
        for period in needed_periods:
            if period > 1:
                dataframe[f"tema_{int(period)}"] = ta.TEMA(dataframe, timeperiod=int(period))

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Entry based on TEMA alignment (multiple MAs pointing down)
        """
        conditions = []
        
        for ma_count in range(self.buy_ma_count.value):
            key = ma_count * self.buy_ma_gap.value
            past_key = (ma_count - 1) * self.buy_ma_gap.value
            if past_key > 1:
                tema_current = f"tema_{int(key)}"
                tema_past = f"tema_{int(past_key)}"
                if tema_current in dataframe.columns and tema_past in dataframe.columns:
                    # Price below shorter TEMA, shorter TEMA below longer TEMA
                    conditions.append(
                        (dataframe["close"] < dataframe[tema_current]) &
                        (dataframe[tema_current] < dataframe[tema_past])
                    )

        if conditions:
            dataframe.loc[reduce(lambda x, y: x & y, conditions), "enter_long"] = 1
        
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Exit based on TEMA reversal (shorter TEMA crosses above longer TEMA)
        """
        conditions = []
        
        for ma_count in range(self.sell_ma_count.value):
            key = ma_count * self.sell_ma_gap.value
            past_key = (ma_count - 1) * self.sell_ma_gap.value
            if past_key > 1:
                tema_current = f"tema_{int(key)}"
                tema_past = f"tema_{int(past_key)}"
                if tema_current in dataframe.columns and tema_past in dataframe.columns:
                    # Shorter TEMA crosses above longer TEMA
                    conditions.append(dataframe[tema_current] > dataframe[tema_past])

        if conditions:
            dataframe.loc[reduce(lambda x, y: x | y, conditions), "exit_long"] = 1
        
        return dataframe
