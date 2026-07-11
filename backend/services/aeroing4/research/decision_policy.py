"""Deterministic Decision Policy for the AeRoing4 Controlled Research Loop (§4).

Input (per decision):
  * Parent Champion evidence (CanonicalMetricsSnapshot)
  * Candidate evidence        (CanonicalMetricsSnapshot)
  * Diagnosis code            (DiagnosisCode)
  * Experiment objective      (optional free-text; the typed mapping below is
                               keyed by DiagnosisCode, not by a global metric
                               ordering)

Output:
  * KEEP       — material improvement vs Parent Champion, guardrails hold
  * DROP       — material regression, or a clear guardrail violation
  * INCONCLUSIVE — no material improvement (noise), missing/sample-insufficient
                   evidence, unsupported objective, or no clear winner

Hard constraints (user decision 2026-07-11):
  * NO global metric ordering (PF → Expectancy → DD). Each DiagnosisCode maps
    to a typed objective via DiagnosisObjectiveRegistry.
  * Metrics SSOT ONLY. We read MetricValue.value / availability; we never
    recompute PF, Expectancy, Sharpe, or DD.
  * PAIR_CONCENTRATION / SINGLE_PAIR_DEPENDENCE / MULTIPLE_NEGATIVE_CONTRIBUTORS
    are UNSUPPORTED: the Candidate Executor produces parameter-mutation
    evidence only, which is not comparable evidence for pair-structure
    diagnosis → INCONCLUSIVE.
  * KEEP requires MATERIAL improvement, not a tiny noise-level change.
  * DROP on material regression or clear guardrail failure.
  * INCONCLUSIVE on missing evidence / insufficient sample / mixed result.
  * NO champion promotion here — this policy returns a decision only.
  * All thresholds are versioned and collected in ONE policy object.
  * Pure function: same input → same decision (deterministic).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from ..diagnosis.models import DiagnosisCode
from ..metrics.models import CanonicalMetricsSnapshot, MetricAvailability
from .experiments import ExperimentDecision


RESEARCH_DECISION_POLICY_VERSION = "1.0.0"

# Floating-point tolerance so an exactly-configured materiality threshold
# (e.g. 0.10) is treated as met when the computed relative change is
# 0.099999999999 due to binary float representation.
_EPS = 1e-9


class MetricDirection(str, Enum):
    HIGHER_BETTER = "higher_better"
    LOWER_BETTER = "lower_better"


@dataclass(frozen=True)
class Guardrail:
    """A secondary metric that must not degrade beyond tolerance.

    ``max_degradation_pct`` is the allowed relative degradation (e.g. 0.05 =
    5%) before the decision becomes DROP. The metric is read from the SSOT;
    if it is unavailable on either side it is treated as missing critical
    evidence → INCONCLUSIVE.
    """

    metric: str
    direction: MetricDirection
    max_degradation_pct: float


@dataclass(frozen=True)
class ObjectiveSpec:
    """Typed objective for one diagnosis code.

    Maps: Diagnosis Code → target metric + direction → materiality threshold
    → guardrails. All thresholds are versioned via the policy version.
    """

    diagnosis_code: DiagnosisCode
    target_metric: str
    target_direction: MetricDirection
    materiality_pct: float
    guardrails: tuple[Guardrail, ...] = ()
    supported: bool = True
    notes: str = ""


# ── Registry: one typed objective per diagnosis code ──────────────────────────
# Materiality: edge-family 10% relative, risk-family (DD) 15% relative.
# Guardrail tolerances: PF/expectancy 5%, DD 15%.

_REGISTRY: dict[DiagnosisCode, ObjectiveSpec] = {
    # Edge-quality family — target = expectancy (higher better)
    DiagnosisCode.NO_EDGE: ObjectiveSpec(
        DiagnosisCode.NO_EDGE,
        target_metric="expectancy",
        target_direction=MetricDirection.HIGHER_BETTER,
        materiality_pct=0.10,
        guardrails=(
            Guardrail("max_drawdown_pct", MetricDirection.LOWER_BETTER, 0.15),
            Guardrail("profit_factor", MetricDirection.HIGHER_BETTER, 0.05),
        ),
        notes="No edge: improving expectancy materially without buying DD/PF loss.",
    ),
    DiagnosisCode.NEGATIVE_EXPECTANCY: ObjectiveSpec(
        DiagnosisCode.NEGATIVE_EXPECTANCY,
        target_metric="expectancy",
        target_direction=MetricDirection.HIGHER_BETTER,
        materiality_pct=0.10,
        guardrails=(
            Guardrail("max_drawdown_pct", MetricDirection.LOWER_BETTER, 0.15),
            Guardrail("profit_factor", MetricDirection.HIGHER_BETTER, 0.05),
        ),
    ),
    DiagnosisCode.WEAK_EDGE: ObjectiveSpec(
        DiagnosisCode.WEAK_EDGE,
        target_metric="expectancy",
        target_direction=MetricDirection.HIGHER_BETTER,
        materiality_pct=0.10,
        guardrails=(
            Guardrail("max_drawdown_pct", MetricDirection.LOWER_BETTER, 0.15),
            Guardrail("profit_factor", MetricDirection.HIGHER_BETTER, 0.05),
        ),
    ),
    DiagnosisCode.LOW_PROFIT_FACTOR: ObjectiveSpec(
        DiagnosisCode.LOW_PROFIT_FACTOR,
        target_metric="profit_factor",
        target_direction=MetricDirection.HIGHER_BETTER,
        materiality_pct=0.10,
        guardrails=(
            Guardrail("max_drawdown_pct", MetricDirection.LOWER_BETTER, 0.15),
            Guardrail("expectancy", MetricDirection.HIGHER_BETTER, 0.05),
        ),
    ),
    # Exit-behavior family — target = win_rate (higher better)
    DiagnosisCode.STOPLOSS_DOMINANCE: ObjectiveSpec(
        DiagnosisCode.STOPLOSS_DOMINANCE,
        target_metric="win_rate",
        target_direction=MetricDirection.HIGHER_BETTER,
        materiality_pct=0.10,
        guardrails=(
            Guardrail("profit_factor", MetricDirection.HIGHER_BETTER, 0.05),
            Guardrail("max_drawdown_pct", MetricDirection.LOWER_BETTER, 0.15),
        ),
        notes="Fewer stop-loss hits: win_rate up, PF/DD must not regress materially.",
    ),
    DiagnosisCode.EXIT_LOSS_CONCENTRATION: ObjectiveSpec(
        DiagnosisCode.EXIT_LOSS_CONCENTRATION,
        target_metric="win_rate",
        target_direction=MetricDirection.HIGHER_BETTER,
        materiality_pct=0.10,
        guardrails=(
            Guardrail("profit_factor", MetricDirection.HIGHER_BETTER, 0.05),
            Guardrail("max_drawdown_pct", MetricDirection.LOWER_BETTER, 0.15),
        ),
    ),
    # Entry-behavior family — target = expectancy (higher better)
    DiagnosisCode.ENTRY_TOO_RESTRICTIVE: ObjectiveSpec(
        DiagnosisCode.ENTRY_TOO_RESTRICTIVE,
        target_metric="expectancy",
        target_direction=MetricDirection.HIGHER_BETTER,
        materiality_pct=0.10,
        guardrails=(
            Guardrail("max_drawdown_pct", MetricDirection.LOWER_BETTER, 0.15),
            Guardrail("profit_factor", MetricDirection.HIGHER_BETTER, 0.05),
        ),
    ),
    # Risk-quality family — target = max_drawdown_pct (lower better)
    DiagnosisCode.EXCESSIVE_DRAWDOWN: ObjectiveSpec(
        DiagnosisCode.EXCESSIVE_DRAWDOWN,
        target_metric="max_drawdown_pct",
        target_direction=MetricDirection.LOWER_BETTER,
        materiality_pct=0.15,
        guardrails=(
            Guardrail("expectancy", MetricDirection.HIGHER_BETTER, 0.05),
            Guardrail("profit_factor", MetricDirection.HIGHER_BETTER, 0.05),
        ),
        notes="Cut DD materially without destroying the edge (expectancy/PF stable).",
    ),
    DiagnosisCode.DOWNSIDE_RISK_DOMINANCE: ObjectiveSpec(
        DiagnosisCode.DOWNSIDE_RISK_DOMINANCE,
        target_metric="max_drawdown_pct",
        target_direction=MetricDirection.LOWER_BETTER,
        materiality_pct=0.15,
        guardrails=(
            Guardrail("expectancy", MetricDirection.HIGHER_BETTER, 0.05),
            Guardrail("profit_factor", MetricDirection.HIGHER_BETTER, 0.05),
        ),
    ),
    DiagnosisCode.POOR_RETURN_TO_DRAWDOWN: ObjectiveSpec(
        DiagnosisCode.POOR_RETURN_TO_DRAWDOWN,
        target_metric="max_drawdown_pct",
        target_direction=MetricDirection.LOWER_BETTER,
        materiality_pct=0.15,
        guardrails=(
            Guardrail("expectancy", MetricDirection.HIGHER_BETTER, 0.05),
            Guardrail("profit_factor", MetricDirection.HIGHER_BETTER, 0.05),
        ),
    ),
    # Pair-structure family — UNSUPPORTED (Candidate Executor has no comparable
    # pair-structure evidence; parameter mutation cannot address these).
    DiagnosisCode.PAIR_CONCENTRATION: ObjectiveSpec(
        diagnosis_code=DiagnosisCode.PAIR_CONCENTRATION,
        target_metric="",
        target_direction=MetricDirection.HIGHER_BETTER,
        materiality_pct=0.0,
        supported=False,
        notes="No comparable candidate evidence → INCONCLUSIVE.",
    ),
    DiagnosisCode.SINGLE_PAIR_DEPENDENCE: ObjectiveSpec(
        diagnosis_code=DiagnosisCode.SINGLE_PAIR_DEPENDENCE,
        target_metric="",
        target_direction=MetricDirection.HIGHER_BETTER,
        materiality_pct=0.0,
        supported=False,
        notes="No comparable candidate evidence → INCONCLUSIVE.",
    ),
    DiagnosisCode.MULTIPLE_NEGATIVE_CONTRIBUTORS: ObjectiveSpec(
        diagnosis_code=DiagnosisCode.MULTIPLE_NEGATIVE_CONTRIBUTORS,
        target_metric="",
        target_direction=MetricDirection.HIGHER_BETTER,
        materiality_pct=0.0,
        supported=False,
        notes="No comparable candidate evidence → INCONCLUSIVE.",
    ),
}


class DecisionRequest(BaseModel):
    """Typed input to the decision policy."""

    diagnosis_code: DiagnosisCode
    experiment_objective: Optional[str] = None  # metadata; registry keyed by code
    parent_metrics: CanonicalMetricsSnapshot
    candidate_metrics: CanonicalMetricsSnapshot
    min_sample_trades: int = Field(default=30, ge=1)


class DecisionResult(BaseModel):
    """Decision output — a verdict and transparent rationale only."""

    decision: ExperimentDecision
    diagnosis_code: DiagnosisCode
    policy_version: str
    reason: str
    target_metric: Optional[str] = None
    target_relative_change: Optional[float] = None
    guardrail_violations: list[str] = Field(default_factory=list)


def _metric_value(snapshot: CanonicalMetricsSnapshot, name: str) -> Optional[float]:
    """Read a canonical metric's value, or None if unavailable."""
    mv = getattr(snapshot, name, None)
    if mv is None or mv.availability != MetricAvailability.AVAILABLE:
        return None
    return mv.value


