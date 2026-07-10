"""Stage implementations for validation stages (1, 3).

This module acts as a coordinator, importing and re-exporting stage functions
from the stages subpackage to maintain backward compatibility.
"""

from .stages import (
    _stage_pre_flight_filtering,
    _stage_sanity_backtest,
    _stage_portfolio_baseline,
    _stage_oos_validation,
    _record_oos_retry_failure,
    _stage_robustness_feature_injection,
    _stage_stress_test,
)

__all__ = [
    "_stage_pre_flight_filtering",
    "_stage_sanity_backtest",
    "_stage_portfolio_baseline",
    "_stage_oos_validation",
    "_record_oos_retry_failure",
    "_stage_robustness_feature_injection",
    "_stage_stress_test",
]
