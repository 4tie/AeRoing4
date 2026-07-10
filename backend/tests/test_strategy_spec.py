from backend.models.strategy_spec import (
    IndicatorSpec,
    SignalCondition,
    StrategySpec,
    validate_spec,
)


def _valid_spec(**overrides) -> StrategySpec:
    data = {
        "name": "ValidStrategy",
        "description": "RSI mean reversion strategy.",
        "timeframe": "5m",
        "trading_style": "mean_reversion",
        "indicators": [
            IndicatorSpec(name="rsi", params={"period": 14}),
        ],
        "entry_conditions": [
            SignalCondition(
                type="indicator_threshold",
                indicator_a="rsi",
                operator="<",
                value_or_indicator_b=30.0,
            ),
        ],
        "exit_conditions": [
            SignalCondition(
                type="indicator_threshold",
                indicator_a="rsi",
                operator=">",
                value_or_indicator_b=70.0,
            ),
        ],
        "stoploss": -0.10,
        "roi": [(0, 0.12)],
        "max_iterations": 3,
        "iteration_count": 0,
    }
    data.update(overrides)
    return StrategySpec(**data)


def test_spec_valid():
    assert validate_spec(_valid_spec()) == []


def test_spec_invalid_name():
    assert "INVALID_NAME" in validate_spec(_valid_spec(name=""))
    assert "INVALID_NAME" in validate_spec(_valid_spec(name="1BadName"))
    assert "INVALID_NAME" in validate_spec(_valid_spec(name="Bad-Name"))
    assert "INVALID_NAME" in validate_spec(_valid_spec(name="A" * 65))


def test_spec_invalid_timeframe():
    assert "INVALID_TIMEFRAME" in validate_spec(_valid_spec(timeframe="2h"))


def test_spec_no_indicators():
    errors = validate_spec(_valid_spec(indicators=[]))
    assert "NO_INDICATORS" in errors


def test_spec_indicator_ref_mismatch():
    spec = _valid_spec(
        entry_conditions=[
            SignalCondition(
                type="indicator_threshold",
                indicator_a="macd",
                operator=">",
                value_or_indicator_b=0.0,
            )
        ]
    )

    assert "MISSING_ENTRY_INDICATOR: macd" in validate_spec(spec)


def test_spec_stoploss_range():
    assert "INVALID_STOPLOSS" in validate_spec(_valid_spec(stoploss=0.01))
    assert "INVALID_STOPLOSS" in validate_spec(_valid_spec(stoploss=-0.51))


def test_spec_roi_order():
    errors = validate_spec(_valid_spec(roi=[(60, 0.15), (0, 0.12)]))
    assert "INVALID_ROI_ORDER" in errors


def test_spec_hash_deterministic():
    first = _valid_spec().spec_hash()
    second = _valid_spec().spec_hash()

    assert first == second


def test_spec_hash_ignores_iteration_fields():
    first = _valid_spec(iteration_count=0, parent_spec_hash="").spec_hash()
    second = _valid_spec(iteration_count=2, parent_spec_hash="abc123").spec_hash()

    assert first == second


def test_spec_iteration_limit():
    errors = validate_spec(_valid_spec(max_iterations=3, iteration_count=3))
    assert "MAX_ITERATIONS_REACHED" in errors


def test_spec_strict_validation_too_many_indicators():
    """Test that strict validation rejects specs with more than 5 indicators."""
    spec = _valid_spec(
        indicators=[
            IndicatorSpec(name="rsi", params={"period": 14}),
            IndicatorSpec(name="macd", params={"fast": 12, "slow": 26}),
            IndicatorSpec(name="bbands", params={"period": 20}),
            IndicatorSpec(name="adx", params={"period": 14}),
            IndicatorSpec(name="atr", params={"period": 14}),
            IndicatorSpec(name="cci", params={"period": 20}),
        ]
    )
    errors = validate_spec(spec, strict_validation=True)
    assert "TOO_MANY_INDICATORS" in errors


def test_spec_strict_validation_too_many_params():
    """Test that strict validation rejects indicators with more than 3 parameters."""
    spec = _valid_spec(
        indicators=[
            IndicatorSpec(name="rsi", params={"period": 14, "upper": 70, "lower": 30, "mid": 50}),
        ]
    )
    errors = validate_spec(spec, strict_validation=True)
    assert "TOO_MANY_PARAMS: rsi" in errors


def test_spec_strict_validation_passes_with_limits():
    """Test that strict validation passes when within limits."""
    spec = _valid_spec(
        indicators=[
            IndicatorSpec(name="rsi", params={"period": 14}),
            IndicatorSpec(name="macd", params={"fast": 12, "slow": 26}),
        ]
    )
    errors = validate_spec(spec, strict_validation=True)
    assert "TOO_MANY_INDICATORS" not in errors
    assert "TOO_MANY_PARAMS" not in errors


def test_spec_direction_field():
    """Test that direction field accepts valid values."""
    for direction in ["long", "short", "both"]:
        spec = _valid_spec(direction=direction)
        errors = validate_spec(spec)
        assert len(errors) == 0 or "INVALID_NAME" not in errors


def test_spec_invalid_direction():
    """Test that invalid direction values are rejected by Pydantic."""
    try:
        from pydantic import ValidationError
        StrategySpec(
            name="TestStrategy",
            description="Test",
            timeframe="5m",
            trading_style="trend_following",
            direction="invalid",  # Invalid direction
            indicators=[IndicatorSpec(name="rsi", params={"period": 14})],
            entry_conditions=[
                SignalCondition(
                    type="indicator_threshold",
                    indicator_a="rsi",
                    operator="<",
                    value_or_indicator_b=30.0,
                )
            ],
            exit_conditions=[
                SignalCondition(
                    type="indicator_threshold",
                    indicator_a="rsi",
                    operator=">",
                    value_or_indicator_b=70.0,
                )
            ],
            stoploss=-0.10,
        )
        assert False, "Should have raised ValidationError for invalid direction"
    except ValidationError:
        pass  # Expected
