"""Tests for Experiment Memory — Milestone 4 §31."""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import Optional

import pytest

from backend.services.aeroing4.research.experiments import (
    DuplicateExperimentDecision,
    ExactChange,
    ExperimentDecision,
    ExperimentIntegrityError,
    ExperimentRecord,
    ExperimentStatus,
    ExperimentStore,
    ExperimentTransitionError,
    IN_FLIGHT_STATUSES,
    OriginalStrategyProvenance,
    TERMINAL_STATUSES,
)
from backend.services.aeroing4.research.budgets import BudgetService
from backend.services.aeroing4.research.identity import (
    compute_experiment_identity_hash,
    compute_original_strategy_provenance_hash,
    compute_pair_set_hash,
)


@pytest.fixture
def tmp_root():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def store(tmp_root):
    return ExperimentStore(tmp_root, budget_service=BudgetService(max_total_experiments=5, max_experiments_per_hypothesis=3))


def _prov(name: str = "MyStrategy", source_hash: str = "abc123") -> OriginalStrategyProvenance:
    return OriginalStrategyProvenance(
        logical_name=name,
        path_reference="user_data/strategies/MyStrategy.py",
        path_hash="pathhash",
        source_hash=source_hash,
        version_id="v1",
    )


def _identity_hash(
    prov_hash: str = "provhash",
    strategy_hash_before: str = "strat",
    parameter_hash_before: str = "param",
    proposed_change=None,
    dataset_zone: str = "develop",
    concrete_timerange: str = "20240101-20240630",
    pair_set_hash: str = "pairs",
    config_hash: str = "cfg",
    timeframe: str = "5m",
) -> str:
    return compute_experiment_identity_hash(
        original_strategy_provenance_hash=prov_hash,
        strategy_hash_before=strategy_hash_before,
        parameter_hash_before=parameter_hash_before,
        proposed_change=proposed_change or {"change_type": "parameter"},
        dataset_zone=dataset_zone,
        concrete_timerange=concrete_timerange,
        pair_set_hash=pair_set_hash,
        configuration_hash=config_hash,
        timeframe=timeframe,
    )


def _make_experiment(
    run_id: str = "run-1",
    hypothesis_id: str = "hyp-1",
    identity_hash: Optional[str] = None,
) -> ExperimentRecord:
    if identity_hash is None:
        identity_hash = _identity_hash()
    return ExperimentRecord(
        run_id=run_id,
        hypothesis_id=hypothesis_id,
        original_strategy_provenance=_prov(),
        experiment_identity_hash=identity_hash,
        dataset_zone="develop",
        concrete_timerange="20240101-20240630",
    )


class TestExperimentReservation:
    def test_reserve_succeeds(self, store):
        exp = _make_experiment()
        saved, dup = store.reserve(exp)
        assert dup is None
        assert saved.status == ExperimentStatus.RESERVED

    def test_reserve_persists(self, store, tmp_root):
        exp = _make_experiment()
        store.reserve(exp)
        store2 = ExperimentStore(tmp_root)
        records = store2.list_for_run("run-1")
        assert len(records) == 1

    def test_get_by_id(self, store):
        exp = _make_experiment()
        saved, _ = store.reserve(exp)
        found = store.get("run-1", saved.experiment_id)
        assert found is not None
        assert found.experiment_id == saved.experiment_id

    def test_list_for_run(self, store):
        store.reserve(_make_experiment("run-1", "hyp-1", _identity_hash(parameter_hash_before="p1")))
        store.reserve(_make_experiment("run-1", "hyp-1", _identity_hash(parameter_hash_before="p2")))
        records = store.list_for_run("run-1")
        assert len(records) == 2

    def test_list_for_hypothesis(self, store):
        store.reserve(_make_experiment("run-1", "hyp-1", _identity_hash(parameter_hash_before="p1")))
        store.reserve(_make_experiment("run-1", "hyp-2", _identity_hash(parameter_hash_before="p2")))
        h1_records = store.list_for_hypothesis("run-1", "hyp-1")
        assert len(h1_records) == 1
        assert all(e.hypothesis_id == "hyp-1" for e in h1_records)


