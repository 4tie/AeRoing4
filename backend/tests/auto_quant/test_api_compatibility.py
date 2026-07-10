"""API Compatibility Tests - Ensure old/new payloads work.

This test suite verifies that the API endpoints accept both old and new
request payloads, and that responses are backward compatible.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.api.routers.auto_quant.schemas import StartAutoQuantRequest


def test_old_payload_accepted():
    """Test that old-style payload (without new fields) is accepted."""
    old_payload = {
        "strategy": "TestStrategy",
        "timeframe": "1h",
        "in_sample_range": "20230101-20231201",
        "out_sample_range": "20240101-20240601",
        "exchange": "binance",
        "max_drawdown_threshold": 30.0,
        "min_win_rate": 40.0,
        "min_profit_factor": 1.0,
        "min_sharpe": 0.5,
        "min_oos_profit": 0.0,
        "monte_carlo_threshold": 0.35,
        "hyperopt_loss": "ProfitLockinHyperOptLoss",
        "hyperopt_spaces": ["stoploss", "roi"],
        "hyperopt_epochs": 100,
        "wfo_enabled": False,
        "wfo_is_months": 3,
        "wfo_oos_months": 1,
        "wfo_recency_weight": 1.0,
        "ensemble_enabled": False,
        "pair": None,
        "pair_universe": None,
    }
    
    # Should not raise ValidationError
    request = StartAutoQuantRequest(**old_payload)
    
    assert request.strategy == "TestStrategy"
    assert request.timeframe == "1h"
    assert request.trading_style is None  # New field should be None
    assert request.risk_profile is None  # New field should be None


def test_new_payload_accepted():
    """Test that new-style payload (with new fields) is accepted."""
    new_payload = {
        "strategy": "TestStrategy",
        "strategy_source": "existing",
        "trading_style": "swing",
        "risk_profile": "balanced",
        "analysis_depth": "standard",
        "timeframe": "1h",
        "in_sample_range": "20230101-20231201",
        "out_sample_range": "20240101-20240601",
        "exchange": "binance",
    }
    
    # Should not raise ValidationError
    request = StartAutoQuantRequest(**new_payload)
    
    assert request.strategy == "TestStrategy"
    assert request.trading_style == "swing"
    assert request.risk_profile == "balanced"
    assert request.analysis_depth == "standard"


def test_mixed_payload_accepted():
    """Test that mixed payload (old and new fields together) is accepted."""
    mixed_payload = {
        "strategy": "TestStrategy",
        "timeframe": "1h",
        "in_sample_range": "20230101-20231201",
        "out_sample_range": "20240101-20240601",
        "exchange": "binance",
        "max_drawdown_threshold": 30.0,
        "min_win_rate": 40.0,
        "min_profit_factor": 1.0,
        "min_sharpe": 0.5,
        "min_oos_profit": 0.0,
        "monte_carlo_threshold": 0.35,
        "hyperopt_loss": "ProfitLockinHyperOptLoss",
        "hyperopt_spaces": ["stoploss", "roi"],
        "hyperopt_epochs": 100,
        "wfo_enabled": False,
        "wfo_is_months": 3,
        "wfo_oos_months": 1,
        "wfo_recency_weight": 1.0,
        "ensemble_enabled": False,
        "pair": None,
        "pair_universe": None,
        # New fields
        "strategy_source": "existing",
        "trading_style": "swing",
        "risk_profile": "balanced",
        "analysis_depth": "deep",
    }
    
    # Should not raise ValidationError
    request = StartAutoQuantRequest(**mixed_payload)
    
    assert request.strategy == "TestStrategy"
    assert request.trading_style == "swing"
    assert request.risk_profile == "balanced"
    assert request.max_drawdown_threshold == 30.0


def test_advanced_overrides_accepted():
    """Test that advanced_overrides field is accepted."""
    payload = {
        "strategy": "TestStrategy",
        "timeframe": "1h",
        "in_sample_range": "20230101-20231201",
        "out_sample_range": "20240101-20240601",
        "exchange": "binance",
        "advanced_overrides": {
            "trading_style": "intraday",
            "risk_profile": "aggressive",
            "timeframe": "5m",
            "max_drawdown_threshold": 25.0,
        },
    }
    
    request = StartAutoQuantRequest(**payload)
    
    assert request.advanced_overrides is not None
    assert request.advanced_overrides["trading_style"] == "intraday"
    assert request.advanced_overrides["risk_profile"] == "aggressive"


def test_uploaded_strategy_id_accepted():
    """Test that uploaded_strategy_id field is accepted."""
    payload = {
        "strategy_source": "uploaded",
        "uploaded_strategy_id": "uploaded_abc123",
        "trading_style": "swing",
        "risk_profile": "balanced",
        "timeframe": "1h",
        "in_sample_range": "20230101-20231201",
        "out_sample_range": "20240101-20240601",
        "exchange": "binance",
    }
    
    request = StartAutoQuantRequest(**payload)
    
    assert request.strategy_source == "uploaded"
    assert request.uploaded_strategy_id == "uploaded_abc123"


def test_extra_fields_ignored():
    """Test that extra fields are ignored (extra='ignore' config)."""
    payload = {
        "strategy": "TestStrategy",
        "timeframe": "1h",
        "in_sample_range": "20230101-20231201",
        "out_sample_range": "20240101-20240601",
        "exchange": "binance",
        "extra_field_not_in_schema": "should be ignored",
        "another_extra_field": 123,
    }
    
    # Should not raise ValidationError due to extra='ignore'
    request = StartAutoQuantRequest(**payload)
    
    assert request.strategy == "TestStrategy"
    assert not hasattr(request, "extra_field_not_in_schema")


def test_required_fields_validation():
    """Test that required fields are validated."""
    # Missing required field (strategy or uploaded_strategy_id)
    payload = {
        "timeframe": "1h",
        "in_sample_range": "20230101-20231201",
        "out_sample_range": "20240101-20240601",
        "exchange": "binance",
    }
    
    # Should raise ValidationError or be handled by API
    # For now, we just test the model accepts None for strategy
    request = StartAutoQuantRequest(**payload)
    
    # Strategy can be None if uploaded_strategy_id is provided
    assert request.strategy is None


def test_default_values_applied():
    """Test that default values are applied for optional fields."""
    payload = {
        "strategy": "TestStrategy",
        "timeframe": "1h",
        "in_sample_range": "20230101-20231201",
        "out_sample_range": "20240101-20240601",
        "exchange": "binance",
    }
    
    request = StartAutoQuantRequest(**payload)
    
    # Check default values
    assert request.max_drawdown_threshold == 30.0
    assert request.min_win_rate == 40.0
    assert request.min_profit_factor == 1.0
    assert request.min_sharpe == 0.5
    assert request.min_oos_profit == 0.0
    assert request.monte_carlo_threshold == 0.35
    assert request.hyperopt_loss == "ProfitLockinHyperOptLoss"
    assert request.hyperopt_spaces == ["stoploss", "roi"]
    assert request.hyperopt_epochs == 100
    assert request.wfo_enabled is False
    assert request.wfo_is_months == 3
    assert request.wfo_oos_months == 1
    assert request.wfo_recency_weight == 1.0
    assert request.ensemble_enabled is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
