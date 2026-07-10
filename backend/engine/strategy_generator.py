"""
Strategy Generator Engine
Pure business logic for generating trading strategies
No dependencies on FastAPI, file I/O, or external services
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum


class StrategyStyle(Enum):
    SCALPING = "scalping"
    INTRADAY = "intraday"
    SWING = "swing"
    POSITION = "position"


class RiskProfile(Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


@dataclass
class StrategyTemplate:
    """Template for strategy generation"""
    name: str
    style: StrategyStyle
    indicators: List[str]
    timeframe: str
    description: str


@dataclass
class GeneratedStrategy:
    """Generated trading strategy"""
    id: str
    name: str
    code: str
    style: StrategyStyle
    timeframe: str
    indicators: List[str]
    parameters: Dict[str, Any]
    description: str


class StrategyGeneratorEngine:
    """
    Pure business logic for generating trading strategies
    Can be tested independently without FastAPI or file I/O
    """
    
    # Predefined strategy templates
    TEMPLATES = {
        StrategyStyle.SCALPING: [
            StrategyTemplate(
                name="RSI Scalper",
                style=StrategyStyle.SCALPING,
                indicators=["RSI", "EMA", "ATR"],
                timeframe="1m",
                description="Fast RSI-based scalping with EMA trend filter"
            ),
            StrategyTemplate(
                name="MACD Scalper",
                style=StrategyStyle.SCALPING,
                indicators=["MACD", "EMA", "Volume"],
                timeframe="5m",
                description="MACD momentum scalping with volume confirmation"
            ),
            StrategyTemplate(
                name="STOCH Scalper",
                style=StrategyStyle.SCALPING,
                indicators=["STOCH", "ATR", "EMA"],
                timeframe="5m",
                description="Stochastic oscillator scalping with ATR volatility filter"
            ),
        ],
        StrategyStyle.INTRADAY: [
            StrategyTemplate(
                name="EMA Crossover",
                style=StrategyStyle.INTRADAY,
                indicators=["EMA", "RSI", "ATR"],
                timeframe="15m",
                description="Classic EMA crossover with RSI filter"
            ),
            StrategyTemplate(
                name="Bollinger Breakout",
                style=StrategyStyle.INTRADAY,
                indicators=["Bollinger Bands", "RSI", "Volume"],
                timeframe="30m",
                description="Bollinger band breakout with RSI confirmation"
            ),
            StrategyTemplate(
                name="CCI Reversal",
                style=StrategyStyle.INTRADAY,
                indicators=["CCI", "EMA", "ATR"],
                timeframe="15m",
                description="Commodity Channel Index reversal with EMA trend"
            ),
        ],
        StrategyStyle.SWING: [
            StrategyTemplate(
                name="Swing RSI",
                style=StrategyStyle.SWING,
                indicators=["RSI", "EMA", "MACD"],
                timeframe="1h",
                description="Swing trading with RSI and EMA trend"
            ),
            StrategyTemplate(
                name="MACD Swing",
                style=StrategyStyle.SWING,
                indicators=["MACD", "EMA", "ATR"],
                timeframe="4h",
                description="MACD-based swing trading with ATR stops"
            ),
            StrategyTemplate(
                name="MFI Swing",
                style=StrategyStyle.SWING,
                indicators=["MFI", "EMA", "SAR"],
                timeframe="1h",
                description="Money Flow Index swing with Parabolic SAR"
            ),
        ],
        StrategyStyle.POSITION: [
            StrategyTemplate(
                name="Position Trend",
                style=StrategyStyle.POSITION,
                indicators=["EMA", "MACD", "RSI"],
                timeframe="1d",
                description="Long-term trend following with multiple indicators"
            ),
            StrategyTemplate(
                name="KAMA Trend",
                style=StrategyStyle.POSITION,
                indicators=["KAMA", "ADX", "ATR"],
                timeframe="1d",
                description="Kaufman Adaptive Moving Average with ADX trend strength"
            ),
        ],
    }
    
    def __init__(self):
        self.templates = self.TEMPLATES
    
    def generate_strategies(
        self,
        style: StrategyStyle,
        risk_profile: RiskProfile,
        count: int = 10,
        timeframe: Optional[str] = None
    ) -> List[GeneratedStrategy]:
        """
        Generate trading strategies based on style and risk profile
        
        Args:
            style: Trading style (scalping, intraday, swing, position)
            risk_profile: Risk tolerance (conservative, balanced, aggressive)
            count: Number of strategies to generate
            timeframe: Specific timeframe (auto-select if None)
        
        Returns:
            List of generated strategies
        """
        templates = self.templates.get(style, [])
        if not templates:
            return []
        
        strategies = []
        for i in range(count):
            # Cycle through templates
            template = templates[i % len(templates)]
            
            # Generate strategy
            strategy = self._generate_from_template(
                template=template,
                risk_profile=risk_profile,
                index=i,
                timeframe=timeframe
            )
            strategies.append(strategy)
        
        return strategies
    
    def _generate_from_template(
        self,
        template: StrategyTemplate,
        risk_profile: RiskProfile,
        index: int,
        timeframe: Optional[str] = None
    ) -> GeneratedStrategy:
        """Generate a single strategy from template"""
        
        # Determine timeframe
        if timeframe:
            strategy_timeframe = timeframe
        else:
            strategy_timeframe = template.timeframe
        
        # Generate parameters based on risk profile
        parameters = self._generate_parameters(
            template.indicators,
            risk_profile,
            strategy_timeframe
        )
        
        # Generate code
        code = self._generate_code(
            template.name,
            template.indicators,
            parameters,
            strategy_timeframe
        )
        
        return GeneratedStrategy(
            id=f"strat_{index}_{template.style.value}",
            name=f"{template.name} #{index + 1}",
            code=code,
            style=template.style,
            timeframe=strategy_timeframe,
            indicators=template.indicators,
            parameters=parameters,
            description=template.description
        )
    
    def _generate_parameters(
        self,
        indicators: List[str],
        risk_profile: RiskProfile,
        timeframe: str
    ) -> Dict[str, Any]:
        """Generate strategy parameters based on risk profile"""
        
        base_params = {}
        
        # Risk-based parameter adjustment
        if risk_profile == RiskProfile.CONSERVATIVE:
            risk_multiplier = 0.8
            stop_loss = 0.02
            take_profit = 0.04
        elif risk_profile == RiskProfile.BALANCED:
            risk_multiplier = 1.0
            stop_loss = 0.03
            take_profit = 0.06
        else:  # AGGRESSIVE
            risk_multiplier = 1.2
            stop_loss = 0.05
            take_profit = 0.10
        
        # Indicator-specific parameters
        for indicator in indicators:
            if indicator == "RSI":
                base_params["rsi_period"] = int(14 * risk_multiplier)
                base_params["rsi_overbought"] = 70
                base_params["rsi_oversold"] = 30
            elif indicator == "EMA":
                base_params["ema_fast"] = int(9 * risk_multiplier)
                base_params["ema_slow"] = int(21 * risk_multiplier)
            elif indicator == "MACD":
                base_params["macd_fast"] = int(12 * risk_multiplier)
                base_params["macd_slow"] = int(26 * risk_multiplier)
                base_params["macd_signal"] = int(9 * risk_multiplier)
            elif indicator == "ATR":
                base_params["atr_period"] = int(14 * risk_multiplier)
                base_params["atr_multiplier"] = 2.0
            elif indicator == "Bollinger Bands":
                base_params["bb_period"] = int(20 * risk_multiplier)
                base_params["bb_std"] = 2.0
            elif indicator == "STOCH":
                base_params["stoch_fastk_period"] = int(14 * risk_multiplier)
                base_params["stoch_slowk_period"] = int(3 * risk_multiplier)
                base_params["stoch_slowd_period"] = int(3 * risk_multiplier)
            elif indicator == "CCI":
                base_params["cci_period"] = int(20 * risk_multiplier)
            elif indicator == "MFI":
                base_params["mfi_period"] = int(14 * risk_multiplier)
            elif indicator == "SAR":
                base_params["sar_acceleration"] = 0.02
                base_params["sar_maximum"] = 0.2
            elif indicator == "ADX":
                base_params["adx_period"] = int(14 * risk_multiplier)
            elif indicator == "KAMA":
                base_params["kama_period"] = int(10 * risk_multiplier)
            elif indicator == "SMA":
                base_params["sma_period"] = int(20 * risk_multiplier)
            elif indicator == "WMA":
                base_params["wma_period"] = int(20 * risk_multiplier)
            elif indicator == "DEMA":
                base_params["dema_period"] = int(20 * risk_multiplier)
            elif indicator == "TEMA":
                base_params["tema_period"] = int(20 * risk_multiplier)
            elif indicator == "WILLR":
                base_params["willr_period"] = int(14 * risk_multiplier)
            elif indicator == "NATR":
                base_params["natr_period"] = int(14 * risk_multiplier)
            elif indicator == "ROC":
                base_params["roc_period"] = int(10 * risk_multiplier)
        
        # Risk management parameters
        base_params["stop_loss"] = stop_loss
        base_params["take_profit"] = take_profit
        base_params["risk_per_trade"] = 0.01 if risk_profile == RiskProfile.CONSERVATIVE else 0.02
        
        return base_params
    
    def _generate_code(
        self,
        name: str,
        indicators: List[str],
        parameters: Dict[str, Any],
        timeframe: str
    ) -> str:
        """Generate strategy code (simplified template)"""
        
        code = f"""
