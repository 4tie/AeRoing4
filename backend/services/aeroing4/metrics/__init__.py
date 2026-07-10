"""AeRoing4 Metrics Single Source of Truth (SSOT).

This package provides one canonical, versioned metric contract for AeRoing4.
It normalizes and adapts existing trusted metric sources (ParsedSummary,
Freqtrade-native summary blocks, raw trade data) into a single
`CanonicalMetricsSnapshot` shape with explicit units, explicit availability
states, and explicit provenance.

It is NOT a second Freqtrade result parser. Raw artifact parsing continues to
live in `backend.services.storage.result_parser.ResultParser`. This package
only adapts already-parsed/trusted values, and calculates a metric from raw
trade data only when the trusted source does not provide it.

See `docs/AEROING4_TARGET_ARCHITECTURE.md` for the ownership decisions this
package must respect (§0.6, §0.7): no new AeRoing4 run-state owner is created
here, and Pair Discovery's ranking policy is not altered by this migration.
"""

from .models import (
    CanonicalMetricsSnapshot,
    MetricAvailability,
    MetricProvenance,
    MetricValue,
)
from .provenance import METRICS_VERSION, SourceType, build_provenance

__all__ = [
    "CanonicalMetricsSnapshot",
    "MetricAvailability",
    "MetricProvenance",
    "MetricValue",
    "METRICS_VERSION",
    "SourceType",
    "build_provenance",
]
