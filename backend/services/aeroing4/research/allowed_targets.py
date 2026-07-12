"""Allowed Mutation Target discovery for the AeRoing4 Research Loop.

This module answers one narrow question:

  "Which strategy/execution targets may be mutated for a research experiment,
   and what are their current/allowed bounds?"

It never invents targets. If no trusted editable target can be discovered, it
returns NO_SAFE_MUTATION_TARGET.

Trusted sources only:
  * strategy sidecar metadata
  * validated declared strategy parameters
  * trusted strategy specification metadata
  * existing validated parameter registry metadata
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class MutationTargetSource(str, Enum):
    """Provenance classification for an allowed mutation target."""

    SIDECAR_METADATA = "sidecar_metadata"
    DECLARED_PARAMETERS = "declared_parameters"
    STRATEGY_SPEC_REGISTRY = "strategy_spec_registry"
    VALIDATED_PARAMETER_REGISTRY = "validated_parameter_registry"
    FALLBACK = "fallback"


class MutationTargetRiskClass(str, Enum):
    """Risk classification for mutation targets."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class AllowedMutationTarget:
    """Typed description of one allowed mutation target."""

    name: str
    type: str
    current_value: Any = None
    min_allowed: Any = None
    max_allowed: Any = None
    mutable: bool = True
    source: MutationTargetSource = MutationTargetSource.FALLBACK
    risk_class: MutationTargetRiskClass = MutationTargetRiskClass.MEDIUM


class NoSafeMutationTargetError(Exception):
    """Raised when no trusted editable mutation target can be discovered."""


def _safe_sidecar_targets(strategy_name: str, strategies_dir: Path) -> list[AllowedMutationTarget]:
    """Return allowed targets from a strategy sidecar metadata file if present."""
    sidecar = strategies_dir / f"{strategy_name}.json"
    if not sidecar.exists():
        return []

    try:
        import json
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return []

    parameters = data.get("parameters") or data.get("editable_parameters") or {}
    targets: list[AllowedMutationTarget] = []
    for name, meta in parameters.items():
        if not isinstance(meta, dict):
            continue
        if not meta.get("editable", False):
            continue
        targets.append(
            AllowedMutationTarget(
                name=str(name),
                type=str(meta.get("type", "unknown")),
                current_value=meta.get("current", meta.get("default")),
                min_allowed=meta.get("min"),
                max_allowed=meta.get("max"),
                mutable=bool(meta.get("editable", True)),
                source=MutationTargetSource.SIDECAR_METADATA,
                risk_class=MutationTargetRiskClass(
                    str(meta.get("risk_class", MutationTargetRiskClass.MEDIUM.value))
                ),
            )
        )
    return targets


def _safe_declared_parameter_targets(
    strategy_name: str, *, services: Any | None = None
) -> list[AllowedMutationTarget]:
    """Return targets from validated declared strategy parameter metadata."""
    targets: list[AllowedMutationTarget] = []

    try:
        if services is None:
            return []
        strategy_registry = getattr(services, "strategy_registry", None)
        if strategy_registry is None:
            return []
        strategy = strategy_registry.get_strategy(strategy_name)
    except Exception:
        return []

    parameters = getattr(strategy, "parameters", None)
    if not parameters:
        return []

    for parameter in parameters:
        name = getattr(parameter, "name", None) or getattr(parameter, "parameter_name", None)
        if not name:
            continue
        mutable = bool(getattr(parameter, "editable", True) is not False)
        if not mutable:
            continue
        parameter_type = type(parameter).__name__
        current_value = getattr(parameter, "value", None)
        min_allowed = getattr(parameter, "min", None)
        max_allowed = getattr(parameter, "max", None)
        risk_class = MutationTargetRiskClass.MEDIUM
        if parameter_type.endswith("BooleanParameter"):
            risk_class = MutationTargetRiskClass.LOW
        elif parameter_type.endswith("RealParameter") or parameter_type.endswith("DecimalParameter"):
            risk_class = MutationTargetRiskClass.MEDIUM
        elif parameter_type.endswith("IntParameter"):
            risk_class = MutationTargetRiskClass.HIGH

        targets.append(
            AllowedMutationTarget(
                name=str(name),
                type=parameter_type,
                current_value=current_value,
                min_allowed=min_allowed,
                max_allowed=max_allowed,
                mutable=mutable,
                source=MutationTargetSource.DECLARED_PARAMETERS,
                risk_class=risk_class,
            )
        )
    return targets


def discover_allowed_mutation_targets(
    strategy_name: str,
    *,
    runs_root: Path,
    services: Any | None = None,
    strategies_dir: Path | None = None,
) -> list[AllowedMutationTarget]:
    """Discover allowed mutation targets from trusted backend evidence.

    Discovery order:
      1. strategy sidecar metadata
      2. validated declared strategy parameters

    Returns empty list if no trusted editable target can be discovered.
    """
    if strategies_dir is None and services is not None:
        strategies_dir = services.paths.strategies_dir
    if strategies_dir is None:
        return []
    targets = _safe_sidecar_targets(strategy_name, strategies_dir)
    if targets:
        return targets

    targets = _safe_declared_parameter_targets(strategy_name, services=services)
    if targets:
        return targets

    return []
