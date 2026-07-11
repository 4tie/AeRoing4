"""Versioned Confirmation policy for the AeRoing4 pipeline (PROMPT 10 §4, §5, §6).

Confirmation is an ABSOLUTE out-of-development (OOS) gate. It does NOT compare
DEVELOP metrics vs CONFIRMATION metrics (that would be a dishonest cross-zone
relative comparison). It evaluates the frozen Champion's CONFIRMATION-zone
metrics against centralized, versioned absolute thresholds.

The minimum-trade requirement is delegated to the shared timeframe-aware policy
`backend.services.aeroing4.policies.get_min_trades` — never duplicated here.
"""

from __future__ import annotations

from enum import Enum

from ..policies import get_min_trades


class ConfirmationExecutionStatus(str, Enum):
    """How the Confirmation stage itself terminated (separate from the research
    decision). A system failure is its own terminal status and must NEVER be
    silently rewritten as a research INCONCLUSIVE."""

    SKIPPED = "skipped"                      # Sensitivity did not PASS → not entered
    BLOCKED = "blocked"                      # paused / unreconciled / no champion
    PROTOCOL_DENIED = "protocol_denied"      # CONFIRMATION zone access denied
    EXECUTION_SYSTEM_FAILURE = "execution_system_failure"  # Freqtrade/parse/metrics failure
    COMPLETED = "completed"                  # backtest ran and produced metrics


class ConfirmationDecision(str, Enum):
    """The research verdict of a COMPLETED Confirmation evaluation."""

    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


# Centralized, explicit, TESTED thresholds (correction #5). Do NOT scatter
# `min_profit_factor = 1.0` literals across the codebase.
CONFIRMATION_POLICY_VERSION = "1.0.0"


class ConfirmationPolicy:
    """Versioned absolute OOS acceptance policy.

    Only the policy_version + these thresholds define what 'good enough to
    confirm' means. Trade-count sufficiency comes from the shared
    timeframe-aware policy (get_min_trades), not from a duplicated constant.
    """

    policy_version: str = CONFIRMATION_POLICY_VERSION
    # Profit Factor must be at or above this (absolute OOS gate). Default 1.10
    # (strictly profitable), explicit and tested — not a scattered 1.0 literal.
    min_profit_factor: float = 1.10
    require_positive_expectancy: bool = True
    max_drawdown_pct: float = 50.0
    # Metrics that MUST be AVAILABLE for a decisive PASS/FAIL (otherwise INCONCLUSIVE).
    required_metrics: tuple[str, ...] = ("total_trades", "profit_factor", "expectancy", "max_drawdown_pct")

    def evaluate(self, metrics, timeframe: str):
        """Return (ConfirmationDecision | None, reason_codes).

        `decision` is None only when execution_status would be
        EXECUTION_SYSTEM_FAILURE (handled by the caller). Here metrics exist.
        """
        from ..metrics.models import MetricAvailability

        reason_codes: list[str] = []

        # Availability gate → INCONCLUSIVE (no fake-zero substitution).
        for name in self.required_metrics:
            mv = getattr(metrics, name, None)
            if mv is None or mv.availability != MetricAvailability.AVAILABLE:
                reason_codes.append(f"metric_unavailable:{name}")
        if reason_codes:
            return ConfirmationDecision.INCONCLUSIVE, reason_codes

        total = metrics.total_trades.value
        min_trades = get_min_trades(timeframe)  # shared timeframe-aware policy (§4)
        if total < min_trades:
            reason_codes.append(f"insufficient_trades:{total}<{min_trades}")
            return ConfirmationDecision.INCONCLUSIVE, reason_codes

        pf = metrics.profit_factor.value
        if pf < self.min_profit_factor:
            reason_codes.append(f"profit_factor_below_threshold:{pf}<{self.min_profit_factor}")
            return ConfirmationDecision.FAIL, reason_codes

        if self.require_positive_expectancy and (metrics.expectancy.value <= 0):
            reason_codes.append(f"nonpositive_expectancy:{metrics.expectancy.value}")
            return ConfirmationDecision.FAIL, reason_codes

        dd = metrics.max_drawdown_pct.value
        if dd > self.max_drawdown_pct:
            reason_codes.append(f"drawdown_above_threshold:{dd}>{self.max_drawdown_pct}")
            return ConfirmationDecision.FAIL, reason_codes

        reason_codes.append("all_absolute_thresholds_met")
        return ConfirmationDecision.PASS, reason_codes
