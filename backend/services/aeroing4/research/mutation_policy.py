"""Mutation Policy for the AeRoing4 Controlled Research Loop.

Evaluates whether a proposed experiment mutation may proceed.

This policy must not reserve budget or mutate state. It answers ONLY whether
the proposed change is structurally allowed before reservation.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel

from .allowed_targets import AllowedMutationTarget
from .experiments import ExperimentDecision, ExperimentRecord, ExperimentStore
from .hypotheses import HypothesisStore


class MutationPolicyCode(str, Enum):
    ALLOWED = "allowed"
    TARGET_UNKNOWN = "target_unknown"
    TARGET_NOT_MUTABLE = "target_not_mutable"
    VALUE_OUTSIDE_ALLOWED_RANGE = "value_outside_allowed_range"
    EXPERIMENT_DUPLICATE = "experiment_duplicate"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ZONE_ACCESS_DENIED = "zone_access_denied"
    CHAMPION_INTEGRITY_FAIL = "champion_integrity_fail"
    NO_SAFE_MUTATION_TARGET = "no_safe_mutation_target"


class MutationPolicyDecision(BaseModel):
    allowed: bool
    code: MutationPolicyCode
    reason: str
    target: str | None = None
    policy_version: str = "1.0.0"


class MutationPolicy:
    """Deterministic mutation approval policy.

    This is a pure evaluation service. Budget reservation, identity creation,
    and persistence remain authoritative inside ExperimentStore.reserve().
    """

    def __init__(
        self,
        experiment_store: ExperimentStore | None = None,
        hypothesis_store: HypothesisStore | None = None,
    ):
        self.experiment_store = experiment_store
        self.hypothesis_store = hypothesis_store

    def evaluate(
        self,
        *,
        run_id: str,
        hypothesis_id: str,
        exact_change: dict[str, Any] | None,
        allowed_targets: list[AllowedMutationTarget],
        experiment_identity_hash: str | None = None,
        champion_strategy_hash: str | None = None,
        champion_parameter_hash: str | None = None,
        input_parameter_hash: str | None = None,
    ) -> MutationPolicyDecision:
        """Evaluate whether the proposed mutation may proceed."""

        if not allowed_targets:
            return MutationPolicyDecision(
                allowed=False,
                code=MutationPolicyCode.NO_SAFE_MUTATION_TARGET,
                reason="No safe mutation targets discovered from trusted metadata",
                target=None,
            )

        if not exact_change or not isinstance(exact_change, dict):
            return MutationPolicyDecision(
                allowed=False,
                code=MutationPolicyCode.TARGET_UNKNOWN,
                reason="Exact change is missing or not a mapping",
                target=None,
            )

        target_name = exact_change.get("target")
        if target_name is None:
            return MutationPolicyDecision(
                allowed=False,
                code=MutationPolicyCode.TARGET_UNKNOWN,
                reason="Exact change missing 'target'",
                target=None,
            )

        target = next((t for t in allowed_targets if t.name == target_name), None)
        if target is None:
            return MutationPolicyDecision(
                allowed=False,
                code=MutationPolicyCode.TARGET_UNKNOWN,
                reason=f"Target '{target_name}' is not an allowed mutation target",
                target=target_name,
            )

        if not target.mutable:
            return MutationPolicyDecision(
                allowed=False,
                code=MutationPolicyCode.TARGET_NOT_MUTABLE,
                reason=f"Target '{target_name}' is not mutable",
                target=target_name,
            )

        after_value = exact_change.get("after_value")
        if target.min_allowed is not None or target.max_allowed is not None:
            try:
                if after_value is None:
                    raise ValueError("after_value is required for bounded targets")
                numeric_after = float(after_value)
                if target.min_allowed is not None and numeric_after < float(target.min_allowed):
                    return MutationPolicyDecision(
                        allowed=False,
                        code=MutationPolicyCode.VALUE_OUTSIDE_ALLOWED_RANGE,
                        reason=f"after_value {numeric_after} is below min {target.min_allowed} for '{target_name}'",
                        target=target_name,
                    )
                if target.max_allowed is not None and numeric_after > float(target.max_allowed):
                    return MutationPolicyDecision(
                        allowed=False,
                        code=MutationPolicyCode.VALUE_OUTSIDE_ALLOWED_RANGE,
                        reason=f"after_value {numeric_after} is above max {target.max_allowed} for '{target_name}'",
                        target=target_name,
                    )
            except (TypeError, ValueError) as exc:
                return MutationPolicyDecision(
                    allowed=False,
                    code=MutationPolicyCode.VALUE_OUTSIDE_ALLOWED_RANGE,
                    reason=f"Cannot validate bounds for '{target_name}': {exc}",
                    target=target_name,
                )

        if self.experiment_store and experiment_identity_hash:
            existing = self.experiment_store.find_by_identity_hash(run_id, experiment_identity_hash)
            if existing is not None:
                return MutationPolicyDecision(
                    allowed=False,
                    code=MutationPolicyCode.EXPERIMENT_DUPLICATE,
                    reason=f"Duplicate experiment identity detected: {existing.experiment_id}",
                    target=target_name,
                )

        return MutationPolicyDecision(
            allowed=True,
            code=MutationPolicyCode.ALLOWED,
            reason=f"Mutation allowed for target '{target_name}'",
            target=target_name,
        )
