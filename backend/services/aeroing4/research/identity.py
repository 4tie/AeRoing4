"""Experiment identity hashing — deterministic, canonical, key-order-independent.

The experiment identity hash uniquely identifies "the same logical experiment"
so duplicate experiments can be detected before reservation.

What IS part of identity:
  - original strategy provenance hash (prevents conflating different source strategies)
  - strategy code hash before the experiment
  - parameter hash before the experiment
  - normalized proposed change (JSON-serialised, sort_keys=True)
  - dataset zone
  - concrete timerange
  - pair set hash (order-independent)
  - relevant execution configuration hash
  - timeframe
  - trading mode
  - exchange (where relevant)
  - protocol version (so a version-bumped re-run is a different experiment)
  - metrics version (where comparison semantics require it)

What is NOT part of identity:
  - experiment_id (assigned after identity is computed)
  - hypothesis_id (multiple hypotheses can share the same experiment identity)
  - created_at / timestamps
  - status / result / decision
  - metrics_before / metrics_after (outcomes, not inputs)
  - access_ledger_entry_id / underlying_execution_id (assigned at execution time)
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any

# Re-export pair set hash from hashing module for convenience
from .hashing import compute_pair_set_hash


def _canonical_json(obj: Any) -> str:
    """Produce a deterministic, key-order-independent JSON string."""
    return json.dumps(obj, sort_keys=True, default=str)


def compute_original_strategy_provenance_hash(
    *,
    logical_name: str,
    path_hash: str | None,
    source_hash: str | None,
    version_id: str | None,
) -> str:
    """Hash capturing original strategy provenance.

    Ensures two different source strategies with identical current parameter
    state are not treated as identical experiments.
    """
    payload = {
        "logical_name": logical_name,
        "path_hash": path_hash or "",
        "source_hash": source_hash or "",
        "version_id": version_id or "",
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def compute_config_hash(config: dict | None) -> str | None:
    """Deterministic, order-independent hash of execution configuration."""
    if config is None:
        return None
    return hashlib.sha256(_canonical_json(config).encode("utf-8")).hexdigest()


def compute_change_hash(proposed_change: dict | str | None) -> str:
    """Deterministic hash of a proposed change (normalized for order-independence)."""
    if proposed_change is None:
        canonical = "null"
    elif isinstance(proposed_change, dict):
        canonical = _canonical_json(proposed_change)
    else:
        canonical = str(proposed_change)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_mutation_value(value: Any) -> Any:
    """Normalize mutation values so exact-value duplicate checks are stable."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _canonical_decimal(str(value))
    if isinstance(value, Decimal):
        return _canonical_decimal(str(value))
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return _canonical_decimal(stripped)
        except ValueError:
            return stripped
    if isinstance(value, list):
        return [_canonical_mutation_value(item) for item in value]
    if isinstance(value, tuple):
        return [_canonical_mutation_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key).strip(): _canonical_mutation_value(val)
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
        }
    return str(value)


def _canonical_decimal(value: str) -> str:
    try:
        decimal_value = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(value) from exc
    if not decimal_value.is_finite():
        raise ValueError(value)
    normalized = decimal_value.normalize()
    if normalized == 0:
        normalized = Decimal("0")
    return format(normalized, "f")


def canonical_mutation_identity(
    *,
    parent_lineage_id: str,
    change_type: Any,
    target: Any,
    before_value: Any,
    after_value: Any,
) -> dict[str, Any]:
    """Canonical identity for exact mutation duplicate checks.

    This intentionally excludes experiment id, hypothesis id, execution
    context, and metrics: it answers only "has this exact mutation already
    been tested in this parent lineage?"
    """
    return {
        "parent_lineage_id": str(parent_lineage_id or "").strip(),
        "change_type": str(change_type or "").strip().lower(),
        "target": str(target or "").strip(),
        "before_value": _canonical_mutation_value(before_value),
        "after_value": _canonical_mutation_value(after_value),
    }


def mutation_identity_from_exact_change(
    *,
    parent_lineage_id: str,
    exact_change: Any,
) -> dict[str, Any]:
    """Build a canonical mutation identity from an ExactChange-like object."""
    if isinstance(exact_change, dict):
        change_type = exact_change.get("change_type")
        target = exact_change.get("target")
        before_value = exact_change.get("before_value")
        after_value = exact_change.get("after_value")
    else:
        change_type = getattr(exact_change, "change_type", None)
        target = getattr(exact_change, "target", None)
        before_value = getattr(exact_change, "before_value", None)
        after_value = getattr(exact_change, "after_value", None)
    return canonical_mutation_identity(
        parent_lineage_id=parent_lineage_id,
        change_type=change_type,
        target=target,
        before_value=before_value,
        after_value=after_value,
    )


def compute_mutation_identity_hash(identity: dict[str, Any]) -> str:
    """Hash the canonical mutation identity for compact comparisons/logging."""
    return hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()


def format_mutation_identity(identity: dict[str, Any]) -> str:
    """Human-readable exact mutation identity for prompts and reports."""
    return (
        f"{identity.get('target')}: {identity.get('before_value')} -> "
        f"{identity.get('after_value')}"
    )


def compute_experiment_identity_hash(
    *,
    original_strategy_provenance_hash: str,
    strategy_hash_before: str | None,
    parameter_hash_before: str | None,
    proposed_change: dict | str | None,
    dataset_zone: str,
    concrete_timerange: str,
    pair_set_hash: str | None,
    configuration_hash: str | None,
    timeframe: str,
    trading_mode: str = "backtesting",
    exchange: str | None = None,
    protocol_version: str = "1.0.0",
    metrics_version: str = "1.0.0",
) -> str:
    """Compute the canonical experiment identity hash.

    The same logical experiment always produces the same hash regardless of
    dictionary key ordering — guaranteed by JSON sort_keys=True throughout.

    Args:
        original_strategy_provenance_hash: Provenance hash from compute_original_strategy_provenance_hash.
        strategy_hash_before: Hash of the strategy code before the experiment.
        parameter_hash_before: Hash of the parameters before the experiment.
        proposed_change: The exact normalized proposed change.
        dataset_zone: The data zone (e.g. "develop").
        concrete_timerange: The concrete timerange string used.
        pair_set_hash: Order-independent hash of the pair set.
        configuration_hash: Hash of relevant execution configuration.
        timeframe: Candle timeframe (e.g. "5m").
        trading_mode: Trading mode (e.g. "backtesting").
        exchange: Exchange name where relevant.
        protocol_version: Research protocol version.
        metrics_version: Metrics SSOT version.

    Returns:
        Hex-encoded SHA-256 identity hash.
    """
    identity_components = {
        "original_strategy_provenance_hash": original_strategy_provenance_hash,
        "strategy_hash_before": strategy_hash_before or "",
        "parameter_hash_before": parameter_hash_before or "",
        "proposed_change_hash": compute_change_hash(proposed_change),
        "dataset_zone": dataset_zone,
        "concrete_timerange": concrete_timerange,
        "pair_set_hash": pair_set_hash or "",
        "configuration_hash": configuration_hash or "",
        "timeframe": timeframe,
        "trading_mode": trading_mode,
        "exchange": exchange or "",
        "protocol_version": protocol_version,
        "metrics_version": metrics_version,
    }
    canonical = _canonical_json(identity_components)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
