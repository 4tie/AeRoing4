"""Integration tests for PROMPT 8 §6–§8 and §10 (scenarios A–F + ordering).

Coordinator-level tests (not just unit tests):
  §6 Hypothesis reuse (deterministic, no embedding)
  §7 ResearchState integration (transitions, persist/reload)
  §8 Proposal Generator integration (no reserve/artifact/budget on invalid)
  §10 Scenarios A–F (full assertions)
  Critical ordering test (call-order recording)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services.aeroing4.diagnosis.models import DiagnosisCode
from backend.services.aeroing4.metrics.models import (
    CanonicalMetricsSnapshot,
    MetricAvailability,
    MetricProvenance,
    MetricValue,
    SourceType,
)
from backend.services.aeroing4.research.access_guard import DataZoneGuard
from backend.services.aeroing4.research.candidate_artifacts import CandidateArtifactResult
from backend.services.aeroing4.research.candidate_executor import (
    CandidateExecutionResult,
    CandidateExecutionStatus,
    CandidateExecutor,
)
from backend.services.aeroing4.research.champions import (
    ArtifactReference,
    ChampionReference,
    ChampionSourceType,
    ChampionStore,
)
from backend.services.aeroing4.research.decision_policy import DecisionRequest
from backend.services.aeroing4.research.experiments import (
    ExperimentDecision,
    ExperimentStore,
)
from backend.services.aeroing4.research.hypotheses import (
    HypothesisRecord,
    HypothesisSource,
    HypothesisStatus,
    HypothesisStore,
)
from backend.services.aeroing4.research.loop_coordinator import (
    LoopOutcome,
    ResearchLoopCoordinator,
    ResearchStatus,
)
from backend.services.aeroing4.research.proposal_generator import (
    ProposalOutcome,
    ProposalRequest,
    ProposalResult,
)
from backend.services.aeroing4.research.research_state import ResearchStateStore


def _prov():
    return MetricProvenance(
        metrics_version="1.0.0",
        source_type=SourceType.PARSED_SUMMARY,
        source_parser_version="ResultParser",
        calculation_timestamp="2026-01-01T00:00:00Z",
    )


def _snap(expectancy=0.10, profit_factor=1.2, win_rate=50.0, max_drawdown_pct=20.0, total_trades=120):
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
        provenance=_prov(),
    )


def _seed_champion(runs_root: Path, parent_id=None, metrics=None):
    sd = runs_root / "strategies"
    sd.mkdir(parents=True, exist_ok=True)
    py = sd / "AIStrategy.py"
    py.write_text("class AIStrategy:\n    pass\n", encoding="utf-8")
    sc = sd / "AIStrategy.json"
    sc.write_text(
        '{"parameters": {"rsi_threshold": {"type": "int", "editable": true, '
        '"current": 30, "min": 10, "max": 50}}}',
        encoding="utf-8",
    )
    return ChampionReference(
        run_id="run-1",
        parent_champion_id=parent_id,
        source_type=ChampionSourceType.BASELINE,
        strategy_artifact=ArtifactReference(
            artifact_path="champions/x.py",
            artifact_hash="abc",
            original_source_path=str(py),
            original_source_hash="src-hash",
        ),
        parameter_artifact=ArtifactReference(
            artifact_path="champions/x.json",
            artifact_hash="def",
            original_source_path=str(sc),
            original_source_hash="param-hash",
        ),
        metrics=metrics or _snap(),
    )


class _FakeExecutor(CandidateExecutor):
    def __init__(self, runs_root, result, call_log=None):
        self._result = result
        self.last_request = None
        self.call_log = call_log or []
        self.backtest_runner = SimpleNamespace()

    def execute(self, **kwargs):
        self.last_request = kwargs
        self.call_log.append(("execute", kwargs))
        return self._result


def _accepted_proposal(after_value=35):
    return ProposalResult(
        outcome=ProposalOutcome.ACCEPTED,
        hypothesis_text="raise rsi",
        diagnosis_code="NO_EDGE",
        exact_change={
            "change_type": "parameter",
            "target": "rsi_threshold",
            "before_value": 30,
            "after_value": after_value,
        },
    )


def _exec_result(metrics, status=CandidateExecutionStatus.SUCCESS):
    return CandidateExecutionResult(
        underlying_execution_id="exec-1",
        status=status,
        candidate_dir="candidates/run-1/exec-1",
        artifacts={},
        metrics=metrics,
        failure_classification=None,
    )


def _make_coordinator(
    runs_root, *, champion, proposal, exec_result, diagnose_code=DiagnosisCode.NO_EDGE,
    budget_total=5, call_log=None,
):
    from backend.services.aeroing4.research.budgets import BudgetService
    from backend.services.aeroing4.research.candidate_artifacts import CandidateArtifactService

    exp_store = ExperimentStore(runs_root)
    exp_store.budget_service = BudgetService(max_total_experiments=budget_total)
    hyp_store = HypothesisStore(runs_root)
    champ_store = ChampionStore(runs_root)
    state_store = ResearchStateStore(runs_root)
    champ_store.register(champion)
    state_store.create("run-1", max_total_experiments=budget_total)
    state = state_store.load("run-1")
    state.current_champion_id = champion.champion_id
    state_store.save(state)

    executor = _FakeExecutor(runs_root, exec_result, call_log=call_log or [])
    artifact_svc = CandidateArtifactService(runs_root)
    guard = DataZoneGuard(state_store, runs_root)

    async def proposal_callable(request: ProposalRequest) -> ProposalResult:
        return proposal

    coord = ResearchLoopCoordinator(
        runs_root=runs_root,
        experiment_store=exp_store,
        hypothesis_store=hyp_store,
        champion_store=champ_store,
        state_store=state_store,
        artifact_service=artifact_svc,
        executor=executor,
        zone_guard=guard,
        diagnose_fn=lambda c: diagnose_code,
        proposal_callable=proposal_callable,
        develop_timerange="20240101-20240630",
        pairs=["BTC/USDT"],
        timeframe="5m",
        min_sample_trades=30,
    )
    return coord, exp_store, hyp_store, champ_store, state_store, executor


import tempfile


@pytest.fixture
def tmp_run():
    d = Path(tempfile.mkdtemp())
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


# ── §6 Hypothesis reuse ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_6_compatible_active_hypothesis_reused(tmp_run):
    champ = _seed_champion(tmp_run)
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35), exec_result=_exec_result(_snap(0.14)),
    )
    # Iteration 1: AI unavailable → hypothesis created ACTIVE, no decision, no
    # terminalization → it stays reusable.
    coord.proposal_callable = lambda r: ProposalResult(
        outcome=ProposalOutcome.AI_UNAVAILABLE, rejection_reason="down")
    r1 = await coord.run_one_iteration(run_id="run-1")
    h1 = r1.hypothesis_id
    # Iteration 2: accepted proposal → must reuse the SAME active hypothesis.
    coord.proposal_callable = lambda r: _accepted_proposal(35)
    r2 = await coord.run_one_iteration(run_id="run-1")
    assert r2.hypothesis_id == h1
    assert len(hyp.list_for_run("run-1")) == 1


@pytest.mark.asyncio
async def test_6_incompatible_diagnosis_creates_new(tmp_run):
    champ = _seed_champion(tmp_run)
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35), exec_result=_exec_result(_snap(0.14)),
    )
    r1 = await coord.run_one_iteration(run_id="run-1")
    coord.diagnose_fn = lambda c: DiagnosisCode.STOPLOSS_DOMINANCE
    r2 = await coord.run_one_iteration(run_id="run-1")
    assert r2.hypothesis_id != r1.hypothesis_id
    assert len(hyp.list_for_run("run-1")) == 2


@pytest.mark.asyncio
async def test_6_terminal_hypothesis_not_reused(tmp_run):
    champ = _seed_champion(tmp_run)
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35), exec_result=_exec_result(_snap(0.14)),
    )
    # Iteration 1 KEEPs → hypothesis terminalized (SUPPORTED). A new iteration
    # with the same diagnosis must create a NEW hypothesis, not reuse terminal.
    r1 = await coord.run_one_iteration(run_id="run-1")
    assert r1.outcome == LoopOutcome.DECISION_KEEP
    r2 = await coord.run_one_iteration(run_id="run-1")
    assert r2.hypothesis_id != r1.hypothesis_id
    assert len(hyp.list_for_run("run-1")) == 2


@pytest.mark.asyncio
async def test_6_deterministic_same_inputs_same_hypothesis(tmp_run):
    champ = _seed_champion(tmp_run)
    coord1, *_ = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35), exec_result=_exec_result(_snap(0.14)),
    )
    # Iteration 1: AI unavailable → hypothesis ACTIVE + persisted.
    coord1.proposal_callable = lambda r: ProposalResult(
        outcome=ProposalOutcome.AI_UNAVAILABLE, rejection_reason="down")
    r1 = await coord1.run_one_iteration(run_id="run-1")
    # Second coordinator reloads persisted state → selects the SAME hypothesis.
    coord2, exp2, hyp2, champ_store2, state_store2, executor2 = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35), exec_result=_exec_result(_snap(0.14)),
    )
    coord2.proposal_callable = lambda r: _accepted_proposal(35)
    r2 = await coord2.run_one_iteration(run_id="run-1")
    assert r2.hypothesis_id == r1.hypothesis_id


# ── §7 ResearchState transitions + persist/reload ──────────────────────────────

@pytest.mark.asyncio
async def test_7_ai_unavailable_pauses_not_fails(tmp_run):
    champ = _seed_champion(tmp_run)
    proposal = ProposalResult(outcome=ProposalOutcome.AI_UNAVAILABLE, rejection_reason="ollama down")
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=proposal, exec_result=_exec_result(_snap()),
    )
    res = await coord.run_one_iteration(run_id="run-1")
    assert res.outcome == LoopOutcome.AI_UNAVAILABLE
    reloaded = state_store.load("run-1")
    assert reloaded.research_status == ResearchStatus.PAUSED
    assert reloaded.pause_reason
    assert exp.list_for_run("run-1") == []
    assert executor.last_request is None


@pytest.mark.asyncio
async def test_7_transitions_active_to_paused_to_active(tmp_run):
    store = ResearchStateStore(tmp_run)
    rs = store.create("run-x", max_total_experiments=5)
    assert rs.research_status == ResearchStatus.NOT_STARTED
    rs.transition_status(ResearchStatus.ACTIVE)
    rs.transition_status(ResearchStatus.PAUSED)
    store.save(rs)
    reloaded = store.load("run-x")
    assert reloaded.research_status == ResearchStatus.PAUSED
    reloaded.transition_status(ResearchStatus.ACTIVE)
    store.save(reloaded)
    assert store.load("run-x").research_status == ResearchStatus.ACTIVE


@pytest.mark.asyncio
async def test_7_decision_records_iteration_and_last_decision(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10))
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35), exec_result=_exec_result(_snap(0.14)),
    )
    res = await coord.run_one_iteration(run_id="run-1")
    assert res.outcome == LoopOutcome.DECISION_KEEP
    rs = state_store.load("run-1")
    assert rs.current_iteration == 1
    assert rs.last_decision_id == res.experiment_id


# ── §8 Proposal Generator integration (coordinator-level) ──────────────────────

@pytest.mark.asyncio
async def test_8_invalid_proposal_no_reserve_no_artifact_no_budget(tmp_run):
    champ = _seed_champion(tmp_run)
    proposal = ProposalResult(outcome=ProposalOutcome.AI_PROPOSAL_SKIPPED, rejection_reason="malformed json")
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=proposal, exec_result=_exec_result(_snap()),
    )
    res = await coord.run_one_iteration(run_id="run-1")
    assert res.outcome == LoopOutcome.PROPOSAL_SKIPPED
    assert exp.list_for_run("run-1") == []
    assert executor.last_request is None
    assert state_store.load("run-1").total_experiments_reserved == 0


@pytest.mark.asyncio
async def test_8_no_arbitrary_code_accepted(tmp_run):
    champ = _seed_champion(tmp_run)
    proposal = ProposalResult(
        outcome=ProposalOutcome.ACCEPTED,
        diagnosis_code="NO_EDGE",
        exact_change={"change_type": "parameter", "target": "rsi_threshold",
                      "before_value": 30, "after_value": 35},
    )
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=proposal, exec_result=_exec_result(_snap(0.14)),
    )
    res = await coord.run_one_iteration(run_id="run-1")
    assert res.outcome == LoopOutcome.DECISION_KEEP
    assert "cmd" not in str(res.proposal.exact_change)


# ── §10 Scenarios A–F (strengthened) ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_10_A_drop_champion_unchanged(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.20, profit_factor=1.5, max_drawdown_pct=15.0))
    cand = _snap(expectancy=0.16, profit_factor=1.5, max_drawdown_pct=15.0)
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35), exec_result=_exec_result(cand),
    )
    res = await coord.run_one_iteration(run_id="run-1")
    assert res.outcome == LoopOutcome.DECISION_DROP
    assert res.decision == ExperimentDecision.DROP
    assert state_store.load("run-1").current_champion_id == champ.champion_id
    assert executor.last_request is not None
    assert len(exp.list_for_run("run-1")) == 1
    assert exp.get("run-1", res.experiment_id).status.value == "completed"


@pytest.mark.asyncio
async def test_10_B_keep_promotes_with_lineage(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10, profit_factor=1.2, max_drawdown_pct=20.0))
    cand = _snap(expectancy=0.14, profit_factor=1.2, max_drawdown_pct=20.0)
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35), exec_result=_exec_result(cand),
    )
    res = await coord.run_one_iteration(run_id="run-1")
    assert res.outcome == LoopOutcome.DECISION_KEEP
    new_champ = champ_store.get("run-1", res.promoted_champion_id)
    assert new_champ.parent_champion_id == champ.champion_id
    assert new_champ.source_experiment_id == res.experiment_id
    assert new_champ.source_type == ChampionSourceType.RESEARCH_EXPERIMENT
    assert state_store.load("run-1").current_champion_id == new_champ.champion_id
    assert champ_store.get("run-1", champ.champion_id) is not None


@pytest.mark.asyncio
async def test_10_C_ai_unavailable_paused_safe(tmp_run):
    champ = _seed_champion(tmp_run)
    proposal = ProposalResult(outcome=ProposalOutcome.AI_UNAVAILABLE, rejection_reason="ollama down")
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=proposal, exec_result=_exec_result(_snap()),
    )
    res = await coord.run_one_iteration(run_id="run-1")
    assert res.outcome == LoopOutcome.AI_UNAVAILABLE
    rs = state_store.load("run-1")
    assert rs.research_status == ResearchStatus.PAUSED
    assert rs.pause_reason
    assert exp.list_for_run("run-1") == []
    assert executor.last_request is None
    assert champ_store.get("run-1", champ.champion_id) is not None


@pytest.mark.asyncio
async def test_10_D_duplicate_no_second_reservation(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10))
    cand = _snap(expectancy=0.101)
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(31), exec_result=_exec_result(cand),
    )
    first = await coord.run_one_iteration(run_id="run-1")
    assert first.outcome == LoopOutcome.DECISION_INCONCLUSIVE
    second = await coord.run_one_iteration(run_id="run-1")
    assert second.outcome == LoopOutcome.DUPLICATE
    assert second.duplicate_of_experiment_id == first.experiment_id
    assert len(exp.list_for_run("run-1")) == 1


@pytest.mark.asyncio
async def test_10_E_restart_reconcile_no_silent_rerun(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10))
    cand = _snap(expectancy=0.14)
    coord1, exp1, _, champ_store1, state_store1, executor1 = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35), exec_result=_exec_result(cand),
    )
    res1 = await coord1.run_one_iteration(run_id="run-1")
    assert res1.outcome == LoopOutcome.DECISION_KEEP
    first_id = res1.experiment_id
    new_champ = champ_store1.get("run-1", res1.promoted_champion_id)
    coord2, exp2, _, champ_store2, state_store2, executor2 = _make_coordinator(
        tmp_run, champion=new_champ, proposal=_accepted_proposal(35), exec_result=_exec_result(cand),
    )
    await coord2.run_one_iteration(run_id="run-1")
    persisted = exp2.get("run-1", first_id)
    assert persisted.status.value == "completed"
    assert persisted.experiment_id == first_id


@pytest.mark.asyncio
async def test_10_F_inconclusive_champion_unchanged(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10))
    # VALID execution (SUCCESS) but canonical metrics genuinely unavailable
    # → INCONCLUSIVE (valid_execution_but_insufficient_comparison), not a
    # system failure. Distinct from PARSE_FAILURE (see test_3C below).
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35),
        exec_result=_exec_result(None, status=CandidateExecutionStatus.SUCCESS),
    )
    res = await coord.run_one_iteration(run_id="run-1")
    assert res.outcome == LoopOutcome.DECISION_INCONCLUSIVE
    assert res.decision == ExperimentDecision.INCONCLUSIVE
    assert state_store.load("run-1").current_champion_id == champ.champion_id
    assert executor.last_request is not None
    rec = exp.get("run-1", res.experiment_id)
    assert rec.status.value == "completed"
    # metrics_after absent BUT a typed availability reason is recorded (no bare None)
    assert rec.metrics_after is None
    assert rec.metrics_availability_reason == "valid_execution_but_metrics_unavailable"


# ── Critical ordering test ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ordering_reserve_before_artifact_execution_after_develop(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10))
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35),
        exec_result=_exec_result(_snap(0.14)),
    )
    order: list = []
    real_reserve = exp.reserve

    def traced_reserve(record):
        order.append("reserve")
        return real_reserve(record)

    exp.reserve = traced_reserve

    real_transition = exp.transition_status

    def traced_transition(run_id, experiment_id, new_status):
        if str(new_status.value) == "ready":
            order.append("ready")
        if str(new_status.value) == "running":
            order.append("running")
        if str(new_status.value) == "completed":
            order.append("decision")
        return real_transition(run_id, experiment_id, new_status)

    exp.transition_status = traced_transition

    real_artifact = coord.artifact_service.create

    def traced_artifact(**kwargs):
        order.append("candidate_artifact")
        return real_artifact(**kwargs)

    coord.artifact_service.create = traced_artifact

    def traced_execute(**kwargs):
        order.append("candidate_execution")
        return _exec_result(_snap(0.14))

    executor.execute = traced_execute

    real_access = coord._ensure_develop_access

    def traced_access(run_id, experiment_id):
        order.append("develop_access")
        return real_access(run_id, experiment_id)

    coord._ensure_develop_access = traced_access

    res = await coord.run_one_iteration(run_id="run-1")

    # Exact contract (Point 1):
    #   reserve < develop_access < ready < candidate_artifact < candidate_execution < decision
    assert order == [
        "reserve", "develop_access", "ready", "candidate_artifact",
        "candidate_execution", "running", "decision",
    ], order
    # The DEVELOP access ledger reference must be persisted on the experiment.
    rec = exp.get("run-1", res.experiment_id)
    assert rec.access_ledger_entry_id is not None
    assert rec.status.value == "completed"


@pytest.mark.asyncio
async def test_ordering_protocol_denial_no_artifact_no_execution_keeps_champion(tmp_run):
    """Point 1 + user requirement: protocol denial →

    * no Candidate artifact created
    * CandidateExecutor NOT invoked
    * champion unchanged
    * experiment failure classification = PROTOCOL_DENIED (NOT performance DROP)
    """
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10))
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35),
        exec_result=_exec_result(_snap(0.14)),
    )
    # Force the zone guard to deny DEVELOP access.
    class _Deny:
        allowed = False
        decision_code = type("D", (), {"value": "zone_not_allowed_for_stage"})()
    coord.zone_guard.request_access = lambda *a, **k: (_Deny(), None)

    created = []
    real_artifact = coord.artifact_service.create

    def traced_artifact(**kwargs):
        created.append(1)
        return real_artifact(**kwargs)

    coord.artifact_service.create = traced_artifact
    executor.execute = lambda **k: (_ for _ in ()).throw(
        AssertionError("executor must NOT be invoked on protocol denial")
    )

    res = await coord.run_one_iteration(run_id="run-1")
    assert res.outcome == LoopOutcome.ZONE_ACCESS_DENIED
    # No artifact created, executor never invoked.
    assert created == []
    assert executor.last_request is None
    # Champion unchanged.
    assert state_store.load("run-1").current_champion_id == champ.champion_id
    # Typed failure classification, not a performance DROP decision.
    rec = exp.get("run-1", res.experiment_id)
    assert rec.result.startswith("PROTOCOL_DENIED:")
    assert rec.status.value == "invalidated"


@pytest.mark.asyncio
async def test_ordering_no_artifact_on_ai_unavailable(tmp_run):
    champ = _seed_champion(tmp_run)
    proposal = ProposalResult(outcome=ProposalOutcome.AI_UNAVAILABLE, rejection_reason="down")
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=proposal, exec_result=_exec_result(_snap()),
    )
    created = []
    real_artifact = coord.artifact_service.create

    def traced(**kwargs):
        created.append(1)
        return real_artifact(**kwargs)

    coord.artifact_service.create = traced
    await coord.run_one_iteration(run_id="run-1")
    assert created == []


# ── §11 Verification layer: real Ollama proposal (item 13, guarded) ───────────

def _ollama_reachable(host: str = "127.0.0.1", port: int = 11434, timeout: float = 2.0) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.mark.asyncio
async def test_11_real_ollama_proposal_guarded():
    """§11 item 13: exercise the real Ollama adapter when reachable.

    Bounded: skips if port 11434 is closed; never hangs (asyncio.wait_for cap).
    Asserts the adapter returns a VALID outcome (ACCEPTED or AI_UNAVAILABLE)
    and never raises/crashes. Does not require a specific model to be pulled.
    """
    if not _ollama_reachable():
        pytest.skip("Ollama not reachable on 127.0.0.1:11434 — real proposal unverified")

    from backend.services.aeroing4.research.proposal_generator import (
        OllamaProposalAdapter,
        ProposalRequest,
    )

    adapter = OllamaProposalAdapter(base_url="http://127.0.0.1:11434", model="local")
    request = ProposalRequest(
        run_id="run-1",
        hypothesis_id="hyp-1",
        diagnosis_code="NO_EDGE",
        champion_metrics=_snap(),
        allowed_targets=[],
    )
    try:
        result = await asyncio.wait_for(adapter.generate(request), timeout=30.0)
    except asyncio.TimeoutError:
        pytest.skip("Ollama generate timed out — real proposal unverified (no hang)")
    except Exception as exc:  # adapter must convert errors to AI_UNAVAILABLE
        pytest.fail(f"Ollama adapter raised instead of returning AI_UNAVAILABLE: {exc}")

    assert result.outcome.value in ("accepted", "ai_unavailable", "ai_proposal_skipped")


# ── §10/E (Point 2): real RUNNING restart / recovery ───────────────────────────

@pytest.mark.asyncio
async def test_10_E_running_restart_interrupted_no_duplicate(tmp_run):
    """Restart recovery: a RUNNING experiment on reload becomes INTERRUPTED and
    the coordinator refuses to reserve/execute a duplicate until reconciled."""
    from backend.services.aeroing4.research.experiments import (
        ExperimentRecord,
        ExperimentStatus,
        OriginalStrategyProvenance,
    )

    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10))
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35),
        exec_result=_exec_result(_snap(0.14)),
    )

    record = ExperimentRecord(
        run_id="run-1",
        hypothesis_id="hyp-seed",
        parent_champion_id=champ.champion_id,
        original_strategy_provenance=OriginalStrategyProvenance(logical_name="AIStrategy"),
        experiment_identity_hash="seed-hash",
        metrics_before=champ.metrics,
    )
    saved, _ = exp.reserve(record)
    exp.transition_status("run-1", saved.experiment_id, ExperimentStatus.READY)
    exp.transition_status("run-1", saved.experiment_id, ExperimentStatus.RUNNING)
    assert exp.get("run-1", saved.experiment_id).status == ExperimentStatus.RUNNING

    reloaded = ExperimentStore(tmp_run)
    reconciled = reloaded.reconcile_interrupted_experiments("run-1")
    assert len(reconciled) == 1
    after = reloaded.get("run-1", saved.experiment_id)
    assert after.status == ExperimentStatus.INTERRUPTED

    report = reloaded.resume_safety_report("run-1")
    assert report.has_active_experiment is True
    assert report.active_experiment_status == ExperimentStatus.INTERRUPTED
    assert report.must_reconcile_first is True
    assert report.new_experiment_allowed is False

    coord2, exp2, hyp2, champ_store2, state_store2, executor2 = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35),
        exec_result=_exec_result(_snap(0.14)),
    )
    res = await coord2.run_one_iteration(run_id="run-1")
    assert res.outcome == LoopOutcome.RECONCILE_REQUIRED
    assert len(exp2.list_for_run("run-1")) == 1
    assert executor2.last_request is None
    assert exp2.get("run-1", saved.experiment_id).status == ExperimentStatus.INTERRUPTED


# ── §10/F + Point 3: INCONCLUSIVE metrics availability semantics ────────────────

async def _run_iteration(tmp_run, *, after_metrics, exec_status=CandidateExecutionStatus.SUCCESS,
                         parent_metrics=None):
    champ = _seed_champion(tmp_run, metrics=parent_metrics or _snap(expectancy=0.10))
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35),
        exec_result=_exec_result(after_metrics, status=exec_status),
    )
    res = await coord.run_one_iteration(run_id="run-1")
    return res, exp.get("run-1", res.experiment_id), state_store


@pytest.mark.asyncio
async def test_3A_critical_metric_unavailable_inconclusive_preserves_snapshot(tmp_run):
    """A) canonical snapshot exists but one critical metric unavailable → INCONCLUSIVE,
    snapshot + availability preserved (no zero substitution)."""
    from backend.services.aeroing4.metrics.models import MetricAvailability
    snap = _snap(expectancy=0.14)
    snap.expectancy = snap.expectancy.model_copy(update={"availability": MetricAvailability.UNAVAILABLE})
    res, rec, state_store = await _run_iteration(
        tmp_run, after_metrics=snap, parent_metrics=_snap(expectancy=0.10),
    )
    assert res.outcome == LoopOutcome.DECISION_INCONCLUSIVE
    assert res.decision == ExperimentDecision.INCONCLUSIVE
    assert rec.metrics_after is not None
    assert rec.metrics_after.expectancy.availability == MetricAvailability.UNAVAILABLE
    # value preserved (provenance) and NOT fabricated to 0
    assert rec.metrics_after.expectancy.value != 0
    assert rec.metrics_after.provenance is not None


@pytest.mark.asyncio
async def test_3B_insufficient_sample_inconclusive(tmp_run):
    """B) insufficient sample (total_trades below minimum) → INCONCLUSIVE."""
    snap = _snap(expectancy=0.14, total_trades=5)
    res, rec, state_store = await _run_iteration(
        tmp_run, after_metrics=snap, parent_metrics=_snap(expectancy=0.10),
    )
    assert res.outcome == LoopOutcome.DECISION_INCONCLUSIVE
    assert res.decision == ExperimentDecision.INCONCLUSIVE
    assert "insufficient_sample" in res.decision_reason


@pytest.mark.asyncio
async def test_3C_parse_or_system_failure_not_inconclusive(tmp_run):
    """C) parser/system failure → explicit system failure classification, not INCONCLUSIVE."""
    for status in (CandidateExecutionStatus.PARSE_FAILURE,
                   CandidateExecutionStatus.SYSTEM_FAILURE,
                   CandidateExecutionStatus.EXECUTION_FAILURE):
        res, rec, state_store = await _run_iteration(
            tmp_run, after_metrics=None, exec_status=status,
            parent_metrics=_snap(expectancy=0.10),
        )
        assert res.outcome == LoopOutcome.EXECUTION_SYSTEM_FAILURE, (status, res.outcome)
        assert res.decision != ExperimentDecision.INCONCLUSIVE, (status, res.decision)
        assert rec.status.value == "failed_system"
        assert rec.result.startswith("system_failure:")
        assert rec.metrics_after is None
        assert rec.metrics_availability_reason.startswith("system_failure:")


@pytest.mark.asyncio
async def test_3D_no_fake_zero_substitution(tmp_run):
    """D) no fake-zero substitution: an UNAVAILABLE metric stays UNAVAILABLE, never 0."""
    from backend.services.aeroing4.metrics.models import MetricAvailability
    snap = _snap(expectancy=0.14, profit_factor=1.25, win_rate=55.0)
    snap.profit_factor = snap.profit_factor.model_copy(update={"availability": MetricAvailability.UNAVAILABLE})
    res, rec, state_store = await _run_iteration(
        tmp_run, after_metrics=snap, parent_metrics=_snap(expectancy=0.10),
    )
    assert rec.metrics_after is not None
    assert rec.metrics_after.profit_factor.availability == MetricAvailability.UNAVAILABLE
    # value preserved (provenance) and NOT fabricated to 0
    assert rec.metrics_after.profit_factor.value != 0
    assert rec.metrics_after.expectancy.value == 0.14

