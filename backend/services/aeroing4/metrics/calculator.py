"""Authoritative formula implementations for the AeRoing4 Metrics SSOT.

These functions are the ONLY place canonical metrics are calculated from raw
trade/return data. They must be called only when a trusted existing source
(`ParsedSummary`, Freqtrade-native summary block) does not already provide
the value — see `adapters.py` for the "prefer existing value" rule.

All functions are pure (no I/O) and take plain floats/lists so they are easy
to unit test in isolation and are not tied to any particular pydantic model.
"""

from __future__ import annotations

import random
import statistics

from .models import MetricAvailability, MetricValue

# Profit-factor "no losing trades" sentinel. Chosen to match the existing,
# already-shipped Pair Discovery scoring behavior (see
# `steps/pair_discovery.py::_compute_profit_factor`, pre-migration): a
# strategy with only winning trades is capped at this large-but-finite value
# rather than represented as literal infinity, since `scoring.py`'s
# `pf_score` formula already saturates at profit_factor >= 3.0. Changing this
# sentinel would change ranking behavior, which this migration must not do.
PROFIT_FACTOR_NO_LOSS_SENTINEL = 999.0

# Bootstrap Sharpe P5 defaults.
BOOTSTRAP_DEFAULT_SAMPLES = 1000
BOOTSTRAP_DEFAULT_SEED = 42
BOOTSTRAP_MIN_TRADES = 5


def compute_profit_factor(profits: list[float]) -> MetricValue:
    """Profit Factor = gross_profit / gross_loss.

    Edge cases (binding policy):
    - Zero trades → UNAVAILABLE (nothing to compute).
    - No losing trades and no winning trades either (all exactly zero) →
      UNAVAILABLE (profit factor is undefined when both sides are zero).
    - No losing trades but at least one winning trade → AVAILABLE, capped at
      `PROFIT_FACTOR_NO_LOSS_SENTINEL` (documented finite sentinel instead of
      infinity, to keep the value usable by downstream scoring formulas).
    """
    if not profits:
        return MetricValue.unavailable()
    gross_profit = sum(p for p in profits if p > 0)
    gross_loss = abs(sum(p for p in profits if p < 0))
    if gross_loss == 0:
        if gross_profit == 0:
            return MetricValue.unavailable()
        return MetricValue.available(PROFIT_FACTOR_NO_LOSS_SENTINEL)
    return MetricValue.available(round(gross_profit / gross_loss, 4))


def compute_expectancy_abs(profits: list[float]) -> MetricValue:
    """Expectancy = average profit per trade, in absolute currency units.

    `sum(profits) / len(profits)`. This is algebraically identical to
    `ResultParser._derive_expectancy`'s `win_rate * avg_win - loss_rate *
    avg_loss` formula — both reduce to total profit divided by trade count,
    regardless of how exactly-zero-profit trades are classified as
    win/loss. Zero trades → UNAVAILABLE.
    """
    if not profits:
        return MetricValue.unavailable()
    return MetricValue.available(round(sum(profits) / len(profits), 6))


def compute_win_rate(profits: list[float]) -> MetricValue:
    """Win rate as a 0-100 percentage. Zero trades → UNAVAILABLE."""
    if not profits:
        return MetricValue.unavailable()
    wins = sum(1 for p in profits if p > 0)
    return MetricValue.available(round(wins / len(profits) * 100, 4))


def compute_trade_counts(profits: list[float]) -> tuple[MetricValue, MetricValue, MetricValue]:
    """Returns (total_trades, winning_trades, losing_trades).

    A trade with exactly zero profit is counted in total_trades but in
    neither winning nor losing — this matches how "win"/"loss" is used
    everywhere else in the codebase (`profit > 0` / `profit < 0`).
    """
    if profits is None:
        return MetricValue.unavailable(), MetricValue.unavailable(), MetricValue.unavailable()
    total = len(profits)
    if total == 0:
        return MetricValue.available(0), MetricValue.unavailable(), MetricValue.unavailable()
    wins = sum(1 for p in profits if p > 0)
    losses = sum(1 for p in profits if p < 0)
    return MetricValue.available(total), MetricValue.available(wins), MetricValue.available(losses)


def compute_max_drawdown_abs(equity_curve: list[float]) -> MetricValue:
    """Max drawdown in absolute currency units from a running equity curve.

    `equity_curve` must be balance-over-time (not returns). Needs at least
    2 points to define a drawdown.
    """
    if not equity_curve or len(equity_curve) < 2:
        return MetricValue.unavailable()
    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        max_dd = max(max_dd, peak - value)
    return MetricValue.available(round(max_dd, 6))


def compute_max_drawdown_pct(equity_curve: list[float]) -> MetricValue:
    """Max drawdown as a 0-100 percentage of the running peak equity."""
    if not equity_curve or len(equity_curve) < 2:
        return MetricValue.unavailable()
    peak = equity_curve[0]
    max_dd_pct = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            max_dd_pct = max(max_dd_pct, (peak - value) / peak * 100)
    return MetricValue.available(round(max_dd_pct, 4))


def compute_average_trade_duration_minutes(durations_minutes: list[float]) -> MetricValue:
    """Average trade duration in minutes. Empty list → UNAVAILABLE."""
    filtered = [d for d in durations_minutes if d is not None]
    if not filtered:
        return MetricValue.unavailable()
    return MetricValue.available(round(sum(filtered) / len(filtered), 4))


