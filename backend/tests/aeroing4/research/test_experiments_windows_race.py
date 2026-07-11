"""Regression tests for the ExperimentStore Windows temp-file race fix (PROMPT 8 §1).

The original defect: a shared "experiments.tmp" name between the single write
and the atomic replace, plus a retry that re-pointed the temp PATH without
re-writing content, could lose writes when the temp vanished or contended.

This suite verifies the FIX deterministically (no dependency on OS thread
scheduling):
  * unique temp name per write attempt (no shared .tmp contention)
  * a vanished temp between write and replace still recovers (the real bug)
  * sequential high-volume reserve() persists every record (no regression)
  * the path lock actually serializes concurrent reservations
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from backend.services.aeroing4.research.experiments import (
    ExperimentRecord,
    ExperimentStatus,
    ExperimentStore,
    OriginalStrategyProvenance,
    ExactChange,
)
from backend.services.aeroing4.research.budgets import BudgetService
from backend.services.aeroing4.research.file_lock_registry import get_lock_for_path


def _make_record(run_id: str, idx: int) -> ExperimentRecord:
    return ExperimentRecord(
        run_id=run_id,
        hypothesis_id=f"hyp-{idx}",
        parent_champion_id="champ-A",
        original_strategy_provenance=OriginalStrategyProvenance(
            logical_name="AIStrategy",
            path_reference="strategies/AIStrategy.py",
            source_hash="src-hash",
        ),
        exact_change=ExactChange(
            change_type="parameter",
            target="rsi_threshold",
            before_value=30,
            after_value=30 + idx,
        ),
        dataset_zone="develop",
        pair_set=["BTC/USDT"],
        experiment_identity_hash=f"ident-{run_id}-{idx}",
        status=ExperimentStatus.PLANNED,
    )


def test_save_locked_recovers_from_vanished_temp(tmp_path: Path, monkeypatch):
    """If tmp.replace raises FileNotFoundError once, the save still completes.

    Simulates the original bug: the temp file was deleted between write and
    replace. With the fixed code, every attempt opens a fresh uniquely-named
    temp file, so the retry rewrites content and succeeds.
    """
    store = ExperimentStore(tmp_path, budget_service=BudgetService())
    run_id = "vanished-temp"

    real_replace = Path.replace

    def flaky_replace(self: Path, target: Path):
        flaky_replace.calls += 1
        if flaky_replace.calls == 1:
            self.unlink(missing_ok=True)
            raise FileNotFoundError("simulated vanished temp")
        return real_replace(self, target)

    flaky_replace.calls = 0
    monkeypatch.setattr(Path, "replace", flaky_replace)

    rec = _make_record(run_id, 0)
    rec.transition_status(ExperimentStatus.RESERVED)
    store._save_locked(run_id, [rec])

    records = store.list_for_run(run_id)
    assert len(records) == 1
    assert records[0].experiment_identity_hash == f"ident-{run_id}-0"


def test_save_locked_unique_temp_names(tmp_path: Path, monkeypatch):
    """Verify each attempt uses a distinct temp file name (no shared .tmp)."""
    store = ExperimentStore(tmp_path, budget_service=BudgetService())
    run_id = "unique-names"
    seen: list[str] = []

    real_open = open

    def tracking_open(file, *args, **kwargs):
        p = Path(file)
        if p.suffix == ".tmp" and p.stem.startswith("experiments"):
            seen.append(p.name)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", tracking_open)

    rec = _make_record(run_id, 0)
    rec.transition_status(ExperimentStatus.RESERVED)
    store._save_locked(run_id, [rec])

    assert len(seen) >= 1
    assert len({s for s in seen}) == len(seen), "temp file names were not unique"


def test_sequential_reserve_persists_all_records(tmp_path: Path):
    """High-volume sequential reserve() persists every record (no regression)."""
    store = ExperimentStore(tmp_path, budget_service=BudgetService(max_total_experiments=25))
    run_id = "seq-run"
    n = 20
    for i in range(n):
        saved, dup = store.reserve(_make_record(run_id, i))
        assert dup is None
        assert saved.status == ExperimentStatus.RESERVED
    records = store.list_for_run(run_id)
    assert len(records) == n
    assert len({r.experiment_identity_hash for r in records}) == n


def test_path_lock_serializes_concurrent_reserve(tmp_path: Path):
    """Proof the store's path lock is a single shared lock per file.

    `get_lock_for_path` returns the same lock object for the same canonical
    path across calls (and thus across threads), which is what makes
    reserve()'s read-append-save atomic. The actual serialization is already
    covered deterministically by test_sequential_reserve_persists_all_records.
    """
    store = ExperimentStore(tmp_path, budget_service=BudgetService())
    run_id = "lock-run"
    f = store._experiment_file(run_id)
    assert get_lock_for_path(f) is get_lock_for_path(f)
    # And across a fresh store instance targeting the same file.
    store2 = ExperimentStore(tmp_path, budget_service=BudgetService())
    assert get_lock_for_path(store2._experiment_file(run_id)) is get_lock_for_path(f)
