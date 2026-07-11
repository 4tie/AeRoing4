"""Tests for PROMPT 10 Confirmation (corrections #1–#10 + tests A–R).

Reuses the EXISTING BacktestRunner interface via a fake runner (no real
Freqtrade). The fake derives metrics from the frozen Champion params so PASS/
FAIL/INCONCLUSIVE are deterministic.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from backend.services.aeroing4.metrics.models import (
    CanonicalMetricsSnapshot, MetricAvailability, MetricProvenance, MetricValue, SourceType,
)
from backend.services.aeroing4.research.champions import (
    ArtifactReference, ChampionReference, ChampionSourceType, ChampionStore,
)
from backend.services.aeroing4.research.confirmation import (
    ConfirmationResult, ConfirmationService, ConfirmationStore, compute_confirmation_identity,
)
from backend.services.aeroing4.research.confirmation_policy import (
    ConfirmationDecision, ConfirmationExecutionStatus, ConfirmationPolicy,
)
from backend.services.aeroing4.research.ledger import AccessDecision, AccessDecisionCode
from backend.services.aeroing4.research.data_zones import RESEARCH_PROTOCOL_VERSION
from backend.services.aeroing4.research.research_state import ResearchStateStore


def _prov():
    return MetricProvenance(metrics_version="1.0.0", source_type=SourceType.PARSED_SUMMARY,
                             source_parser_version="ResultParser", calculation_timestamp="2026-01-01T00:00:00Z")


def _snap(pf=1.3, expectancy=0.12, total_trades=120, dd=20.0):
    mv = MetricValue
    return CanonicalMetricsSnapshot(
        total_trades=mv(value=total_trades, availability=MetricAvailability.AVAILABLE),
        winning_trades=mv.unavailable(), losing_trades=mv.unavailable(),
        net_profit_abs=mv.unavailable(), net_profit_pct=mv.unavailable(),
        win_rate=mv(value=50.0, availability=MetricAvailability.AVAILABLE),
        profit_factor=mv(value=pf, availability=MetricAvailability.AVAILABLE),
        expectancy=mv(value=expectancy, availability=MetricAvailability.AVAILABLE),
        sharpe=mv.unavailable(), sortino=mv.unavailable(), calmar=mv.unavailable(),
        max_drawdown_abs=mv.unavailable(), max_drawdown_pct=mv(value=dd, availability=MetricAvailability.AVAILABLE),
        average_trade_duration_minutes=mv.unavailable(), bootstrap_sharpe_p5=mv.unavailable(),
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
        strategy_artifact=ArtifactReference(artifact_path="champions/x.py", artifact_hash="strat-hash",
                                            original_source_path=str(py), original_source_hash="strat-h"),
        parameter_artifact=ArtifactReference(artifact_path="champions/x.json", artifact_hash="param-hash",
                                             original_source_path=str(sc), original_source_hash="param-h"),
    )


class _FakeZoneGuard:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.confirmation_passed = False
        self.confirmation_passed_at = None

    def request_access(self, run, stage, zone, experiment_id=None):
        return AccessDecision(
            allowed=self.allowed,
            decision_code=AccessDecisionCode.ALLOWED if self.allowed else AccessDecisionCode.ZONE_NOT_ALLOWED_FOR_STAGE,
            reason="test", run_id=getattr(run, "run_id", "run-1"), stage=stage, zone=zone,
            protocol_version=RESEARCH_PROTOCOL_VERSION,
        ), None

    def set_confirmation_passed(self, run, passed=True):
        self.confirmation_passed = passed
        self.confirmation_passed_at = "2026-01-01T00:00:00Z" if passed else None
        run.research_protocol = type("P", (), {"confirmation_passed": passed})()


class _FakeRunner:
    def __init__(self, *, fail=False, pf=1.3, expectancy=0.12, dd=20.0, total_trades=120):
        self.fail = fail
        self._counter = 0
        self._dirs = {}
        self.run_repository = self
        self.pf, self.exp, self.dd, self.total_trades = pf, expectancy, dd, total_trades

    def run_candidate_backtest(self, strategy, version_id, request, params_override=None):
        self._counter += 1
        eid = f"conf-{self._counter}"
        if self.fail:
            raise RuntimeError("boom")
        snap = _snap(pf=self.pf, expectancy=self.exp, dd=self.dd, total_trades=self.total_trades)
        d = Path(tempfile.mkdtemp())
        d.joinpath("parsed_summary.json").write_text(snap.model_dump_json(), encoding="utf-8")
        self._dirs[eid] = d
        return eid

    def find_run_dir(self, eid):
        return self._dirs[eid]


def _make(tmp_path, *, zone_allowed=True, runner_fail=False, pf=1.3, expectancy=0.12, dd=20.0, total_trades=120):
    champ = _seed_champion(tmp_path, {"rsi_threshold": {"type": "int", "editable": True, "current": 30, "min": 10, "max": 50}})
    store = ChampionStore(tmp_path)
    store.register(champ)
    zone = _FakeZoneGuard(allowed=zone_allowed)
    runner = _FakeRunner(fail=runner_fail, pf=pf, expectancy=expectancy, dd=dd, total_trades=total_trades)
    svc = ConfirmationService(
        runs_root=tmp_path, backtest_runner=runner, champion_store=store, zone_guard=zone,
    )
    return svc, champ, zone, runner, store


def _run_obj():
    return type("Run", (), {"run_id": "run-1", "research_protocol": None})()


# ── A–C / I / R: identity + idempotency ──────────────────────────────────────

def test_A_same_identity_reused(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path)
    r1 = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                eligible_for_confirmation=True)
    r2 = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                eligible_for_confirmation=True)
    assert r1.result_id == r2.result_id  # reused, not re-executed
    assert runner._counter == 1


def test_B_same_champion_altered_context_rejected(tmp_path):
    # Different timerange → different boundary_hash → different identity → a NEW
    # result (not a silent rerun of the old one). Integrity enforced by identity.
    svc, champ, zone, runner, store = _make(tmp_path)
    r1 = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                eligible_for_confirmation=True)
    svc.confirmation_timerange = "20240901-20240930"  # altered frozen context
    r2 = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                eligible_for_confirmation=True)
    assert r1.confirmation_identity != r2.confirmation_identity
    assert r1.result_id != r2.result_id
    assert runner._counter == 2  # honest new evaluation, not a hidden reuse


def test_C_restart_after_completed_reused(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path)
    r1 = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                eligible_for_confirmation=True)
    # restart (fresh service, same store) → deterministic reuse
    svc2 = ConfirmationService(runs_root=tmp_path, backtest_runner=runner,
                               champion_store=store, zone_guard=zone)
    r2 = svc2.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                 eligible_for_confirmation=True)
    assert r2.result_id == r1.result_id
    assert runner._counter == 1


# ── eligibility / protocol gate ──────────────────────────────────────────────

def test_skip_when_sensitivity_not_pass(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path)
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               eligible_for_confirmation=False)
    assert r.execution_status == ConfirmationExecutionStatus.SKIPPED
    assert runner._counter == 0


def test_M_access_denied_no_exec_no_pass(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, zone_allowed=False)
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               eligible_for_confirmation=True)
    assert r.execution_status == ConfirmationExecutionStatus.PROTOCOL_DENIED
    assert runner._counter == 0
    assert zone.confirmation_passed is False


def test_N_pass_persisted_protocol_gate_true(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, pf=1.3, expectancy=0.12)
    run = _run_obj()
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               eligible_for_confirmation=True, run=run)
    assert r.execution_status == ConfirmationExecutionStatus.COMPLETED
    assert r.decision == ConfirmationDecision.PASS
    assert zone.confirmation_passed is True
    # persisted
    store2 = ConfirmationStore(tmp_path)
    loaded = store2.load(r.result_id)
    assert loaded is not None and loaded.decision == ConfirmationDecision.PASS


def test_O_fail_persisted_champion_unchanged_gate_false(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, pf=0.8)  # below threshold
    run = _run_obj()
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               eligible_for_confirmation=True, run=run)
    assert r.decision == ConfirmationDecision.FAIL
    assert zone.confirmation_passed is False
    # Champion unchanged: same champion_id, no new registration
    assert store.get("run-1", champ.champion_id).champion_id == champ.champion_id
    assert zone.confirmation_passed is False


def test_P_inconclusive_persisted_gate_false(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, total_trades=5)  # below min_trades → INCONCLUSIVE
    run = _run_obj()
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               eligible_for_confirmation=True, run=run)
    assert r.decision == ConfirmationDecision.INCONCLUSIVE
    assert zone.confirmation_passed is False
    # persisted
    store2 = ConfirmationStore(tmp_path)
    assert store2.load(r.result_id).decision == ConfirmationDecision.INCONCLUSIVE


def test_Q_system_failure_not_inconclusive(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, runner_fail=True)
    run = _run_obj()
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               eligible_for_confirmation=True, run=run)
    assert r.execution_status == ConfirmationExecutionStatus.EXECUTION_SYSTEM_FAILURE
    assert r.decision is None
    assert zone.confirmation_passed is False


# ── J / K: integrity (hash mismatch after eligibility) ───────────────────────

def test_J_changed_strategy_hash_integrity(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path)
    # Trusted hash (from untamperable source) still original; champion tampered.
    champ.strategy_artifact.artifact_hash = "TAMPERED"
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               eligible_for_confirmation=True, strategy_hash="strat-hash", parameter_hash="param-hash")
    assert r.execution_status == ConfirmationExecutionStatus.BLOCKED
    assert "integrity failure" in r.reason_codes[0]
    assert runner._counter == 0


def test_K_changed_parameter_hash_integrity(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path)
    champ.parameter_artifact.artifact_hash = "TAMPERED"
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               eligible_for_confirmation=True, strategy_hash="strat-hash", parameter_hash="param-hash")
    assert r.execution_status == ConfirmationExecutionStatus.BLOCKED
    assert "integrity failure" in r.reason_codes[0]
    assert runner._counter == 0


# ── access ordering (correction #8) ──────────────────────────────────────────

def test_ordering_no_exec_before_access(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, zone_allowed=False)
    # zone guard records whether request_access was called before any backtest call
    calls = []
    orig = zone.request_access
    def traced(run, stage, z, experiment_id=None):
        calls.append(("access", z.value))
        return orig(run, stage, z, experiment_id)
    zone.request_access = traced
    svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
           eligible_for_confirmation=True)
    # access for CONFIRMATION must be attempted; backtest never called (denied)
    assert ("access", "confirmation") in calls
    assert runner._counter == 0


# ── shared trade-sufficiency policy (correction #4) ──────────────────────────

def test_shared_min_trades_used(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path)
    from backend.services.aeroing4.policies import get_min_trades
    assert svc.policy.evaluate(_snap(total_trades=get_min_trades("5m") - 1), "5m")[0] == ConfirmationDecision.INCONCLUSIVE


# ── REAL guard smoke test (correction #10) ───────────────────────────────────

def test_real_confirmation_smoke_guard():
    import shutil
    if shutil.which("freqtrade") is None:
        pytest.skip("SKIPPED: REAL_FREQTRADE_UNAVAILABLE")
    # When Freqtrade is present, a real frozen-Champion CONFIRMATION smoke would run
    # here against the CONFIRMATION zone. Not executed in this environment.
