import json

import pytest

from backend.models.strategy_spec import StrategySpec
from backend.services.auto_quant.strategy_designer import generate_strategy_spec


class MockOllamaClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def generate(self, prompt, system_prompt=None, feature="default"):
        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "feature": feature,
            }
        )
        return self.response


def _valid_spec_payload(**overrides):
    payload = {
        "name": "DesignedRsiStrategy",
        "description": "RSI mean reversion design.",
        "timeframe": "5m",
        "trading_style": "mean_reversion",
        "direction": "both",
        "indicators": [
            {"name": "rsi", "params": {"period": 14}},
        ],
        "entry_conditions": [
            {
                "type": "indicator_threshold",
                "indicator_a": "rsi",
                "operator": "<",
                "value_or_indicator_b": 30.0,
            }
        ],
        "exit_conditions": [
            {
                "type": "indicator_threshold",
                "indicator_a": "rsi",
                "operator": ">",
                "value_or_indicator_b": 70.0,
            }
        ],
        "stoploss": -0.10,
        "trailing": {
            "trailing_stop": False,
            "trailing_stop_positive": None,
            "trailing_stop_offset": None,
            "trailing_only_offset_is_reached": False,
        },
        "position_sizing": {
            "method": "fixed",
            "atr_multiplier": None,
            "risk_per_trade_pct": None,
        },
        "max_open_trades": 3,
        "roi": [[0, 0.12]],
        "max_iterations": 3,
        "iteration_count": 0,
        "parent_spec_hash": "",
    }
    payload.update(overrides)
    return payload


async def _generate(response):
    client = MockOllamaClient(response)
    result = await generate_strategy_spec(
        client,
        trading_style="mean_reversion",
        timeframe="5m",
        direction="long",
        risk_profile="balanced",
    )
    return result, client


@pytest.mark.asyncio
async def test_strategy_designer_valid_json_works():
    result, _client = await _generate(json.dumps(_valid_spec_payload()))

    assert isinstance(result["spec"], StrategySpec)
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_strategy_designer_markdown_wrapped_json_works():
    response = f"```json\n{json.dumps(_valid_spec_payload())}\n```"

    result, _client = await _generate(response)

    assert isinstance(result["spec"], StrategySpec)
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_strategy_designer_invalid_json_returns_error():
    result, _client = await _generate("{not json")

    assert result["spec"] is None
    assert result["errors"] == ["INVALID_JSON"]


@pytest.mark.asyncio
async def test_strategy_designer_schema_invalid_json_returns_error():
    payload = _valid_spec_payload(trading_style="not_a_style")

    result, _client = await _generate(json.dumps(payload))

    assert result["spec"] is None
    assert result["errors"] == ["INVALID_STRATEGY_SPEC_SCHEMA"]


@pytest.mark.asyncio
async def test_strategy_designer_valid_schema_invalid_spec_returns_validator_errors():
    payload = _valid_spec_payload(indicators=[])

    result, _client = await _generate(json.dumps(payload))

    assert result["spec"] is None
    assert "NO_INDICATORS" in result["errors"]


@pytest.mark.asyncio
async def test_strategy_designer_passes_feature_name():
    result, client = await _generate(json.dumps(_valid_spec_payload()))

    assert result["errors"] == []
    assert client.calls[0]["feature"] == "strategy_designer"


@pytest.mark.asyncio
async def test_strategy_designer_valid_direction_field():
    payload = _valid_spec_payload(direction="long")
    result, _client = await _generate(json.dumps(payload))

    assert isinstance(result["spec"], StrategySpec)
    assert result["spec"].direction == "long"
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_strategy_designer_invalid_direction_returns_error():
    payload = _valid_spec_payload(direction="invalid_direction")
    result, _client = await _generate(json.dumps(payload))

    assert result["spec"] is None
    assert result["errors"] == ["INVALID_STRATEGY_SPEC_SCHEMA"]


@pytest.mark.asyncio
async def test_strategy_designer_too_many_indicators_strict_validation():
    # Create 6 indicators (exceeds limit of 5)
    indicators = [
        {"name": "rsi", "params": {"period": 14}},
        {"name": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}},
        {"name": "bbands", "params": {"period": 20, "std": 2}},
        {"name": "adx", "params": {"period": 14}},
        {"name": "atr", "params": {"period": 14}},
        {"name": "cci", "params": {"period": 20}},
    ]
    payload = _valid_spec_payload(indicators=indicators)
    result, _client = await _generate(json.dumps(payload))

    assert result["spec"] is None
    assert "TOO_MANY_INDICATORS" in result["errors"]


@pytest.mark.asyncio
async def test_strategy_designer_too_many_params_strict_validation():
    # Create indicator with 4 parameters (exceeds limit of 3)
    indicators = [
        {"name": "rsi", "params": {"period": 14, "param2": 1, "param3": 2, "param4": 3}},
    ]
    payload = _valid_spec_payload(indicators=indicators)
    result, _client = await _generate(json.dumps(payload))

    assert result["spec"] is None
    assert "TOO_MANY_PARAMS" in result["errors"]
