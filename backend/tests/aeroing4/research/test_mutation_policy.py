"""Tests for Mutation Policy."""

from __future__ import annotations

import pytest

from backend.services.aeroing4.research.allowed_targets import (
    AllowedMutationTarget,
    MutationTargetRiskClass,
    MutationTargetSource,
    NoSafeMutationTargetError,
    discover_allowed_mutation_targets,
)
from backend.services.aeroing4.research.experiments import ExperimentStore
from backend.services.aeroing4.research.mutation_policy import (
    MutationPolicy,
    MutationPolicyCode,
    MutationPolicyDecision,
)


class FakeExperimentRecord:
    def __init__(self, experiment_id):
        self.experiment_id = experiment_id


class FakeExperimentStore:
    def __init__(self, existing_identity=None):
        self.existing = existing_identity

    def find_by_identity_hash(self, run_id, identity_hash):
        if self.existing and self.existing == identity_hash:
            return FakeExperimentRecord("existing-exp-1")
        return None


def target(name, min_allowed=None, max_allowed=None, mutable=True):
    return AllowedMutationTarget(
        name=name,
        type="float",
        current_value=-0.05,
        min_allowed=min_allowed,
        max_allowed=max_allowed,
        mutable=mutable,
        source=MutationTargetSource.SIDECAR_METADATA,
        risk_class=MutationTargetRiskClass.MEDIUM,
    )


def test_allowed_when_target_allowed_and_in_bounds():
    policy = MutationPolicy()
    decision = policy.evaluate(
        run_id="run-1",
        hypothesis_id="hyp-1",
        exact_change={"target": "stoploss", "after_value": -0.1},
        allowed_targets=[target("stoploss", min_allowed=-0.5, max_allowed=0.0)],
    )
    assert decision.allowed is True
    assert decision.code == MutationPolicyCode.ALLOWED


def test_denied_when_target_unknown():
    policy = MutationPolicy()
    decision = policy.evaluate(
        run_id="run-1",
        hypothesis_id="hyp-1",
        exact_change={"target": "unknown_param"},
        allowed_targets=[target("stoploss")],
    )
    assert decision.allowed is False
    assert decision.code == MutationPolicyCode.TARGET_UNKNOWN


def test_denied_when_target_not_mutable():
    policy = MutationPolicy()
    decision = policy.evaluate(
        run_id="run-1",
        hypothesis_id="hyp-1",
        exact_change={"target": "locked_param", "after_value": 1},
        allowed_targets=[target("locked_param", mutable=False)],
    )
    assert decision.allowed is False
    assert decision.code == MutationPolicyCode.TARGET_NOT_MUTABLE


def test_denied_when_out_of_range_min():
    policy = MutationPolicy()
    decision = policy.evaluate(
        run_id="run-1",
        hypothesis_id="hyp-1",
        exact_change={"target": "stoploss", "after_value": -0.9},
        allowed_targets=[target("stoploss", min_allowed=-0.5, max_allowed=0.0)],
    )
    assert decision.allowed is False
    assert decision.code == MutationPolicyCode.VALUE_OUTSIDE_ALLOWED_RANGE


def test_denied_when_out_of_range_max():
    policy = MutationPolicy()
    decision = policy.evaluate(
        run_id="run-1",
        hypothesis_id="hyp-1",
        exact_change={"target": "stoploss", "after_value": 0.1},
        allowed_targets=[target("stoploss", min_allowed=-0.5, max_allowed=0.0)],
    )
    assert decision.allowed is False
    assert decision.code == MutationPolicyCode.VALUE_OUTSIDE_ALLOWED_RANGE


def test_denied_duplicate_identity():
    policy = MutationPolicy(experiment_store=FakeExperimentStore(existing_identity="dup-id"))
    decision = policy.evaluate(
        run_id="run-1",
        hypothesis_id="hyp-1",
        exact_change={"target": "stoploss", "after_value": -0.1},
        allowed_targets=[target("stoploss")],
        experiment_identity_hash="dup-id",
    )
    assert decision.allowed is False
    assert decision.code == MutationPolicyCode.EXPERIMENT_DUPLICATE
