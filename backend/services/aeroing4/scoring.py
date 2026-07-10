"""AeRoing4 Pair Discovery scoring.

Deterministic, explainable scoring for ranking pair discovery candidates.
Does NOT use AI or LLM scoring — all metrics are direct backtest evidence.

Scoring formula (version 1.0.0):

  raw_score = pf_score + np_score + exp_score - dd_penalty
  final_score = raw_score * trade_sufficiency_multiplier

Components:
  pf_score    [0–35]  Profit factor above breakeven, capped at PF 3.0
  np_score    [0–25]  Net profit %, capped at 30%
  exp_score   [0–20]  Expectancy (per-trade profit ratio), capped at 0.01
  dd_penalty  [0–20]  Drawdown above 10% costs 1 point per 1% excess, capped at 20
  multiplier  [0–1]   Trade sufficiency dampener; prevents few-trade pairs dominating

The multiplier is always < 1 until a pair reaches 5× the minimum trade threshold.
This ensures a pair with 10 trades and PF 3.5 cannot automatically outrank a pair
with 250 trades, PF 1.25, positive expectancy, and reasonable drawdown.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# ── Policy constants ────────────────────────────────────────────────────────────

RANKING_POLICY_VERSION = "1.0.0"

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


# ── Score inputs ────────────────────────────────────────────────────────────────

@dataclass
class PairScoreInputs:
    """All metric inputs used to compute a pair's rank score.

    Null metrics are handled explicitly — they are never substituted with zero.
    The ``metrics_available`` dict records which metrics were present.
    """

    pair: str
    total_trades: int
    timeframe: str

    profit_factor: Optional[float] = None
    net_profit_pct: Optional[float] = None
    expectancy: Optional[float] = None
    max_drawdown_pct: Optional[float] = None

    # Derived or recorded
    metrics_available: dict[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.metrics_available = {
            "profit_factor": self.profit_factor is not None,
            "net_profit_pct": self.net_profit_pct is not None,
            "expectancy": self.expectancy is not None,
            "max_drawdown_pct": self.max_drawdown_pct is not None,
        }


@dataclass
class PairScoreResult:
    """Output of the scoring function."""

    pair: str
    rank_score: float
    components: dict[str, float]  # individual score components for audit
    trade_sufficiency_multiplier: float
    policy_version: str = RANKING_POLICY_VERSION
    metrics_available: dict[str, bool] = field(default_factory=dict)


# ── Scoring function ────────────────────────────────────────────────────────────

def _safe_float(value: Optional[float], *, label: str) -> Optional[float]:
    """Return value if it is finite, or None with a debug note.

    Guards against NaN / ±Inf values that could corrupt ranking order.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def score_pair(inputs: PairScoreInputs) -> PairScoreResult:
    """Compute a deterministic rank score for a discovered pair.

    Args:
        inputs: Metric inputs for the pair

    Returns:
        PairScoreResult with final score and component breakdown

    Raises:
        ValueError: If total_trades is negative (indicates a data error)
    """
    if inputs.total_trades < 0:
        raise ValueError(f"total_trades cannot be negative, got {inputs.total_trades}")

    # Guard all metric inputs against NaN / ±Inf before scoring
    profit_factor = _safe_float(inputs.profit_factor, label="profit_factor")
    net_profit_pct = _safe_float(inputs.net_profit_pct, label="net_profit_pct")
    expectancy = _safe_float(inputs.expectancy, label="expectancy")
    max_drawdown_pct = _safe_float(inputs.max_drawdown_pct, label="max_drawdown_pct")

    min_trades = get_min_trades(inputs.timeframe)

    # ── Trade sufficiency multiplier ─────────────────────────────────────────
    # Rises from 0.5 at min_trades to 1.0 at 5× min_trades, then stays at 1.0.
    # Pairs below min_trades should be rejected before scoring; we clamp to 0.
    trades = inputs.total_trades
    if trades < min_trades:
        # Rejected pairs should not reach scoring; return near-zero score
        multiplier = 0.0
    elif trades >= min_trades * 5:
        multiplier = 1.0
    else:
        # Linear interpolation from 0.5 → 1.0 in [min_trades, 5×min_trades]
        multiplier = 0.5 + 0.5 * (trades - min_trades) / (min_trades * 4.0)

    # Update metrics_available to reflect any values sanitized to None (NaN/Inf)
    metrics_available_final = {
        "profit_factor": profit_factor is not None,
        "net_profit_pct": net_profit_pct is not None,
        "expectancy": expectancy is not None,
        "max_drawdown_pct": max_drawdown_pct is not None,
    }

    # ── Profit factor component [0–35] ───────────────────────────────────────
    # PF 1.0 = breakeven (0 pts), PF 3.0+ = max (35 pts)
    if profit_factor is not None:
        pf_score = min(35.0, max(0.0, (profit_factor - 1.0) / 2.0 * 35.0))
    else:
        pf_score = 0.0  # no evidence → no points; recorded in metrics_available

    # ── Net profit % component [0–25] ───────────────────────────────────────
    # 0% = 0 pts, 30%+ = 25 pts
    if net_profit_pct is not None:
        np_score = min(25.0, max(0.0, net_profit_pct / 30.0 * 25.0))
    else:
        np_score = 0.0

    # ── Expectancy component [0–20] ─────────────────────────────────────────
    # 0 = 0 pts, 0.01 (1% per trade) = 20 pts
    if expectancy is not None:
        exp_score = min(20.0, max(0.0, expectancy / 0.01 * 20.0))
    else:
        exp_score = 0.0

    # ── Drawdown penalty [0–20] ──────────────────────────────────────────────
    # First 10% DD is free; beyond that, -1 pt per 1% additional, max 20 pts deducted
    if max_drawdown_pct is not None:
        dd_excess = max(0.0, max_drawdown_pct - 10.0)
        dd_penalty = min(20.0, dd_excess * 1.0)
    else:
        dd_penalty = 0.0  # unknown → no penalty, but recorded in metrics_available

    # ── Combine ──────────────────────────────────────────────────────────────
    raw_score = pf_score + np_score + exp_score - dd_penalty
    raw_score = max(0.0, raw_score)  # floor at 0
    final_score = round(raw_score * multiplier, 2)

    components = {
        "pf_score": round(pf_score, 4),
        "np_score": round(np_score, 4),
        "exp_score": round(exp_score, 4),
        "dd_penalty": round(dd_penalty, 4),
        "raw_score": round(raw_score, 4),
        "trade_sufficiency_multiplier": round(multiplier, 4),
    }

    return PairScoreResult(
        pair=inputs.pair,
        rank_score=final_score,
        components=components,
        trade_sufficiency_multiplier=round(multiplier, 4),
        metrics_available=metrics_available_final,
    )


def rank_candidates(scored: list[PairScoreResult]) -> list[PairScoreResult]:
    """Sort a list of scored pairs deterministically.

    Primary key:   rank_score descending
    Tie-break 1:   total_trades descending (not held in PairScoreResult, so
                   callers should ensure unique scores or use rank_candidates_with_trades)
    Tie-break 2:   pair name ascending (alphabetical, deterministic)

    For the common case where callers don't need trade-count tie-breaking use
    ``rank_candidates_with_trades`` instead.
    """
    return sorted(scored, key=lambda r: (-r.rank_score, r.pair))


def rank_candidates_with_trades(
    scored_and_trades: list[tuple[PairScoreResult, int]],
) -> list[tuple[PairScoreResult, int]]:
    """Sort (score_result, total_trades) tuples deterministically.

    Primary key:   rank_score descending
    Tie-break 1:   total_trades descending
    Tie-break 2:   pair name ascending
    """
    return sorted(
        scored_and_trades,
        key=lambda t: (-t[0].rank_score, -t[1], t[0].pair),
    )
