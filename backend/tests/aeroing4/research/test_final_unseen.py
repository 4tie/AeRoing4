"""Tests for PROMPT 11 Final Unseen (corrections + amendment #1 preflight + no-retry).

Reuses the EXISTING BacktestRunner interface via a fake runner (no real Freqtrade).
The fake derives metrics from the frozen Champion params so PASS/FAIL/INCONCLUSIVE
are deterministic. Preflight is injectable so the non-data environment check can be
exercised without a real Freqtrade binary.
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
    ConfirmationDecision, ConfirmationExecutionStatus, ConfirmationResult,
)
from backend.services.aeroing4.research.confirmation_policy import ConfirmationPolicy
from backend.services.aeroing4.research.final_unseen import (
    FinalUnseenResult, FinalUnseenService, FinalUnseenStore, compute_final_unseen_identity,
)
from backend.services.aeroing4.research.final_unseen_policy import (
    FinalUnseenDecision, FinalUnseenExecutionStatus, FinalUnseenPolicy,
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

    def request_access(self, run, stage, zone, experiment_id=None):
        return AccessDecision(
            allowed=self.allowed,
            decision_code=AccessDecisionCode.ALLOWED if self.allowed else AccessDecisionCode.ZONE_NOT_ALLOWED_FOR_STAGE,
            reason="test", run_id=getattr(run, "run_id", "run-1"), stage=stage, zone=zone,
            protocol_version=RESEARCH_PROTOCOL_VERSION,
        ), None

    def set_confirmation_passed(self, run, passed=True):
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
        eid = f"fu-{self._counter}"
        if self.fail:
            raise RuntimeError("boom")
        snap = _snap(pf=self.pf, expectancy=self.exp, dd=self.dd, total_trades=self.total_trades)
        d = Path(tempfile.mkdtemp())
        d.joinpath("parsed_summary.json").write_text(snap.model_dump_json(), encoding="utf-8")
        self._dirs[eid] = d
        return eid

    def find_run_dir(self, eid):
        return self._dirs[eid]


def _pass_confirmation(tmp_path, champ) -> ConfirmationResult:
    return ConfirmationResult(
        result_id="conf-1", run_id="run-1", champion_id=champ.champion_id,
        strategy_hash=champ.strategy_artifact.artifact_hash, parameter_hash=champ.parameter_artifact.artifact_hash,
        boundary_hash="bhash", confirmation_timerange="20240701-20240731",
        configuration_hash="chash", protocol_version="1.0.0", metrics_version="1.0.0",
        confirmation_policy_version=ConfirmationPolicy().policy_version,
        execution_status=ConfirmationExecutionStatus.COMPLETED, decision=ConfirmationDecision.PASS,
        reason_codes=["ok"], evaluated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        confirmation_identity="cid",
    )


def _make(tmp_path, *, zone_allowed=True, runner_fail=False, pf=1.3, expectancy=0.12, dd=20.0, total_trades=120,
          preflight=None):
    champ = _seed_champion(tmp_path, {"rsi_threshold": {"type": "int", "editable": True, "current": 30, "min": 10, "max": 50}})
    store = ChampionStore(tmp_path)
    store.register(champ)
    zone = _FakeZoneGuard(allowed=zone_allowed)
    runner = _FakeRunner(fail=runner_fail, pf=pf, expectancy=expectancy, dd=dd, total_trades=total_trades)
    svc = FinalUnseenService(
        runs_root=tmp_path, backtest_runner=runner, champion_store=store, zone_guard=zone,
        preflight_check=preflight,
    )
    return svc, champ, zone, runner, store


def _run_obj(confirmation_passed=True):
    return type("Run", (), {"run_id": "run-1", "research_protocol": type("P", (), {"confirmation_passed": confirmation_passed})()})()


# ── A–D: eligibility gate ─────────────────────────────────────────────────────

def test_A_blocked_no_confirmation_result(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, preflight=lambda: (True, "ok"))
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               confirmation_result=None, protocol_confirmation_passed=False,
               eligible_for_confirmation=True)
    assert r.execution_status == FinalUnseenExecutionStatus.SKIPPED
    assert runner._counter == 0


def test_B_blocked_protocol_not_passed(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, preflight=lambda: (True, "ok"))
    conf = _pass_confirmation(tmp_path, champ)
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               confirmation_result=conf, protocol_confirmation_passed=False,
               eligible_for_confirmation=True)
    assert r.execution_status == FinalUnseenExecutionStatus.BLOCKED
    assert runner._counter == 0


def test_C_blocked_strategy_hash_differs(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, preflight=lambda: (True, "ok"))
    conf = _pass_confirmation(tmp_path, champ)
    champ.strategy_artifact.artifact_hash = "TAMPERED"
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               confirmation_result=conf, protocol_confirmation_passed=True,
               eligible_for_confirmation=True, strategy_hash="strat-hash", parameter_hash="param-hash")
    assert r.execution_status == FinalUnseenExecutionStatus.BLOCKED
    assert "strategy hash differs" in r.reason_codes[0]
    assert runner._counter == 0


def test_D_blocked_parameter_hash_differs(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, preflight=lambda: (True, "ok"))
    conf = _pass_confirmation(tmp_path, champ)
    champ.parameter_artifact.artifact_hash = "TAMPERED"
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               confirmation_result=conf, protocol_confirmation_passed=True,
               eligible_for_confirmation=True, strategy_hash="strat-hash", parameter_hash="param-hash")
    assert r.execution_status == FinalUnseenExecutionStatus.BLOCKED
    assert "parameter hash differs" in r.reason_codes[0]
    assert runner._counter == 0


# ── E: access denied ──────────────────────────────────────────────────────────

def test_E_access_denied_no_execution(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, zone_allowed=False, preflight=lambda: (True, "ok"))
    conf = _pass_confirmation(tmp_path, champ)
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               confirmation_result=conf, protocol_confirmation_passed=True,
               eligible_for_confirmation=True)
    assert r.execution_status == FinalUnseenExecutionStatus.PROTOCOL_DENIED
    assert runner._counter == 0


# ── F / M: identity + idempotency (reuse before access) ──────────────────────

def test_F_same_identity_reused(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, preflight=lambda: (True, "ok"))
    conf = _pass_confirmation(tmp_path, champ)
    r1 = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                confirmation_result=conf, protocol_confirmation_passed=True,
                eligible_for_confirmation=True)
    r2 = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                confirmation_result=conf, protocol_confirmation_passed=True,
                eligible_for_confirmation=True)
    assert r1.result_id == r2.result_id
    assert runner._counter == 1  # executed once, reused after


def test_M_restart_after_completed_reused(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, preflight=lambda: (True, "ok"))
    conf = _pass_confirmation(tmp_path, champ)
    r1 = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                confirmation_result=conf, protocol_confirmation_passed=True,
                eligible_for_confirmation=True)
    svc2 = FinalUnseenService(runs_root=tmp_path, backtest_runner=runner, champion_store=store,
                              zone_guard=zone, preflight_check=lambda: (True, "ok"))
    r2 = svc2.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                 confirmation_result=conf, protocol_confirmation_passed=True,
                 eligible_for_confirmation=True)
    assert r2.result_id == r1.result_id
    assert runner._counter == 1


# ── G: changed frozen config → identity conflict (new identity, honest new eval) ─

def test_G_changed_config_new_identity(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, preflight=lambda: (True, "ok"))
    conf = _pass_confirmation(tmp_path, champ)
    r1 = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                confirmation_result=conf, protocol_confirmation_passed=True,
                eligible_for_confirmation=True)
    svc.final_unseen_timerange = "20240901-20240930"  # altered frozen context
    r2 = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
                confirmation_result=conf, protocol_confirmation_passed=True,
                eligible_for_confirmation=True)
    assert r1.final_unseen_identity != r2.final_unseen_identity
    assert r1.result_id != r2.result_id
    assert runner._counter == 2


# ── H / I / J: decisions + delivery_eligible ─────────────────────────────────

def test_H_pass_delivery_eligible(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, preflight=lambda: (True, "ok"), pf=1.3, expectancy=0.12)
    conf = _pass_confirmation(tmp_path, champ)
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               confirmation_result=conf, protocol_confirmation_passed=True,
               eligible_for_confirmation=True)
    assert r.decision == FinalUnseenDecision.PASS
    assert r.delivery_eligible is True
    store2 = FinalUnseenStore(tmp_path)
    assert store2.load(r.result_id).delivery_eligible is True


def test_I_fail_delivery_ineligible(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, preflight=lambda: (True, "ok"), pf=0.8)
    conf = _pass_confirmation(tmp_path, champ)
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               confirmation_result=conf, protocol_confirmation_passed=True,
               eligible_for_confirmation=True)
    assert r.decision == FinalUnseenDecision.FAIL
    assert r.delivery_eligible is False


def test_J_inconclusive_delivery_ineligible(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, preflight=lambda: (True, "ok"), total_trades=5)
    conf = _pass_confirmation(tmp_path, champ)
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               confirmation_result=conf, protocol_confirmation_passed=True,
               eligible_for_confirmation=True)
    assert r.decision == FinalUnseenDecision.INCONCLUSIVE
    assert r.delivery_eligible is False


# ── K: system failure not INCONCLUSIVE ────────────────────────────────────────

def test_K_system_failure_not_inconclusive(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, preflight=lambda: (True, "ok"), runner_fail=True)
    conf = _pass_confirmation(tmp_path, champ)
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               confirmation_result=conf, protocol_confirmation_passed=True,
               eligible_for_confirmation=True)
    assert r.execution_status == FinalUnseenExecutionStatus.EXECUTION_SYSTEM_FAILURE
    assert r.decision is None
    assert r.delivery_eligible is False


# ── L: ordering — access before execution ─────────────────────────────────────

def test_L_ordering_access_before_execution(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, zone_allowed=False, preflight=lambda: (True, "ok"))
    conf = _pass_confirmation(tmp_path, champ)
    calls = []
    orig = zone.request_access
    def traced(run, stage, z, experiment_id=None):
        calls.append(("access", z.value))
        return orig(run, stage, z, experiment_id)
    zone.request_access = traced
    svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
           confirmation_result=conf, protocol_confirmation_passed=True,
           eligible_for_confirmation=True)
    assert ("access", "final_unseen") in calls
    assert runner._counter == 0


# ── N: guarded real Freqtrade smoke (amendment #1 default path) ───────────────

def test_N_real_freqtrade_smoke_guard():
    import shutil
    if shutil.which("freqtrade") is None:
        pytest.skip("SKIPPED: REAL_FREQTRADE_UNAVAILABLE")
    # When Freqtrade is present, a real frozen-Champion FINAL_UNSEEN smoke would run
    # against the FINAL_UNSEEN zone. Not executed in this environment.


# ── O: preflight (non-data) blocks WITHOUT access / ledger / result (amendment #1) ─

def test_O_preflight_failure_blocks_without_access(tmp_path):
    svc, champ, zone, runner, store = _make(tmp_path, preflight=lambda: (False, "REAL_FREQTRADE_UNAVAILABLE"))
    conf = _pass_confirmation(tmp_path, champ)
    calls = []
    orig = zone.request_access
    def traced(run, stage, z, experiment_id=None):
        calls.append(("access", z.value))
        return orig(run, stage, z, experiment_id)
    zone.request_access = traced
    r = svc.run(run_id="run-1", strategy_name="AIStrategy", version_id="v1", champion=champ,
               confirmation_result=conf, protocol_confirmation_passed=True,
               eligible_for_confirmation=True)
    assert r.execution_status == FinalUnseenExecutionStatus.BLOCKED
    assert "REAL_FREQTRADE_UNAVAILABLE" in r.reason_codes[0]
    # NO access request, NO execution, NO persistent result
    assert calls == []
    assert runner._counter == 0
    store2 = FinalUnseenStore(tmp_path)
    assert store2.latest_for_run("run-1") is None
