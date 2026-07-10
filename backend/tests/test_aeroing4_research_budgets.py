"""Tests for Budget & Concurrency — Milestone 4 §32."""

from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

import pytest

from backend.services.aeroing4.research.budgets import (
    RESEARCH_BUDGET_POLICY_VERSION,
    BudgetDecisionCode,
    BudgetService,
    DEFAULT_MAX_TOTAL_EXPERIMENTS,
    DEFAULT_MAX_EXPERIMENTS_PER_HYPOTHESIS,
)
from backend.services.aeroing4.research.experiments import (
    ExperimentRecord,
    ExperimentStatus,
    ExperimentStore,
    OriginalStrategyProvenance,
)
from backend.services.aeroing4.research.identity import compute_experiment_identity_hash


def _make_exp(
    run_id: str,
    hypothesis_id: str = "hyp-1",
    suffix: str = "",
) -> ExperimentRecord:
    identity = compute_experiment_identity_hash(
        original_strategy_provenance_hash=f"prov{suffix}",
        strategy_hash_before=f"strat{suffix}",
        parameter_hash_before=f"param{suffix}",
        proposed_change={"type": "parameter", "suffix": suffix},
        dataset_zone="develop",
        concrete_timerange="20240101-20240630",
        pair_set_hash="pairhash",
        configuration_hash="cfg",
        timeframe="5m",
    )
    return ExperimentRecord(
        run_id=run_id,
        hypothesis_id=hypothesis_id,
        original_strategy_provenance=OriginalStrategyProvenance(logical_name="S"),
        experiment_identity_hash=identity,
    )


class TestBudgetPolicy:
    def test_version_constant_exists(self):
        assert RESEARCH_BUDGET_POLICY_VERSION == "1.0.0"

    def test_default_limits(self):
        svc = BudgetService()
        assert svc.max_total_experiments == DEFAULT_MAX_TOTAL_EXPERIMENTS
        assert svc.max_experiments_per_hypothesis == DEFAULT_MAX_EXPERIMENTS_PER_HYPOTHESIS

    def test_allow_when_within_budget(self):
        svc = BudgetService(max_total_experiments=5, max_experiments_per_hypothesis=3)
        decision = svc.can_reserve(total_reserved=2, hypothesis_experiment_count=1)
        assert decision.allowed
        assert decision.code == BudgetDecisionCode.ALLOWED

    def test_deny_when_total_exhausted(self):
        svc = BudgetService(max_total_experiments=5, max_experiments_per_hypothesis=3)
        decision = svc.can_reserve(total_reserved=5, hypothesis_experiment_count=1)
        assert not decision.allowed
        assert decision.code == BudgetDecisionCode.TOTAL_BUDGET_EXHAUSTED

    def test_deny_when_hypothesis_exhausted(self):
        svc = BudgetService(max_total_experiments=5, max_experiments_per_hypothesis=3)
        decision = svc.can_reserve(total_reserved=1, hypothesis_experiment_count=3)
        assert not decision.allowed
        assert decision.code == BudgetDecisionCode.HYPOTHESIS_BUDGET_EXHAUSTED

    def test_remaining_total_calculation(self):
        svc = BudgetService(max_total_experiments=5)
        assert svc.remaining_total(total_reserved=2) == 3
        assert svc.remaining_total(total_reserved=5) == 0

    def test_remaining_for_hypothesis(self):
        svc = BudgetService(max_experiments_per_hypothesis=3)
        assert svc.remaining_for_hypothesis(hypothesis_experiment_count=1) == 2
        assert svc.remaining_for_hypothesis(hypothesis_experiment_count=3) == 0

    def test_is_run_exhausted(self):
        svc = BudgetService(max_total_experiments=5)
        assert not svc.is_run_exhausted(total_reserved=4)
        assert svc.is_run_exhausted(total_reserved=5)

    def test_result_is_typed_with_counts(self):
        svc = BudgetService(max_total_experiments=5, max_experiments_per_hypothesis=3)
        decision = svc.can_reserve(total_reserved=2, hypothesis_experiment_count=1)
        assert decision.total_reserved == 2
        assert decision.total_max == 5
        assert decision.remaining_total == 3


class TestBudgetConcurrency:
    """Simultaneous reservations must not exceed the configured limits."""

    @pytest.mark.skipif(sys.platform == "win32", reason="Concurrent file writes have platform-specific issues on Windows")
    def test_total_limit_cannot_be_exceeded_concurrently(self, tmp_path):
        """With max_total_experiments=3, concurrent requests can reserve at most 3."""
        store = ExperimentStore(
            tmp_path,
            budget_service=BudgetService(max_total_experiments=3, max_experiments_per_hypothesis=10),
        )
        run_id = "run-concurrent"
        errors = []
        reserved_ids = []
        lock = threading.Lock()

        def try_reserve(i: int):
            exp = _make_exp(run_id, suffix=str(i))
            try:
                saved, dup = store.reserve(exp)
                if dup is None:
                    with lock:
                        reserved_ids.append(saved.experiment_id)
            except ValueError:
                pass  # budget exhausted — expected
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=try_reserve, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Unexpected errors: {errors}"
        # At most 3 should have been reserved (the budget limit)
        records = store.list_for_run(run_id)
        assert len(records) <= 3

    def test_duplicate_concurrent_creates_one_experiment(self, tmp_path):
        """Two concurrent requests with the same identity must create only one experiment."""
        store = ExperimentStore(tmp_path, budget_service=BudgetService())
        run_id = "run-dup"
        identity_hash = compute_experiment_identity_hash(
            original_strategy_provenance_hash="prov",
            strategy_hash_before="s", parameter_hash_before="p",
            proposed_change={"x": 1}, dataset_zone="develop",
            concrete_timerange="20240101-20240630",
            pair_set_hash="ps", configuration_hash="cfg", timeframe="5m",
        )
        results = []
        lock = threading.Lock()

        def try_reserve():
            exp = ExperimentRecord(
                run_id=run_id, hypothesis_id="hyp-1",
                original_strategy_provenance=OriginalStrategyProvenance(logical_name="S"),
                experiment_identity_hash=identity_hash,
            )
            saved, dup = store.reserve(exp)
            with lock:
                results.append((saved, dup))

        threads = [threading.Thread(target=try_reserve) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        records = store.list_for_run(run_id)
        assert len(records) == 1, f"Expected exactly 1 experiment, got {len(records)}"

    @pytest.mark.skipif(sys.platform == "win32", reason="Concurrent file writes have platform-specific issues on Windows")
    def test_simultaneous_writes_do_not_lose_history(self, tmp_path):
        """Concurrent writes with different identities all land."""
        store = ExperimentStore(tmp_path, budget_service=BudgetService(max_total_experiments=50))
        run_id = "run-history"
        n = 15
        errors = []

        def reserve_one(i: int):
            # Use different hypothesis IDs to avoid per-hypothesis budget limits
            exp = _make_exp(run_id, hypothesis_id=f"hyp-{i}", suffix=str(i))
            try:
                store.reserve(exp)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reserve_one, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors: {errors}"
        records = store.list_for_run(run_id)
        assert len(records) == n
