"""Stage → zone permission registry (Stage Permission Registry).

One authoritative policy for which stage may access which zone. Do not
scatter permission checks across if-statements elsewhere — every call site
that needs a zone must go through `allowed_zones_for_stage` /
`access_guard.DataZoneGuard.can_access`.

Every stage AeRoing4 currently implements (or is documented to implement
next) is classified explicitly — never guessed silently:

  PRE_RESEARCH_OPERATIONAL  runs before any research zone is touched; not
                            zone-gated at all (validation/data plumbing).
  ZONE_NEUTRAL              inspects the strategy/code itself, not
                            zone-scoped market data; not zone-gated.
  DEVELOP_CONSUMER          may only ever access the DEVELOP zone.
  CONFIRMATION_CONSUMER     may only ever access the CONFIRMATION zone.
  FINAL_UNSEEN_CONSUMER     may only ever access the FINAL_UNSEEN zone.
"""

from __future__ import annotations

from enum import Enum

from .data_zones import ResearchZone


class ResearchStage(str, Enum):
    """Every AeRoing4 stage relevant to the Research Protocol.

    Names match the existing `step_name` strings used in `AeRoing4Run.steps`
    where a stage is already implemented (`validation`, `data_preparation`,
    `smoke_backtest`, `pair_discovery`); the rest are future stages named per
    `docs/AEROING4_TARGET_ARCHITECTURE.md`'s 15-stage target workflow so the
    registry does not need to change shape when they are implemented.
    """

    # ── Pre-research operational stages (implemented today) ────────────────
    STRATEGY_VALIDATION = "validation"
    DATA_PREPARATION = "data_preparation"
    SMOKE_BACKTEST = "smoke_backtest"

    # ── Zone-neutral stage (not yet implemented) ────────────────────────────
    BIAS_CHECK = "bias_check"

    # ── DEVELOP-only consumers ───────────────────────────────────────────────
    PAIR_DISCOVERY = "pair_discovery"  # implemented today
    PORTFOLIO_BASELINE = "portfolio_baseline"  # not yet implemented
    RESEARCH_EXPERIMENT = "research_experiment"  # not yet implemented
    HYPEROPT = "hyperopt"  # not yet implemented
    SENSITIVITY = "sensitivity"  # not yet implemented

    # ── Single-zone terminal consumers (execution not implemented) ─────────
    CONFIRMATION = "confirmation"
    FINAL_UNSEEN = "final_unseen"


class StageClassification(str, Enum):
    """Explicit classification of a stage relative to the Data Zone Guard."""

    PRE_RESEARCH_OPERATIONAL = "pre_research_operational"
    ZONE_NEUTRAL = "zone_neutral"
    DEVELOP_CONSUMER = "develop_consumer"
    CONFIRMATION_CONSUMER = "confirmation_consumer"
    FINAL_UNSEEN_CONSUMER = "final_unseen_consumer"


# Documented, one-time classification decision — see module docstring.
STAGE_CLASSIFICATIONS: dict[ResearchStage, StageClassification] = {
    ResearchStage.STRATEGY_VALIDATION: StageClassification.PRE_RESEARCH_OPERATIONAL,
    ResearchStage.DATA_PREPARATION: StageClassification.PRE_RESEARCH_OPERATIONAL,
    ResearchStage.SMOKE_BACKTEST: StageClassification.PRE_RESEARCH_OPERATIONAL,
    ResearchStage.BIAS_CHECK: StageClassification.ZONE_NEUTRAL,
    ResearchStage.PAIR_DISCOVERY: StageClassification.DEVELOP_CONSUMER,
    ResearchStage.PORTFOLIO_BASELINE: StageClassification.DEVELOP_CONSUMER,
    ResearchStage.RESEARCH_EXPERIMENT: StageClassification.DEVELOP_CONSUMER,
    ResearchStage.HYPEROPT: StageClassification.DEVELOP_CONSUMER,
    ResearchStage.SENSITIVITY: StageClassification.DEVELOP_CONSUMER,
    ResearchStage.CONFIRMATION: StageClassification.CONFIRMATION_CONSUMER,
    ResearchStage.FINAL_UNSEEN: StageClassification.FINAL_UNSEEN_CONSUMER,
}

# The authoritative stage → allowed-zone(s) policy. Stages absent from this
# mapping (pre-research/zone-neutral) are never allowed to access a
# protected zone — `allowed_zones_for_stage` returns an empty set for them.
STAGE_ALLOWED_ZONES: dict[ResearchStage, frozenset[ResearchZone]] = {
    ResearchStage.PAIR_DISCOVERY: frozenset({ResearchZone.DEVELOP}),
    ResearchStage.PORTFOLIO_BASELINE: frozenset({ResearchZone.DEVELOP}),
    ResearchStage.RESEARCH_EXPERIMENT: frozenset({ResearchZone.DEVELOP}),
    ResearchStage.HYPEROPT: frozenset({ResearchZone.DEVELOP}),
    ResearchStage.SENSITIVITY: frozenset({ResearchZone.DEVELOP}),
    ResearchStage.CONFIRMATION: frozenset({ResearchZone.CONFIRMATION}),
    ResearchStage.FINAL_UNSEEN: frozenset({ResearchZone.FINAL_UNSEEN}),
}


def allowed_zones_for_stage(stage: ResearchStage) -> frozenset[ResearchZone]:
    """Return the set of zones `stage` may access (empty if none)."""
    return STAGE_ALLOWED_ZONES.get(stage, frozenset())


def classification_for_stage(stage: ResearchStage) -> StageClassification:
    """Return the documented classification for `stage`.

    Raises `KeyError` rather than guessing if a stage is ever added to
    `ResearchStage` without an explicit classification decision.
    """
    return STAGE_CLASSIFICATIONS[stage]
