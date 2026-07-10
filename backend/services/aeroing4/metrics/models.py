"""Canonical typed metric models for the AeRoing4 Metrics SSOT.

Canonical unit conventions (binding for every field below):

- Percentages (`*_pct`, `win_rate`) use a 0-100 scale, matching the existing
  `ParsedSummary` convention (e.g. 12.0 means 12%, never 0.12).
- Currency amounts (`*_abs`) are absolute numeric amounts in the account's
  stake currency, never normalized/ratio values.
- `expectancy` is the average profit per trade in absolute currency units —
  i.e. `sum(profit_abs) / total_trades`. This matches
  `ResultParser._derive_expectancy`'s existing formula
  (`win_rate * avg_win - loss_rate * avg_loss`), which is algebraically
  identical to `sum(profit_abs) / total_trades`.
- `profit_factor`, `sharpe`, `sortino`, `calmar` are unitless ratios.
- `average_trade_duration_minutes` is in minutes (matches existing
  `ParsedSummary.avg_trade_duration_minutes`).
- `bootstrap_sharpe_p5` is a unitless ratio (same scale as `sharpe`).

Never mix 0-1 and 0-100 representations for the same percentage metric
within this package.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .provenance import SourceType


class MetricAvailability(str, Enum):
    """Explicit availability state for every canonical metric.

    A metric's numeric `value` must be interpreted together with its
    `availability` — a `None` value with `AVAILABLE` never occurs; an
    unavailable metric must never be silently read as 0.
    """

    AVAILABLE = "available"
    """The metric has a trustworthy numeric value."""

    UNAVAILABLE = "unavailable"
    """The metric could not be produced from the evidence at hand (e.g. no
    trades at all, or the underlying source never reported it)."""

    NOT_APPLICABLE = "not_applicable"
    """The metric is mathematically undefined for this evidence (e.g. Calmar
    with zero drawdown, Sharpe with zero volatility, Sortino with no
    downside returns) — distinct from simply missing data."""

    INSUFFICIENT_DATA = "insufficient_data"
    """There is some evidence, but not enough to compute the metric reliably
    (e.g. fewer than 2 trade returns for Sharpe, fewer than 5 for the
    bootstrap Sharpe)."""


class MetricValue(BaseModel):
    """A single canonical metric: its value plus its availability state."""

    value: float | int | None = None
    availability: MetricAvailability

    @classmethod
    def available(cls, value: float | int) -> "MetricValue":
        return cls(value=value, availability=MetricAvailability.AVAILABLE)

    @classmethod
    def unavailable(cls) -> "MetricValue":
        return cls(value=None, availability=MetricAvailability.UNAVAILABLE)

    @classmethod
    def not_applicable(cls) -> "MetricValue":
        return cls(value=None, availability=MetricAvailability.NOT_APPLICABLE)

    @classmethod
    def insufficient_data(cls) -> "MetricValue":
        return cls(value=None, availability=MetricAvailability.INSUFFICIENT_DATA)


class MetricProvenance(BaseModel):
    """Answers "where did this number come from?" for a whole snapshot."""

    metrics_version: str
    source_type: SourceType
    source_run_id: str | None = None
    source_artifact: str | None = None
    source_parser_version: str | None = None
    calculation_timestamp: Any  # datetime, kept loose to survive round-trip via model_dump(mode="json")
    unavailable_metrics: list[str] = Field(default_factory=list)
    derived_metrics: list[str] = Field(default_factory=list)
    adapted_metrics: list[str] = Field(default_factory=list)


class CanonicalMetricsSnapshot(BaseModel):
    """The one canonical metric contract for AeRoing4.

    Every AeRoing4 stage that needs performance metrics must consume this
    shape rather than recomputing formulas privately (see
    `docs/AEROING4_TARGET_ARCHITECTURE.md` §0.6/§0.7 and Prompt 2 §10).
    """

    # ── Activity ──────────────────────────────────────────────────────────
    total_trades: MetricValue
    winning_trades: MetricValue
    losing_trades: MetricValue

    # ── Profitability ─────────────────────────────────────────────────────
    net_profit_abs: MetricValue
    net_profit_pct: MetricValue
    win_rate: MetricValue
    profit_factor: MetricValue
    expectancy: MetricValue

    # ── Risk-adjusted performance ────────────────────────────────────────
    sharpe: MetricValue
    sortino: MetricValue
    calmar: MetricValue

    # ── Risk ──────────────────────────────────────────────────────────────
    max_drawdown_abs: MetricValue
    max_drawdown_pct: MetricValue

    # ── Trade behavior ────────────────────────────────────────────────────
    average_trade_duration_minutes: MetricValue

    # ── Statistical robustness ───────────────────────────────────────────
    bootstrap_sharpe_p5: MetricValue

    # ── Provenance ────────────────────────────────────────────────────────
    provenance: MetricProvenance
