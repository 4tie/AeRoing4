"""Unit tests for Freqtrade result adapter."""

import pytest

from backend.services.aeroing4.metrics.freqtrade_result_adapter import (
    FreqtradeAdapterError,
    canonical_snapshot_from_freqtrade_backtest_result,
)
from backend.services.aeroing4.metrics.models import (
    CanonicalMetricsSnapshot,
    MetricAvailability,
    MetricValue,
)


def test_adapter_parses_total_trades():
    """Adapter parses total trades from Freqtrade result."""
    payload = {
        "strategy": {
            "AIStrategy": {
                "total_trades": 42,
                "wins": 25,
                "losses": 17,
                "profit_total_abs": 123.45,
                "profit_factor": 1.8,
                "expectancy": 0.05,
                "max_drawdown_abs": 50.0,
                "max_relative_drawdown": 10.0,
                "sharpe": 2.5,
                "sortino": 3.0,
                "calmar": 1.5,
                "winrate": 0.6,
                "holding_avg": "2:30:00",
                "strategy_name": "AIStrategy",
                "timerange": "20240101-20240131",
                "timeframe": "5m",
            }
        }
    }
    
    result = canonical_snapshot_from_freqtrade_backtest_result(payload)
    
    assert isinstance(result, CanonicalMetricsSnapshot)
    assert result.total_trades.value == 42
    assert result.total_trades.availability == MetricAvailability.AVAILABLE


def test_adapter_parses_profit_factor():
    """Adapter parses profit factor from Freqtrade result."""
    payload = {
        "strategy": {
            "AIStrategy": {
                "total_trades": 10,
                "wins": 6,
                "losses": 4,
                "profit_total_abs": 100.0,
                "profit_factor": 2.5,
                "expectancy": 0.1,
                "max_drawdown_abs": 20.0,
                "max_relative_drawdown": 5.0,
                "sharpe": 1.5,
                "sortino": 2.0,
                "calmar": 1.0,
                "winrate": 0.6,
                "holding_avg": "1:00:00",
                "strategy_name": "AIStrategy",
                "timerange": "20240101-20240131",
                "timeframe": "5m",
            }
        }
    }
    
    result = canonical_snapshot_from_freqtrade_backtest_result(payload)
    
    assert result.profit_factor.value == 2.5
    assert result.profit_factor.availability == MetricAvailability.AVAILABLE


def test_adapter_parses_drawdown():
    """Adapter parses max drawdown from Freqtrade result."""
    payload = {
        "strategy": {
            "AIStrategy": {
                "total_trades": 10,
                "wins": 6,
                "losses": 4,
                "profit_total_abs": 100.0,
                "profit_factor": 2.0,
                "expectancy": 0.1,
                "max_drawdown_abs": 50.0,
                "max_relative_drawdown": 15.0,
                "sharpe": 1.5,
                "sortino": 2.0,
                "calmar": 1.0,
                "winrate": 0.6,
                "holding_avg": "1:00:00",
                "strategy_name": "AIStrategy",
                "timerange": "20240101-20240131",
                "timeframe": "5m",
            }
        }
    }
    
    result = canonical_snapshot_from_freqtrade_backtest_result(payload)
    
    # Freqtrade reports drawdown as positive, adapter converts to negative
    assert result.max_drawdown_pct.value == -15.0
    assert result.max_drawdown_pct.availability == MetricAvailability.AVAILABLE
    assert result.max_drawdown_abs.value == 50.0
    assert result.max_drawdown_abs.availability == MetricAvailability.AVAILABLE


def test_adapter_handles_missing_critical_metrics_as_parse_failure():
    """Adapter raises error when critical metric (total_trades) is missing."""
    payload = {
        "strategy": {
            "AIStrategy": {
                "wins": 6,
                "losses": 4,
                "profit_total_abs": 100.0,
                "profit_factor": 2.0,
                "expectancy": 0.1,
                "max_drawdown_abs": 50.0,
                "max_relative_drawdown": 15.0,
                "sharpe": 1.5,
                "sortino": 2.0,
                "calmar": 1.0,
                "winrate": 0.6,
                "holding_avg": "1:00:00",
                "strategy_name": "AIStrategy",
                "timerange": "20240101-20240131",
                "timeframe": "5m",
            }
        }
    }
    
    with pytest.raises(FreqtradeAdapterError, match="Critical metric 'total_trades' is missing"):
        canonical_snapshot_from_freqtrade_backtest_result(payload)


