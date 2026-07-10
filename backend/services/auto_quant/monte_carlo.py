"""Monte Carlo simulation engine for Auto-Quant Stage 6.

Shuffles the OOS trade profit-ratio series ``n`` times using NumPy to estimate
the distribution of worst-case Max Drawdown across randomised trade orderings.
Scalar summaries (p5/p95 drawdown, median return) are always returned.
A compact ``equity_fan`` dict (p5/p50/p95 equity-curve arrays) is also
included so the frontend can render a fan chart without storing every path.
"""

from __future__ import annotations

import numpy as np


def run_monte_carlo(profit_ratios: list[float], n: int = 1000, threshold: float = 0.35) -> dict:
    """Run ``n`` Monte Carlo shuffles of the OOS trade profit series.

    Parameters
    ----------
    profit_ratios:
        Per-trade profit ratios from the out-of-sample backtest (e.g. 0.012
        for a +1.2 % trade, -0.008 for a -0.8 % trade).
    n:
        Number of shuffles.  Default 1000.

    Returns
    -------
    dict with keys:
        simulations        — actual number of shuffles run
        p5_drawdown        — 5th-percentile max drawdown (fraction, e.g. 0.10 = 10 %)
        p95_drawdown       — 95th-percentile max drawdown (worst-case)
        median_final_return — median final cumulative return across shuffles
        passed             — bool: p95_drawdown < threshold
        equity_fan         — dict with keys p5, p50, p95, each a list[float]
                             giving the percentile equity-curve at every trade step
                             (length = len(profit_ratios) + 1, starting at 1.0)
    """
    if not profit_ratios:
        return {
            "simulations": 0,
            "p5_drawdown": 0.0,
            "p95_drawdown": 0.0,
            "median_final_return": 0.0,
            "passed": True,
            "equity_fan": {"p5": [], "p50": [], "p95": []},
        }

    arr = np.array(profit_ratios, dtype=np.float64)
    rng = np.random.default_rng()

    num_steps = len(profit_ratios) + 1  # +1 for the starting 1.0

    drawdowns: list[float] = []
    final_returns: list[float] = []
    all_equity_paths = np.empty((n, num_steps), dtype=np.float64)

    for i in range(n):
        shuffled = arr.copy()
        rng.shuffle(shuffled)

        equity = np.cumprod(1.0 + shuffled)
        full_equity = np.concatenate(([1.0], equity))

        all_equity_paths[i] = full_equity

        running_max = np.maximum.accumulate(full_equity)
        dd = (running_max - full_equity) / running_max
        drawdowns.append(float(np.max(dd)))
        final_returns.append(float(equity[-1]) - 1.0)

    dd_arr = np.array(drawdowns)
    p5 = float(np.percentile(dd_arr, 5))
    p95 = float(np.percentile(dd_arr, 95))
    median_ret = float(np.median(final_returns))

    fan_p5 = np.percentile(all_equity_paths, 5, axis=0)
    fan_p50 = np.percentile(all_equity_paths, 50, axis=0)
    fan_p95 = np.percentile(all_equity_paths, 95, axis=0)

    equity_fan = {
        "p5":  [round(float(v), 6) for v in fan_p5],
        "p50": [round(float(v), 6) for v in fan_p50],
        "p95": [round(float(v), 6) for v in fan_p95],
    }

    return {
        "simulations": n,
        "p5_drawdown": round(p5, 4),
        "p95_drawdown": round(p95, 4),
        "median_final_return": round(median_ret, 4),
        "passed": p95 < threshold,
        "equity_fan": equity_fan,
    }
