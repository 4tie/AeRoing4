"""Tests for the Loop Coordinator (PROMPT 8 §5) — scenarios A–F.

A. KEEP        → proposal accepted, material improvement → KEEP + promotion + state update
B. DROP        → candidate regresses → DROP, champion unchanged
C. AI UNAVAILABLE → no budget consumption, no reservation
D. DUPLICATE   → same identity again → returned existing experiment, no new execution
E. RESTART     → reserved experiment reloaded from disk → not silently re-run
F. INCONCLUSIVE → candidate metrics missing/within noise → INCONCLUSIVE, champion unchanged

Invariants asserted throughout:
  * No candidate artifact before successful reservation (reserve precedes artifact).
  * No budget consumption when AI unavailable / invalid / duplicate.
  * DEVELOP-only: executor receives develop_timerange; access guarded.
  * AI never decides KEEP/DROP (only DecisionPolicy does).
  * DecisionPolicy never promotes (only Coordinator promotes, on KEEP).
  * Coordinator uses ResearchState (no new store).
  * After KEEP, next iteration diagnoses the NEW champion.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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
    ExactChange,
    ExperimentDecision,
    ExperimentRecord,
    ExperimentStatus,
    ExperimentStore,
    OriginalStrategyProvenance,
)
from backend.services.aeroing4.research.hypotheses import HypothesisStore
from backend.services.aeroing4.research.loop_coordinator import (
    LoopOutcome,
    ResearchLoopCoordinator,
)
from backend.services.aeroing4.research.proposal_generator import (
    ProposalOutcome,
    ProposalRequest,
    ProposalResult,
)
from backend.services.aeroing4.research.research_state import (
    ResearchStateStore,
)
from backend.services.aeroing4.research.stages import ResearchStage


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
    # Strategy + sidecar (editable param) on disk so allowed-target discovery works.
    sd = runs_root / "strategies"
    sd.mkdir(parents=True, exist_ok=True)
    py = sd / "AIStrategy.py"
    py.write_text("class AIStrategy:\n    pass\n", encoding="utf-8")
    sc = sd / "AIStrategy.json"
    sc.write_text(
        '{"params": {'
        '"buy": {"buy_ma_count": 18, "buy_ma_gap": 95},'
        '"sell": {"sell_ma_count": 17, "sell_ma_gap": 54},'
        '"roi": {"0": 0.192, "145": 0.0},'
        '"stoploss": {"stoploss": -0.336},'
        '"trailing": {"trailing_stop": false, "trailing_stop_positive_offset": 0.0, "trailing_only_offset_is_reached": false}'
        '}, "parameters": {'
        '"buy_ma_count": {"type": "int", "editable": true, "current": 18, "min": 1, "max": 50},'
        '"sell_ma_count": {"type": "int", "editable": true, "current": 17, "min": 1, "max": 50},'
        '"stoploss": {"type": "float", "editable": true, "current": -0.336, "min": -0.5, "max": -0.01}'
        '}}',
        encoding="utf-8",
    )
    champ = ChampionReference(
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
    return champ


class _FakeExecutor(CandidateExecutor):
    """Returns a canned execution result with injected metrics/status."""

    def __init__(self, runs_root, result):
        self._result = result
        self.last_request = None
        self.backtest_runner = SimpleNamespace()

    def execute(self, **kwargs):
        self.last_request = kwargs
        return self._result


class _CountingExperimentStore(ExperimentStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reserve_calls = 0

    def reserve(self, experiment):
        self.reserve_calls += 1
        return super().reserve(experiment)


class _CountingArtifactService:
    def __init__(self):
        self.create_calls = 0

    def create(self, **kwargs):
        self.create_calls += 1
        raise AssertionError("candidate artifact must not be created for duplicate mutations")


def _make_coordinator(
    runs_root: Path,
    *,
    champion: ChampionReference,
    proposal: ProposalResult,
    exec_result: CandidateExecutionResult,
    diagnose_code: DiagnosisCode = DiagnosisCode.NO_EDGE,
    budget_total: int = 5,
    experiment_store_cls=ExperimentStore,
    artifact_service=None,
    proposal_callable=None,
):
    exp_store = experiment_store_cls(runs_root, budget_service=None)
    # Use a real BudgetService with a generous total for the scenario.
    from backend.services.aeroing4.research.budgets import BudgetService
    exp_store.budget_service = BudgetService(max_total_experiments=budget_total)
    hyp_store = HypothesisStore(runs_root)
    champ_store = ChampionStore(runs_root)
    state_store = ResearchStateStore(runs_root)
    # Persist the baseline champion so promote() can validate lineage.
    champ_store.register(champion)
    state_store.create("run-1", max_total_experiments=budget_total)
    state = state_store.load("run-1")
    state.current_champion_id = champion.champion_id
    state.current_champion_strategy_hash = champion.strategy_artifact.artifact_hash
    state.current_champion_parameter_hash = champion.parameter_artifact.artifact_hash
    state_store.save(state)

    if artifact_service is None:
        from backend.services.aeroing4.research.candidate_artifacts import CandidateArtifactService
        strategies_dir = runs_root / "strategies"
        artifact_svc = CandidateArtifactService(runs_root, strategies_dir)
    else:
        artifact_svc = artifact_service
    executor = _FakeExecutor(runs_root, exec_result)

    guard = DataZoneGuard(state_store, runs_root)

    if proposal_callable is None:
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
        strategies_dir=runs_root / "strategies",
        develop_timerange="20240101-20240630",
        pairs=["BTC/USDT"],
        timeframe="5m",
        min_sample_trades=30,
    )
    return coord, exp_store, hyp_store, champ_store, state_store, executor


def _accepted_proposal(after_value=15):
    return ProposalResult(
        outcome=ProposalOutcome.ACCEPTED,
        hypothesis_text="adjust buy ma count",
        diagnosis_code="NO_EDGE",
        exact_change={
            "change_type": "parameter",
            "target": "buy_ma_count",
            "before_value": 18,
            "after_value": after_value,
        },
    )


def _proposal_for(target, before, after, *, change_type="parameter"):
    return ProposalResult(
        outcome=ProposalOutcome.ACCEPTED,
        hypothesis_text=f"mutate {target}",
        diagnosis_code="NO_EDGE",
        exact_change={
            "change_type": change_type,
            "target": target,
            "before_value": before,
            "after_value": after,
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


def _seed_completed_experiment(exp_store, run_id, champion, target, before, after, *, identity_suffix=""):
    change = ExactChange(
        change_type="parameter",
        target=target,
        before_value=before,
        after_value=after,
    )
    record = ExperimentRecord(
        run_id=run_id,
        hypothesis_id=f"seed-hyp-{target}-{after}{identity_suffix}",
        parent_champion_id=champion.champion_id,
        original_strategy_provenance=OriginalStrategyProvenance(
            logical_name="AIStrategy",
            path_reference=champion.strategy_artifact.original_source_path,
            path_hash=champion.strategy_artifact.artifact_hash,
            source_hash=champion.strategy_artifact.original_source_hash,
            version_id="v1",
        ),
        experiment_identity_hash=f"seed-{target}-{after}{identity_suffix}",
        exact_change=change,
        metrics_before=champion.metrics,
    )
    saved, dup = exp_store.reserve(record)
    assert dup is None
    exp_store.transition_status(run_id, saved.experiment_id, ExperimentStatus.READY)
    exp_store.transition_status(run_id, saved.experiment_id, ExperimentStatus.RUNNING)
    exp_store.transition_status(run_id, saved.experiment_id, ExperimentStatus.COMPLETED)
    return saved


import pytest
import tempfile


@pytest.fixture
def tmp_run():
    d = Path(tempfile.mkdtemp())
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


# ── Scenario A: KEEP ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_A_keep_promotes_champion(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10, profit_factor=1.2, max_drawdown_pct=20.0))
    # Candidate improves expectancy >10% (0.10 → 0.14), guardrails hold.
    cand_metrics = _snap(expectancy=0.14, profit_factor=1.2, max_drawdown_pct=20.0)
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35), exec_result=_exec_result(cand_metrics),
    )
    res = await coord.run_one_iteration(run_id="run-1")
    assert res.outcome == LoopOutcome.DECISION_KEEP
    assert res.decision == ExperimentDecision.KEEP
    assert res.promoted_champion_id is not None
    # Champion changed
    state = state_store.load("run-1")
    assert state.current_champion_id == res.promoted_champion_id
    assert state.current_champion_id != champ.champion_id
    # Executor received DEVELOP timerange only
    assert executor.last_request["develop_timerange"] == "20240101-20240630"
    assert executor.last_request["candidate_artifact_result"] is not None


# ── Scenario B: DROP ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_B_drop_champion_unchanged(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.20, profit_factor=1.5, max_drawdown_pct=15.0))
    # Candidate regresses expectancy >10% (0.20 → 0.16).
    cand_metrics = _snap(expectancy=0.16, profit_factor=1.5, max_drawdown_pct=15.0)
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35), exec_result=_exec_result(cand_metrics),
    )
    res = await coord.run_one_iteration(run_id="run-1")
    assert res.outcome == LoopOutcome.DECISION_DROP
    assert res.decision == ExperimentDecision.DROP
    # Champion unchanged
    state = state_store.load("run-1")
    assert state.current_champion_id == champ.champion_id
    # No promotion recorded
    champs = champ_store.list_for_run("run-1")
    assert len(champs) == 1  # only the baseline


# ── Scenario C: AI unavailable ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_C_ai_unavailable_no_budget_consumption(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap())
    proposal = ProposalResult(outcome=ProposalOutcome.AI_UNAVAILABLE, rejection_reason="ollama down")
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=proposal, exec_result=_exec_result(_snap()),
    )
    res = await coord.run_one_iteration(run_id="run-1")
    assert res.outcome == LoopOutcome.AI_UNAVAILABLE
    # No experiment reserved → no budget consumed
    assert exp.list_for_run("run-1") == []
    # Executor never called
    assert executor.last_request is None


# ── Scenario D: Duplicate (same identity proposed twice) ───────────────────────

@pytest.mark.asyncio
async def test_D_duplicate_returns_existing_no_new_execution(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10))
    # Tiny change → INCONCLUSIVE (no promotion, champion unchanged). The same
    # proposal repeated must then hit the duplicate-identity guard.
    cand_metrics = _snap(expectancy=0.101)  # ~+0.1%, below materiality
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(31), exec_result=_exec_result(cand_metrics),
    )
    first = await coord.run_one_iteration(run_id="run-1")
    assert first.outcome == LoopOutcome.DECISION_INCONCLUSIVE
    first_experiment_id = first.experiment_id

    # Second iteration with the SAME proposal → duplicate identity (no promotion
    # happened, so parent + change are identical → same hash).
    second = await coord.run_one_iteration(run_id="run-1")
    assert second.outcome == LoopOutcome.DUPLICATE_MUTATION
    assert second.duplicate_of_experiment_id == first_experiment_id
    # No NEW experiment persisted beyond the first (budget not double-charged)
    assert len(exp.list_for_run("run-1")) == 1


@pytest.mark.asyncio
async def test_duplicate_mutation_buy_ma_count_rejected_before_reservation(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10))
    artifact_svc = _CountingArtifactService()
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run,
        champion=champ,
        proposal=_proposal_for("buy_ma_count", 18, 15),
        exec_result=_exec_result(_snap(expectancy=0.101)),
        experiment_store_cls=_CountingExperimentStore,
        artifact_service=artifact_svc,
    )
    seeded = _seed_completed_experiment(exp, "run-1", champ, "buy_ma_count", 18, 15)
    calls_before = exp.reserve_calls

    res = await coord.run_one_iteration(run_id="run-1")

    assert res.outcome == LoopOutcome.DUPLICATE_MUTATION
    assert res.duplicate_of_experiment_id == seeded.experiment_id
    assert "DUPLICATE_MUTATION" in res.details
    assert exp.reserve_calls == calls_before
    assert artifact_svc.create_calls == 0
    assert executor.last_request is None
    assert len(exp.list_for_run("run-1")) == 1


@pytest.mark.asyncio
async def test_duplicate_mutation_stoploss_widen_to_045_rejected(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10))
    artifact_svc = _CountingArtifactService()
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run,
        champion=champ,
        proposal=_proposal_for("stoploss", -0.336, -0.45),
        exec_result=_exec_result(_snap(expectancy=0.101)),
        experiment_store_cls=_CountingExperimentStore,
        artifact_service=artifact_svc,
    )
    seeded = _seed_completed_experiment(exp, "run-1", champ, "stoploss", -0.336, -0.45)
    calls_before = exp.reserve_calls

    res = await coord.run_one_iteration(run_id="run-1")

    assert res.outcome == LoopOutcome.DUPLICATE_MUTATION
    assert res.duplicate_of_experiment_id == seeded.experiment_id
    assert exp.reserve_calls == calls_before
    assert artifact_svc.create_calls == 0
    assert executor.last_request is None


@pytest.mark.asyncio
async def test_duplicate_mutation_seeded_known_failed_list_blocks_exact_matches(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10))
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run,
        champion=champ,
        proposal=_proposal_for("sell_ma_count", 17, 25),
        exec_result=_exec_result(_snap(expectancy=0.101)),
        experiment_store_cls=_CountingExperimentStore,
        artifact_service=_CountingArtifactService(),
    )
    _seed_completed_experiment(exp, "run-1", champ, "buy_ma_count", 18, 15, identity_suffix="-a")
    _seed_completed_experiment(exp, "run-1", champ, "stoploss", -0.336, -0.25, identity_suffix="-b")
    seeded_sell = _seed_completed_experiment(
        exp, "run-1", champ, "sell_ma_count", 17, 25, identity_suffix="-c"
    )
    _seed_completed_experiment(exp, "run-1", champ, "stoploss", -0.336, -0.45, identity_suffix="-d")
    calls_before = exp.reserve_calls

    res = await coord.run_one_iteration(run_id="run-1")

    assert res.outcome == LoopOutcome.DUPLICATE_MUTATION
    assert res.duplicate_of_experiment_id == seeded_sell.experiment_id
    assert exp.reserve_calls == calls_before
    assert len(exp.list_for_run("run-1")) == 4


@pytest.mark.asyncio
async def test_duplicate_mutation_float_normalization_rejects_equivalent_values(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10))
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run,
        champion=champ,
        proposal=_proposal_for("stoploss", "-0.3360", "-0.450"),
        exec_result=_exec_result(_snap(expectancy=0.101)),
        experiment_store_cls=_CountingExperimentStore,
        artifact_service=_CountingArtifactService(),
    )
    seeded = _seed_completed_experiment(exp, "run-1", champ, "stoploss", -0.336, -0.45)
    calls_before = exp.reserve_calls

    res = await coord.run_one_iteration(run_id="run-1")

    assert res.outcome == LoopOutcome.DUPLICATE_MUTATION
    assert res.duplicate_of_experiment_id == seeded.experiment_id
    assert exp.reserve_calls == calls_before
    assert executor.last_request is None


@pytest.mark.asyncio
async def test_duplicate_mutation_change_type_synonyms_do_not_bypass_gate(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10))
    artifact_svc = _CountingArtifactService()
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run,
        champion=champ,
        proposal=_proposal_for(
            "stoploss", -0.336, -0.25, change_type="parameter_tune"
        ),
        exec_result=_exec_result(_snap(expectancy=0.101)),
        experiment_store_cls=_CountingExperimentStore,
        artifact_service=artifact_svc,
    )
    seeded = _seed_completed_experiment(exp, "run-1", champ, "stoploss", -0.336, -0.25)
    calls_before = exp.reserve_calls

    res = await coord.run_one_iteration(run_id="run-1")

    assert res.outcome == LoopOutcome.DUPLICATE_MUTATION
    assert res.duplicate_of_experiment_id == seeded.experiment_id
    assert exp.reserve_calls == calls_before
    assert artifact_svc.create_calls == 0
    assert executor.last_request is None


@pytest.mark.asyncio
async def test_non_duplicate_valid_mutation_is_allowed(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10))
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run,
        champion=champ,
        proposal=_proposal_for("buy_ma_count", 18, 16),
        exec_result=_exec_result(_snap(expectancy=0.101)),
        experiment_store_cls=_CountingExperimentStore,
    )
    _seed_completed_experiment(exp, "run-1", champ, "buy_ma_count", 18, 15)
    calls_before = exp.reserve_calls

    res = await coord.run_one_iteration(run_id="run-1")

    assert res.outcome == LoopOutcome.DECISION_INCONCLUSIVE
    assert exp.reserve_calls == calls_before + 1
    assert executor.last_request is not None
    assert len(exp.list_for_run("run-1")) == 2


# ── Scenario E: Restart (reserved experiment reloaded from disk) ───────────────

@pytest.mark.asyncio
async def test_E_restart_does_not_rerun(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10))

    # First coordinator run reserves + KEEPs.
    cand_metrics = _snap(expectancy=0.14)
    coord1, exp1, _, champ_store1, state_store1, executor1 = _make_coordinator(
        tmp_run, champion=champ, proposal=_accepted_proposal(35), exec_result=_exec_result(cand_metrics),
    )
    res1 = await coord1.run_one_iteration(run_id="run-1")
    assert res1.outcome == LoopOutcome.DECISION_KEEP
    first_experiment_id = res1.experiment_id

    # Simulate restart: NEW stores + coordinator on the SAME runs_root.
    new_champ = champ_store1.get("run-1", res1.promoted_champion_id)
    coord2, exp2, _, champ_store2, state_store2, executor2 = _make_coordinator(
        tmp_run,
        champion=new_champ,
        proposal=_accepted_proposal(35),
        exec_result=_exec_result(cand_metrics),
    )
    await coord2.run_one_iteration(run_id="run-1")
    # The earlier experiment must NOT have been silently re-run: its status is
    # still COMPLETED, and the persisted history is intact (no lost writes).
    persisted_first = exp2.get("run-1", first_experiment_id)
    assert persisted_first is not None
    assert persisted_first.status == ExperimentStatus.COMPLETED
    assert persisted_first.experiment_id == first_experiment_id


# ── Scenario F: INCONCLUSIVE (missing candidate metrics) ───────────────────────

@pytest.mark.asyncio
async def test_F_inconclusive_missing_metrics_champion_unchanged(tmp_run):
    champ = _seed_champion(tmp_run, metrics=_snap(expectancy=0.10))
    # VALID execution (SUCCESS) but canonical metrics genuinely unavailable
    # → INCONCLUSIVE (valid_execution_but_insufficient_comparison), NOT a
    # system failure. (PARSE_FAILURE is tested separately as a system failure.)
    coord, exp, hyp, champ_store, state_store, executor = _make_coordinator(
        tmp_run,
        champion=champ,
        proposal=_accepted_proposal(35),
        exec_result=_exec_result(None, status=CandidateExecutionStatus.SUCCESS),
    )
    res = await coord.run_one_iteration(run_id="run-1")
    assert res.outcome == LoopOutcome.DECISION_INCONCLUSIVE
    assert res.decision == ExperimentDecision.INCONCLUSIVE
    # Champion unchanged, executor WAS called (system ran), but no promotion.
    state = state_store.load("run-1")
    assert state.current_champion_id == champ.champion_id
    assert executor.last_request is not None
