"""Shared AeRoing4 policy constants.

This module contains versioned policy constants used across multiple
AeRoing4 components (Pair Discovery, Diagnosis, etc.) to ensure
consistency and avoid duplication.

Policy version: 1.0.0
"""

from __future__ import annotations

# ── Policy constants ────────────────────────────────────────────────────────────

POLICY_VERSION = "1.0.0"

# Minimum number of trades required per timeframe for a pair to be classified
# VALID_CANDIDATE.  Below this → INSUFFICIENT_TRADES rejection.
# Values are independent of AutoQuant PipelineState.
TIMEFRAME_MIN_TRADES: dict[str, int] = {
    "1m":  80,
    "3m":  50,
    "5m":  30,
    "15m": 15,
    "30m": 12,
    "1h":   8,
    "2h":   6,
    "4h":   5,
    "6h":   4,
    "8h":   3,
    "12h":  2,
    "1d":   2,
}

DEFAULT_MIN_TRADES: int = 10  # fallback for unknown timeframes


def get_min_trades(timeframe: str) -> int:
    """Return the minimum number of trades required to be a VALID_CANDIDATE.

    Timeframe-aware and independent of AutoQuant PipelineState.

    Args:
        timeframe: Freqtrade candle timeframe string (e.g. "1h", "5m")

    Returns:
        Minimum trade count required
    """
    return TIMEFRAME_MIN_TRADES.get(timeframe.lower(), DEFAULT_MIN_TRADES)
