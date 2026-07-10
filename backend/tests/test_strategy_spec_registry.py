import json
from pathlib import Path

from backend.models.strategy_spec import (
    IndicatorSpec,
    SignalCondition,
    StrategySpec,
)
from backend.services.strategy.strategy_spec_registry import (
    is_duplicate_spec,
    load_spec_registry,
    record_spec,
    save_spec_registry,
)


def _spec(**overrides) -> StrategySpec:
    data = {
        "name": "TestStrat",
        "description": "A test strategy.",
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
    }
    data.update(**overrides)
    return StrategySpec(**data)


def test_new_spec_not_duplicate():
    registry = {"hashes": {}}
    spec = _spec()
    assert is_duplicate_spec(spec, registry) is False


def test_recorded_spec_becomes_duplicate():
    registry = {"hashes": {}}
    spec = _spec()
    record_spec(spec, registry)
    assert is_duplicate_spec(spec, registry) is True


def test_iteration_fields_ignored_for_dedup():
    registry = {"hashes": {}}
    spec_a = _spec(iteration_count=3)
    spec_b = _spec(iteration_count=5)
    assert spec_a.spec_hash() == spec_b.spec_hash()
    record_spec(spec_a, registry)
    assert is_duplicate_spec(spec_b, registry) is True


def test_changed_spec_different_hash():
    registry = {"hashes": {}}
    spec_a = _spec(stoploss=-0.10)
    spec_b = _spec(stoploss=-0.20)
    assert spec_a.spec_hash() != spec_b.spec_hash()
    record_spec(spec_a, registry)
    assert is_duplicate_spec(spec_b, registry) is False


def test_missing_registry_file(tmp_path: Path):
    path = tmp_path / "nonexistent" / "registry.json"
    result = load_spec_registry(path)
    assert result == {"hashes": {}}


def test_corrupted_registry_file(tmp_path: Path):
    path = tmp_path / "registry.json"
    path.write_text("this is not json", encoding="utf-8")
    result = load_spec_registry(path)
    assert result == {"hashes": {}}


def test_save_and_reload(tmp_path: Path):
    path = tmp_path / "registry.json"
    spec = _spec()
    registry = {"hashes": {}}
    record_spec(spec, registry, name="PersistedStrat")
    save_spec_registry(path, registry)
    assert path.exists()
    loaded = load_spec_registry(path)
    assert spec.spec_hash() in loaded["hashes"]
    assert loaded["hashes"][spec.spec_hash()]["name"] == "PersistedStrat"


def test_invalid_registry_structure(tmp_path: Path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"not_hashes": []}), encoding="utf-8")
    result = load_spec_registry(path)
    assert result == {"hashes": {}}


def test_empty_registry_loads_safely(tmp_path: Path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({}), encoding="utf-8")
    result = load_spec_registry(path)
    assert result == {"hashes": {}}


def test_record_spec_without_hashes_key():
    registry: dict = {}
    spec = _spec()
    record_spec(spec, registry)
    assert "hashes" in registry
    assert spec.spec_hash() in registry["hashes"]