def test_adapter_does_not_fake_missing_values():
    """Adapter marks missing non-critical metrics as unavailable, not zero."""
    payload = {
        "strategy": {
            "AIStrategy": {
                "total_trades": 10,
                "wins": 6,
                "losses": 4,
                "profit_total_abs": 100.0,
                # profit_factor missing
                "expectancy": 0.1,
                "max_drawdown_abs": 50.0,
                "max_relative_drawdown": 15.0,
                # sharpe missing
                # sortino missing
                # calmar missing
                "winrate": 0.6,
                "holding_avg": "1:00:00",
                "strategy_name": "AIStrategy",
                "timerange": "20240101-20240131",
                "timeframe": "5m",
            }
        }
    }
    
    result = canonical_snapshot_from_freqtrade_backtest_result(payload)
    
    # Missing metrics should be unavailable, not zero
    assert result.profit_factor.availability == MetricAvailability.UNAVAILABLE
    assert result.profit_factor.value is None
    assert result.sharpe.availability == MetricAvailability.UNAVAILABLE
    assert result.sharpe.value is None
    assert result.sortino.availability == MetricAvailability.UNAVAILABLE
    assert result.sortino.value is None
    assert result.calmar.availability == MetricAvailability.UNAVAILABLE
    assert result.calmar.value is None


def test_adapter_preserves_metric_availability():
    """Adapter correctly sets availability state for all metrics."""
    payload = {
        "strategy": {
            "AIStrategy": {
                "total_trades": 10,
                "wins": 6,
                "losses": 4,
                "profit_total_abs": 100.0,
                "profit_factor": 2.0,
                "expectancy": 0.1,
                "max_drawdown_abs": 50.0,
                "max_relative_drawdown": 15.0,
                "sharpe": 1.5,
                "sortino": 2.0,
                "calmar": 1.0,
                "winrate": 0.6,
                "holding_avg": "1:00:00",
                "strategy_name": "AIStrategy",
                "timerange": "20240101-20240131",
                "timeframe": "5m",
            }
        }
    }
    
    result = canonical_snapshot_from_freqtrade_backtest_result(payload)
    
    # Available metrics
    assert result.total_trades.availability == MetricAvailability.AVAILABLE
    assert result.winning_trades.availability == MetricAvailability.AVAILABLE
    assert result.losing_trades.availability == MetricAvailability.AVAILABLE
    assert result.net_profit_abs.availability == MetricAvailability.AVAILABLE
    assert result.profit_factor.availability == MetricAvailability.AVAILABLE
    assert result.expectancy.availability == MetricAvailability.AVAILABLE
    assert result.sharpe.availability == MetricAvailability.AVAILABLE
    assert result.sortino.availability == MetricAvailability.AVAILABLE
    assert result.calmar.availability == MetricAvailability.AVAILABLE
    assert result.max_drawdown_abs.availability == MetricAvailability.AVAILABLE
    assert result.max_drawdown_pct.availability == MetricAvailability.AVAILABLE
    assert result.win_rate.availability == MetricAvailability.AVAILABLE
    assert result.average_trade_duration_minutes.availability == MetricAvailability.AVAILABLE
    
    # Bootstrap Sharpe is not available in Freqtrade native results
    assert result.bootstrap_sharpe_p5.availability == MetricAvailability.UNAVAILABLE


def test_adapter_handles_invalid_structure():
    """Adapter raises error for missing strategy key."""
    payload = {
        "invalid_key": "value"
    }
    
    with pytest.raises(FreqtradeAdapterError, match="Missing 'strategy' key in payload"):
        canonical_snapshot_from_freqtrade_backtest_result(payload)


