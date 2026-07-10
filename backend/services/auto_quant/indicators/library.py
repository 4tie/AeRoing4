"""Indicator Library with market condition categorization.

Defines comprehensive indicator library with computation methods, parameters,
and market condition suitability for AutoQuant dynamic selection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class MarketCondition(Enum):
    """Market condition categories for indicator selection."""
    TRENDING = "trending"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"


class IndicatorCategory(Enum):
    """Indicator functional categories."""
    TREND = "trend"
    MOMENTUM = "momentum"
    VOLATILITY = "volatility"
    VOLUME = "volume"
    PATTERN = "pattern"


@dataclass
class IndicatorDefinition:
    """Definition of a technical indicator with its properties."""
    
    name: str
    category: IndicatorCategory
    market_conditions: List[MarketCondition]
    computation: Callable[[Any, Dict[str, Any]], Any]
    default_params: Dict[str, Any] = field(default_factory=dict)
    param_ranges: Dict[str, tuple] = field(default_factory=dict)
    description: str = ""
    requires_volume: bool = False
    confirmation_weight: float = 1.0


class IndicatorLibrary:
    """Central registry of all available indicators."""
    
    def __init__(self):
        self._indicators: Dict[str, IndicatorDefinition] = {}
        self._register_default_indicators()
    
    def register(self, indicator: IndicatorDefinition) -> None:
        """Register a new indicator definition."""
        self._indicators[indicator.name] = indicator
    
    def get(self, name: str) -> Optional[IndicatorDefinition]:
        """Get indicator definition by name."""
        return self._indicators.get(name)
    
    def get_by_category(self, category: IndicatorCategory) -> List[IndicatorDefinition]:
        """Get all indicators in a category."""
        return [ind for ind in self._indicators.values() if ind.category == category]
    
    def get_by_market_condition(self, condition: MarketCondition) -> List[IndicatorDefinition]:
        """Get indicators suitable for a market condition."""
        return [
            ind for ind in self._indicators.values()
            if condition in ind.market_conditions
        ]
    
    def list_all(self) -> List[str]:
        """List all registered indicator names."""
        return list(self._indicators.keys())
    
    def _register_default_indicators(self) -> None:
        """Register the default indicator library."""
        
        # Trend Indicators
        self.register(IndicatorDefinition(
            name="ema_crossover",
            category=IndicatorCategory.TREND,
            market_conditions=[MarketCondition.TRENDING, MarketCondition.HIGH_VOLATILITY],
            computation=self._compute_ema_crossover,
            default_params={"fast_period": 9, "slow_period": 21},
            param_ranges={"fast_period": (5, 30), "slow_period": (15, 50)},
            description="EMA fast/slow crossover for trend following",
            confirmation_weight=1.2,
        ))
        
        self.register(IndicatorDefinition(
            name="tema",
            category=IndicatorCategory.TREND,
            market_conditions=[MarketCondition.TRENDING],
            computation=self._compute_tema,
            default_params={"period": 20},
            param_ranges={"period": (10, 30)},
            description="Triple Exponential Moving Average for trend smoothing",
            confirmation_weight=1.1,
        ))
        
        self.register(IndicatorDefinition(
            name="dema",
            category=IndicatorCategory.TREND,
            market_conditions=[MarketCondition.TRENDING],
            computation=self._compute_dema,
            default_params={"period": 20},
            param_ranges={"period": (10, 30)},
            description="Double Exponential Moving Average for reduced lag",
            confirmation_weight=1.1,
        ))
        
        self.register(IndicatorDefinition(
            name="adx",
            category=IndicatorCategory.TREND,
            market_conditions=[MarketCondition.TRENDING, MarketCondition.HIGH_VOLATILITY],
            computation=self._compute_adx,
            default_params={"period": 14, "threshold": 25},
            param_ranges={"period": (10, 20), "threshold": (15, 40)},
            description="Average Directional Index for trend strength",
            confirmation_weight=1.3,
        ))
        
        self.register(IndicatorDefinition(
            name="parabolic_sar",
            category=IndicatorCategory.TREND,
            market_conditions=[MarketCondition.TRENDING],
            computation=self._compute_parabolic_sar,
            default_params={"acceleration": 0.02, "maximum": 0.2},
            param_ranges={"acceleration": (0.01, 0.04), "maximum": (0.15, 0.25)},
            description="Parabolic SAR for trend direction and stops",
            confirmation_weight=1.2,
        ))
        
        # Momentum Indicators
        self.register(IndicatorDefinition(
            name="rsi",
            category=IndicatorCategory.MOMENTUM,
            market_conditions=[MarketCondition.RANGING, MarketCondition.LOW_VOLATILITY],
            computation=self._compute_rsi,
            default_params={"period": 14, "oversold": 30, "overbought": 70},
            param_ranges={"period": (10, 20), "oversold": (20, 35), "overbought": (65, 80)},
            description="Relative Strength Index for momentum",
            confirmation_weight=1.0,
        ))
        
        self.register(IndicatorDefinition(
            name="stochastic",
            category=IndicatorCategory.MOMENTUM,
            market_conditions=[MarketCondition.RANGING],
            computation=self._compute_stochastic,
            default_params={"fastk_period": 14, "slowk_period": 3, "slowd_period": 3},
            param_ranges={"fastk_period": (10, 20), "slowk_period": (2, 5), "slowd_period": (2, 5)},
            description="Stochastic Oscillator for momentum",
            confirmation_weight=1.0,
        ))
        
        self.register(IndicatorDefinition(
            name="cci",
            category=IndicatorCategory.MOMENTUM,
            market_conditions=[MarketCondition.RANGING],
            computation=self._compute_cci,
            default_params={"period": 20, "threshold": -100},
            param_ranges={"period": (15, 25), "threshold": (-120, -80)},
            description="Commodity Channel Index for momentum",
            confirmation_weight=0.9,
        ))
        
        self.register(IndicatorDefinition(
            name="williams_r",
            category=IndicatorCategory.MOMENTUM,
            market_conditions=[MarketCondition.RANGING],
            computation=self._compute_williams_r,
            default_params={"period": 14, "threshold": -80},
            param_ranges={"period": (10, 20), "threshold": (-90, -70)},
            description="Williams %R for momentum",
            confirmation_weight=0.9,
        ))
        
        self.register(IndicatorDefinition(
            name="roc",
            category=IndicatorCategory.MOMENTUM,
            market_conditions=[MarketCondition.TRENDING, MarketCondition.HIGH_VOLATILITY],
            computation=self._compute_roc,
            default_params={"period": 12},
            param_ranges={"period": (8, 20)},
            description="Rate of Change for momentum",
            confirmation_weight=1.0,
        ))
        
        self.register(IndicatorDefinition(
            name="momentum",
            category=IndicatorCategory.MOMENTUM,
            market_conditions=[MarketCondition.TRENDING],
            computation=self._compute_momentum,
            default_params={"period": 10},
            param_ranges={"period": (5, 15)},
            description="Momentum indicator",
            confirmation_weight=1.0,
        ))
        
        # Volatility Indicators
        self.register(IndicatorDefinition(
            name="atr",
            category=IndicatorCategory.VOLATILITY,
            market_conditions=[MarketCondition.HIGH_VOLATILITY, MarketCondition.LOW_VOLATILITY],
            computation=self._compute_atr,
            default_params={"period": 14},
            param_ranges={"period": (10, 20)},
            description="Average True Range for volatility",
            confirmation_weight=1.2,
        ))
        
        self.register(IndicatorDefinition(
            name="bollinger_bands",
            category=IndicatorCategory.VOLATILITY,
            market_conditions=[MarketCondition.RANGING, MarketCondition.HIGH_VOLATILITY],
            computation=self._compute_bollinger_bands,
            default_params={"period": 20, "std_dev": 2.0},
            param_ranges={"period": (15, 25), "std_dev": (1.5, 2.5)},
            description="Bollinger Bands for volatility",
            confirmation_weight=1.1,
        ))
        
        self.register(IndicatorDefinition(
            name="keltner_channels",
            category=IndicatorCategory.VOLATILITY,
            market_conditions=[MarketCondition.HIGH_VOLATILITY],
            computation=self._compute_keltner_channels,
            default_params={"period": 20, "atr_multiplier": 2.0},
            param_ranges={"period": (15, 25), "atr_multiplier": (1.5, 2.5)},
            description="Keltner Channels for volatility",
            confirmation_weight=1.1,
        ))
        
        self.register(IndicatorDefinition(
            name="donchian_channels",
            category=IndicatorCategory.VOLATILITY,
            market_conditions=[MarketCondition.HIGH_VOLATILITY],
            computation=self._compute_donchian_channels,
            default_params={"period": 20},
            param_ranges={"period": (15, 30)},
            description="Donchian Channels for volatility",
            confirmation_weight=1.0,
        ))
        
        # Volume Indicators
        self.register(IndicatorDefinition(
            name="obv",
            category=IndicatorCategory.VOLUME,
            market_conditions=[MarketCondition.LOW_VOLATILITY, MarketCondition.RANGING],
            computation=self._compute_obv,
            default_params={},
            param_ranges={},
            description="On Balance Volume for volume analysis",
            requires_volume=True,
            confirmation_weight=0.9,
        ))
        
        self.register(IndicatorDefinition(
            name="mfi",
            category=IndicatorCategory.VOLUME,
            market_conditions=[MarketCondition.RANGING],
            computation=self._compute_mfi,
            default_params={"period": 14, "threshold": 30},
            param_ranges={"period": (10, 20), "threshold": (20, 40)},
            description="Money Flow Index for volume-weighted momentum",
            requires_volume=True,
            confirmation_weight=1.0,
        ))
        
        self.register(IndicatorDefinition(
            name="volume_roc",
            category=IndicatorCategory.VOLUME,
            market_conditions=[MarketCondition.HIGH_VOLATILITY],
            computation=self._compute_volume_roc,
            default_params={"period": 12},
            param_ranges={"period": (8, 20)},
            description="Volume Rate of Change",
            requires_volume=True,
            confirmation_weight=0.8,
        ))
        
        # Pattern Indicators
        self.register(IndicatorDefinition(
            name="hammer",
            category=IndicatorCategory.PATTERN,
            market_conditions=[MarketCondition.RANGING, MarketCondition.LOW_VOLATILITY],
            computation=self._detect_hammer,
            default_params={"body_ratio": 0.3},
            param_ranges={"body_ratio": (0.2, 0.4)},
            description="Hammer candlestick pattern",
            confirmation_weight=1.3,
        ))
        
        self.register(IndicatorDefinition(
            name="engulfing",
            category=IndicatorCategory.PATTERN,
            market_conditions=[MarketCondition.TRENDING, MarketCondition.HIGH_VOLATILITY],
            computation=self._detect_engulfing,
            default_params={},
            param_ranges={},
            description="Engulfing candlestick pattern",
            confirmation_weight=1.4,
        ))
        
        # Existing indicators (from current templates)
        self.register(IndicatorDefinition(
            name="macd",
            category=IndicatorCategory.MOMENTUM,
            market_conditions=[MarketCondition.TRENDING, MarketCondition.RANGING],
            computation=self._compute_macd,
            default_params={"fast": 12, "slow": 26, "signal": 9},
            param_ranges={"fast": (8, 15), "slow": (20, 30), "signal": (5, 10)},
            description="MACD for momentum",
            confirmation_weight=1.0,
        ))
    
    # Computation methods (simplified - actual implementation would use talib)
    def _compute_ema_crossover(self, dataframe, params):
        import talib.abstract as ta
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=params["fast_period"])
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=params["slow_period"])
        return dataframe
    
    def _compute_tema(self, dataframe, params):
        import talib.abstract as ta
        dataframe["tema"] = ta.TEMA(dataframe, timeperiod=params["period"])
        return dataframe
    
    def _compute_dema(self, dataframe, params):
        import talib.abstract as ta
        dataframe["dema"] = ta.DEMA(dataframe, timeperiod=params["period"])
        return dataframe
    
    def _compute_adx(self, dataframe, params):
        import talib.abstract as ta
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=params["period"])
        return dataframe
    
    def _compute_parabolic_sar(self, dataframe, params):
        import talib.abstract as ta
        dataframe["sar"] = ta.SAR(dataframe, acceleration=params["acceleration"], maximum=params["maximum"])
        return dataframe
    
    def _compute_rsi(self, dataframe, params):
        import talib.abstract as ta
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=params["period"])
        return dataframe
    
    def _compute_stochastic(self, dataframe, params):
        import talib.abstract as ta
        stoch = ta.STOCH(dataframe, fastk_period=params["fastk_period"], 
                        slowk_period=params["slowk_period"], slowd_period=params["slowd_period"])
        dataframe["stoch_slowk"] = stoch["slowk"]
        dataframe["stoch_slowd"] = stoch["slowd"]
        return dataframe
    
    def _compute_cci(self, dataframe, params):
        import talib.abstract as ta
        dataframe["cci"] = ta.CCI(dataframe, timeperiod=params["period"])
        return dataframe
    
    def _compute_williams_r(self, dataframe, params):
        import talib.abstract as ta
        dataframe["willr"] = ta.WILLR(dataframe, timeperiod=params["period"])
        return dataframe
    
    def _compute_roc(self, dataframe, params):
        import talib.abstract as ta
        dataframe["roc"] = ta.ROC(dataframe, timeperiod=params["period"])
        return dataframe
    
    def _compute_momentum(self, dataframe, params):
        import talib.abstract as ta
        dataframe["momentum"] = ta.MOM(dataframe, timeperiod=params["period"])
        return dataframe
    
    def _compute_atr(self, dataframe, params):
        import talib.abstract as ta
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=params["period"])
        return dataframe
    
    def _compute_bollinger_bands(self, dataframe, params):
        import freqtrade.vendor.qtpylib.indicators as qtpylib
        bollinger = qtpylib.bollinger_bands(
            qtpylib.typical_price(dataframe), window=params["period"], stds=params["std_dev"]
        )
        dataframe["bb_lowerband"] = bollinger["lower"]
        dataframe["bb_middleband"] = bollinger["mid"]
        dataframe["bb_upperband"] = bollinger["upper"]
        return dataframe
    
    def _compute_keltner_channels(self, dataframe, params):
        import talib.abstract as ta
        import numpy as np
        atr = ta.ATR(dataframe, timeperiod=params["period"])
        ema = ta.EMA(dataframe, timeperiod=params["period"])
        dataframe["kc_upper"] = ema + (atr * params["atr_multiplier"])
        dataframe["kc_lower"] = ema - (atr * params["atr_multiplier"])
        dataframe["kc_middle"] = ema
        return dataframe
    
    def _compute_donchian_channels(self, dataframe, params):
        dataframe["dc_upper"] = dataframe["high"].rolling(window=params["period"]).max()
        dataframe["dc_lower"] = dataframe["low"].rolling(window=params["period"]).min()
        dataframe["dc_middle"] = (dataframe["dc_upper"] + dataframe["dc_lower"]) / 2
        return dataframe
    
    def _compute_obv(self, dataframe, params):
        import talib.abstract as ta
        dataframe["obv"] = ta.OBV(dataframe)
        return dataframe
    
    def _compute_mfi(self, dataframe, params):
        import talib.abstract as ta
        dataframe["mfi"] = ta.MFI(dataframe, timeperiod=params["period"])
        return dataframe
    
    def _compute_volume_roc(self, dataframe, params):
        dataframe["volume_roc"] = dataframe["volume"].pct_change(params["period"])
        return dataframe
    
    def _detect_hammer(self, dataframe, params):
        import numpy as np
        body = abs(dataframe["close"] - dataframe["open"])
        lower_shadow = dataframe[["open", "close"]].min(axis=1) - dataframe["low"]
        upper_shadow = dataframe[["open", "close"]].max(axis=1) - dataframe["high"]
        total_range = dataframe["high"] - dataframe["low"]
        
        dataframe["hammer"] = (
            (lower_shadow > 2 * body) &
            (upper_shadow < body * 0.1) &
            (body / total_range < params["body_ratio"])
        ).astype(int)
        return dataframe
    
    def _detect_engulfing(self, dataframe, params):
        import numpy as np
        # Simple engulfing detection
        prev_body = abs(dataframe["close"].shift(1) - dataframe["open"].shift(1))
        curr_body = abs(dataframe["close"] - dataframe["open"])
        
        bullish_engulfing = (
            (dataframe["close"].shift(1) < dataframe["open"].shift(1)) &  # Previous red
            (dataframe["close"] > dataframe["open"]) &  # Current green
            (dataframe["open"] < dataframe["close"].shift(1)) &  # Open below previous close
            (dataframe["close"] > dataframe["open"].shift(1))  # Close above previous open
        )
        
        dataframe["bullish_engulfing"] = bullish_engulfing.astype(int)
        return dataframe
    
    def _compute_macd(self, dataframe, params):
        import talib.abstract as ta
        macd = ta.MACD(dataframe, fastperiod=params["fast"], 
                       slowperiod=params["slow"], signalperiod=params["signal"])
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]
        return dataframe


# Global library instance
_library = IndicatorLibrary()


def get_indicator(name: str) -> Optional[IndicatorDefinition]:
    """Get indicator definition by name."""
    return _library.get(name)


def get_indicators_by_category(category: IndicatorCategory) -> List[IndicatorDefinition]:
    """Get all indicators in a category."""
    return _library.get_by_category(category)


def get_indicators_by_market_condition(condition: MarketCondition) -> List[IndicatorDefinition]:
    """Get indicators suitable for a market condition."""
    return _library.get_by_market_condition(condition)
