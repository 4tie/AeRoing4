"""services/execution/pair_sweep_runner.py contains backend logic for pair sweep runner.

This file is intentionally documented in plain English so readers can follow
what each section does even without deep Python experience.

This file now serves as a facade for the pair_sweep subpackage to maintain
backward compatibility with existing imports.
"""

from .pair_sweep import (
    PairSweepRunner,
    run_individual_pair_sweep,
    run_portfolio_backtest,
    decide_final_pair_set,
)

__all__ = [
    "PairSweepRunner",
    "run_individual_pair_sweep",
    "run_portfolio_backtest",
    "decide_final_pair_set",
]

