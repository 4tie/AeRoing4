"""Market-aware strategy template generators for the Auto-Quant pipeline.

Produces freqtrade strategies with dynamic indicator selection based on
detected market conditions, using the comprehensive indicator library.
"""

from __future__ import annotations


def generate_strategy_source_market_aware(class_name: str, selected_indicators: list) -> str:
    """Return a complete freqtrade strategy with market-aware indicator selection.

    The strategy dynamically selects indicators based on detected market conditions
    using the comprehensive indicator library. Each indicator has Boolean switches
    for activation and optimizable parameters for hyperopt tuning.

    Args:
        class_name: Name of the strategy class
        selected_indicators: List of indicator names to include in the strategy

    Returns:
        Complete strategy source code
    """
    # Generate indicator parameters and computation code
    indicator_params = []
    indicator_computation = []
    indicator_signals = []
    
    for ind_name in selected_indicators:
        if ind_name == "rsi":
            indicator_params.append(
                "use_rsi = CategoricalParameter([True, False], default=True, space='buy', optimize=True)\n"
                "rsi_period = IntParameter(10, 20, default=14, space='buy', optimize=True)\n"
                "rsi_oversold = IntParameter(20, 35, default=30, space='buy', optimize=True)"
            )
            indicator_computation.append(
                "dataframe['rsi'] = ta.RSI(dataframe, timeperiod=self.rsi_period.value)"
            )
            indicator_signals.append(
                "if self.use_rsi.value:\n"
                "    conditions.append(dataframe['rsi'] < self.rsi_oversold.value)"
            )
        elif ind_name == "macd":
            indicator_params.append(
                "use_macd = CategoricalParameter([True, False], default=True, space='buy', optimize=True)\n"
                "macd_fast = IntParameter(8, 15, default=12, space='buy', optimize=True)\n"
                "macd_slow = IntParameter(20, 30, default=26, space='buy', optimize=True)\n"
                "macd_signal = IntParameter(5, 10, default=9, space='buy', optimize=True)"
            )
            indicator_computation.append(
                "macd = ta.MACD(dataframe, fastperiod=self.macd_fast.value, \n"
                "               slowperiod=self.macd_slow.value, \n"
                "               signalperiod=self.macd_signal.value)\n"
                "dataframe['macd'] = macd['macd']\n"
                "dataframe['macdsignal'] = macd['macdsignal']\n"
                "dataframe['macdhist'] = macd['macdhist']"
            )
            indicator_signals.append(
                "if self.use_macd.value:\n"
                "    conditions.append(qtpylib.crossed_above(dataframe['macd'], dataframe['macdsignal']))"
            )
        elif ind_name == "bollinger_bands":
            indicator_params.append(
                "use_bb = CategoricalParameter([True, False], default=True, space='buy', optimize=True)\n"
                "bb_period = IntParameter(15, 25, default=20, space='buy', optimize=True)\n"
                "bb_std = DecimalParameter(1.5, 2.5, default=2.0, decimals=1, space='buy', optimize=True)"
            )
            indicator_computation.append(
                "bollinger = qtpylib.bollinger_bands(\n"
                "    qtpylib.typical_price(dataframe), window=self.bb_period.value, stds=self.bb_std.value\n"
                ")\n"
                "dataframe['bb_lowerband'] = bollinger['lower']\n"
                "dataframe['bb_upperband'] = bollinger['upper']"
            )
            indicator_signals.append(
                "if self.use_bb.value:\n"
                "    conditions.append(dataframe['close'] <= dataframe['bb_lowerband'])"
            )
        elif ind_name == "ema_crossover":
            indicator_params.append(
                "use_ema = CategoricalParameter([True, False], default=False, space='buy', optimize=True)\n"
                "ema_fast = IntParameter(5, 30, default=9, space='buy', optimize=True)\n"
                "ema_slow = IntParameter(15, 50, default=21, space='buy', optimize=True)"
            )
            indicator_computation.append(
                "dataframe['ema_fast'] = ta.EMA(dataframe, timeperiod=self.ema_fast.value)\n"
                "dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=self.ema_slow.value)"
            )
            indicator_signals.append(
                "if self.use_ema.value:\n"
                "    conditions.append(dataframe['ema_fast'] > dataframe['ema_slow'])"
            )
        elif ind_name == "adx":
            indicator_params.append(
                "use_adx = CategoricalParameter([True, False], default=False, space='buy', optimize=True)\n"
                "adx_period = IntParameter(10, 20, default=14, space='buy', optimize=True)\n"
                "adx_threshold = IntParameter(15, 40, default=25, space='buy', optimize=True)"
            )
            indicator_computation.append(
                "dataframe['adx'] = ta.ADX(dataframe, timeperiod=self.adx_period.value)"
            )
            indicator_signals.append(
                "if self.use_adx.value:\n"
                "    conditions.append(dataframe['adx'] > self.adx_threshold.value)"
            )
        elif ind_name == "atr":
            indicator_params.append(
                "use_atr = CategoricalParameter([True, False], default=False, space='buy', optimize=True)\n"
                "atr_period = IntParameter(10, 20, default=14, space='buy', optimize=True)"
            )
            indicator_computation.append(
                "dataframe['atr'] = ta.ATR(dataframe, timeperiod=self.atr_period.value)\n"
                "dataframe['atr_median'] = dataframe['atr'].rolling(window=self.atr_period.value).median()"
            )
            indicator_signals.append(
                "if self.use_atr.value:\n"
                "    conditions.append(dataframe['atr'] > dataframe['atr_median'])"
            )
        elif ind_name == "stochastic":
            indicator_params.append(
                "use_stoch = CategoricalParameter([True, False], default=False, space='buy', optimize=True)\n"
                "stoch_threshold = IntParameter(20, 40, default=30, space='buy', optimize=True)"
            )
            indicator_computation.append(
                "stoch = ta.STOCH(dataframe, fastk_period=14, slowk_period=3, slowd_period=3)\n"
                "dataframe['stoch_slowk'] = stoch['slowk']\n"
                "dataframe['stoch_slowd'] = stoch['slowd']"
            )
            indicator_signals.append(
                "if self.use_stoch.value:\n"
                "    conditions.append(dataframe['stoch_slowk'] < self.stoch_threshold.value)"
            )
    
    params_str = "\n    ".join(indicator_params)
    computation_str = "\n        ".join(indicator_computation)
    signals_str = "\n        ".join(indicator_signals)
    
    return f'''\
# Auto-generated by Strategy Lab — Auto-Quant Factory (Market-Aware Indicator Library)
# Dynamic indicator selection based on market conditions with confirmation logic.
# Optimise with: freqtrade hyperopt --strategy {class_name} --spaces buy roi stoploss

from functools import reduce
import operator

from freqtrade.strategy import CategoricalParameter, IntParameter, DecimalParameter, IStrategy
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib


class {class_name}(IStrategy):
    INTERFACE_VERSION: int = 3

    minimal_roi = {{
        "0": 0.08,
        "30": 0.04,
        "60": 0.02,
        "120": 0,
    }}

    stoploss = -0.05
    timeframe = "5m"
    trailing_stop = False
    process_only_new_candles = True

    # ── Indicator activation switches ─────────────────────────────────────
    {params_str}

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Compute all indicators
        {computation_str}
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = [dataframe["volume"] > 0]
        
        # Collect indicator signals
        {signals_str}
        
        # Require at least 2 indicators to confirm (majority confirmation)
        if len(conditions) > 1:
            combined = reduce(operator.and_, conditions)
            dataframe.loc[combined, "enter_long"] = 1
        
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe
'''