# {name}
# Timeframe: {timeframe}
# Indicators: {', '.join(indicators)}

from freqtrade.strategy import IStrategy
from pandas import DataFrame
import talib.abstract as ta

class {name.replace(' ', '')}(IStrategy):
    timeframe = '{timeframe}'
    stoploss = {parameters.get('stop_loss', 0.03)}
    
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
"""
        
        # Add indicator code
        for indicator in indicators:
            if indicator == "RSI":
                code += f"""
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod={parameters.get('rsi_period', 14)})
"""
            elif indicator == "EMA":
                code += f"""
        dataframe['ema_fast'] = ta.EMA(dataframe, timeperiod={parameters.get('ema_fast', 9)})
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod={parameters.get('ema_slow', 21)})
"""
            elif indicator == "MACD":
                code += f"""
        macd = ta.MACD(dataframe, fastperiod={parameters.get('macd_fast', 12)}, 
                       slowperiod={parameters.get('macd_slow', 26)}, 
                       signalperiod={parameters.get('macd_signal', 9)})
        dataframe['macd'] = macd['macd']
        dataframe['macd_signal'] = macd['macdsignal']
"""
            elif indicator == "ATR":
                code += f"""
        dataframe['atr'] = ta.ATR(dataframe, timeperiod={parameters.get('atr_period', 14)})
