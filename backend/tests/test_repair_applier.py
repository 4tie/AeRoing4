"""Tests for repair_applier.py."""

from backend.models.strategy_spec import (
    IndicatorSpec,
    PositionSizing,
    SignalCondition,
    StrategySpec,
)
from backend.services.execution.repair_applier import apply_repair_proposal


def _make_spec(**overrides) -> StrategySpec:
    data = {
        "name": "TestStrategy",
        "description": "A test strategy.",
        "timeframe": "5m",
        "trading_style": "trend_following",
        "indicators": [
            IndicatorSpec(name="rsi", params={"period": 14}),
            IndicatorSpec(name="macd", params={"period": 12}),
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
        "roi": [(0, 0.3), (60, 0.15)],
        "max_iterations": 3,
        "iteration_count": 0,
    }
    data.update(overrides)
    return StrategySpec(**data)


class TestApplyStoploss:
    def test_applies_stoploss(self):
        spec = _make_spec(stoploss=-0.10, roi=[(0, 0.2)])
        result, errors = apply_repair_proposal(spec, {
            "repair_scope": "stoploss",
            "change": {"stoploss": -0.15},
            "reasoning": "test",
        })
        assert errors == []
        assert result is not None
        assert result.stoploss == -0.15

    def test_original_spec_unchanged(self):
        spec = _make_spec(stoploss=-0.10, roi=[(0, 0.2)])
        orig_stoploss = spec.stoploss
        orig_iteration = spec.iteration_count
        orig_parent_hash = spec.parent_spec_hash

        result, _ = apply_repair_proposal(spec, {
            "repair_scope": "stoploss",
            "change": {"stoploss": -0.15},
            "reasoning": "test",
        })
        assert result is not None
        assert spec.stoploss == orig_stoploss
        assert spec.iteration_count == orig_iteration
        assert spec.parent_spec_hash == orig_parent_hash

    def test_iteration_count_incremented(self):
        spec = _make_spec(iteration_count=1, roi=[(0, 0.2)])
        result, _ = apply_repair_proposal(spec, {
            "repair_scope": "stoploss",
            "change": {"stoploss": -0.15},
            "reasoning": "test",
        })
        assert result is not None
        assert result.iteration_count == 2

    def test_parent_spec_hash_set(self):
        spec = _make_spec(roi=[(0, 0.2)])
        orig_hash = spec.spec_hash()
        result, _ = apply_repair_proposal(spec, {
            "repair_scope": "stoploss",
            "change": {"stoploss": -0.15},
            "reasoning": "test",
        })
        assert result is not None
        assert result.parent_spec_hash == orig_hash


class TestApplyEntryLogic:
    def test_applies_entry_logic(self):
        spec = _make_spec()
        result, errors = apply_repair_proposal(spec, {
            "repair_scope": "entry_logic",
            "change": {"index": 0, "field": "operator", "new_value": "crosses_above"},
            "reasoning": "test",
        })
        assert errors == []
        assert result is not None
        assert result.entry_conditions[0].operator == "crosses_above"


class TestApplyExitLogic:
    def test_applies_exit_logic(self):
        spec = _make_spec()
        result, errors = apply_repair_proposal(spec, {
            "repair_scope": "exit_logic",
            "change": {"index": 0, "field": "value_or_indicator_b", "new_value": 75.0},
            "reasoning": "test",
        })
        assert errors == []
        assert result is not None
        assert result.exit_conditions[0].value_or_indicator_b == 75.0


class TestApplyEntryParameter:
    def test_applies_entry_parameter(self):
        spec = _make_spec()
        result, errors = apply_repair_proposal(spec, {
            "repair_scope": "entry_parameter",
            "change": {"indicator": "rsi", "parameter": "period", "new_value": 10},
            "reasoning": "test",
        })
        assert errors == []
        assert result is not None
        assert result.indicators[0].params["period"] == 10


class TestApplyROI:
    def test_roi_add(self):
        spec = _make_spec()
        orig_len = len(spec.roi)
        result, errors = apply_repair_proposal(spec, {
            "repair_scope": "roi",
            "change": {"action": "add", "index": 1, "minutes": 30, "ratio": 0.08},
            "reasoning": "test",
        })
        assert errors == []
        assert result is not None
        assert len(result.roi) == orig_len + 1
        assert result.roi[1] == (30, 0.08)

    def test_roi_remove(self):
        spec = _make_spec()
        orig_len = len(spec.roi)
        result, errors = apply_repair_proposal(spec, {
            "repair_scope": "roi",
            "change": {"action": "remove", "index": 0},
            "reasoning": "test",
        })
        assert errors == []
        assert result is not None
        assert len(result.roi) == orig_len - 1

    def test_roi_modify(self):
        spec = _make_spec()
        result, errors = apply_repair_proposal(spec, {
            "repair_scope": "roi",
            "change": {"action": "modify", "index": 0, "minutes": 10, "ratio": 0.15},
            "reasoning": "test",
        })
        assert errors == []
        assert result is not None
        assert result.roi[0] == (10, 0.15)


class TestApplyPositionSizing:
    def test_position_sizing_field(self):
        spec = _make_spec()
        result, errors = apply_repair_proposal(spec, {
            "repair_scope": "position_sizing",
            "change": {"field": "max_open_trades", "new_value": 5},
            "reasoning": "test",
        })
        assert errors == []
        assert result is not None
        assert result.max_open_trades == 5

    def test_position_sizing_method(self):
        spec = _make_spec(
            position_sizing=PositionSizing(
                method="fixed", atr_multiplier=2.0,
            ),
        )
        result, errors = apply_repair_proposal(spec, {
            "repair_scope": "position_sizing",
            "change": {"field": "method", "new_value": "atr_percent"},
            "reasoning": "test",
        })
        assert errors == []
        assert result is not None
        assert result.position_sizing.method == "atr_percent"

    def test_position_sizing_atr_multiplier(self):
        spec = _make_spec(
            position_sizing=PositionSizing(
                method="atr_percent", atr_multiplier=1.5,
            ),
        )
        result, errors = apply_repair_proposal(spec, {
            "repair_scope": "position_sizing",
            "change": {"field": "atr_multiplier", "new_value": 2.5},
            "reasoning": "test",
        })
        assert errors == []
        assert result is not None
        assert result.position_sizing.atr_multiplier == 2.5


class TestInvalidSpecRejected:
    def test_invalid_scope_rejected(self):
        spec = _make_spec()
        result, errors = apply_repair_proposal(spec, {
            "repair_scope": "no_repair_possible",
            "change": {"stoploss": -0.15},
            "reasoning": "test",
        })
        assert result is None
        assert any("non-actionable" in e for e in errors)

    def test_final_reject_scope_rejected(self):
        spec = _make_spec()
        result, errors = apply_repair_proposal(spec, {
            "repair_scope": "final_reject",
            "change": {},
            "reasoning": "test",
        })
        assert result is None
        assert any("non-actionable" in e for e in errors)

    def test_missing_change_key_rejected(self):
        spec = _make_spec()
        result, errors = apply_repair_proposal(spec, {
            "repair_scope": "stoploss",
            "change": {"wrong_key": -0.15},
            "reasoning": "test",
        })
        assert result is None
        assert any("stoploss" in e and "key" in e for e in errors)

    def test_index_out_of_bounds(self):
        spec = _make_spec()
        result, errors = apply_repair_proposal(spec, {
            "repair_scope": "entry_logic",
            "change": {"index": 5, "field": "operator", "new_value": "crosses_above"},
            "reasoning": "test",
        })
        assert result is None
        assert any("out of bounds" in e for e in errors)


class TestInvalidRepairedSpec:
    def test_validate_spec_called(self):
        spec = _make_spec(max_iterations=2, iteration_count=1, roi=[(0, 0.2)])
        result, errors = apply_repair_proposal(spec, {
            "repair_scope": "stoploss",
            "change": {"stoploss": -0.15},
            "reasoning": "test",
        })
        assert result is None
        assert "MAX_ITERATIONS_REACHED" in errors
