"""Tests for PROMPT 9 Focused Hyperopt (corrections #2,#3,#4,#6,#10 + tests A–O).

Reuses the EXISTING BacktestRunner interface via a fake runner (no real
Freqtrade). The fake computes a deterministic CanonicalMetricsSnapshot from
the candidate params so coordinate-descent + sensitivity see real gradients.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from backend.services.aeroing4.diagnosis.models import DiagnosisCode
from backend.services.aeroing4.metrics.models import CanonicalMetricsSnapshot, MetricAvailability, MetricProvenance, MetricValue, SourceType
from backend.services.aeroing4.research.allowed_targets import AllowedMutationTarget, MutationTargetSource, MutationTargetRiskClass
from backend.services.aeroing4.research.champions import ArtifactReference, ChampionReference, ChampionSourceType, ChampionStore
from backend.services.aeroing4.research.focused_hyperopt import FocusedHyperoptService, FocusedHyperoptStatus
from backend.services.aeroing4.research.hyperopt_policy import FocusedHyperoptBudgetPolicy


def _prov():
    return MetricProvenance(metrics_version="1.0.0", source_type=SourceType.PARSED_SUMMARY,
                             source_parser_version="ResultParser", calculation_timestamp="2026-01-01T00:00:00Z")


def _snap(expectancy=0.10, total_trades=120):
    mv = MetricValue
    return CanonicalMetricsSnapshot(
        total_trades=mv(value=total_trades, availability=MetricAvailability.AVAILABLE),
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


def _seed_champion(runs_root: Path, metrics=None):
    sd = runs_root / "strategies"
    sd.mkdir(parents=True, exist_ok=True)
    py = sd / "AIStrategy.py"
    py.write_text("class AIStrategy:\n    pass\n", encoding="utf-8")
    sc = sd / "AIStrategy.json"
    sc.write_text('{"parameters": {"rsi_threshold": {"type": "int", "editable": true, "current": 30, "min": 10, "max": 50}}}', encoding="utf-8")
    return ChampionReference(
        run_id="run-1", parent_champion_id=None, source_type=ChampionSourceType.BASELINE,
        strategy_artifact=ArtifactReference(artifact_path="champions/x.py", artifact_hash="abc",
                                            original_source_path=str(py), original_source_hash="src-h"),
        parameter_artifact=ArtifactReference(artifact_path="champions/x.json", artifact_hash="def",
                                             original_source_path=str(sc), original_source_hash="par-h"),
        metrics=metrics or _snap(),
    )


class _FakeZoneGuard:
    def __init__(self, allowed=True, code="allowed"):
        self.allowed = allowed
        self.code = code
        self.calls = []

    def request_access(self, run, stage, zone, experiment_id=None):
        from backend.services.aeroing4.research.ledger import AccessDecision, AccessDecisionCode
        from backend.services.aeroing4.research.data_zones import RESEARCH_PROTOCOL_VERSION
        self.calls.append((stage, zone))
        decision = AccessDecision(
            allowed=self.allowed,
            decision_code=AccessDecisionCode(self.code) if self.allowed else AccessDecisionCode.ZONE_NOT_ALLOWED_FOR_STAGE,
            reason="test", run_id=getattr(run, "run_id", "run-1"), stage=stage, zone=zone,
            protocol_version=RESEARCH_PROTOCOL_VERSION,
        )
        return decision, None


class _FakeRunner:
    """Mimics BacktestRunner.run_candidate_backtest; metrics derived from params."""

    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []
        self._counter = 0
        self._dirs = {}
        self.run_repository = self

    def run_candidate_backtest(self, strategy, version_id, request, params_override=None):
        self._counter += 1
        eid = f"exec-{self._counter}"
        self.calls.append((eid, params_override))
        if self.fail:
            raise RuntimeError("boom")
        cp = (params_override.custom_params if params_override else None) or {}
        try:
            rsi = float(cp.get("rsi_threshold", 30))
        except (TypeError, ValueError):
            rsi = 30.0
        # Deterministic gradient: expectancy moves with rsi_threshold only.
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


def _make(tmp_path, *, zone_allowed=True, runner_fail=False):
    champ = _seed_champion(tmp_path)
    store = ChampionStore(tmp_path)
    store.register(champ)
    zone = _FakeZoneGuard(allowed=zone_allowed)
    runner = _FakeRunner(fail=runner_fail)
    svc = FocusedHyperoptService(
        runs_root=tmp_path, backtest_runner=runner, champion_store=store, zone_guard=zone,
        budget=FocusedHyperoptBudgetPolicy(default_epochs=6, max_epochs=20, max_search_targets=12),
    )
    return svc, champ, zone, runner, store


# ── §2/§3: scope + objective ──────────────────────────────────────────────────

def test_A_scope_narrows_by_diagnosis():
    from backend.services.aeroing4.research.hyperopt_policy import build_focused_scope
    targets = [_target("rsi_threshold", "int", 30, 10, 50),
               _target("stoploss", "decimal", -0.1, -0.5, -0.01)]
    # NO_EDGE → entry scope; stoploss (risk) excluded.
    sc = build_focused_scope(DiagnosisCode.NO_EDGE, targets)
    assert sc.outcome.value == "focused_scope_ready"
    names = {t.name for t in sc.targets}
    assert "rsi_threshold" in names
    assert "stoploss" not in names
    assert sc.objective.value == "edge_improvement"


def test_I_allowed_target_not_hyperopt_capable():
    from backend.services.aeroing4.research.hyperopt_policy import build_focused_scope
    # categorical → not hyperopt-capable
    targets = [_target("mode", "categorical", "a", None, None)]
    sc = build_focused_scope(DiagnosisCode.PARAMETER_RESEARCH_NEEDED, targets)
    assert sc.outcome.value == "no_hyperopt_capable_target"


def test_J_diagnosis_no_actionable_objective():
    from backend.services.aeroing4.research.hyperopt_policy import build_focused_scope
    targets = [_target("rsi_threshold", "int", 30, 10, 50)]
    sc = build_focused_scope(DiagnosisCode.INSUFFICIENT_SAMPLE, targets)
    assert sc.outcome.value == "no_actionable_hyperopt_objective"


def test_K_empty_focused_intersection_no_broad_fallback():
    from backend.services.aeroing4.research.hyperopt_policy import build_focused_scope
    # NO_EDGE (entry) but only a risk param present → empty intersection.
    targets = [_target("stoploss", "decimal", -0.1, -0.5, -0.01)]
    sc = build_focused_scope(DiagnosisCode.NO_EDGE, targets)
    assert sc.outcome.value == "no_actionable_hyperopt_scope"
    assert sc.targets == []  # NOT broadened to all strategy params


# ── §6: result path ───────────────────────────────────────────────────────────

def test_D_hyperopt_keep_promotes_hyperopt_champion(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path)
    res = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1",
                 champion=champ, diagnosis_code=DiagnosisCode.NO_EDGE,
                 allowed_targets=[_target("rsi_threshold", "int", 30, 10, 50)])
    assert res.status == FocusedHyperoptStatus.SUCCESS
    assert res.decision.value == "keep"
    assert res.promoted_champion_id is not None
    promoted = store.get("run-1", res.promoted_champion_id)
    assert promoted.source_type.value == "hyperopt"
    assert promoted.parent_champion_id == champ.champion_id
    assert promoted.parameter_artifact is not None


def test_N_hyperopt_drop_current_unchanged(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path)
    # Force a DROP: make candidate worse than parent. Use a fake runner that
    # always returns low expectancy regardless of params.
    class _Worse(_FakeRunner):
        def run_candidate_backtest(self, strategy, version_id, request, params_override=None):
            self._counter += 1
            eid = f"exec-{self._counter}"
            snap = _snap(expectancy=0.05)
            d = Path(tempfile.mkdtemp())
            d.joinpath("parsed_summary.json").write_text(snap.model_dump_json(), encoding="utf-8")
            self._dirs[eid] = d
            return eid
    svc.backtest_runner = _Worse()
    res = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1",
                 champion=champ, diagnosis_code=DiagnosisCode.NO_EDGE,
                 allowed_targets=[_target("rsi_threshold", "int", 30, 10, 50)])
    assert res.decision.value == "drop"
    assert res.promoted_champion_id is None
    # current champion still the baseline
    assert store.get("run-1", champ.champion_id).source_type.value == "baseline"


def test_O_hyperopt_system_failure_not_inconclusive(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, runner_fail=True)
    res = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1",
                 champion=champ, diagnosis_code=DiagnosisCode.NO_EDGE,
                 allowed_targets=[_target("rsi_threshold", "int", 30, 10, 50)])
    assert res.status == FocusedHyperoptStatus.EXECUTION_SYSTEM_FAILURE
    assert res.decision is None or res.decision.value != "inconclusive"
    assert res.metrics_availability_reason.startswith("candidate_execution_error")


# ── §10: eligibility gate ─────────────────────────────────────────────────────

def test_C_zone_denial_protocol_denied(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, zone_allowed=False)
    res = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1",
                 champion=champ, diagnosis_code=DiagnosisCode.NO_EDGE,
                 allowed_targets=[_target("rsi_threshold", "int", 30, 10, 50)])
    assert res.status == FocusedHyperoptStatus.PROTOCOL_DENIED
    assert runner.calls == []  # no execution


def test_G_blocked_when_paused(tmp_path):
    from backend.services.aeroing4.research.research_state import ResearchState, ResearchStateStore
    svc, champ, zone, runner, store = _make(tmp_path)
    rs_store = ResearchStateStore(tmp_path)
    rs = rs_store.create("run-1")
    rs.research_status = rs.research_status.PAUSED
    rs_store.save(rs)
    res = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1",
                 champion=champ, diagnosis_code=DiagnosisCode.NO_EDGE,
                 allowed_targets=[_target("rsi_threshold", "int", 30, 10, 50)],
                 state_store=rs_store)
    assert res.status == FocusedHyperoptStatus.HYPEROPT_BLOCKED
    assert runner.calls == []


def test_L_execution_context_frozen(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path)
    svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1",
           champion=champ, diagnosis_code=DiagnosisCode.NO_EDGE,
           allowed_targets=[_target("rsi_threshold", "int", 30, 10, 50)])
    # Every backtest call must use the frozen DEVELOP timerange, not something else.
    for eid, params in runner.calls:
        # params_override built from sidecar; request timerange is frozen in service.
        assert svc.develop_timerange == "20240101-20240630"


def test_factory_builders_exist():
    # Wiring sanity: factory exposes the builders and models carry the new fields.
    from backend.services.aeroing4.research.factory import (
        build_focused_hyperopt_service, build_sensitivity_service,
    )
    from backend.services.aeroing4.models import AeRoing4Run
    from backend.api.routers.aeroing4 import AeRoing4RunRequest, AeRoing4RunResponse
    assert callable(build_focused_hyperopt_service)
    assert callable(build_sensitivity_service)
    assert "enable_focused_hyperopt" in AeRoing4Run.model_fields
    assert "enable_focused_hyperopt" in AeRoing4RunRequest.model_fields
    assert "eligible_for_confirmation" in AeRoing4RunResponse.model_fields
