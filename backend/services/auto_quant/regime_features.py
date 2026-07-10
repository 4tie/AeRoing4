"""Regime feature engineering for market regime detection.

This module extracts and normalizes features for Hidden Markov Model-based
regime classification. Features are organized into 5 categories:
- Trend: SMA, EMA, MACD, ADX, Kaufman Efficiency Ratio
- Volatility: ATR, Bollinger Bands width, Historical Volatility
- Momentum: RSI, Stochastic, ROC
- Volume: OBV, VWAP, MFI
- Statistical: Skewness, Kurtosis, Hurst exponent
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import talib

logger = logging.getLogger(__name__)


@dataclass
class RegimeFeatures:
    """Container for regime detection features."""
    
    # Trend features
    sma_short: float
    sma_long: float
    ema_short: float
    ema_long: float
    macd: float
    macd_signal: float
    macd_hist: float
    adx: float
    plus_di: float
    minus_di: float
    efficiency_ratio: float
    
    # Volatility features
    atr: float
    atr_percent: float
    bollinger_upper: float
    bollinger_middle: float
    bollinger_lower: float
    bollinger_width: float
    bollinger_position: float
    historical_volatility: float
    
    # Momentum features
    rsi: float
    stochastic_k: float
    stochastic_d: float
    roc: float
    momentum: float
    
    # Volume features
    obv: float
    vwap: float
    mfi: float
    
    # Statistical features
    skewness: float
    kurtosis: float
    hurst: float
    
    def to_array(self) -> np.ndarray:
        """Convert features to numpy array for HMM input."""
        return np.array([
            self.sma_short, self.sma_long, self.ema_short, self.ema_long,
            self.macd, self.macd_signal, self.macd_hist,
            self.adx, self.plus_di, self.minus_di, self.efficiency_ratio,
            self.atr, self.atr_percent,
            self.bollinger_upper, self.bollinger_middle, self.bollinger_lower,
            self.bollinger_width, self.bollinger_position, self.historical_volatility,
            self.rsi, self.stochastic_k, self.stochastic_d, self.roc, self.momentum,
            self.obv, self.vwap, self.mfi,
            self.skewness, self.kurtosis, self.hurst,
        ])


def extract_regime_features(
    df: pd.DataFrame,
    short_period: int = 20,
    long_period: int = 50,
    rsi_period: int = 14,
    atr_period: int = 14,
) -> pd.DataFrame:
    """Extract regime features from OHLCV dataframe.
    
    Args:
        df: DataFrame with columns: open, high, low, close, volume
        short_period: Short lookback period (default 20)
        long_period: Long lookback period (default 50)
        rsi_period: RSI period (default 14)
        atr_period: ATR period (default 14)
        
    Returns:
        DataFrame with regime features for each row
    """
    logger.info("Extracting regime features from %d rows", len(df))
    
    # Validate input
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    # Make a copy to avoid modifying original
    df = df.copy()
    
    # Handle missing data
    df = df.ffill().bfill()
    
    # Extract price data
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values
    
    # ── Trend Features ─────────────────────────────────────────────────────
    # Simple Moving Averages
    df['sma_short'] = talib.SMA(close, timeperiod=short_period)
    df['sma_long'] = talib.SMA(close, timeperiod=long_period)
    
    # Exponential Moving Averages
    df['ema_short'] = talib.EMA(close, timeperiod=short_period)
    df['ema_long'] = talib.EMA(close, timeperiod=long_period)
    
    # MACD
    macd, macd_signal, macd_hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    df['macd'] = macd
    df['macd_signal'] = macd_signal
    df['macd_hist'] = macd_hist
    
    # ADX (Average Directional Index)
    df['adx'] = talib.ADX(high, low, close, timeperiod=14)
    df['plus_di'] = talib.PLUS_DI(high, low, close, timeperiod=14)
    df['minus_di'] = talib.MINUS_DI(high, low, close, timeperiod=14)
    
    # Kaufman Efficiency Ratio
    df['efficiency_ratio'] = _calculate_efficiency_ratio(close, period=14)
    
    # ── Volatility Features ─────────────────────────────────────────────────
    # ATR (Average True Range)
    df['atr'] = talib.ATR(high, low, close, timeperiod=atr_period)
    df['atr_percent'] = (df['atr'] / close) * 100
    
    # Bollinger Bands
    df['bollinger_upper'], df['bollinger_middle'], df['bollinger_lower'] = talib.BBANDS(
        close, timeperiod=20, nbdevup=2, nbdevdn=2
    )
    df['bollinger_width'] = (df['bollinger_upper'] - df['bollinger_lower']) / df['bollinger_middle']
    df['bollinger_position'] = (close - df['bollinger_lower']) / (df['bollinger_upper'] - df['bollinger_lower'])
    
    # Historical Volatility (standard deviation of returns)
    df['returns'] = df['close'].pct_change()
    df['historical_volatility'] = df['returns'].rolling(window=20).std() * np.sqrt(252)
    
    # ── Momentum Features ─────────────────────────────────────────────────
    # RSI (Relative Strength Index)
    df['rsi'] = talib.RSI(close, timeperiod=rsi_period)
    
    # Stochastic Oscillator
    df['stochastic_k'], df['stochastic_d'] = talib.STOCH(
        high, low, close, fastk_period=14, slowk_period=3, slowd_period=3
    )
    
    # Rate of Change
    df['roc'] = talib.ROC(close, timeperiod=10)
    
    # Momentum
    df['momentum'] = close - df['close'].shift(10)
    
    # ── Volume Features ───────────────────────────────────────────────────
    # On-Balance Volume
    df['obv'] = talib.OBV(close, volume)
    
    # VWAP (Volume Weighted Average Price)
    df['vwap'] = _calculate_vwap(df)
    
    # Money Flow Index
    df['mfi'] = talib.MFI(high, low, close, volume, timeperiod=14)
    
    # ── Statistical Features ───────────────────────────────────────────────
    # Skewness and Kurtosis of returns
    df['skewness'] = df['returns'].rolling(window=30).skew()
    df['kurtosis'] = df['returns'].rolling(window=30).kurt()
    
    # Hurst Exponent (measure of long-term memory)
    df['hurst'] = df['close'].rolling(window=100).apply(_calculate_hurst)
    
    # Clean up temporary columns
    df = df.drop(columns=['returns'])
    
    # Handle any remaining NaN values
    df = df.ffill().bfill()
    
    logger.info("Extracted %d features for %d rows", len(df.columns) - len(required_cols), len(df))
    
    return df


def normalize_features_percentile(
    df: pd.DataFrame,
    feature_columns: list[str] | None = None,
    window: int = 252,
) -> pd.DataFrame:
    """Normalize features using percentile scoring (self-calibrating).
    
    This approach ranks each metric against its own recent distribution,
    making it adaptive to different symbols and timeframes without
    fixed thresholds.
    
    Args:
        df: DataFrame with features
        feature_columns: List of columns to normalize (default: all non-OHLCV)
        window: Rolling window for percentile calculation (default 252 = 1 year)
        
    Returns:
        DataFrame with normalized features (0-1 scale)
    """
    if feature_columns is None:
        # Exclude OHLCV columns
        exclude_cols = ['open', 'high', 'low', 'close', 'volume', 'date', 'time']
        feature_columns = [col for col in df.columns if col not in exclude_cols]
    
    logger.info("Normalizing %d features using percentile scoring", len(feature_columns))
    
    df_norm = df.copy()
    
    for col in feature_columns:
        if col in df.columns:
            # Calculate rolling percentile
            df_norm[f'{col}_norm'] = df[col].rolling(window=window, min_periods=50).apply(
                lambda x: (x.iloc[-1] - x.min()) / (x.max() - x.min()) if x.max() != x.min() else 0.5
            )
            # Forward-fill for early periods
            df_norm[f'{col}_norm'] = df_norm[f'{col}_norm'].ffill().bfill()
    
    return df_norm


def _calculate_efficiency_ratio(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """Calculate Kaufman Efficiency Ratio.
    
    Measures signal-to-noise ratio of price movement.
    Near 1 = clean trend, near 0 = chop.
    """
    efficiency = np.full_like(prices, np.nan)
    
    for i in range(period, len(prices)):
        direction = abs(prices[i] - prices[i - period])
        volatility = np.sum(np.abs(np.diff(prices[i - period:i + 1])))
        
        if volatility > 0:
            efficiency[i] = direction / volatility
        else:
            efficiency[i] = 0.5
    
    return efficiency


def _calculate_vwap(df: pd.DataFrame) -> np.ndarray:
    """Calculate Volume Weighted Average Price."""
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    vwap = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()
    return vwap.values


def _calculate_hurst(prices: pd.Series) -> float:
    """Calculate Hurst Exponent.
    
    Measures long-term memory of time series.
    H < 0.5: Mean reverting
    H = 0.5: Random walk
    H > 0.5: Trending
    """
    try:
        # Need at least 100 data points
        if len(prices) < 100:
            return 0.5
        
        # Calculate range of scales
        lags = range(2, 20)
        tau = [np.std(np.subtract(prices[lag:], prices[:-lag])) for lag in lags]
        
        # Fit linear regression to log-log plot
        reg = np.polyfit(np.log(lags), np.log(tau), 1)
        hurst = reg[0]
        
        return hurst
    except Exception:
        return 0.5


def get_feature_columns() -> list[str]:
    """Get list of feature column names."""
    return [
        # Trend
        'sma_short', 'sma_long', 'ema_short', 'ema_long',
        'macd', 'macd_signal', 'macd_hist',
        'adx', 'plus_di', 'minus_di', 'efficiency_ratio',
        # Volatility
        'atr', 'atr_percent',
        'bollinger_upper', 'bollinger_middle', 'bollinger_lower',
        'bollinger_width', 'bollinger_position', 'historical_volatility',
        # Momentum
        'rsi', 'stochastic_k', 'stochastic_d', 'roc', 'momentum',
        # Volume
        'obv', 'vwap', 'mfi',
        # Statistical
        'skewness', 'kurtosis', 'hurst',
    ]


__all__ = [
    "RegimeFeatures",
    "extract_regime_features",
    "normalize_features_percentile",
    "get_feature_columns",
]
