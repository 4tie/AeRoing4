"""Tests for the Deterministic Decision Policy (PROMPT 8 §4).

Covers the user-mandated cases plus boundary/regression tests:
  * NO_EDGE → material improvement → KEEP
  * NO_EDGE → tiny improvement → INCONCLUSIVE
  * STOPLOSS_DOMINANCE → target improves + PF stable → KEEP
  * STOPLOSS_DOMINANCE → target improves + DD materially worse → DROP
  * EXCESSIVE_DRAWDOWN → DD improves materially + edge stable → KEEP
  * missing critical evidence → INCONCLUSIVE
  * unsupported objective (PAIR_CONCENTRATION) → INCONCLUSIVE
  * same input → same decision (determinism)
Plus:
  * NO_EDGE → material regression → DROP
  * insufficient candidate sample → INCONCLUSIVE
  * guardrail PF regression beyond tolerance → DROP
  * boundary exactly at materiality → KEEP (>=), one tick below → INCONCLUSIVE
"""

from __future__ import annotations

from backend.services.aeroing4.diagnosis.models import DiagnosisCode
from backend.services.aeroing4.metrics.models import (
    CanonicalMetricsSnapshot,
    MetricAvailability,
    MetricProvenance,
    MetricValue,
    SourceType,
)
from backend.services.aeroing4.research.decision_policy import (
    DecisionPolicy,
    DecisionRequest,
    ExperimentDecision,
)
from backend.services.aeroing4.research.experiments import ExperimentDecision as ED


def _snap(
    *,
    expectancy=0.0,
    profit_factor=1.0,
    win_rate=50.0,
    max_drawdown_pct=20.0,
    total_trades=120,
):
    prov = MetricProvenance(
        metrics_version="1.0.0",
        source_type=SourceType.PARSED_SUMMARY,
        source_parser_version="ResultParser",
        calculation_timestamp="2026-01-01T00:00:00Z",
    )
    return CanonicalMetricsSnapshot(
        total_trades=MetricValue(value=total_trades, availability=MetricAvailability.AVAILABLE),
        winning_trades=MetricValue.unavailable(),
        losing_trades=MetricValue.unavailable(),
        net_profit_abs=MetricValue.unavailable(),
        net_profit_pct=MetricValue.unavailable(),
        win_rate=MetricValue(value=win_rate, availability=MetricAvailability.AVAILABLE),
        profit_factor=MetricValue(value=profit_factor, availability=MetricAvailability.AVAILABLE),
        expectancy=MetricValue(value=expectancy, availability=MetricAvailability.AVAILABLE),
        sharpe=MetricValue.unavailable(),
        sortino=MetricValue.unavailable(),
        calmar=MetricValue.unavailable(),
        max_drawdown_abs=MetricValue.unavailable(),
        max_drawdown_pct=MetricValue(value=max_drawdown_pct, availability=MetricAvailability.AVAILABLE),
        average_trade_duration_minutes=MetricValue.unavailable(),
        bootstrap_sharpe_p5=MetricValue.unavailable(),
        provenance=prov,
    )


def _req(code, parent, cand, min_sample_trades=30):
    return DecisionRequest(
        diagnosis_code=code,
        experiment_objective=None,
        parent_metrics=parent,
        candidate_metrics=cand,
        min_sample_trades=min_sample_trades,
    )


def test_no_edge_material_improvement_keep():
    parent = _snap(expectancy=0.10, profit_factor=1.2, max_drawdown_pct=20.0)
    # Candidate improves expectancy >10% (0.10 → 0.13 = +30%), DD/PF hold.
    cand = _snap(expectancy=0.13, profit_factor=1.2, max_drawdown_pct=20.0)
    res = DecisionPolicy.decide(_req(DiagnosisCode.NO_EDGE, parent, cand))
    assert res.decision == ExperimentDecision.KEEP
    assert res.target_relative_change is not None and res.target_relative_change > 0.10


def test_no_edge_tiny_improvement_inconclusive():
    parent = _snap(expectancy=0.10, profit_factor=1.2, max_drawdown_pct=20.0)
    # +5% change is within noise (materiality 10%) → INCONCLUSIVE.
    cand = _snap(expectancy=0.105, profit_factor=1.2, max_drawdown_pct=20.0)
    res = DecisionPolicy.decide(_req(DiagnosisCode.NO_EDGE, parent, cand))
    assert res.decision == ExperimentDecision.INCONCLUSIVE
    assert "noise" in res.reason


def test_stoploss_target_improves_pf_stable_keep():
    parent = _snap(win_rate=50.0, profit_factor=1.2, max_drawdown_pct=20.0)
    # Win rate up >10% (50 → 56 = +12%), PF/DD stable.
    cand = _snap(win_rate=56.0, profit_factor=1.2, max_drawdown_pct=20.0)
    res = DecisionPolicy.decide(_req(DiagnosisCode.STOPLOSS_DOMINANCE, parent, cand))
    assert res.decision == ExperimentDecision.KEEP


def test_stoploss_target_improves_dd_materially_worse_drop():
    parent = _snap(win_rate=50.0, profit_factor=1.2, max_drawdown_pct=20.0)
    # Win rate up +12% BUT DD worsens >15% (20 → 24 = +20% → -20% improvement).
    cand = _snap(win_rate=56.0, profit_factor=1.2, max_drawdown_pct=24.0)
    res = DecisionPolicy.decide(_req(DiagnosisCode.STOPLOSS_DOMINANCE, parent, cand))
    assert res.decision == ExperimentDecision.DROP
    assert "max_drawdown_pct" in res.guardrail_violations


