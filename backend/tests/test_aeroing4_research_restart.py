"""Restart enforcement tests for the Research Protocol (Milestone 3 §13).

Verifies that all protocol decisions, frozen boundaries, and ledger entries
survive process/state reload — i.e. a fresh AeRoing4StateStore and DataZoneGuard
constructed from the same on-disk state behave identically to the original.

Three canonical scenarios from the specification:

  Scenario A  boundaries created → frozen → protected access → reload → forbidden still denied
  Scenario B  FINAL_UNSEEN access recorded → reload → second attempt still blocked
  Scenario C  boundary hash persisted → reload → changed input still rejected
"""

import tempfile
from pathlib import Path

import pytest

from backend.services.aeroing4.research.access_guard import DataZoneGuard
from backend.services.aeroing4.research.data_zones import ResearchZone
from backend.services.aeroing4.research.errors import BoundaryFrozenError
from backend.services.aeroing4.research.ledger import AccessDecisionCode
from backend.services.aeroing4.research.stages import ResearchStage
from backend.services.aeroing4.state_store import AeRoing4StateStore


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_runs_root():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def store(temp_runs_root):
    return AeRoing4StateStore(temp_runs_root)


@pytest.fixture
def guard(store, temp_runs_root):
    return DataZoneGuard(store, temp_runs_root)


def _fresh_guard(runs_root: Path) -> tuple[AeRoing4StateStore, DataZoneGuard]:
    """Simulate a process restart by constructing entirely new store + guard."""
    new_store = AeRoing4StateStore(runs_root)
    new_guard = DataZoneGuard(new_store, runs_root)
    return new_store, new_guard


def _explicit_boundaries(guard, run):
    return guard.initialize_boundaries(
        run,
        develop_timerange="20240101-20240301",
        confirmation_timerange="20240305-20240401",
        final_unseen_timerange="20240405-20240501",
    )


# ── Scenario A ────────────────────────────────────────────────────────────────

class TestRestartScenarioA:
    """After reload, protocol state that was forbidden remains forbidden.

    Scenario A (from spec §13):
    1. Run boundaries are created.
    2. Boundaries freeze (via first granted DEVELOP access).
    3. Protected access occurs and is recorded in the ledger.
    4. Application / state reload occurs (new store + guard from disk).
    5. Attempted forbidden access is still denied.
    """

    def test_frozen_boundaries_survive_reload(self, guard, store, temp_runs_root):
        run = store.create_run(strategy_name="s")
        run = _explicit_boundaries(guard, run)
        _, run = guard.request_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)
        assert run.research_protocol.boundaries.is_frozen

        new_store, _ = _fresh_guard(temp_runs_root)
        reloaded = new_store.load_run(run.run_id)
        assert reloaded is not None
        assert reloaded.research_protocol.boundaries.is_frozen is True

    def test_denied_access_remains_denied_after_reload(self, guard, store, temp_runs_root):
        """FINAL_UNSEEN denied (no confirmation_passed) and still denied after reload."""
        run = store.create_run(strategy_name="s")
        run = _explicit_boundaries(guard, run)
        # Freeze boundaries via a DEVELOP access.
        _, run = guard.request_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)

        # Before reload: confirmation not passed → FINAL_UNSEEN denied.
        pre_decision = guard.can_access(
            run, ResearchStage.FINAL_UNSEEN, ResearchZone.FINAL_UNSEEN
        )
        assert pre_decision.allowed is False
        assert pre_decision.decision_code == AccessDecisionCode.CONFIRMATION_NOT_PASSED

        # Reload.
        new_store, new_guard = _fresh_guard(temp_runs_root)
        reloaded = new_store.load_run(run.run_id)

        # After reload: still denied, for the same reason.
        post_decision = new_guard.can_access(
            reloaded, ResearchStage.FINAL_UNSEEN, ResearchZone.FINAL_UNSEEN
        )
        assert post_decision.allowed is False
        assert post_decision.decision_code == AccessDecisionCode.CONFIRMATION_NOT_PASSED

    def test_protocol_version_state_survives_reload(self, guard, store, temp_runs_root):
        """The protocol_version stored in frozen boundaries matches after reload."""
        from backend.services.aeroing4.research.data_zones import RESEARCH_PROTOCOL_VERSION

        run = store.create_run(strategy_name="s")
        run = _explicit_boundaries(guard, run)
        _, run = guard.request_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)

        new_store, _ = _fresh_guard(temp_runs_root)
        reloaded = new_store.load_run(run.run_id)
        assert reloaded.research_protocol.boundaries.protocol_version == RESEARCH_PROTOCOL_VERSION

    def test_ledger_entries_survive_reload(self, guard, store, temp_runs_root):
        """All access ledger entries are readable after a fresh guard is created."""
        run = store.create_run(strategy_name="s")
        run = _explicit_boundaries(guard, run)
        guard.request_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)

        _, new_guard = _fresh_guard(temp_runs_root)
        entries = new_guard.ledger.load_entries(run.run_id)
        assert len(entries) == 1
        assert entries[0].allowed is True
        assert entries[0].zone == ResearchZone.DEVELOP
        assert entries[0].stage == ResearchStage.PAIR_DISCOVERY


# ── Scenario B ────────────────────────────────────────────────────────────────

