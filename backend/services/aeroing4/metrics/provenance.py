"""Metrics versioning and provenance helpers for the AeRoing4 Metrics SSOT.

`METRICS_VERSION` is the single authoritative version string for the
canonical metric contract. It must not be hardcoded anywhere else — every
`CanonicalMetricsSnapshot` provenance record is stamped via
`build_provenance()`, which reads this constant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum


# Single authoritative version of the canonical metric contract.
# Bump this only when a formula, unit, or edge-case policy changes in a way
# that could change previously-persisted snapshot values. Centralizing metric
# calculation (this milestone) does not by itself require a bump unless it
# changes a value's meaning.
METRICS_VERSION = "1.0.0"


class SourceType(str, Enum):
    """Where the raw evidence for a canonical metrics snapshot came from."""

    PARSED_SUMMARY = "parsed_summary"
    """Adapted from `backend.models.runs.ParsedSummary` (smoke backtests, full
    single-strategy backtests) — the existing, trusted result parser output."""

    PAIR_DISCOVERY_GROUP = "pair_discovery_group"
    """Adapted/derived from a Pair Explorer group-result payload (per-pair
    trades + summary fields returned by `start_pair_explorer_job`), which has
    no `ParsedSummary` of its own."""

    RAW_TRADES = "raw_trades"
    """Derived directly from a raw list of trade dicts/`BacktestTrade`
    records, with no existing summary available at all."""


def build_provenance(
    *,
    source_type: SourceType,
    source_run_id: str | None,
    source_artifact: str | None = None,
    source_parser_version: str | None = None,
    unavailable_metrics: list[str] | None = None,
    derived_metrics: list[str] | None = None,
    adapted_metrics: list[str] | None = None,
) -> dict:
    """Build a provenance dict for a `CanonicalMetricsSnapshot`.

    Returns a plain dict (not the pydantic model) so callers in
    `adapters.py` can pass it straight into `MetricProvenance(**...)`.
    """
    return {
        "metrics_version": METRICS_VERSION,
        "source_type": source_type,
        "source_run_id": source_run_id,
        "source_artifact": source_artifact,
        "source_parser_version": source_parser_version,
        "calculation_timestamp": datetime.now(tz=UTC),
        "unavailable_metrics": sorted(unavailable_metrics or []),
        "derived_metrics": sorted(derived_metrics or []),
        "adapted_metrics": sorted(adapted_metrics or []),
    }


def is_version_current(metrics_version: str) -> bool:
    """Whether a persisted snapshot's version matches the current METRICS_VERSION.

    Callers that cache/persist canonical snapshots (future milestones) must
    call this before reusing a cached snapshot, and recompute on mismatch
    rather than silently trusting a stale value.
    """
    return metrics_version == METRICS_VERSION
