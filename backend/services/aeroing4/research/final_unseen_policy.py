"""Versioned Final Unseen policy for the AeRoing4 pipeline (PROMPT 11 §4).

Final Unseen is the FINAL independent test — an ABSOLUTE out-of-sample (OOS)
gate. It is NOT a cross-zone comparison and NEVER substitutes missing metrics
with zero.

The minimum-trade requirement is delegated to the shared timeframe-aware policy
`backend.services.aeroing4.policies.get_min_trades` — never duplicated here.
"""

from __future__ import annotations

from enum import Enum

from ..policies import get_min_trades


class FinalUnseenExecutionStatus(str, Enum):
    """How the Final Unseen stage itself terminated (separate from the research
    decision). A system failure is its own terminal status and must NEVER be
    silently rewritten as INCONCLUSIVE (correction — no retry, terminal evidence)."""

    SKIPPED = "skipped"                       # not yet eligible (Confirmation not PASS)
    BLOCKED = "blocked"                       # contaminated / integrity / preflight failure
    PROTOCOL_DENIED = "protocol_denied"       # FINAL_UNSEEN zone access denied
    EXECUTION_SYSTEM_FAILURE = "execution_system_failure"  # Freqtrade/parse/metrics failure
    COMPLETED = "completed"                   # backtest ran and produced metrics


class FinalUnseenDecision(str, Enum):
    """The research verdict of a COMPLETED Final Unseen evaluation."""

    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


FINAL_UNSEEN_POLICY_VERSION = "1.0.0"


class FinalUnseenPolicy:
    """Versioned absolute OOS acceptance policy (terminal evidence).

    Only policy_version + these thresholds define 'delivery eligible'. Trade
    count sufficiency comes from the shared timeframe-aware policy.
    """

    policy_version: str = FINAL_UNSEEN_POLICY_VERSION
    min_profit_factor: float = 1.10           # centralized, tested — not a scattered literal
    require_positive_expectancy: bool = True
    max_drawdown_pct: float = 50.0
    required_metrics: tuple[str, ...] = ("total_trades", "profit_factor", "expectancy", "max_drawdown_pct")

    def evaluate(self, metrics, timeframe: str):
        """Return (FinalUnseenDecision | None, reason_codes).

        `decision` is None only when execution_status would be
        EXECUTION_SYSTEM_FAILURE (handled by the caller). Here metrics exist.
        No zero-substitution for missing/ unavailable metrics.
        """
        from ..metrics.models import MetricAvailability

        reason_codes: list[str] = []

        for name in self.required_metrics:
            mv = getattr(metrics, name, None)
            if mv is None or mv.availability != MetricAvailability.AVAILABLE:
                reason_codes.append(f"metric_unavailable:{name}")
        if reason_codes:
            return FinalUnseenDecision.INCONCLUSIVE, reason_codes

        total = metrics.total_trades.value
        min_trades = get_min_trades(timeframe)
        if total < min_trades:
            reason_codes.append(f"insufficient_trades:{total}<{min_trades}")
            return FinalUnseenDecision.INCONCLUSIVE, reason_codes

        pf = metrics.profit_factor.value
        if pf < self.min_profit_factor:
            reason_codes.append(f"profit_factor_below_threshold:{pf}<{self.min_profit_factor}")
            return FinalUnseenDecision.FAIL, reason_codes

        if self.require_positive_expectancy and (metrics.expectancy.value <= 0):
            reason_codes.append(f"nonpositive_expectancy:{metrics.expectancy.value}")
            return FinalUnseenDecision.FAIL, reason_codes

        dd = metrics.max_drawdown_pct.value
        if dd > self.max_drawdown_pct:
            reason_codes.append(f"drawdown_above_threshold:{dd}>{self.max_drawdown_pct}")
            return FinalUnseenDecision.FAIL, reason_codes

        reason_codes.append("all_absolute_thresholds_met")
        return FinalUnseenDecision.PASS, reason_codes
