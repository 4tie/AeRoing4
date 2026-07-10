"""Stage implementations for assessment stages (4, 5).

This module acts as a coordinator, importing and re-exporting assessment functions
from the assessment subpackage to maintain backward compatibility.
"""

from .assessment import (
    # Data helpers
    _load_stage4_result,
    _extract_oos_trades,
    _extract_oos_profit_ratios,
    _first_float,
    # Readiness assessment
    _validate_existing_gate_summary,
    # Stage implementations
    _stage_risk_assessment,
    _stage_joint_portfolio_backtest,
)

__all__ = [
    # Data helpers
    "_load_stage4_result",
    "_extract_oos_trades",
    "_extract_oos_profit_ratios",
    "_first_float",
    # Readiness assessment
    "_validate_existing_gate_summary",
    # Stage implementations
    "_stage_risk_assessment",
    "_stage_joint_portfolio_backtest",
]
