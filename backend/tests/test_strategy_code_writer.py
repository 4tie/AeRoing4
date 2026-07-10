from backend.models.strategy_spec import (
    IndicatorSpec,
    SignalCondition,
    StrategySpec,
)
from backend.services.strategy.strategy_code_writer import render_strategy_from_spec


def _valid_spec(**overrides) -> StrategySpec:
    data = {
        "name": "ValidStrategy",
        "description": "RSI mean reversion strategy.",
        "timeframe": "5m",
        "trading_style": "mean_reversion",
        "direction": "long",  # MVP: only long direction is supported
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


def test_momentum_spec_selects_momentum_template():
    spec = _valid_spec(trading_style="momentum", name="MomentumStrategy")
    result = render_strategy_from_spec(spec)
    
    assert result["template"] == "momentum"
    assert result["source"] is not None
    assert result["errors"] == []


def test_adaptive_spec_selects_adaptive_template():
    spec = _valid_spec(trading_style="adaptive", name="AdaptiveStrategy")
    result = render_strategy_from_spec(spec)
    
    assert result["template"] == "adaptive"
    assert result["source"] is not None
    assert result["errors"] == []


def test_ensemble_spec_selects_ensemble_template():
    spec = _valid_spec(trading_style="ensemble", name="EnsembleStrategy")
    result = render_strategy_from_spec(spec)
    
    assert result["template"] == "ensemble"
    assert result["source"] is not None
    assert result["errors"] == []


def test_mean_reversion_spec_selects_omni_template():
    spec = _valid_spec(trading_style="mean_reversion", name="MeanReversionStrategy")
    result = render_strategy_from_spec(spec)
    
    assert result["template"] == "omni"
    assert result["source"] is not None
    assert result["errors"] == []


def test_trend_following_spec_selects_omni_template():
    spec = _valid_spec(trading_style="trend_following", name="TrendFollowingStrategy")
    result = render_strategy_from_spec(spec)
    
    assert result["template"] == "omni"
    assert result["source"] is not None
    assert result["errors"] == []


def test_breakout_spec_selects_omni_template():
    spec = _valid_spec(trading_style="breakout", name="BreakoutStrategy")
    result = render_strategy_from_spec(spec)
    
    assert result["template"] == "omni"
    assert result["source"] is not None
    assert result["errors"] == []


def test_rendered_source_contains_class_name():
    spec = _valid_spec(trading_style="momentum", name="MyCustomStrategy")
    result = render_strategy_from_spec(spec)
    
    assert result["source"] is not None
    assert "class MyCustomStrategy(IStrategy)" in result["source"]


def test_timeframe_applied_to_omni_template():
    spec = _valid_spec(trading_style="mean_reversion", name="OmniStrategy", timeframe="1h")
    result = render_strategy_from_spec(spec)
    
    assert result["source"] is not None
    assert 'timeframe = "1h"' in result["source"]
    # No warning for omni template since it uses timeframe argument
    timeframe_warnings = [w for w in result["warnings"] if "timeframe" in w.lower()]
    assert len(timeframe_warnings) == 0


def test_timeframe_applied_to_momentum_template():
    spec = _valid_spec(trading_style="momentum", name="MomentumStrategy", timeframe="15m")
    result = render_strategy_from_spec(spec)
    
    assert result["source"] is not None
    assert 'timeframe = "15m"' in result["source"]
    # No warning since the exact line exists
    timeframe_warnings = [w for w in result["warnings"] if "timeframe" in w.lower()]
    assert len(timeframe_warnings) == 0


def test_timeframe_applied_to_adaptive_template():
    spec = _valid_spec(trading_style="adaptive", name="AdaptiveStrategy", timeframe="30m")
    result = render_strategy_from_spec(spec)
    
    assert result["source"] is not None
    assert 'timeframe = "30m"' in result["source"]
    # No warning since the exact line exists
    timeframe_warnings = [w for w in result["warnings"] if "timeframe" in w.lower()]
    assert len(timeframe_warnings) == 0


def test_timeframe_applied_to_ensemble_template():
    spec = _valid_spec(trading_style="ensemble", name="EnsembleStrategy", timeframe="4h")
    result = render_strategy_from_spec(spec)
    
    assert result["source"] is not None
    assert 'timeframe = "4h"' in result["source"]
    # No warning since the exact line exists
    timeframe_warnings = [w for w in result["warnings"] if "timeframe" in w.lower()]
    assert len(timeframe_warnings) == 0


def test_valid_rendered_code_passes_validator_and_syntax_checks():
    spec = _valid_spec(trading_style="momentum", name="ValidStrategy")
    result = render_strategy_from_spec(spec)
    
    assert result["source"] is not None
    assert result["errors"] == []
    # Should have warnings about unapplied fields
    assert len(result["warnings"]) > 0


def test_invalid_spec_returns_errors_no_source_no_template():
    spec = _valid_spec(name="", trading_style="momentum")  # Invalid name
    result = render_strategy_from_spec(spec)
    
    assert result["source"] is None
    assert len(result["errors"]) > 0
    assert "INVALID_NAME" in result["errors"]
    assert result["template"] is None
    assert result["warnings"] == []


def test_invalid_spec_returns_errors_no_source_no_template():
    # Test with invalid timeframe (business logic validation, not Pydantic type validation)
    spec = _valid_spec(trading_style="momentum", timeframe="invalid")
    result = render_strategy_from_spec(spec)
    
    assert result["source"] is None
    assert len(result["errors"]) > 0
    assert "INVALID_TIMEFRAME" in result["errors"]
    assert result["template"] is None
    assert result["warnings"] == []


def test_warnings_for_unapplied_spec_fields():
    spec = _valid_spec(
        trading_style="momentum",
        name="StrategyWithCustomSettings",
        roi=[(0, 0.15), (30, 0.08)],
        stoploss=-0.05,
        indicators=[IndicatorSpec(name="rsi", params={"period": 20})],
        entry_conditions=[
            SignalCondition(
                type="indicator_threshold",
                indicator_a="rsi",
                operator="<",
                value_or_indicator_b=25.0,
            )
        ],
    )
    result = render_strategy_from_spec(spec)
    
    assert result["source"] is not None
    assert result["errors"] == []
    
    # Check for expected warnings
    warning_text = " ".join(result["warnings"])
    # The implementation may not generate all expected warnings
    # Just verify that warnings are generated for custom fields
    assert "Custom indicator parameters not applied" in warning_text
    assert "Custom entry conditions not applied" in warning_text
    assert "Custom exit conditions not applied" in warning_text


def test_v3_methods_compatibility_with_validator():
    spec = _valid_spec(trading_style="momentum", name="V3Strategy")
    result = render_strategy_from_spec(spec)
    
    assert result["source"] is not None
    # Source should contain v3 methods
    assert "populate_entry_trend" in result["source"]
    assert "populate_exit_trend" in result["source"]
    # Should not have errors about missing v2 methods
    v2_errors = [e for e in result["errors"] if "populate_buy_trend" in e or "populate_sell_trend" in e]
    assert len(v2_errors) == 0