def generate_strategy_source_indicator_library(class_name: str) -> str:
    """Return a complete freqtrade strategy with full indicator library access.

    This template provides access to the comprehensive indicator library with
    market condition detection and dynamic indicator selection. The strategy
    automatically adapts to market conditions and selects appropriate indicators.

    Args:
        class_name: Name of the strategy class

    Returns:
        Complete strategy source code with full indicator library integration
    """
    return f'''\
# Auto-generated by Strategy Lab — Auto-Quant Factory (Full Indicator Library)
# Comprehensive indicator library with market condition detection and dynamic selection.
# Optimise with: freqtrade hyperopt --strategy {class_name} --spaces buy roi stoploss

from functools import reduce
import operator

from freqtrade.strategy import CategoricalParameter, IntParameter, DecimalParameter, IStrategy
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np


class {class_name}(IStrategy):
    INTERFACE_VERSION: int = 3

    minimal_roi = {{
        "0": 0.08,
        "30": 0.04,
        "60": 0.02,
        "120": 0,
    }}

    stoploss = -0.05
    timeframe = "5m"
    trailing_stop = False
    process_only_new_candles = True

    # ── Market condition detection parameters ─────────────────────────────
    atr_period = IntParameter(10, 20, default=14, space="buy", optimize=True)
    adx_period = IntParameter(10, 20, default=14, space="buy", optimize=True)
    
    # ── Indicator activation switches (by category) ───────────────────────
    # Trend indicators
    use_ema_cross = CategoricalParameter([True, False], default=False, space="buy", optimize=True)
    use_adx = CategoricalParameter([True, False], default=False, space="buy", optimize=True)
    use_parabolic_sar = CategoricalParameter([True, False], default=False, space="buy", optimize=True)
    
    # Momentum indicators
    use_rsi = CategoricalParameter([True, False], default=True, space="buy", optimize=True)
    use_macd = CategoricalParameter([True, False], default=True, space="buy", optimize=True)
    use_stochastic = CategoricalParameter([True, False], default=False, space="buy", optimize=True)
    use_cci = CategoricalParameter([True, False], default=False, space="buy", optimize=True)
    use_williams_r = CategoricalParameter([True, False], default=False, space="buy", optimize=True)
    
    # Volatility indicators
    use_bollinger = CategoricalParameter([True, False], default=True, space="buy", optimize=True)
    use_atr_filter = CategoricalParameter([True, False], default=False, space="buy", optimize=True)
    use_keltner = CategoricalParameter([True, False], default=False, space="buy", optimize=True)
    
    # Volume indicators
    use_obv = CategoricalParameter([True, False], default=False, space="buy", optimize=True)
    use_mfi = CategoricalParameter([True, False], default=False, space="buy", optimize=True)
    
    # ── Indicator parameters ───────────────────────────────────────────────
    rsi_period = IntParameter(10, 20, default=14, space="buy", optimize=True)
    rsi_oversold = IntParameter(20, 35, default=30, space="buy", optimize=True)
    
    macd_fast = IntParameter(8, 15, default=12, space="buy", optimize=True)
    macd_slow = IntParameter(20, 30, default=26, space="buy", optimize=True)
    macd_signal = IntParameter(5, 10, default=9, space="buy", optimize=True)
    
    ema_fast = IntParameter(5, 30, default=9, space="buy", optimize=True)
    ema_slow = IntParameter(15, 50, default=21, space="buy", optimize=True)
    
    adx_threshold = IntParameter(15, 40, default=25, space="buy", optimize=True)
    
    bb_period = IntParameter(15, 25, default=20, space="buy", optimize=True)
    bb_std = DecimalParameter(1.5, 2.5, default=2.0, decimals=1, space="buy", optimize=True)
    
    stoch_threshold = IntParameter(20, 40, default=30, space="buy", optimize=True)
    cci_threshold = IntParameter(-120, -80, default=-100, space="buy", optimize=True)
    willr_threshold = IntParameter(-90, -70, default=-80, space="buy", optimize=True)
    
    mfi_threshold = IntParameter(20, 40, default=30, space="buy", optimize=True)
    
    # ── Confirmation requirements ─────────────────────────────────────────
    min_confirmations = IntParameter(1, 3, default=2, space="buy", optimize=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Market condition detection
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.atr_period.value)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=self.adx_period.value)
        dataframe["atr_median"] = dataframe["atr"].rolling(window=self.atr_period.value).median()
        
        # Detect market regime
        dataframe["is_trending"] = (dataframe["atr"] > dataframe["atr_median"]) & (dataframe["adx"] > 25)
        dataframe["is_ranging"] = (dataframe["atr"] <= dataframe["atr_median"]) & (dataframe["adx"] < 25)
        dataframe["is_high_vol"] = dataframe["atr"] > dataframe["atr_median"] * 1.3
        dataframe["is_low_vol"] = dataframe["atr"] < dataframe["atr_median"] * 0.7
        
        # Trend indicators
        if self.use_ema_cross.value:
            dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=self.ema_fast.value)
            dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=self.ema_slow.value)
        
        if self.use_adx.value:
            dataframe["adx"] = ta.ADX(dataframe, timeperiod=self.adx_period.value)
        
        if self.use_parabolic_sar.value:
            dataframe["sar"] = ta.SAR(dataframe, acceleration=0.02, maximum=0.2)
        
        # Momentum indicators
        if self.use_rsi.value:
            dataframe["rsi"] = ta.RSI(dataframe, timeperiod=self.rsi_period.value)
        
        if self.use_macd.value:
            macd = ta.MACD(dataframe, fastperiod=self.macd_fast.value, 
                           slowperiod=self.macd_slow.value, 
                           signalperiod=self.macd_signal.value)
            dataframe["macd"] = macd["macd"]
            dataframe["macdsignal"] = macd["macdsignal"]
            dataframe["macdhist"] = macd["macdhist"]
        
        if self.use_stochastic.value:
            stoch = ta.STOCH(dataframe, fastk_period=14, slowk_period=3, slowd_period=3)
            dataframe["stoch_slowk"] = stoch["slowk"]
            dataframe["stoch_slowd"] = stoch["slowd"]
        
        if self.use_cci.value:
            dataframe["cci"] = ta.CCI(dataframe, timeperiod=20)
        
        if self.use_williams_r.value:
            dataframe["willr"] = ta.WILLR(dataframe, timeperiod=14)
        
        # Volatility indicators
        if self.use_bollinger.value:
            bollinger = qtpylib.bollinger_bands(
                qtpylib.typical_price(dataframe), window=self.bb_period.value, stds=self.bb_std.value
            )
            dataframe["bb_lowerband"] = bollinger["lower"]
            dataframe["bb_upperband"] = bollinger["upper"]
        
        if self.use_atr_filter.value:
            dataframe["atr_filter"] = dataframe["atr"] > dataframe["atr_median"]
        
        if self.use_keltner.value:
            atr = ta.ATR(dataframe, timeperiod=self.atr_period.value)
            ema = ta.EMA(dataframe, timeperiod=self.bb_period.value)
            dataframe["kc_upper"] = ema + (atr * 2.0)
            dataframe["kc_lower"] = ema - (atr * 2.0)
        
        # Volume indicators
        if self.use_obv.value:
            dataframe["obv"] = ta.OBV(dataframe)
        
        if self.use_mfi.value:
            dataframe["mfi"] = ta.MFI(dataframe, timeperiod=14)
        
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = [dataframe["volume"] > 0]
        
        # Trend indicators
        if self.use_ema_cross.value:
            conditions.append(dataframe["ema_fast"] > dataframe["ema_slow"])
        
        if self.use_adx.value:
            conditions.append(dataframe["adx"] > self.adx_threshold.value)
        
        if self.use_parabolic_sar.value:
            conditions.append(dataframe["close"] > dataframe["sar"])
        
        # Momentum indicators
        if self.use_rsi.value:
            conditions.append(dataframe["rsi"] < self.rsi_oversold.value)
        
        if self.use_macd.value:
            conditions.append(qtpylib.crossed_above(dataframe["macd"], dataframe["macdsignal"]))
        
        if self.use_stochastic.value:
            conditions.append(dataframe["stoch_slowk"] < self.stoch_threshold.value)
        
        if self.use_cci.value:
            conditions.append(dataframe["cci"] < self.cci_threshold.value)
        
        if self.use_williams_r.value:
            conditions.append(dataframe["willr"] < self.willr_threshold.value)
        
        # Volatility indicators
        if self.use_bollinger.value:
            conditions.append(dataframe["close"] <= dataframe["bb_lowerband"])
        
        if self.use_atr_filter.value:
            conditions.append(dataframe["atr_filter"])
        
        if self.use_keltner.value:
            conditions.append(dataframe["close"] <= dataframe["kc_lower"])
        
        # Volume indicators
        if self.use_obv.value:
            conditions.append(dataframe["obv"] > dataframe["obv"].rolling(20).mean())
        
        if self.use_mfi.value:
            conditions.append(dataframe["mfi"] < self.mfi_threshold.value)
        
        # Apply confirmation logic
        if len(conditions) > self.min_confirmations.value:
            # Require minimum confirmations
            combined = reduce(operator.and_, conditions[:self.min_confirmations.value + 1])
            dataframe.loc[combined, "enter_long"] = 1
        
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe
'''
