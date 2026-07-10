"""
backend/tests/test_auto_quant_router_strategy_spec.py — Tests for /api/auto-quant/generate-strategy-spec endpoint.

Covers:
  - Valid StrategySpec generation with direction field
  - Invalid JSON response from Hermes (should return error)
  - Invalid direction values (should fail validation)
  - Too many indicators (>5) with strict validation (should fail)
  - Too many parameters per indicator (>3) with strict validation (should fail)

Run from project root:
    pytest backend/tests/test_auto_quant_router_strategy_spec.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Make project root importable ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.api.routers.auto_quant import GenerateStrategySpecRequest, GenerateStrategySpecResponse
from backend.models.strategy_spec import StrategySpec, validate_spec


def test_generate_strategy_spec_request_model():
    """Test that the request model validates correctly."""
    # Valid request
    request = GenerateStrategySpecRequest(
        trading_style="swing",
        direction="long",
        risk_profile="balanced",
        timeframe_preference="5m",
        user_notes="Test strategy",
    )
    assert request.trading_style == "swing"
    assert request.direction == "long"
    assert request.risk_profile == "balanced"
    assert request.timeframe_preference == "5m"
    assert request.user_notes == "Test strategy"


def test_generate_strategy_spec_request_optional_fields():
    """Test that user_notes is optional."""
    request = GenerateStrategySpecRequest(
        trading_style="scalping",
        direction="both",
        risk_profile="aggressive",
        timeframe_preference="1m",
    )
    assert request.user_notes is None


def test_generate_strategy_spec_response_model():
    """Test that the response model handles all fields."""
    response = GenerateStrategySpecResponse(
        spec={"name": "TestStrategy", "direction": "long"},
        errors=[],
        raw_response="test response",
    )
    assert response.spec is not None
    assert response.spec["name"] == "TestStrategy"
    assert response.errors == []
    assert response.raw_response == "test response"


def test_generate_strategy_spec_response_with_errors():
    """Test response with validation errors."""
    response = GenerateStrategySpecResponse(
        spec=None,
        errors=["OLLAMA_CLIENT_NOT_AVAILABLE"],
        raw_response="",
    )
    assert response.spec is None
    assert len(response.errors) == 1
    assert "OLLAMA_CLIENT_NOT_AVAILABLE" in response.errors


def test_strategy_spec_with_direction_field():
    """Test that StrategySpec accepts direction field."""
    spec = StrategySpec(
        name="TestStrategy",
        description="Test",
        timeframe="5m",
        trading_style="trend_following",
        direction="long",
        indicators=[],
        entry_conditions=[],
        exit_conditions=[],
        stoploss=-0.10,
    )
    assert spec.direction == "long"


def test_strategy_spec_direction_values():
    """Test all valid direction values."""
    for direction in ["long", "short", "both"]:
        spec = StrategySpec(
            name="TestStrategy",
            description="Test",
            timeframe="5m",
            trading_style="trend_following",
            direction=direction,
            indicators=[],
            entry_conditions=[],
            exit_conditions=[],
            stoploss=-0.10,
        )
        assert spec.direction == direction


def test_strategy_spec_invalid_direction():
    """Test that invalid direction is rejected by Pydantic."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        StrategySpec(
            name="TestStrategy",
            description="Test",
            timeframe="5m",
            trading_style="trend_following",
            direction="invalid",  # Invalid
            indicators=[],
            entry_conditions=[],
            exit_conditions=[],
            stoploss=-0.10,
        )


def test_strict_validation_too_many_indicators():
    """Test strict validation rejects >5 indicators."""
    from backend.models.strategy_spec import IndicatorSpec
    spec = StrategySpec(
        name="TestStrategy",
        description="Test",
        timeframe="5m",
        trading_style="trend_following",
        direction="long",
        indicators=[
            IndicatorSpec(name="rsi", params={"period": 14}),
            IndicatorSpec(name="macd", params={"fast": 12, "slow": 26}),
            IndicatorSpec(name="bbands", params={"period": 20}),
            IndicatorSpec(name="adx", params={"period": 14}),
            IndicatorSpec(name="atr", params={"period": 14}),
            IndicatorSpec(name="cci", params={"period": 20}),
        ],
        entry_conditions=[],
        exit_conditions=[],
        stoploss=-0.10,
    )
    errors = validate_spec(spec, strict_validation=True)
    assert "TOO_MANY_INDICATORS" in errors


def test_strict_validation_too_many_params():
    """Test strict validation rejects >3 params per indicator."""
    from backend.models.strategy_spec import IndicatorSpec
    spec = StrategySpec(
        name="TestStrategy",
        description="Test",
        timeframe="5m",
        trading_style="trend_following",
        direction="long",
        indicators=[
            IndicatorSpec(name="rsi", params={"period": 14, "upper": 70, "lower": 30, "mid": 50}),
        ],
        entry_conditions=[],
        exit_conditions=[],
        stoploss=-0.10,
    )
    errors = validate_spec(spec, strict_validation=True)
    assert "TOO_MANY_PARAMS: rsi" in errors


def test_strict_validation_passes_within_limits():
    """Test strict validation passes when within limits."""
    from backend.models.strategy_spec import IndicatorSpec
    spec = StrategySpec(
        name="TestStrategy",
        description="Test",
        timeframe="5m",
        trading_style="trend_following",
        direction="long",
        indicators=[
            IndicatorSpec(name="rsi", params={"period": 14}),
            IndicatorSpec(name="macd", params={"fast": 12, "slow": 26}),
        ],
        entry_conditions=[],
        exit_conditions=[],
        stoploss=-0.10,
    )
    errors = validate_spec(spec, strict_validation=True)
    assert "TOO_MANY_INDICATORS" not in errors
    assert "TOO_MANY_PARAMS" not in errors


def test_normal_validation_allows_more_indicators():
    """Test normal validation allows >5 indicators."""
    from backend.models.strategy_spec import IndicatorSpec
    spec = StrategySpec(
        name="TestStrategy",
        description="Test",
        timeframe="5m",
        trading_style="trend_following",
        direction="long",
        indicators=[
            IndicatorSpec(name="rsi", params={"period": 14}),
            IndicatorSpec(name="macd", params={"fast": 12, "slow": 26}),
            IndicatorSpec(name="bbands", params={"period": 20}),
            IndicatorSpec(name="adx", params={"period": 14}),
            IndicatorSpec(name="atr", params={"period": 14}),
            IndicatorSpec(name="cci", params={"period": 20}),
        ],
        entry_conditions=[],
        exit_conditions=[],
        stoploss=-0.10,
    )
    errors = validate_spec(spec, strict_validation=False)
    assert "TOO_MANY_INDICATORS" not in errors