class TestRestartScenarioB:
    """After reload, FINAL_UNSEEN remains blocked because the ledger remembers it.

    Scenario B (from spec §13):
    1. FINAL_UNSEEN access is recorded.
    2. Application reload occurs.
    3. Second unauthorized Final Unseen attempt remains blocked.
    """

    def _prepare_consumed_run(self, guard, store):
        run = store.create_run(strategy_name="s")
        run = _explicit_boundaries(guard, run)
        _, run = guard.request_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)
        run = guard.set_confirmation_passed(run, True)
        # Consume FINAL_UNSEEN once.
        decision, run = guard.request_access(
            run, ResearchStage.FINAL_UNSEEN, ResearchZone.FINAL_UNSEEN
        )
        assert decision.allowed is True
        return run

    def test_prior_final_unseen_access_remains_known_after_reload(
        self, guard, store, temp_runs_root
    ):
        run = self._prepare_consumed_run(guard, store)

        # Reload — new guard reads the ledger from disk.
        _, new_guard = _fresh_guard(temp_runs_root)

        # FINAL_UNSEEN is still seen as consumed.
        assert new_guard.ledger.has_allowed_access(
            run.run_id, zone=ResearchZone.FINAL_UNSEEN
        ) is True

    def test_second_final_unseen_attempt_still_denied_after_reload(
        self, guard, store, temp_runs_root
    ):
        run = self._prepare_consumed_run(guard, store)

        new_store, new_guard = _fresh_guard(temp_runs_root)
        reloaded = new_store.load_run(run.run_id)

        decision = new_guard.can_access(
            reloaded, ResearchStage.FINAL_UNSEEN, ResearchZone.FINAL_UNSEEN
        )
        assert decision.allowed is False
        assert decision.decision_code == AccessDecisionCode.FINAL_UNSEEN_ALREADY_CONSUMED


# ── Scenario C ────────────────────────────────────────────────────────────────

class TestRestartScenarioC:
    """After reload, a different boundary input is rejected, not silently accepted.

    Scenario C (from spec §13):
    1. Boundary hash is persisted (boundaries are frozen).
    2. Application reload occurs.
    3. Changed boundary input is rejected rather than silently accepted.
    """

    def test_changed_boundary_input_rejected_after_reload(
        self, guard, store, temp_runs_root
    ):
        run = store.create_run(strategy_name="s")
        run = _explicit_boundaries(guard, run)
        # Freeze.
        _, run = guard.request_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)
        assert run.research_protocol.boundaries.is_frozen

        # Simulate restart.
        new_store, new_guard = _fresh_guard(temp_runs_root)
        reloaded = new_store.load_run(run.run_id)
        assert reloaded.research_protocol.boundaries.is_frozen

        # Attempt to initialize with a *different* boundary set — must raise.
        with pytest.raises(BoundaryFrozenError):
            new_guard.initialize_boundaries(
                reloaded,
                develop_timerange="20240101-20240315",  # different
                confirmation_timerange="20240320-20240401",
                final_unseen_timerange="20240405-20240501",
            )

    def test_same_boundary_input_idempotent_after_reload(
        self, guard, store, temp_runs_root
    ):
        """Calling initialize_boundaries with the *same* explicit input on a frozen
        run returns the run unchanged (idempotent) — even after reload."""
        run = store.create_run(strategy_name="s")
        run = _explicit_boundaries(guard, run)
        original_hash = run.research_protocol.boundaries.boundary_hash
        _, run = guard.request_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)

        new_store, new_guard = _fresh_guard(temp_runs_root)
        reloaded = new_store.load_run(run.run_id)

        # Same input → idempotent, no error.
        result = new_guard.initialize_boundaries(
            reloaded,
            develop_timerange="20240101-20240301",
            confirmation_timerange="20240305-20240401",
            final_unseen_timerange="20240405-20240501",
        )
        assert result.research_protocol.boundaries.boundary_hash == original_hash


# ── Additional reload / persistence tests ─────────────────────────────────────

class TestAdditionalReloadBehavior:
    def test_derived_boundaries_survive_reload(self, guard, store, temp_runs_root):
        """DERIVED boundaries persist their concrete values and remain valid after reload."""
        run = store.create_run(strategy_name="s")
        run = guard.initialize_boundaries(run, research_timerange="20230101-20231231")
        original_dev = run.research_protocol.boundaries.develop_timerange

        new_store, _ = _fresh_guard(temp_runs_root)
        reloaded = new_store.load_run(run.run_id)
        assert reloaded.research_protocol.boundaries.develop_timerange == original_dev

    def test_confirmation_passed_gate_survives_reload(self, guard, store, temp_runs_root):
        """confirmation_passed=True on the run persists and gates FINAL_UNSEEN correctly."""
        run = store.create_run(strategy_name="s")
        run = _explicit_boundaries(guard, run)
        _, run = guard.request_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)
        run = guard.set_confirmation_passed(run, True)

        new_store, new_guard = _fresh_guard(temp_runs_root)
        reloaded = new_store.load_run(run.run_id)
        assert reloaded.research_protocol.confirmation_passed is True

        # FINAL_UNSEEN should now be accessible (confirmation passed, not yet consumed).
        decision = new_guard.can_access(
            reloaded, ResearchStage.FINAL_UNSEEN, ResearchZone.FINAL_UNSEEN
        )
        assert decision.allowed is True

    def test_denied_ledger_entries_survive_reload(self, guard, store, temp_runs_root):
        """Denied access attempts are persisted and visible after reload."""
        run = store.create_run(strategy_name="s")
        # Attempt denied access (zone not allowed for stage).
        guard.request_access(run, ResearchStage.CONFIRMATION, ResearchZone.DEVELOP)

        _, new_guard = _fresh_guard(temp_runs_root)
        entries = new_guard.ledger.load_entries(run.run_id)
        assert len(entries) == 1
        assert entries[0].allowed is False
        assert entries[0].decision_code == AccessDecisionCode.ZONE_NOT_ALLOWED_FOR_STAGE