def test_excessive_drawdown_dd_improves_edge_stable_keep():
    parent = _snap(max_drawdown_pct=30.0, expectancy=0.10, profit_factor=1.2)
    # DD down >15% (30 → 24 = -20% → +20% improvement), edge stable.
    cand = _snap(max_drawdown_pct=24.0, expectancy=0.10, profit_factor=1.2)
    res = DecisionPolicy.decide(_req(DiagnosisCode.EXCESSIVE_DRAWDOWN, parent, cand))
    assert res.decision == ExperimentDecision.KEEP
    assert res.target_relative_change is not None and res.target_relative_change > 0.15


def test_missing_critical_evidence_inconclusive():
    parent = _snap(expectancy=0.10, profit_factor=1.2, max_drawdown_pct=20.0)
    # Candidate expectancy unavailable → cannot judge target.
    cand = _snap(profit_factor=1.2, max_drawdown_pct=20.0)
    cand.expectancy = MetricValue.unavailable()
    res = DecisionPolicy.decide(_req(DiagnosisCode.NO_EDGE, parent, cand))
    assert res.decision == ExperimentDecision.INCONCLUSIVE
    assert "missing_critical_evidence" in res.reason


def test_unsupported_objective_inconclusive():
    parent = _snap()
    cand = _snap()
    res = DecisionPolicy.decide(_req(DiagnosisCode.PAIR_CONCENTRATION, parent, cand))
    assert res.decision == ExperimentDecision.INCONCLUSIVE
    assert "unsupported_objective" in res.reason
    # Same for the other unsupported pair-structure codes.
    res2 = DecisionPolicy.decide(_req(DiagnosisCode.SINGLE_PAIR_DEPENDENCE, parent, cand))
    assert res2.decision == ExperimentDecision.INCONCLUSIVE
    res3 = DecisionPolicy.decide(_req(DiagnosisCode.MULTIPLE_NEGATIVE_CONTRIBUTORS, parent, cand))
    assert res3.decision == ExperimentDecision.INCONCLUSIVE


def test_same_input_same_decision():
    parent = _snap(expectancy=0.10, profit_factor=1.2, max_drawdown_pct=20.0)
    cand = _snap(expectancy=0.13, profit_factor=1.2, max_drawdown_pct=20.0)
    req = _req(DiagnosisCode.NO_EDGE, parent, cand)
    a = DecisionPolicy.decide(req)
    b = DecisionPolicy.decide(req)
    assert a.decision == b.decision
    assert a.target_relative_change == b.target_relative_change
    assert a.reason == b.reason


def test_no_edge_material_regression_drop():
    parent = _snap(expectancy=0.20, profit_factor=1.5, max_drawdown_pct=15.0)
    # Expectancy drops >10% (0.20 → 0.16 = -20%).
    cand = _snap(expectancy=0.16, profit_factor=1.5, max_drawdown_pct=15.0)
    res = DecisionPolicy.decide(_req(DiagnosisCode.NO_EDGE, parent, cand))
    assert res.decision == ExperimentDecision.DROP
    assert "regression" in res.reason


def test_insufficient_candidate_sample_inconclusive():
    parent = _snap(expectancy=0.10, profit_factor=1.2, max_drawdown_pct=20.0)
    cand = _snap(expectancy=0.20, profit_factor=1.2, max_drawdown_pct=20.0, total_trades=10)
    res = DecisionPolicy.decide(_req(DiagnosisCode.NO_EDGE, parent, cand, min_sample_trades=30))
    assert res.decision == ExperimentDecision.INCONCLUSIVE
    assert "insufficient_sample" in res.reason


def test_guardrail_pf_regression_drop():
    parent = _snap(expectancy=0.10, profit_factor=1.5, max_drawdown_pct=15.0)
    # Expectancy up +30% but PF drops >5% (1.5 → 1.4 = -6.7%).
    cand = _snap(expectancy=0.13, profit_factor=1.4, max_drawdown_pct=15.0)
    res = DecisionPolicy.decide(_req(DiagnosisCode.NO_EDGE, parent, cand))
    assert res.decision == ExperimentDecision.DROP
    assert "profit_factor" in res.guardrail_violations


def test_boundary_materiality_keep_and_below_inconclusive():
    parent = _snap(expectancy=0.10, profit_factor=1.2, max_drawdown_pct=20.0)
    # Exactly +10% (materiality) → KEEP (>=).
    boundary = _snap(expectancy=0.11, profit_factor=1.2, max_drawdown_pct=20.0)
    res_up = DecisionPolicy.decide(_req(DiagnosisCode.NO_EDGE, parent, boundary))
    assert res_up.decision == ExperimentDecision.KEEP
    # One tick below materiality (9%) → INCONCLUSIVE.
    below = _snap(expectancy=0.109, profit_factor=1.2, max_drawdown_pct=20.0)
    res_below = DecisionPolicy.decide(_req(DiagnosisCode.NO_EDGE, parent, below))
    assert res_below.decision == ExperimentDecision.INCONCLUSIVE


def test_decision_enum_matches_experiment_decision():
    # The policy reuses the same ExperimentDecision enum (no duplicate).
    assert ExperimentDecision.KEEP == ED.KEEP
    assert ExperimentDecision.DROP == ED.DROP
    assert ExperimentDecision.INCONCLUSIVE == ED.INCONCLUSIVE