def _relative_improvement(
    parent: float, candidate: float, direction: MetricDirection
) -> Optional[float]:
    """Signed relative IMPROVEMENT fraction (positive = better).

    Returns None when the parent baseline is zero (undefined improvement).
    """
    if parent == 0:
        return None
    denom = abs(parent)
    if direction == MetricDirection.HIGHER_BETTER:
        return (candidate - parent) / denom
    # LOWER_BETTER: candidate lower is better
    return (parent - candidate) / denom


class DecisionPolicy:
    """Versioned, deterministic decision policy.

    Stateless: same DecisionRequest → same DecisionResult.
    """

    VERSION = RESEARCH_DECISION_POLICY_VERSION

    @classmethod
    def supports(cls, code: DiagnosisCode) -> bool:
        spec = _REGISTRY.get(code)
        return spec is not None and spec.supported

    @classmethod
    def decide(cls, request: DecisionRequest) -> DecisionResult:
        spec = _REGISTRY.get(request.diagnosis_code)
        if spec is None or not spec.supported:
            return DecisionResult(
                decision=ExperimentDecision.INCONCLUSIVE,
                diagnosis_code=request.diagnosis_code,
                policy_version=cls.VERSION,
                reason="unsupported_objective: no comparable candidate evidence",
                target_metric=None,
                target_relative_change=None,
            )

        # Insufficient sample on the candidate → INCONCLUSIVE.
        cand_trades = _metric_value(request.candidate_metrics, "total_trades")
        if cand_trades is None or cand_trades < request.min_sample_trades:
            return DecisionResult(
                decision=ExperimentDecision.INCONCLUSIVE,
                diagnosis_code=request.diagnosis_code,
                policy_version=cls.VERSION,
                reason="insufficient_sample: candidate trades below minimum",
                target_metric=spec.target_metric,
            )

        # Critical target evidence must be available on both sides.
        parent_target = _metric_value(request.parent_metrics, spec.target_metric)
        cand_target = _metric_value(request.candidate_metrics, spec.target_metric)
        if parent_target is None or cand_target is None:
            return DecisionResult(
                decision=ExperimentDecision.INCONCLUSIVE,
                diagnosis_code=request.diagnosis_code,
                policy_version=cls.VERSION,
                reason="missing_critical_evidence: target metric unavailable",
                target_metric=spec.target_metric,
            )

        # Guardrail evidence must be available on both sides.
        for g in spec.guardrails:
            if (
                _metric_value(request.parent_metrics, g.metric) is None
                or _metric_value(request.candidate_metrics, g.metric) is None
            ):
                return DecisionResult(
                    decision=ExperimentDecision.INCONCLUSIVE,
                    diagnosis_code=request.diagnosis_code,
                    policy_version=cls.VERSION,
                    reason=f"missing_critical_evidence: guardrail {g.metric} unavailable",
                    target_metric=spec.target_metric,
                )

        rel = _relative_improvement(parent_target, cand_target, spec.target_direction)
        if rel is None:
            return DecisionResult(
                decision=ExperimentDecision.INCONCLUSIVE,
                diagnosis_code=request.diagnosis_code,
                policy_version=cls.VERSION,
                reason="missing_critical_evidence: zero parent baseline (undefined)",
                target_metric=spec.target_metric,
            )

        # Material regression → DROP.
        if rel <= -spec.materiality_pct - _EPS:
            return DecisionResult(
                decision=ExperimentDecision.DROP,
                diagnosis_code=request.diagnosis_code,
                policy_version=cls.VERSION,
                reason="target_regression_material",
                target_metric=spec.target_metric,
                target_relative_change=rel,
            )

        # Material improvement → check guardrails.
        if rel >= spec.materiality_pct - _EPS:
            violations: list[str] = []
            for g in spec.guardrails:
                p = _metric_value(request.parent_metrics, g.metric)
                c = _metric_value(request.candidate_metrics, g.metric)
                assert p is not None and c is not None
                g_rel = _relative_improvement(p, c, g.direction)
                if g_rel is None:
                    violations.append(g.metric)
                    continue
                # Degradation = negative improvement.
                if -g_rel > g.max_degradation_pct:
                    violations.append(g.metric)
            if violations:
                return DecisionResult(
                    decision=ExperimentDecision.DROP,
                    diagnosis_code=request.diagnosis_code,
                    policy_version=cls.VERSION,
                    reason="guardrail_violation",
                    target_metric=spec.target_metric,
                    target_relative_change=rel,
                    guardrail_violations=violations,
                )
            return DecisionResult(
                decision=ExperimentDecision.KEEP,
                diagnosis_code=request.diagnosis_code,
                policy_version=cls.VERSION,
                reason="material_improvement_guardrails_hold",
                target_metric=spec.target_metric,
                target_relative_change=rel,
            )

        # Within noise / no clear winner → INCONCLUSIVE.
        return DecisionResult(
            decision=ExperimentDecision.INCONCLUSIVE,
            diagnosis_code=request.diagnosis_code,
            policy_version=cls.VERSION,
            reason="no_material_improvement: change within noise",
            target_metric=spec.target_metric,
            target_relative_change=rel,
        )


def decide(request: DecisionRequest) -> DecisionResult:
    """Module-level convenience: decide via the versioned policy."""
    return DecisionPolicy.decide(request)