def compute_sharpe(returns: list[float]) -> MetricValue:
    """Sharpe ratio fallback, computed directly on a per-trade return series.

    Documented assumptions (fallback-only; prefer Freqtrade's native
    `sharpe`/`sharpe_ratio` value via `adapters.py` whenever it is present):
    - Return series: per-trade `profit_ratio` values (NOT per-day returns —
      AeRoing4 does not have a reliable trade-frequency-to-calendar-time
      mapping independent of Freqtrade's own internal calculation).
    - No annualization is applied. This value is therefore NOT directly
      comparable to Freqtrade's own (annualized) Sharpe and must always be
      recorded as a `derived_metrics` entry in provenance so consumers know
      it is a conservative fallback, not the native value.
    - Risk-free rate assumption: 0.
    - Population standard deviation (`statistics.pstdev`) is used for
      determinism (no sample-size Bessel-correction ambiguity).
    - Minimum sample size: 2 returns. Fewer → INSUFFICIENT_DATA.
    - Zero volatility (all returns identical) → NOT_APPLICABLE (Sharpe is
      undefined, not zero, when there is no variance to divide by).
    """
    if len(returns) < 2:
        return MetricValue.insufficient_data()
    mean = statistics.mean(returns)
    stdev = statistics.pstdev(returns)
    if stdev == 0:
        return MetricValue.not_applicable()
    return MetricValue.available(round(mean / stdev, 6))


def compute_sortino(returns: list[float], minimum_acceptable_return: float = 0.0) -> MetricValue:
    """Sortino ratio fallback, computed on a per-trade return series.

    Documented assumptions (fallback-only; same non-annualized caveat as
    `compute_sharpe`):
    - Downside deviation: root-mean-square of `(return - MAR)` for returns
      below MAR (population, not sample).
    - `minimum_acceptable_return` (MAR) defaults to 0.
    - No downside returns at all → NOT_APPLICABLE (there is no meaningful
      downside risk to normalize by — not the same as "zero risk", so it is
      not represented as an unbounded/sentinel value).
    - Minimum sample size: 2 returns. Fewer → INSUFFICIENT_DATA.
    """
    if len(returns) < 2:
        return MetricValue.insufficient_data()
    downside = [r - minimum_acceptable_return for r in returns if r < minimum_acceptable_return]
    if not downside:
        return MetricValue.not_applicable()
    downside_deviation = statistics.pstdev([0.0] + downside) if len(downside) == 1 else statistics.pstdev(downside)
    # Population stdev of a single-element downside list is 0 by definition;
    # use RMS instead for a single downside observation so a single loss
    # still yields a defined (non-zero) downside deviation.
    if len(downside) == 1:
        downside_deviation = abs(downside[0])
    if downside_deviation == 0:
        return MetricValue.not_applicable()
    mean_excess = statistics.mean(r - minimum_acceptable_return for r in returns)
    return MetricValue.available(round(mean_excess / downside_deviation, 6))


def compute_calmar(total_return_pct: float | None, max_drawdown_pct: float | None) -> MetricValue:
    """Calmar ratio fallback = total_return_pct / max_drawdown_pct.

    Documented assumptions (fallback-only):
    - `total_return_pct` and `max_drawdown_pct` are both 0-100 scale
      percentages (canonical convention), not annualized (AeRoing4 does not
      currently track calendar-year-normalized returns independently of
      Freqtrade's own Calmar calculation).
    - Zero (or missing) max_drawdown_pct → NOT_APPLICABLE (division by zero
      drawdown is undefined, not "infinitely good").
    """
    if total_return_pct is None or max_drawdown_pct is None:
        return MetricValue.unavailable()
    if max_drawdown_pct == 0:
        return MetricValue.not_applicable()
    return MetricValue.available(round(total_return_pct / max_drawdown_pct, 6))


def compute_bootstrap_sharpe_p5(
    returns: list[float],
    *,
    n_samples: int = BOOTSTRAP_DEFAULT_SAMPLES,
    seed: int = BOOTSTRAP_DEFAULT_SEED,
) -> MetricValue:
    """5th-percentile Sharpe ratio from a deterministic bootstrap resample.

    Method (binding):
    - Source return series: the same per-trade return series used by
      `compute_sharpe` (per-trade `profit_ratio`, non-annualized).
    - Resampling: `n_samples` (default 1000) bootstrap resamples, each drawn
      with replacement at the original sample size, using `random.Random(seed)`
      (default seed 42) — NOT the global `random` module, so this never
      interferes with unrelated randomness elsewhere in the process and is
      fully reproducible given the same `returns`, `n_samples`, and `seed`.
    - Statistic: population-Sharpe (mean/pstdev, risk-free rate 0) computed
      per resample; resamples with zero variance are skipped.
    - Percentile: 5th percentile of the sorted resample Sharpe distribution,
      via `sorted_values[floor(0.05 * len) ]` (clamped to a valid index).
    - Minimum sample size: `BOOTSTRAP_MIN_TRADES` (5) source returns.
      Fewer → INSUFFICIENT_DATA.
    - Determinism: identical `returns`/`n_samples`/`seed` always produce an
      identical result. A different `seed` may produce a different (but
      still statistically valid) result — this is expected, not a bug.
    """
    if len(returns) < BOOTSTRAP_MIN_TRADES:
        return MetricValue.insufficient_data()
    rng = random.Random(seed)
    n = len(returns)
    sample_sharpes: list[float] = []
    for _ in range(n_samples):
        sample = [returns[rng.randrange(n)] for _ in range(n)]
        stdev = statistics.pstdev(sample)
        if stdev == 0:
            continue
        sample_sharpes.append(statistics.mean(sample) / stdev)
    if not sample_sharpes:
        return MetricValue.not_applicable()
    sample_sharpes.sort()
    index = min(len(sample_sharpes) - 1, max(0, int(0.05 * len(sample_sharpes))))
    return MetricValue.available(round(sample_sharpes[index], 6))
