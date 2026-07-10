"""Tests for the Research Protocol Access Ledger (Milestone 3)."""

import sys
import tempfile
from pathlib import Path

import pytest

from backend.services.aeroing4.research.data_zones import ResearchZone
from backend.services.aeroing4.research.errors import LedgerIntegrityError
from backend.services.aeroing4.research.ledger import (
    AccessDecision,
    AccessDecisionCode,
    AccessLedger,
)
from backend.services.aeroing4.research.stages import ResearchStage


@pytest.fixture
def temp_runs_root():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def ledger(temp_runs_root):
    return AccessLedger(temp_runs_root)


def _decision(allowed: bool, code: AccessDecisionCode, run_id: str = "run-1") -> AccessDecision:
    return AccessDecision(
        allowed=allowed,
        decision_code=code,
        reason="test reason",
        run_id=run_id,
        stage=ResearchStage.PAIR_DISCOVERY,
        zone=ResearchZone.DEVELOP,
        protocol_version="1.0.0",
    )


class TestAccessLedger:
    def test_append_persists_entry(self, ledger):
        entry = ledger.append(
            run_id="run-1",
            stage=ResearchStage.PAIR_DISCOVERY,
            zone=ResearchZone.DEVELOP,
            decision=_decision(True, AccessDecisionCode.ALLOWED),
        )
        assert entry.sequence == 0
        assert entry.allowed is True

        reloaded = ledger.load_entries("run-1")
        assert len(reloaded) == 1
        assert reloaded[0].access_id == entry.access_id

    def test_sequence_increments_and_is_stable_across_reload(self, ledger):
        for _ in range(5):
            ledger.append(
                run_id="run-1",
                stage=ResearchStage.PAIR_DISCOVERY,
                zone=ResearchZone.DEVELOP,
                decision=_decision(True, AccessDecisionCode.ALLOWED),
            )

        entries = ledger.load_entries("run-1")
        assert [e.sequence for e in entries] == [0, 1, 2, 3, 4]
        # access_ids are unique
        assert len({e.access_id for e in entries}) == 5

    def test_denied_and_allowed_entries_both_recorded(self, ledger):
        ledger.append(
            run_id="run-1",
            stage=ResearchStage.PAIR_DISCOVERY,
            zone=ResearchZone.DEVELOP,
            decision=_decision(True, AccessDecisionCode.ALLOWED),
        )
        ledger.append(
            run_id="run-1",
            stage=ResearchStage.CONFIRMATION,
            zone=ResearchZone.CONFIRMATION,
            decision=_decision(False, AccessDecisionCode.BOUNDARIES_NOT_FROZEN),
        )
        entries = ledger.load_entries("run-1")
        assert len(entries) == 2
        assert entries[0].allowed is True
        assert entries[1].allowed is False
        assert entries[1].decision_code == AccessDecisionCode.BOUNDARIES_NOT_FROZEN

    def test_runs_are_isolated(self, ledger):
        ledger.append(
            run_id="run-a",
            stage=ResearchStage.PAIR_DISCOVERY,
            zone=ResearchZone.DEVELOP,
            decision=_decision(True, AccessDecisionCode.ALLOWED, run_id="run-a"),
        )
        assert ledger.load_entries("run-a")
        assert ledger.load_entries("run-b") == []

    def test_load_entries_unknown_run_returns_empty_list(self, ledger):
        assert ledger.load_entries("nonexistent") == []

    def test_has_allowed_access_true_only_for_allowed(self, ledger):
        ledger.append(
            run_id="run-1",
            stage=ResearchStage.FINAL_UNSEEN,
            zone=ResearchZone.FINAL_UNSEEN,
            decision=AccessDecision(
                allowed=False,
                decision_code=AccessDecisionCode.CONFIRMATION_NOT_PASSED,
                reason="not passed",
                run_id="run-1",
                stage=ResearchStage.FINAL_UNSEEN,
                zone=ResearchZone.FINAL_UNSEEN,
                protocol_version="1.0.0",
            ),
        )
        assert ledger.has_allowed_access("run-1", zone=ResearchZone.FINAL_UNSEEN) is False

        ledger.append(
            run_id="run-1",
            stage=ResearchStage.FINAL_UNSEEN,
            zone=ResearchZone.FINAL_UNSEEN,
            decision=AccessDecision(
                allowed=True,
                decision_code=AccessDecisionCode.ALLOWED,
                reason="ok",
                run_id="run-1",
                stage=ResearchStage.FINAL_UNSEEN,
                zone=ResearchZone.FINAL_UNSEEN,
                protocol_version="1.0.0",
            ),
        )
        assert ledger.has_allowed_access("run-1", zone=ResearchZone.FINAL_UNSEEN) is True

    def test_persists_to_sibling_json_file_under_run_dir(self, ledger, temp_runs_root):
        ledger.append(
            run_id="run-1",
            stage=ResearchStage.PAIR_DISCOVERY,
            zone=ResearchZone.DEVELOP,
            decision=_decision(True, AccessDecisionCode.ALLOWED),
        )
        expected_path = temp_runs_root / "run-1" / "access_ledger.json"
        assert expected_path.exists()

    def test_new_ledger_instance_sees_persisted_entries(self, temp_runs_root):
        ledger1 = AccessLedger(temp_runs_root)
        ledger1.append(
            run_id="run-1",
            stage=ResearchStage.PAIR_DISCOVERY,
            zone=ResearchZone.DEVELOP,
            decision=_decision(True, AccessDecisionCode.ALLOWED),
        )

        ledger2 = AccessLedger(temp_runs_root)
        entries = ledger2.load_entries("run-1")
        assert len(entries) == 1

    def test_strategy_hash_preserved_across_reload(self, ledger, temp_runs_root):
        decision = AccessDecision(
            allowed=True,
            decision_code=AccessDecisionCode.ALLOWED,
            reason="ok",
            run_id="run-1",
            stage=ResearchStage.PAIR_DISCOVERY,
            zone=ResearchZone.DEVELOP,
            protocol_version="1.0.0",
            strategy_hash="sha256-strategy-abc",
        )
        entry = ledger.append(
            run_id="run-1",
            stage=ResearchStage.PAIR_DISCOVERY,
            zone=ResearchZone.DEVELOP,
            decision=decision,
        )
        assert entry.strategy_hash == "sha256-strategy-abc"

        # Survives disk round-trip via a fresh instance.
        ledger2 = AccessLedger(temp_runs_root)
        reloaded = ledger2.load_entries("run-1")
        assert reloaded[0].strategy_hash == "sha256-strategy-abc"

    def test_parameter_hash_preserved_across_reload(self, ledger, temp_runs_root):
        decision = AccessDecision(
            allowed=True,
            decision_code=AccessDecisionCode.ALLOWED,
            reason="ok",
            run_id="run-1",
            stage=ResearchStage.HYPEROPT,
            zone=ResearchZone.DEVELOP,
            protocol_version="1.0.0",
            parameter_hash="sha256-params-xyz",
        )
        entry = ledger.append(
            run_id="run-1",
            stage=ResearchStage.HYPEROPT,
            zone=ResearchZone.DEVELOP,
            decision=decision,
        )
        assert entry.parameter_hash == "sha256-params-xyz"

        ledger2 = AccessLedger(temp_runs_root)
        reloaded = ledger2.load_entries("run-1")
        assert reloaded[0].parameter_hash == "sha256-params-xyz"

    def test_experiment_id_preserved_across_reload(self, ledger, temp_runs_root):
        decision = AccessDecision(
            allowed=True,
            decision_code=AccessDecisionCode.ALLOWED,
            reason="ok",
            run_id="run-1",
            stage=ResearchStage.RESEARCH_EXPERIMENT,
            zone=ResearchZone.DEVELOP,
            protocol_version="1.0.0",
            experiment_id="exp-42",
        )
        entry = ledger.append(
            run_id="run-1",
            stage=ResearchStage.RESEARCH_EXPERIMENT,
            zone=ResearchZone.DEVELOP,
            decision=decision,
        )
        assert entry.experiment_id == "exp-42"

        ledger2 = AccessLedger(temp_runs_root)
        reloaded = ledger2.load_entries("run-1")
        assert reloaded[0].experiment_id == "exp-42"

    def test_underlying_result_id_preserved_across_reload(self, ledger, temp_runs_root):
        decision = _decision(True, AccessDecisionCode.ALLOWED)
        entry = ledger.append(
            run_id="run-1",
            stage=ResearchStage.PAIR_DISCOVERY,
            zone=ResearchZone.DEVELOP,
            decision=decision,
            underlying_result_id="backtest-run-999",
        )
        assert entry.underlying_result_id == "backtest-run-999"

        ledger2 = AccessLedger(temp_runs_root)
        reloaded = ledger2.load_entries("run-1")
        assert reloaded[0].underlying_result_id == "backtest-run-999"

    def test_pair_set_hash_preserved_across_reload(self, ledger, temp_runs_root):
        decision = _decision(True, AccessDecisionCode.ALLOWED)
        entry = ledger.append(
            run_id="run-1",
            stage=ResearchStage.PAIR_DISCOVERY,
            zone=ResearchZone.DEVELOP,
            decision=decision,
            pair_set_hash="sha256-pairs-abc123",
        )
        assert entry.pair_set_hash == "sha256-pairs-abc123"

        ledger2 = AccessLedger(temp_runs_root)
        reloaded = ledger2.load_entries("run-1")
        assert reloaded[0].pair_set_hash == "sha256-pairs-abc123"

    def test_protocol_version_preserved_across_reload(self, ledger, temp_runs_root):
        decision = _decision(True, AccessDecisionCode.ALLOWED)
        ledger.append(
            run_id="run-1",
            stage=ResearchStage.PAIR_DISCOVERY,
            zone=ResearchZone.DEVELOP,
            decision=decision,
        )
        ledger2 = AccessLedger(temp_runs_root)
        reloaded = ledger2.load_entries("run-1")
        assert reloaded[0].protocol_version == "1.0.0"

    @pytest.mark.skipif(sys.platform == "win32", reason="Concurrent file writes have platform-specific issues on Windows")
    def test_simultaneous_writes_do_not_overwrite_each_other(self, temp_runs_root):
        """Concurrent appends must all land; no entry must silently overwrite another."""
        import threading

        ledger = AccessLedger(temp_runs_root)
        n_threads = 20
        errors: list[Exception] = []

        def write_entry():
            try:
                ledger.append(
                    run_id="run-concurrent",
                    stage=ResearchStage.PAIR_DISCOVERY,
                    zone=ResearchZone.DEVELOP,
                    decision=_decision(
                        True, AccessDecisionCode.ALLOWED, run_id="run-concurrent"
                    ),
                )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=write_entry) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        entries = ledger.load_entries("run-concurrent")
        assert len(entries) == n_threads, (
            f"Expected {n_threads} entries but got {len(entries)}"
        )
        # Sequences must be unique and contiguous (0 … n-1).
        sequences = sorted(e.sequence for e in entries)
        assert sequences == list(range(n_threads))
        # access_ids must be unique (no UUID collision / overwrite).
        assert len({e.access_id for e in entries}) == n_threads

    # ── Corrupted ledger (fail-closed) ─────────────────────────────────────

    def test_corrupted_ledger_raises_integrity_error(self, temp_runs_root):
        """A corrupted ledger file must raise LedgerIntegrityError, not return []."""
        run_id = "run-corrupt"
        ledger_dir = temp_runs_root / run_id
        ledger_dir.mkdir(parents=True)
        (ledger_dir / "access_ledger.json").write_text("not valid json!!!", encoding="utf-8")

        ledger = AccessLedger(temp_runs_root)
        with pytest.raises(LedgerIntegrityError) as exc_info:
            ledger.load_entries(run_id)
        assert exc_info.value.run_id == run_id

    def test_absent_ledger_file_returns_empty_list(self, ledger):
        """No ledger file yet (first access) is valid — returns empty list."""
        entries = ledger.load_entries("no-such-run")
        assert entries == []

    def test_corrupted_ledger_prevents_has_allowed_access(self, temp_runs_root):
        """has_allowed_access on a corrupt ledger raises LedgerIntegrityError."""
        run_id = "run-corrupt2"
        ledger_dir = temp_runs_root / run_id
        ledger_dir.mkdir(parents=True)
        (ledger_dir / "access_ledger.json").write_text("[{bad json", encoding="utf-8")

        ledger = AccessLedger(temp_runs_root)
        with pytest.raises(LedgerIntegrityError):
            ledger.has_allowed_access(run_id, zone=ResearchZone.FINAL_UNSEEN)

    # ── Atomic FINAL_UNSEEN gate ──────────────────────────────────────────────

    @pytest.mark.skipif(sys.platform == "win32", reason="Concurrent file writes have platform-specific issues on Windows")
    def test_concurrent_final_unseen_requests_only_one_allowed(self, temp_runs_root):
        """Two simultaneous FINAL_UNSEEN requests: exactly one is ALLOWED,
        the second (under the lock) sees the first entry and is DENIED."""
        import threading

        ledger = AccessLedger(temp_runs_root)
        run_id = "run-fu-concurrent"

        def _allowed_decision():
            return AccessDecision(
                allowed=True,
                decision_code=AccessDecisionCode.ALLOWED,
                reason="ok",
                run_id=run_id,
                stage=ResearchStage.FINAL_UNSEEN,
                zone=ResearchZone.FINAL_UNSEEN,
                protocol_version="1.0.0",
            )

        def _denied_decision():
            return AccessDecision(
                allowed=False,
                decision_code=AccessDecisionCode.FINAL_UNSEEN_ALREADY_CONSUMED,
                reason="already consumed",
                run_id=run_id,
                stage=ResearchStage.FINAL_UNSEEN,
                zone=ResearchZone.FINAL_UNSEEN,
                protocol_version="1.0.0",
            )

        results: list[AccessDecision] = []
        errors: list[Exception] = []

        def request():
            try:
                decision, _ = ledger.atomic_final_unseen_append(
                    run_id=run_id,
                    stage=ResearchStage.FINAL_UNSEEN,
                    pre_check_decision=_allowed_decision(),
                    denied_decision=_denied_decision(),
                )
                results.append(decision)
            except Exception as exc:
                errors.append(exc)

        n = 10
        threads = [threading.Thread(target=request) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors: {errors}"
        assert len(results) == n
        allowed_count = sum(1 for d in results if d.allowed)
        denied_count = sum(1 for d in results if not d.allowed)
        assert allowed_count == 1, f"Expected exactly 1 allowed, got {allowed_count}"
        assert denied_count == n - 1

        # Ledger must have exactly n entries, exactly 1 allowed.
        entries = ledger.load_entries(run_id)
        assert len(entries) == n
        assert sum(1 for e in entries if e.allowed) == 1