def test_adapter_handles_empty_strategy_dict():
    """Adapter raises error when strategy dict is empty."""
    payload = {
        "strategy": {}
    }
    
    with pytest.raises(FreqtradeAdapterError, match="No strategy name found in strategy dict"):
        canonical_snapshot_from_freqtrade_backtest_result(payload)


def test_adapter_parses_holding_avg_format():
    """Adapter correctly parses holding_avg format (HH:MM:SS) to minutes."""
    payload = {
        "strategy": {
            "AIStrategy": {
                "total_trades": 10,
                "wins": 6,
                "losses": 4,
                "profit_total_abs": 100.0,
                "profit_factor": 2.0,
                "expectancy": 0.1,
                "max_drawdown_abs": 50.0,
                "max_relative_drawdown": 15.0,
                "sharpe": 1.5,
                "sortino": 2.0,
                "calmar": 1.0,
                "winrate": 0.6,
                "holding_avg": "2:30:00",  # 2 hours 30 minutes = 150 minutes
                "strategy_name": "AIStrategy",
                "timerange": "20240101-20240131",
                "timeframe": "5m",
            }
        }
    }
    
    result = canonical_snapshot_from_freqtrade_backtest_result(payload)
    
    assert result.average_trade_duration_minutes.value == 150.0
    assert result.average_trade_duration_minutes.availability == MetricAvailability.AVAILABLE


def test_adapter_handles_invalid_holding_avg():
    """Adapter marks holding_avg as unavailable for invalid format."""
    payload = {
        "strategy": {
            "AIStrategy": {
                "total_trades": 10,
                "wins": 6,
                "losses": 4,
                "profit_total_abs": 100.0,
                "profit_factor": 2.0,
                "expectancy": 0.1,
                "max_drawdown_abs": 50.0,
                "max_relative_drawdown": 15.0,
                "sharpe": 1.5,
                "sortino": 2.0,
                "calmar": 1.0,
                "winrate": 0.6,
                "holding_avg": "invalid_format",
                "strategy_name": "AIStrategy",
                "timerange": "20240101-20240131",
                "timeframe": "5m",
            }
        }
    }
    
    result = canonical_snapshot_from_freqtrade_backtest_result(payload)
    
    assert result.average_trade_duration_minutes.availability == MetricAvailability.UNAVAILABLE
    assert result.average_trade_duration_minutes.value is None


def test_adapter_with_minimal_real_freqtrade_shape():
    """Adapter works with minimal Freqtrade JSON shape from real execution."""
    # Based on actual Freqtrade 2026.6 output structure
    payload = {
        "strategy": {
            "AIStrategy": {
                "trades": [],
                "locks": [],
                "total_trades": 3,
                "trade_count_long": 3,
                "trade_count_short": 0,
                "wins": 3,
                "losses": 0,
                "draws": 0,
                "profit_total_abs": 0.46398956999999996,
                "profit_factor": 0.0,
                "expectancy": 0.15466318999999998,
                "max_drawdown_abs": 0.0,
                "max_relative_drawdown": 0.0,
                "sharpe": 4.177794068000485,
                "sortino": -100.0,
                "calmar": -100.0,
                "winrate": 1.0,
                "holding_avg": "2:25:00",
                "strategy_name": "AIStrategy",
                "timerange": "20240101-20240131",
                "timeframe": "5m",
            }
        },
        "strategy_comparison": {}
    }
    
    result = canonical_snapshot_from_freqtrade_backtest_result(payload)
    
    assert result.total_trades.value == 3
    assert result.winning_trades.value == 3
    assert result.losing_trades.value == 0
    assert result.net_profit_abs.value == 0.46398956999999996
    assert result.profit_factor.value == 0.0
    assert result.expectancy.value == 0.15466318999999998
    assert result.max_drawdown_abs.value == 0.0
    assert result.max_drawdown_pct.value == 0.0
    assert result.sharpe.value == 4.177794068000485
    assert result.win_rate.value == 1.0
    assert result.average_trade_duration_minutes.value == 145.0  # 2:25:00 = 145 minutes
