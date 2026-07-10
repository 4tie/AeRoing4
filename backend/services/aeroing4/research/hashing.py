"""Deterministic identity hashes used by the Research Protocol and its ledger.

These are lightweight identity fingerprints (not code-content hashes) —
sufficient to answer "was this the same strategy/parameter-set/pair-set as
before?" for audit purposes. They are intentionally independent of
`RANKING_POLICY_VERSION` / `METRICS_VERSION` and never influence scoring.
"""

from __future__ import annotations

import hashlib
import json


def compute_strategy_hash(strategy_name: str, version_id: str | None = None) -> str:
    """Deterministic identity hash for a strategy (+ optional accepted version)."""
    canonical = f"{strategy_name}:{version_id or ''}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_parameter_hash(parameters: dict | None) -> str | None:
    """Deterministic, order-independent hash of a parameter set (or None)."""
    if parameters is None:
        return None
    canonical = json.dumps(parameters, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_pair_set_hash(pairs: list[str] | None) -> str | None:
    """Deterministic, order-independent hash of a pair universe (or None)."""
    if pairs is None:
        return None
    canonical = json.dumps(sorted(pairs), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