"""
            elif indicator == "STOCH":
                code += f"""
        stoch = ta.STOCH(dataframe, fastk_period={parameters.get('stoch_fastk_period', 14)},
                        slowk_period={parameters.get('stoch_slowk_period', 3)},
                        slowd_period={parameters.get('stoch_slowd_period', 3)})
        dataframe['stoch_slowk'] = stoch['slowk']
        dataframe['stoch_slowd'] = stoch['slowd']
"""
            elif indicator == "CCI":
                code += f"""
        dataframe['cci'] = ta.CCI(dataframe, timeperiod={parameters.get('cci_period', 20)})
"""
            elif indicator == "MFI":
                code += f"""
        dataframe['mfi'] = ta.MFI(dataframe, timeperiod={parameters.get('mfi_period', 14)})
"""
            elif indicator == "SAR":
                code += f"""
        dataframe['sar'] = ta.SAR(dataframe, acceleration={parameters.get('sar_acceleration', 0.02)},
                                 maximum={parameters.get('sar_maximum', 0.2)})
"""
            elif indicator == "ADX":
                code += f"""
        dataframe['adx'] = ta.ADX(dataframe, timeperiod={parameters.get('adx_period', 14)})
"""
            elif indicator == "KAMA":
                code += f"""
        dataframe['kama'] = ta.KAMA(dataframe, timeperiod={parameters.get('kama_period', 10)})
"""
            elif indicator == "SMA":
                code += f"""
        dataframe['sma'] = ta.SMA(dataframe, timeperiod={parameters.get('sma_period', 20)})
"""
            elif indicator == "WMA":
                code += f"""
        dataframe['wma'] = ta.WMA(dataframe, timeperiod={parameters.get('wma_period', 20)})
"""
            elif indicator == "DEMA":
                code += f"""
        dataframe['dema'] = ta.DEMA(dataframe, timeperiod={parameters.get('dema_period', 20)})
"""
            elif indicator == "TEMA":
                code += f"""
        dataframe['tema'] = ta.TEMA(dataframe, timeperiod={parameters.get('tema_period', 20)})
"""
            elif indicator == "WILLR":
                code += f"""
        dataframe['willr'] = ta.WILLR(dataframe, timeperiod={parameters.get('willr_period', 14)})
"""
            elif indicator == "NATR":
                code += f"""
        dataframe['natr'] = ta.NATR(dataframe, timeperiod={parameters.get('natr_period', 14)})
"""
            elif indicator == "ROC":
                code += f"""
        dataframe['roc'] = ta.ROC(dataframe, timeperiod={parameters.get('roc_period', 10)})
"""
            elif indicator == "OBV":
                code += """
        dataframe['obv'] = ta.OBV(dataframe)
"""
            elif indicator == "AD":
                code += """
        dataframe['ad'] = ta.AD(dataframe)
"""
            elif indicator == "Volume":
                code += """
        dataframe['volume'] = dataframe['volume']
"""
        
        code += """
        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Add your buy conditions here
            ),
            'buy'
        ] = 1
        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Add your sell conditions here
            ),
            'sell'
        ] = 1
        return dataframe
"""
        
        return code
    
    def get_available_styles(self) -> List[StrategyStyle]:
        """Get available trading styles"""
        return list(StrategyStyle)
    
    def get_available_risk_profiles(self) -> List[RiskProfile]:
        """Get available risk profiles"""
        return list(RiskProfile)
