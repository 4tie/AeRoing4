"""mplfinance service for generating professional financial chart data."""

from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Any, Dict, List, Optional
from datetime import datetime


class MplfinanceService:
    """Service for generating professional financial chart data from Freqtrade backtest results."""

    def __init__(self):
        """Initialize the mplfinance service."""
        pass

    def generate_candlestick_data(
        self,
        trades: List[Dict[str, Any]],
        timeframe: str = "1h"
    ) -> Dict[str, Any]:
        """
        Convert Freqtrade trades to OHLC candlestick data format.
        
        Args:
            trades: List of trade dictionaries from Freqtrade backtest results
            timeframe: Timeframe for candlestick aggregation (e.g., '1h', '1d')
            
        Returns:
            Dictionary containing OHLC data ready for frontend rendering
        """
        if not trades:
            return {
                "timestamps": [],
                "open": [],
                "high": [],
                "low": [],
                "close": [],
                "volume": []
            }

        # Convert trades to DataFrame
        df = pd.DataFrame(trades)
        
        # Ensure required columns exist
        required_cols = ['open_rate', 'close_rate', 'min_rate', 'max_rate']
        for col in required_cols:
            if col not in df.columns:
                df[col] = df.get(col, 0.0)
        
        # Use open_date as timestamp
        if 'open_date' in df.columns:
            df['timestamp'] = pd.to_datetime(df['open_date'])
        elif 'open_timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['open_timestamp'], unit='s')
        else:
            df['timestamp'] = pd.to_datetime(df.index)
        
        # Sort by timestamp
        df = df.sort_values('timestamp')
        
        # For candlestick data, we'll use individual trades as data points
        # In a real implementation, you might aggregate by timeframe
        result = {
            "timestamps": df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(),
            "open": df['open_rate'].fillna(0).tolist(),
            "high": df['max_rate'].fillna(0).tolist(),
            "low": df['min_rate'].fillna(0).tolist(),
            "close": df['close_rate'].fillna(0).tolist(),
            "volume": df.get('amount', [0] * len(df)).fillna(0).tolist()
        }
        
        return result

    def add_moving_averages(
        self,
        close_prices: List[float],
        periods: List[int] = [20, 50]
    ) -> Dict[str, List[float]]:
        """
        Calculate simple moving averages for given periods.
        
        Args:
            close_prices: List of close prices
            periods: List of periods for SMA calculation
            
        Returns:
            Dictionary mapping period to SMA values
        """
        result = {}
        series = pd.Series(close_prices)
        
        for period in periods:
            if len(close_prices) >= period:
                sma = series.rolling(window=period, min_periods=1).mean()
                result[f"sma_{period}"] = sma.fillna(0).tolist()
            else:
                result[f"sma_{period}"] = [0.0] * len(close_prices)
        
        return result

    def add_exponential_moving_averages(
        self,
        close_prices: List[float],
        periods: List[int] = [12, 26]
    ) -> Dict[str, List[float]]:
        """
        Calculate exponential moving averages for given periods.
        
        Args:
            close_prices: List of close prices
            periods: List of periods for EMA calculation
            
        Returns:
            Dictionary mapping period to EMA values
        """
        result = {}
        series = pd.Series(close_prices)
        
        for period in periods:
            if len(close_prices) >= period:
                ema = series.ewm(span=period, adjust=False).mean()
                result[f"ema_{period}"] = ema.fillna(0).tolist()
            else:
                result[f"ema_{period}"] = [0.0] * len(close_prices)
        
        return result

    def calculate_rsi(
        self,
        close_prices: List[float],
        period: int = 14
    ) -> List[float]:
        """
        Calculate Relative Strength Index (RSI).
        
        Args:
            close_prices: List of close prices
            period: RSI period (default 14)
            
        Returns:
            List of RSI values
        """
        if len(close_prices) < period + 1:
            return [50.0] * len(close_prices)
        
        series = pd.Series(close_prices)
        delta = series.diff()
        
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi.fillna(50).tolist()

    def calculate_macd(
        self,
        close_prices: List[float],
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9
    ) -> Dict[str, List[float]]:
        """
        Calculate MACD (Moving Average Convergence Divergence).
        
        Args:
            close_prices: List of close prices
            fast_period: Fast EMA period (default 12)
            slow_period: Slow EMA period (default 26)
            signal_period: Signal line period (default 9)
            
        Returns:
            Dictionary with MACD line, signal line, and histogram
        """
        if len(close_prices) < slow_period:
            return {
                "macd": [0.0] * len(close_prices),
                "signal": [0.0] * len(close_prices),
                "histogram": [0.0] * len(close_prices)
            }
        
        series = pd.Series(close_prices)
        
        ema_fast = series.ewm(span=fast_period, adjust=False).mean()
        ema_slow = series.ewm(span=slow_period, adjust=False).mean()
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        histogram = macd_line - signal_line
        
        return {
            "macd": macd_line.fillna(0).tolist(),
            "signal": signal_line.fillna(0).tolist(),
            "histogram": histogram.fillna(0).tolist()
        }

    def calculate_bollinger_bands(
        self,
        close_prices: List[float],
        period: int = 20,
        std_dev: float = 2.0
    ) -> Dict[str, List[float]]:
        """
        Calculate Bollinger Bands.
        
        Args:
            close_prices: List of close prices
            period: Period for moving average (default 20)
            std_dev: Standard deviation multiplier (default 2.0)
            
        Returns:
            Dictionary with upper band, middle band (SMA), and lower band
        """
        if len(close_prices) < period:
            return {
                "upper": [0.0] * len(close_prices),
                "middle": [0.0] * len(close_prices),
                "lower": [0.0] * len(close_prices)
            }
        
        series = pd.Series(close_prices)
        sma = series.rolling(window=period, min_periods=1).mean()
        std = series.rolling(window=period, min_periods=1).std()
        
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        
        return {
            "upper": upper_band.fillna(0).tolist(),
            "middle": sma.fillna(0).tolist(),
            "lower": lower_band.fillna(0).tolist()
        }

    def prepare_chart_data(
        self,
        trades: List[Dict[str, Any]],
        include_sma: bool = True,
        include_ema: bool = True,
        include_rsi: bool = True,
        include_macd: bool = True,
        include_bollinger: bool = True
    ) -> Dict[str, Any]:
        """
        Prepare complete chart data with multiple indicators.
        
        Args:
            trades: List of trade dictionaries from Freqtrade backtest results
            include_sma: Include simple moving averages
            include_ema: Include exponential moving averages
            include_rsi: Include RSI indicator
            include_macd: Include MACD indicator
            include_bollinger: Include Bollinger Bands
            
        Returns:
            Complete chart data dictionary
        """
        # Generate base candlestick data
        candlestick_data = self.generate_candlestick_data(trades)
        
        result = {
            "candlestick": candlestick_data,
            "indicators": {}
        }
        
        close_prices = candlestick_data["close"]
        
        if include_sma and close_prices:
            result["indicators"]["sma"] = self.add_moving_averages(close_prices)
        
        if include_ema and close_prices:
            result["indicators"]["ema"] = self.add_exponential_moving_averages(close_prices)
        
        if include_rsi and close_prices:
            result["indicators"]["rsi"] = self.calculate_rsi(close_prices)
        
        if include_macd and close_prices:
            result["indicators"]["macd"] = self.calculate_macd(close_prices)
        
        if include_bollinger and close_prices:
            result["indicators"]["bollinger"] = self.calculate_bollinger_bands(close_prices)
        
        return result
