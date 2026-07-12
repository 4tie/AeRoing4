"""Tests for Allowed Mutation Target discovery."""

from __future__ import annotations

from pathlib import Path

from backend.services.aeroing4.research.allowed_targets import (
    AllowedMutationTarget,
    MutationTargetRiskClass,
    MutationTargetSource,
    NoSafeMutationTargetError,
    discover_allowed_mutation_targets,
)


class FakeParameter:
    def __init__(self, name, value=1.0, editable=True, min=0.0, max=10.0):
        self.name = name
        self.parameter_name = name
        self.value = value
        self.editable = editable
        self.min = min
        self.max = max
        self.__class__.__name__ = "DecimalParameter"


class FakeBoolParameter(FakeParameter):
    def __init__(self, name, value=True):
        super().__init__(name, value=value, min=None, max=None)
        self.__class__.__name__ = "BooleanParameter"


class FakeStrategy:
    def __init__(self, parameters):
        self.parameters = parameters


class FakeStrategyRegistry:
    def __init__(self, strategy):
        self.strategy = strategy

    def get_strategy(self, strategy_name):
        return self.strategy


class FakeServices:
    def __init__(self, strategy, strategies_dir=None):
        self.strategy_registry = FakeStrategyRegistry(strategy)
        self.paths = type('obj', (object,), {'strategies_dir': strategies_dir})() if strategies_dir else None


def test_sidecar_metadata_discovery(tmp_path: Path):
    strategy_name = "strategy_with_sidecar"
    strategies_dir = tmp_path / "strategies"
    sidecar = strategies_dir / f"{strategy_name}.json"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        '{"parameters": {"stoploss": {"editable": true, "type": "float", "current": -0.05, "min": -0.5, "max": 0.0, "risk_class": "high"}}}',
        encoding="utf-8",
    )

    targets = discover_allowed_mutation_targets(strategy_name, runs_root=tmp_path, strategies_dir=strategies_dir)
    assert len(targets) == 1
    target = targets[0]
    assert target.name == "stoploss"
    assert target.current_value == -0.05
    assert target.source == MutationTargetSource.SIDECAR_METADATA
    assert target.risk_class == MutationTargetRiskClass.HIGH


def test_missing_sidecar_returns_empty_without_services():
    targets = discover_allowed_mutation_targets("unknown", runs_root=Path("/tmp"))
    assert targets == []


def test_declared_parameter_targets_used_when_sidecar_missing(tmp_path: Path):
    strategies_dir = tmp_path / "strategies"
    strategy = FakeStrategy([FakeParameter("stoploss", value=-0.03)])
    targets = discover_allowed_mutation_targets(
        "strategy_no_sidecar", runs_root=tmp_path, services=FakeServices(strategy, strategies_dir)
    )
    assert len(targets) == 1
    assert targets[0].source == MutationTargetSource.DECLARED_PARAMETERS


def test_non_editable_parameters_are_excluded(tmp_path: Path):
    strategies_dir = tmp_path / "strategies"
    strategy = FakeStrategy(
        [
            FakeParameter("stoploss", value=-0.03, editable=True),
            FakeParameter("locked_param", value=100, editable=False),
        ]
    )
    targets = discover_allowed_mutation_targets(
        "strategy_mixed", runs_root=tmp_path, services=FakeServices(strategy, strategies_dir)
    )
    assert [t.name for t in targets] == ["stoploss"]


def test_no_trusted_targets_returns_empty():
    targets = discover_allowed_mutation_targets("no_meta", runs_root=Path("/tmp"), services=None)
    assert targets == []


def test_boolean_parameter_risk_class():
    strategies_dir = Path("/tmp/strategies")
    strategy = FakeStrategy([FakeBoolParameter("buy_enabled")])
    targets = discover_allowed_mutation_targets(
        "bool_strategy", runs_root=Path("/tmp"), services=FakeServices(strategy, strategies_dir)
    )
    assert targets[0].risk_class == MutationTargetRiskClass.LOW
