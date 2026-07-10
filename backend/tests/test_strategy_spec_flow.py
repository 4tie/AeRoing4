import json

import pytest

from backend.services.strategy.strategy_spec_flow import design_validate_register_spec
from backend.services.strategy.strategy_spec_registry import load_spec_registry


class MockOllamaClient:
    def __init__(self, responses):
        if isinstance(responses, list):
            self.responses = list(responses)
        else:
            self.responses = [responses]
        self.calls = []

    async def generate(self, prompt, system_prompt=None, feature="default"):
        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "feature": feature,
            }
        )
        return self.responses.pop(0)


def _valid_spec_payload(**overrides):
    payload = {
        "name": "DesignedRsiStrategy",
        "description": "RSI mean reversion design.",
        "timeframe": "5m",
        "trading_style": "mean_reversion",
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


async def _run_flow(tmp_path, response):
    client = MockOllamaClient(response)
    result = await design_validate_register_spec(
        client,
        tmp_path / "strategy_spec_registry.json",
        trading_style="mean_reversion",
        timeframe="5m",
        direction="long",
        risk_profile="balanced",
    )
    return result, client


@pytest.mark.asyncio
async def test_flow_ready_records_spec(tmp_path):
    result, _client = await _run_flow(tmp_path, json.dumps(_valid_spec_payload()))

    assert result["status"] == "ready"
    assert result["errors"] == []
    assert result["spec"] is not None
    assert result["spec_hash"] == result["spec"].spec_hash()
    assert result["registry_entry"]["hash"] == result["spec_hash"]

    registry = load_spec_registry(tmp_path / "strategy_spec_registry.json")
    assert result["spec_hash"] in registry["hashes"]


@pytest.mark.asyncio
async def test_flow_duplicate_spec_returns_duplicate(tmp_path):
    response = json.dumps(_valid_spec_payload())

    first, _client = await _run_flow(tmp_path, response)
    second, _client = await _run_flow(tmp_path, response)

    assert first["status"] == "ready"
    assert second["status"] == "duplicate"
    assert second["spec_hash"] == first["spec_hash"]
    assert second["registry_entry"]["hash"] == first["spec_hash"]


@pytest.mark.asyncio
async def test_flow_invalid_json_returns_ai_error(tmp_path):
    result, _client = await _run_flow(tmp_path, "{not json")

    assert result["status"] == "ai_error"
    assert result["spec"] is None
    assert result["errors"] == ["INVALID_JSON"]


@pytest.mark.asyncio
async def test_flow_schema_invalid_returns_ai_error(tmp_path):
    payload = _valid_spec_payload(trading_style="not_a_style")

    result, _client = await _run_flow(tmp_path, json.dumps(payload))

    assert result["status"] == "ai_error"
    assert result["spec"] is None
    assert result["errors"] == ["INVALID_STRATEGY_SPEC_SCHEMA"]


@pytest.mark.asyncio
async def test_flow_valid_schema_invalid_spec_returns_validation_error(tmp_path):
    payload = _valid_spec_payload(indicators=[])

    result, _client = await _run_flow(tmp_path, json.dumps(payload))

    assert result["status"] == "validation_error"
    assert result["spec"] is None
    assert "NO_INDICATORS" in result["errors"]


@pytest.mark.asyncio
async def test_flow_iteration_count_duplicate(tmp_path):
    first_response = json.dumps(_valid_spec_payload(iteration_count=0))
    second_response = json.dumps(_valid_spec_payload(iteration_count=2))

    first, _client = await _run_flow(tmp_path, first_response)
    second, _client = await _run_flow(tmp_path, second_response)

    assert first["status"] == "ready"
    assert second["status"] == "duplicate"
    assert second["spec_hash"] == first["spec_hash"]
