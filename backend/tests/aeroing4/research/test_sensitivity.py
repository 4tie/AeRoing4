"""Tests for PROMPT 9 Sensitivity Analysis (corrections #7,#8,#9 + tests P–W).

Reuses the EXISTING BacktestRunner interface via a fake runner. The fake
derives expectancy from rsi_threshold only, so:
  * rsi_threshold (entry int) → moves expectancy → fragile/stable by magnitude
  * stoploss (risk decimal)   → does NOT move expectancy in fake → STABLE
  * boolean/categorical        → NOT_APPLICABLE
  * zero-valued numeric        → non-zero perturbation derived safely
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from backend.services.aeroing4.diagnosis.models import DiagnosisCode
from backend.services.aeroing4.metrics.models import CanonicalMetricsSnapshot, MetricAvailability, MetricProvenance, MetricValue, SourceType
from backend.services.aeroing4.research.allowed_targets import AllowedMutationTarget, MutationTargetSource, MutationTargetRiskClass
from backend.services.aeroing4.research.champions import ArtifactReference, ChampionReference, ChampionSourceType
from backend.services.aeroing4.research.sensitivity import SensitivityService, ParamSensitivityClass, SensitivityStatus
from backend.services.aeroing4.research.ledger import AccessDecision, AccessDecisionCode
from backend.services.aeroing4.research.data_zones import RESEARCH_PROTOCOL_VERSION


def _prov():
    return MetricProvenance(metrics_version="1.0.0", source_type=SourceType.PARSED_SUMMARY,
                             source_parser_version="ResultParser", calculation_timestamp="2026-01-01T00:00:00Z")


def _snap(expectancy=0.10):
    mv = MetricValue
    return CanonicalMetricsSnapshot(
        total_trades=mv(value=120, availability=MetricAvailability.AVAILABLE),
        winning_trades=mv.unavailable(),
        losing_trades=mv.unavailable(),
        net_profit_abs=mv.unavailable(),
        net_profit_pct=mv.unavailable(),
        win_rate=mv(value=50.0, availability=MetricAvailability.AVAILABLE),
        profit_factor=mv(value=1.2, availability=MetricAvailability.AVAILABLE),
        expectancy=mv(value=expectancy, availability=MetricAvailability.AVAILABLE),
        sharpe=mv.unavailable(),
        sortino=mv.unavailable(),
        calmar=mv.unavailable(),
        max_drawdown_abs=mv.unavailable(),
        max_drawdown_pct=mv(value=20.0, availability=MetricAvailability.AVAILABLE),
        average_trade_duration_minutes=mv.unavailable(),
        bootstrap_sharpe_p5=mv.unavailable(),
        provenance=_prov(),
    )


def _seed_champion(tmp_path: Path, params: dict):
    sd = tmp_path / "strategies"
    sd.mkdir(parents=True, exist_ok=True)
    py = sd / "AIStrategy.py"
    py.write_text("class AIStrategy:\n    pass\n", encoding="utf-8")
    sc = sd / "AIStrategy.json"
    sc.write_text(json.dumps({"parameters": params}), encoding="utf-8")
    return ChampionReference(
        run_id="run-1", parent_champion_id=None, source_type=ChampionSourceType.BASELINE,
        strategy_artifact=ArtifactReference(artifact_path="champions/x.py", artifact_hash="abc",
                                            original_source_path=str(py), original_source_hash="src-h"),
        parameter_artifact=ArtifactReference(artifact_path="champions/x.json", artifact_hash="def",
                                             original_source_path=str(sc), original_source_hash="par-h"),
        metrics=_snap(),
    )


class _FakeZoneGuard:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def request_access(self, run, stage, zone, experiment_id=None):
        return AccessDecision(
            allowed=self.allowed,
            decision_code=AccessDecisionCode.ALLOWED if self.allowed else AccessDecisionCode.ZONE_NOT_ALLOWED_FOR_STAGE,
            reason="test", run_id=getattr(run, "run_id", "run-1"), stage=stage, zone=zone,
            protocol_version=RESEARCH_PROTOCOL_VERSION,
        ), None


class _FakeRunner:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.call_count = 0
        self._dirs = {}
        self.run_repository = self

    def run_candidate_backtest(self, strategy, version_id, request, params_override=None):
        self.call_count += 1
        eid = f"sens-{self.call_count}"
        if self.fail:
            raise RuntimeError("boom")
        cp = (params_override.custom_params if params_override else None) or {}
        try:
            rsi = float(cp.get("rsi_threshold", 30))
        except (TypeError, ValueError):
            rsi = 30.0
        expectancy = 0.10 + (rsi - 30.0) * 0.005
        snap = _snap(expectancy=expectancy)
        d = Path(tempfile.mkdtemp())
        d.joinpath("parsed_summary.json").write_text(snap.model_dump_json(), encoding="utf-8")
        self._dirs[eid] = d
        return eid

    def find_run_dir(self, eid):
        return self._dirs[eid]


def _target(name, type_, current, lo, hi):
    return AllowedMutationTarget(
        name=name, type=type_, current_value=current, min_allowed=lo, max_allowed=hi,
        mutable=True, source=MutationTargetSource.SIDECAR_METADATA, risk_class=MutationTargetRiskClass.LOW,
    )


def _make(tmp_path, sidecar_params, *, zone_allowed=True, runner_fail=False):
    champ = _seed_champion(tmp_path, sidecar_params)
    zone = _FakeZoneGuard(allowed=zone_allowed)
    runner = _FakeRunner(fail=runner_fail)
    strategies_dir = tmp_path / "strategies"
    svc = SensitivityService(runs_root=tmp_path, backtest_runner=runner, zone_guard=zone, strategies_dir=strategies_dir)
    return svc, champ, zone, runner


# ── §7: type-aware perturbation ───────────────────────────────────────────────

def test_P_float_two_sided_perturbation(tmp_path):
    svc, champ, zone, runner = _make(tmp_path, {
        "stoploss": {"type": "decimal", "editable": True, "current": -0.1, "min": -0.5, "max": -0.01},
    })
    res = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                 diagnosis_code=DiagnosisCode.STOPLOSS_DOMINANCE,
                 allowed_targets=[_target("stoploss", "decimal", -0.1, -0.5, -0.01)])
    p = res.per_param[0]
    # stoploss doesn't move expectancy in fake → STABLE, but perturbation is two-sided
    assert len(p.swept_values) == 2
    assert p.swept_values[0] < -0.1 < p.swept_values[1]  # around base, clamped
    assert p.classification == ParamSensitivityClass.STABLE


def test_Q_int_neighbor_perturbation(tmp_path):
    svc, champ, zone, runner = _make(tmp_path, {
        "rsi_threshold": {"type": "int", "editable": True, "current": 30, "min": 10, "max": 50},
    })
    res = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                 diagnosis_code=DiagnosisCode.NO_EDGE,
                 allowed_targets=[_target("rsi_threshold", "int", 30, 10, 50)])
    p = res.per_param[0]
    assert all(isinstance(v, int) for v in p.swept_values)  # integer neighbors only
    assert len(set(p.swept_values)) == len(p.swept_values)  # deduped


def test_R_zero_valued_numeric_nonzero_perturbation(tmp_path):
    svc, champ, zone, runner = _make(tmp_path, {
        "take_profit": {"type": "decimal", "editable": True, "current": 0.0, "min": -0.05, "max": 0.05},
    })
    res = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                 diagnosis_code=DiagnosisCode.PARAMETER_RESEARCH_NEEDED,
                 allowed_targets=[_target("take_profit", "decimal", 0.0, -0.05, 0.05)])
    p = res.per_param[0]
    # base == 0 → perturbation must be non-zero (derived from allowed range)
    assert p.swept_values, "must produce perturbation points"
    assert all(v != 0 for v in p.swept_values)
    assert p.classification == ParamSensitivityClass.STABLE  # doesn't move expectancy in fake


def test_S_categorical_boolean_not_applicable(tmp_path):
    svc, champ, zone, runner = _make(tmp_path, {
        "use_filter": {"type": "bool", "editable": True, "current": True, "min": None, "max": None},
        "mode": {"type": "categorical", "editable": True, "current": "a", "min": None, "max": None},
    })
    res = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                 diagnosis_code=DiagnosisCode.PARAMETER_RESEARCH_NEEDED,
                 allowed_targets=[
                     _target("use_filter", "bool", True, None, None),
                     _target("mode", "categorical", "a", None, None),
                 ])
    for p in res.per_param:
        assert p.classification == ParamSensitivityClass.NOT_APPLICABLE


# ── §8: classifications ───────────────────────────────────────────────────────

def test_fragile_classification_emitted(tmp_path):
    # rsi_threshold moves expectancy; wide range → fragile.
    svc, champ, zone, runner = _make(tmp_path, {
        "rsi_threshold": {"type": "int", "editable": True, "current": 30, "min": 10, "max": 50},
    })
    svc.perturbation_pct = 0.5  # big perturbation → material move
    res = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                 diagnosis_code=DiagnosisCode.NO_EDGE,
                 allowed_targets=[_target("rsi_threshold", "int", 30, 10, 50)])
    p = res.per_param[0]
    assert p.classification in (ParamSensitivityClass.ONE_SIDED_FRAGILE, ParamSensitivityClass.TWO_SIDED_FRAGILE)


# ── §9: progression gate ──────────────────────────────────────────────────────

def test_T_fragile_not_eligible_for_confirmation(tmp_path):
    svc, champ, zone, runner = _make(tmp_path, {
        "rsi_threshold": {"type": "int", "editable": True, "current": 30, "min": 10, "max": 50},
    })
    svc.perturbation_pct = 0.5
    res = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                 diagnosis_code=DiagnosisCode.NO_EDGE,
                 allowed_targets=[_target("rsi_threshold", "int", 30, 10, 50)])
    assert res.status == SensitivityStatus.SENSITIVITY_FRAGILE
    assert res.eligible_for_confirmation is False
    assert "rsi_threshold" in res.fragile_params


def test_V_pass_eligible_for_confirmation(tmp_path):
    # Only a stable (non-objective) param → STABLE → PASS.
    svc, champ, zone, runner = _make(tmp_path, {
        "stoploss": {"type": "decimal", "editable": True, "current": -0.1, "min": -0.5, "max": -0.01},
    })
    res = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                 diagnosis_code=DiagnosisCode.PARAMETER_RESEARCH_NEEDED,
                 allowed_targets=[_target("stoploss", "decimal", -0.1, -0.5, -0.01)])
    assert res.status == SensitivityStatus.SENSITIVITY_PASS
    assert res.eligible_for_confirmation is True


def test_U_inconclusive_not_eligible(tmp_path):
    # No hyperopt-capable params → INCONCLUSIVE per param → stage INCONCLUSIVE.
    svc, champ, zone, runner = _make(tmp_path, {
        "mode": {"type": "categorical", "editable": True, "current": "a", "min": None, "max": None},
    })
    res = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                 diagnosis_code=DiagnosisCode.PARAMETER_RESEARCH_NEEDED,
                 allowed_targets=[_target("mode", "categorical", "a", None, None)])
    assert res.status == SensitivityStatus.SENSITIVITY_INCONCLUSIVE
    assert res.eligible_for_confirmation is False


def test_denial_protocol_denied(tmp_path):
    svc, champ, zone, runner = _make(tmp_path, {
        "rsi_threshold": {"type": "int", "editable": True, "current": 30, "min": 10, "max": 50},
    }, zone_allowed=False)
    res = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                 diagnosis_code=DiagnosisCode.NO_EDGE,
                 allowed_targets=[_target("rsi_threshold", "int", 30, 10, 50)])
    assert res.status == SensitivityStatus.PROTOCOL_DENIED
    assert res.eligible_for_confirmation is False