class TestExperimentIdentity:
    def test_canonical_identity_stability(self):
        """Same inputs → same identity hash."""
        h1 = _identity_hash()
        h2 = _identity_hash()
        assert h1 == h2

    def test_key_order_independence(self):
        """JSON key order must not affect identity hash."""
        import json, hashlib
        from backend.services.aeroing4.research.identity import compute_experiment_identity_hash
        change1 = {"b": 2, "a": 1}
        change2 = {"a": 1, "b": 2}
        h1 = compute_experiment_identity_hash(
            original_strategy_provenance_hash="prov",
            strategy_hash_before="s",
            parameter_hash_before="p",
            proposed_change=change1,
            dataset_zone="develop",
            concrete_timerange="20240101-20240630",
            pair_set_hash="ps",
            configuration_hash="cfg",
            timeframe="5m",
        )
        h2 = compute_experiment_identity_hash(
            original_strategy_provenance_hash="prov",
            strategy_hash_before="s",
            parameter_hash_before="p",
            proposed_change=change2,
            dataset_zone="develop",
            concrete_timerange="20240101-20240630",
            pair_set_hash="ps",
            configuration_hash="cfg",
            timeframe="5m",
        )
        assert h1 == h2

    def test_different_strategy_hash_produces_different_identity(self):
        h1 = _identity_hash(strategy_hash_before="strat-A")
        h2 = _identity_hash(strategy_hash_before="strat-B")
        assert h1 != h2

    def test_different_parameter_hash_produces_different_identity(self):
        h1 = _identity_hash(parameter_hash_before="param-A")
        h2 = _identity_hash(parameter_hash_before="param-B")
        assert h1 != h2

    def test_different_timerange_produces_different_identity(self):
        h1 = _identity_hash(concrete_timerange="20240101-20240630")
        h2 = _identity_hash(concrete_timerange="20240101-20240930")
        assert h1 != h2

    def test_different_pair_set_produces_different_identity(self):
        h1 = _identity_hash(pair_set_hash="pairhash-A")
        h2 = _identity_hash(pair_set_hash="pairhash-B")
        assert h1 != h2

    def test_pair_ordering_does_not_change_pair_set_hash(self):
        from backend.services.aeroing4.research.identity import compute_experiment_identity_hash
        pairs_a = ["ETH/USDT", "BTC/USDT"]
        pairs_b = ["BTC/USDT", "ETH/USDT"]
        from backend.services.aeroing4.research.hashing import compute_pair_set_hash
        h_a = compute_pair_set_hash(pairs_a)
        h_b = compute_pair_set_hash(pairs_b)
        assert h_a == h_b

    def test_different_config_produces_different_identity(self):
        h1 = _identity_hash(config_hash="cfg-A")
        h2 = _identity_hash(config_hash="cfg-B")
        assert h1 != h2

    def test_different_source_strategy_provenance_not_deduplicated(self):
        """Two different source strategies must not produce the same identity."""
        prov_hash_1 = compute_original_strategy_provenance_hash(
            logical_name="StratA", path_hash="p1", source_hash="src1", version_id="v1"
        )
        prov_hash_2 = compute_original_strategy_provenance_hash(
            logical_name="StratB", path_hash="p2", source_hash="src2", version_id="v1"
        )
        h1 = _identity_hash(prov_hash=prov_hash_1, parameter_hash_before="same", strategy_hash_before="same")
        h2 = _identity_hash(prov_hash=prov_hash_2, parameter_hash_before="same", strategy_hash_before="same")
        assert h1 != h2


class TestExperimentDuplicateDetection:
    def test_duplicate_detected_by_identity_hash(self, store):
        exp = _make_experiment()
        store.reserve(exp)

        exp2 = _make_experiment(hypothesis_id="hyp-2")  # same identity_hash default
        saved, dup = store.reserve(exp2)
        assert dup is not None
        assert isinstance(dup, DuplicateExperimentDecision)
        assert dup.existing_experiment_id == exp.experiment_id

    def test_duplicate_includes_status_and_result(self, store):
        exp = _make_experiment()
        store.reserve(exp)
        exp2 = _make_experiment(hypothesis_id="hyp-2")
        _, dup = store.reserve(exp2)
        assert dup.existing_status == ExperimentStatus.RESERVED

    def test_find_by_identity_hash(self, store):
        exp = _make_experiment()
        store.reserve(exp)
        found = store.find_by_identity_hash("run-1", exp.experiment_identity_hash)
        assert found is not None
        assert found.experiment_id == exp.experiment_id

    def test_find_by_identity_hash_returns_none_if_not_found(self, store):
        assert store.find_by_identity_hash("run-1", "no-such-hash") is None


