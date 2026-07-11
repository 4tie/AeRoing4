"""Versioned, centralized Focused Hyperopt policy (PROMPT 9 §3, §4).

This module is the SINGLE source of truth for:
  * the hyperopt budget policy (epochs / max targets / version),
  * the diagnosis → parameter-category → objective-profile mapping,
  * the "is this target hyperopt-capable" capability filter.

It contains NO execution logic. FocusedHyperoptService (focused_hyperopt.py)
consumes these typed policies. Keeping them here means call sites never
hardcode 50 epochs or re-derive the diagnosis→scope mapping.

Reuse, don't rewrite: it reads ``DiagnosisCode`` and ``AllowedMutationTarget``
from existing modules; it does not invent a new diagnosis taxonomy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .allowed_targets import AllowedMutationTarget
from ..diagnosis.models import DiagnosisCode


FOCUSED_HYPEROPT_POLICY_VERSION = "1.0.0"


# ── §4: versioned, centralized budget policy ───────────────────────────────────

@dataclass(frozen=True)
class FocusedHyperoptBudgetPolicy:
    """Bounded budget for a Focused Hyperopt run.

    The stage must remain bounded. 50 epochs is the current default; future
    Quick/Deep profiles can supply different instances of this same dataclass
    without changing any call site.
    """

    policy_version: str = FOCUSED_HYPEROPT_POLICY_VERSION
    default_epochs: int = 50
    max_epochs: int = 200
    max_search_targets: int = 12

    def clamp_epochs(self, epochs: Optional[int]) -> int:
        if epochs is None:
            return self.default_epochs
        return max(1, min(int(epochs), self.max_epochs))

    def clamp_targets(self, targets: list) -> list:
        return targets[: self.max_search_targets]


# ── §2 / §3: capability filter + diagnosis-aware objective profiles ────────────

class HyperoptCapability(str, Enum):
    """Why a target is / is not in the focused hyperopt search space."""

    CAPABLE = "capable"
    NOT_NUMERIC = "not_numeric"          # boolean / categorical → NOT_APPLICABLE in v1
    NO_BOUNDS = "no_bounds"              # missing min/max → cannot bound the search


def is_hyperopt_capable(target: AllowedMutationTarget) -> HyperoptCapability:
    """A target is hyperopt-capable only if it is a numeric type with finite
    trusted bounds (continuous/int/decimal). Boolean/categorical are excluded
    from v1 search (mirrors Sensitivity §7)."""
    t = (target.type or "").lower()
    if any(k in t for k in ("bool", "categor", "choice", "enum")):
        return HyperoptCapability.NOT_NUMERIC
    if target.min_allowed is None or target.max_allowed is None:
        return HyperoptCapability.NO_BOUNDS
    return HyperoptCapability.CAPABLE


class HyperoptObjectiveProfile(str, Enum):
    """The optimization objective chosen for a diagnosis family."""

    EDGE_IMPROVEMENT = "edge_improvement"      # NO_EDGE / NEGATIVE_EXPECTANCY / LOW_PROFIT_FACTOR
    RISK_ADJUSTED = "risk_adjusted"            # STOPLOSS_DOMINANCE / EXCESSIVE_DRAWDOWN / POOR_RETURN_TO_DRAWDOWN
    BALANCED = "balanced"                      # PARAMETER_RESEARCH_NEEDED family


@dataclass(frozen=True)
class DiagnosisHyperoptRouting:
    """Maps a DiagnosisCode to its trusted parameter category + objective."""

    category: str                       # "entry" | "exit" | "risk" | "all"
    objective: HyperoptObjectiveProfile


# Diagnosis → trusted parameter category + objective profile (§3).
_DIAGNOSIS_ROUTING: dict[DiagnosisCode, DiagnosisHyperoptRouting] = {
    DiagnosisCode.NO_EDGE: DiagnosisHyperoptRouting("entry", HyperoptObjectiveProfile.EDGE_IMPROVEMENT),
    DiagnosisCode.NEGATIVE_EXPECTANCY: DiagnosisHyperoptRouting("entry", HyperoptObjectiveProfile.EDGE_IMPROVEMENT),
    DiagnosisCode.LOW_PROFIT_FACTOR: DiagnosisHyperoptRouting("entry", HyperoptObjectiveProfile.EDGE_IMPROVEMENT),
    DiagnosisCode.WEAK_EDGE: DiagnosisHyperoptRouting("entry", HyperoptObjectiveProfile.EDGE_IMPROVEMENT),
    DiagnosisCode.STOPLOSS_DOMINANCE: DiagnosisHyperoptRouting("risk", HyperoptObjectiveProfile.RISK_ADJUSTED),
    DiagnosisCode.EXCESSIVE_DRAWDOWN: DiagnosisHyperoptRouting("risk", HyperoptObjectiveProfile.RISK_ADJUSTED),
    DiagnosisCode.POOR_RETURN_TO_DRAWDOWN: DiagnosisHyperoptRouting("risk", HyperoptObjectiveProfile.RISK_ADJUSTED),
    DiagnosisCode.DOWNSIDE_RISK_DOMINANCE: DiagnosisHyperoptRouting("risk", HyperoptObjectiveProfile.RISK_ADJUSTED),
    DiagnosisCode.EXIT_LOSS_CONCENTRATION: DiagnosisHyperoptRouting("exit", HyperoptObjectiveProfile.RISK_ADJUSTED),
    DiagnosisCode.ENTRY_TOO_RESTRICTIVE: DiagnosisHyperoptRouting("entry", HyperoptObjectiveProfile.EDGE_IMPROVEMENT),
    DiagnosisCode.PARAMETER_RESEARCH_NEEDED: DiagnosisHyperoptRouting("all", HyperoptObjectiveProfile.BALANCED),
    DiagnosisCode.ENTRY_PARAMETER_RESEARCH_NEEDED: DiagnosisHyperoptRouting("entry", HyperoptObjectiveProfile.BALANCED),
    DiagnosisCode.EXIT_PARAMETER_RESEARCH_NEEDED: DiagnosisHyperoptRouting("exit", HyperoptObjectiveProfile.BALANCED),
    DiagnosisCode.RISK_PARAMETER_RESEARCH_NEEDED: DiagnosisHyperoptRouting("risk", HyperoptObjectiveProfile.BALANCED),
}


def routing_for(diagnosis_code: DiagnosisCode) -> Optional[DiagnosisHyperoptRouting]:
    """Return the routing for a diagnosis, or None if hyperopt is not actionable."""
    return _DIAGNOSIS_ROUTING.get(diagnosis_code)


def has_actionable_objective(diagnosis_code: DiagnosisCode) -> bool:
    """§3: only diagnoses with a routing have a meaningful hyperopt objective.

    Sample-quality, pair-structure, and other non-parameter-research diagnoses
    return False → NO_ACTIONABLE_HYPEROPT_OBJECTIVE (no broad hyperopt).
    """
    return routing_for(diagnosis_code) is not None


# Parameter-name prefix sets per category (used to narrow the trusted targets).
_CATEGORY_PREFIXES: dict[str, tuple[str, ...]] = {
    "entry": ("buy", "entry", "rsi", "ema", "sma", "indicator"),
    "exit": ("sell", "exit", "roi", "profit"),
    "risk": ("stoploss", "trailing", "risk", "max_open", "stake"),
    "all": tuple(),  # empty → no name filter, use all capable targets
}


def _target_matches_category(target: AllowedMutationTarget, category: str) -> bool:
    if category == "all":
        return True
    name = (target.name or "").lower()
    return any(name.startswith(p) for p in _CATEGORY_PREFIXES.get(category, ()))


def diagnose_scope(diagnosis_code: DiagnosisCode) -> str:
    """Return the parameter category scope string for a diagnosis ('entry'/
    'exit'/'risk'/'all'), or '' if not actionable."""
    r = routing_for(diagnosis_code)
    return r.category if r else ""


# ── §2: the trusted intersection ──────────────────────────────────────────────

class FocusedScopeOutcome(str, Enum):
    FOCUSED_SCOPE_READY = "focused_scope_ready"
    NO_SAFE_TARGET = "no_safe_target"            # no trusted allowed target at all
    NO_HYPEROPT_CAPABLE_TARGET = "no_hyperopt_capable_target"  # allowed but none capable
    NO_ACTIONABLE_HYPEROPT_SCOPE = "no_actionable_hyperopt_scope"      # empty after diagnosis narrowing
    NO_ACTIONABLE_HYPEROPT_OBJECTIVE = "no_actionable_hyperopt_objective"  # diagnosis not hyperopt-addressable


@dataclass
class FocusedScope:
    outcome: FocusedScopeOutcome
    targets: list[AllowedMutationTarget] = field(default_factory=list)
    objective: Optional[HyperoptObjectiveProfile] = None
    diagnosis_code: Optional[DiagnosisCode] = None
    reason: str = ""


def build_focused_scope(
    diagnosis_code: DiagnosisCode,
    allowed_targets: list[AllowedMutationTarget],
) -> FocusedScope:
    """§2: search space = Trusted Allowed Targets ∩ Hyperopt-capable ∩ Diagnosis scope.

    Never silently broadens to all strategy parameters. Returns a typed outcome.
    """
    if not allowed_targets:
        return FocusedScope(
            FocusedScopeOutcome.NO_SAFE_TARGET, diagnosis_code=diagnosis_code,
            reason="no trusted allowed mutation target discovered",
        )

    if not has_actionable_objective(diagnosis_code):
        return FocusedScope(
            FocusedScopeOutcome.NO_ACTIONABLE_HYPEROPT_OBJECTIVE, diagnosis_code=diagnosis_code,
            reason=f"diagnosis {diagnosis_code.value} has no actionable hyperopt objective",
        )

    # Trusted ∩ hyperopt-capable
    capable = [t for t in allowed_targets if is_hyperopt_capable(t) is HyperoptCapability.CAPABLE]
    if not capable:
        return FocusedScope(
            FocusedScopeOutcome.NO_HYPEROPT_CAPABLE_TARGET, diagnosis_code=diagnosis_code,
            reason="allowed targets exist but none are hyperopt-capable (numeric+bounded)",
        )

    # ∩ diagnosis-specific parameter scope
    category = diagnose_scope(diagnosis_code)
    scoped = [t for t in capable if _target_matches_category(t, category)]
    if not scoped:
        return FocusedScope(
            FocusedScopeOutcome.NO_ACTIONABLE_HYPEROPT_SCOPE, diagnosis_code=diagnosis_code,
            reason=f"no capable target matches diagnosis category '{category}'",
        )

    return FocusedScope(
        FocusedScopeOutcome.FOCUSED_SCOPE_READY,
        targets=scoped,
        objective=routing_for(diagnosis_code).objective,
        diagnosis_code=diagnosis_code,
        reason="trusted ∩ hyperopt-capable ∩ diagnosis-scope intersection",
    )
