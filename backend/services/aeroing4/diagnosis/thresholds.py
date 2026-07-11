"""Threshold policy and evidence quality for AeRoing4 Diagnosis.

Contains versioned threshold constants for diagnosis evaluation and
deterministic evidence quality classification.
"""

from __future__ import annotations

from typing import Optional

from ..metrics.models import CanonicalMetricsSnapshot, MetricAvailability
from ..portfolio_baseline.models import PortfolioBaselineResult
from ..policies import get_min_trades
from .models import DIAGNOSIS_POLICY_VERSION, EvidenceQuality


# ── Threshold Policy Version ─────────────────────────────────────────────────────

THRESHOLD_POLICY_VERSION = "1.0.0"


# ── Profit Factor Thresholds ─────────────────────────────────────────────────────

# PF < 1.00: clearly negative evidence
PF_NEGATIVE_THRESHOLD = 1.00

# PF 1.00–1.10: weak
PF_WEAK_MIN = 1.00
PF_WEAK_MAX = 1.10

# PF 1.10–1.30: marginal/promising depending on supporting evidence
PF_MARGINAL_MIN = 1.10
PF_MARGINAL_MAX = 1.30

# PF >= 1.30: stronger evidence, but not automatic validation
PF_STRONG_THRESHOLD = 1.30


# ── Drawdown Thresholds ─────────────────────────────────────────────────────────

# < 20%: generally acceptable evidence range
DRAWDOWN_ACCEPTABLE_THRESHOLD = 20.0

# 20–30%: elevated
DRAWDOWN_ELEVATED_MIN = 20.0
DRAWDOWN_ELEVATED_MAX = 30.0

# 30–40%: high
DRAWDOWN_HIGH_MIN = 30.0
DRAWDOWN_HIGH_MAX = 40.0

# > 40%: critical
DRAWDOWN_CRITICAL_THRESHOLD = 40.0


# ── Expectancy Thresholds ───────────────────────────────────────────────────────

# Expectancy < 0: negative per-trade profit
EXPECTANCY_NEGATIVE_THRESHOLD = 0.0


# ── Concentration Thresholds ───────────────────────────────────────────────────

# Top pair profit share above this indicates concentration
CONCENTRATION_TOP_PAIR_THRESHOLD = 0.50  # 50%

# Single pair dependence
SINGLE_PAIR_DEPENDENCE_THRESHOLD = 1


# ── Exit Reason Thresholds ─────────────────────────────────────────────────────

# Stop loss exit share above this indicates stoploss dominance
STOPLOSS_DOMINANCE_THRESHOLD = 0.60  # 60%


# ── Evidence Quality Classification ───────────────────────────────────────────────


def classify_evidence_quality(
    baseline: PortfolioBaselineResult,
    metrics: CanonicalMetricsSnapshot | dict,
    timeframe: str,
) -> EvidenceQuality:
    """Classify the quality of available evidence.

    Considers factors such as:
    - Sufficient trade count
    - Number of selected pairs
    - Canonical metric availability
    - Per-pair evidence availability
    - Exit reason availability
    - Sample duration

    Returns:
        EvidenceQuality classification
    """
    # Handle both dict and CanonicalMetricsSnapshot
    if isinstance(metrics, dict):
        metrics = CanonicalMetricsSnapshot(**metrics)

    # Check total trades against timeframe minimum
    total_trades = _get_metric_value(metrics.total_trades.value)
    min_trades = get_min_trades(timeframe)

    if total_trades is None or total_trades < min_trades:
        return EvidenceQuality.INSUFFICIENT

    quality_score = 0
    max_score = 5

    # 1. Trade count sufficiency (1 point)
    if total_trades >= min_trades * 2:
        quality_score += 1

    # 2. Pair count (1 point)
    pair_count = len(baseline.selected_pairs)
    if pair_count >= 3:
        quality_score += 1

    # 3. Metric availability (1 point)
    available_metrics = 0
    required_metrics = [
        metrics.profit_factor,
        metrics.expectancy,
        metrics.max_drawdown_pct,
        metrics.sharpe,
    ]
    for metric in required_metrics:
        if metric.availability == MetricAvailability.AVAILABLE:
            available_metrics += 1

    if available_metrics >= 3:
        quality_score += 1

    # 4. Per-pair evidence (1 point)
    if baseline.per_pair_contribution and len(baseline.per_pair_contribution) >= pair_count:
        quality_score += 1

    # 5. Exit reason availability (1 point)
    if baseline.exit_reason_distribution and len(baseline.exit_reason_distribution) > 0:
        quality_score += 1

    # Classify based on score
    if quality_score >= 4:
        return EvidenceQuality.HIGH
    elif quality_score >= 2:
        return EvidenceQuality.MEDIUM
    elif quality_score >= 1:
        return EvidenceQuality.LOW
    else:
        return EvidenceQuality.INSUFFICIENT


def _get_metric_value(value: Optional[float]) -> Optional[float]:
    """Extract metric value, handling None."""
    return value if value is not None else None