class TestExperimentStatusTransitions:
    def test_valid_planned_to_reserved(self, store):
        # reserve() transitions PLANNED → RESERVED atomically
        exp = _make_experiment()
        saved, _ = store.reserve(exp)
        assert saved.status == ExperimentStatus.RESERVED

    def test_valid_reserved_to_ready(self, store):
        exp = _make_experiment()
        saved, _ = store.reserve(exp)
        updated = store.transition_status("run-1", saved.experiment_id, ExperimentStatus.READY)
        assert updated.status == ExperimentStatus.READY

    def test_valid_ready_to_running(self, store):
        exp = _make_experiment()
        saved, _ = store.reserve(exp)
        store.transition_status("run-1", saved.experiment_id, ExperimentStatus.READY)
        updated = store.transition_status("run-1", saved.experiment_id, ExperimentStatus.RUNNING)
        assert updated.status == ExperimentStatus.RUNNING

    def test_valid_running_to_completed(self, store):
        exp = _make_experiment()
        saved, _ = store.reserve(exp)
        store.transition_status("run-1", saved.experiment_id, ExperimentStatus.READY)
        store.transition_status("run-1", saved.experiment_id, ExperimentStatus.RUNNING)
        updated = store.transition_status("run-1", saved.experiment_id, ExperimentStatus.COMPLETED)
        assert updated.status == ExperimentStatus.COMPLETED

    def test_invalid_transition_raises(self, store):
        exp = _make_experiment()
        saved, _ = store.reserve(exp)
        with pytest.raises(ExperimentTransitionError):
            store.transition_status("run-1", saved.experiment_id, ExperimentStatus.COMPLETED)

    def test_terminal_to_any_raises(self, store):
        exp = _make_experiment()
        saved, _ = store.reserve(exp)
        store.transition_status("run-1", saved.experiment_id, ExperimentStatus.CANCELLED)
        with pytest.raises(ExperimentTransitionError):
            store.transition_status("run-1", saved.experiment_id, ExperimentStatus.READY)

    def test_transition_not_found_raises(self, store):
        with pytest.raises(KeyError):
            store.transition_status("run-1", "no-such-id", ExperimentStatus.READY)


class TestExperimentMetrics:
    def test_record_metrics_preserved_across_reload(self, store, tmp_root):
        from backend.services.aeroing4.metrics.models import (
            CanonicalMetricsSnapshot, MetricValue, MetricAvailability, MetricProvenance
        )
        from backend.services.aeroing4.metrics.provenance import METRICS_VERSION, SourceType
        from datetime import UTC, datetime

        exp = _make_experiment()
        saved, _ = store.reserve(exp)

        def _unavailable():
            return MetricValue(value=None, availability=MetricAvailability.UNAVAILABLE)

        def _available(v):
            return MetricValue(value=v, availability=MetricAvailability.AVAILABLE)

        prov = MetricProvenance(
            metrics_version=METRICS_VERSION,
            source_type=SourceType.PARSED_SUMMARY,
            source_run_id="run-1",
            calculation_timestamp=datetime.now(UTC),
        )
        snap = CanonicalMetricsSnapshot(
            total_trades=_available(10),
            winning_trades=_available(7),
            losing_trades=_available(3),
            net_profit_abs=_available(100.0),
            net_profit_pct=_available(10.0),
            win_rate=_available(70.0),
            profit_factor=_available(1.5),
            expectancy=_available(10.0),
            sharpe=_unavailable(),
            sortino=_unavailable(),
            calmar=_unavailable(),
            max_drawdown_abs=_unavailable(),
            max_drawdown_pct=_unavailable(),
            average_trade_duration_minutes=_available(60.0),
            bootstrap_sharpe_p5=_unavailable(),
            provenance=prov,
        )
        store.record_metrics("run-1", saved.experiment_id, metrics_before=snap)

        store2 = ExperimentStore(tmp_root)
        loaded = store2.get("run-1", saved.experiment_id)
        assert loaded.metrics_before is not None
        assert loaded.metrics_before.total_trades.value == 10
        # Unavailable metrics are not silently flattened to 0
        assert loaded.metrics_before.sharpe.value is None

    def test_record_decision(self, store):
        exp = _make_experiment()
        saved, _ = store.reserve(exp)
        updated = store.record_decision("run-1", saved.experiment_id, ExperimentDecision.DROP, "No improvement")
        assert updated.decision == ExperimentDecision.DROP
        assert updated.result == "No improvement"


class TestExperimentIntegrity:
    def test_corrupted_file_raises_integrity_error(self, tmp_root):
        run_id = "corrupt-run"
        run_dir = tmp_root / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "experiments.json").write_text("not valid json!!!")
        store = ExperimentStore(tmp_root)
        with pytest.raises(ExperimentIntegrityError) as exc_info:
            store.list_for_run(run_id)
        assert exc_info.value.run_id == run_id
