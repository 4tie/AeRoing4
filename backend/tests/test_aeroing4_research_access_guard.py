"""Tests for the Data Zone Guard (Milestone 3): permission matrix, boundary
lifecycle, freeze-on-first-access, FINAL_UNSEEN single-use, restart safety.
"""

import tempfile
from pathlib import Path

import pytest

from backend.services.aeroing4.research.access_guard import BoundaryManager, DataZoneGuard
from backend.services.aeroing4.research.data_zones import (
    RESEARCH_PROTOCOL_VERSION,
    BoundarySource,
    ResearchZone,
)
from backend.services.aeroing4.research.errors import BoundaryFrozenError
from backend.services.aeroing4.research.ledger import AccessDecisionCode
from backend.services.aeroing4.research.stages import ResearchStage
from backend.services.aeroing4.state_store import AeRoing4StateStore


@pytest.fixture
def temp_runs_root():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def state_store(temp_runs_root):
    return AeRoing4StateStore(temp_runs_root)


@pytest.fixture
def guard(state_store, temp_runs_root):
    return DataZoneGuard(state_store, temp_runs_root)


@pytest.fixture
def run(state_store):
    return state_store.create_run(strategy_name="test_strategy")


class TestBoundariesNotInitialized:
    """Legacy/uninitialized runs must be treated as guard-not-applicable."""

    def test_missing_boundaries_allows_with_note(self, guard, run):
        decision = guard.can_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)
        assert decision.allowed is True
        assert decision.decision_code == AccessDecisionCode.BOUNDARIES_NOT_INITIALIZED


class TestStagePermissionMatrix:
    def _init(self, guard, run):
        return guard.initialize_boundaries(
            run,
            develop_timerange="20240101-20240301",
            confirmation_timerange="20240305-20240401",
            final_unseen_timerange="20240405-20240501",
        )

    def _freeze(self, guard, run):
        """Initialize + freeze boundaries via a granted DEVELOP access."""
        run = self._init(guard, run)
        _, run = guard.request_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)
        return run

    # ── Pair Discovery ────────────────────────────────────────────────────────

    def test_pair_discovery_allowed_for_develop(self, guard, run):
        run = self._init(guard, run)
        decision = guard.can_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)
        assert decision.allowed is True
        assert decision.decision_code == AccessDecisionCode.ALLOWED

    def test_pair_discovery_denied_for_confirmation_zone(self, guard, run):
        run = self._init(guard, run)
        decision = guard.can_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.CONFIRMATION)
        assert decision.allowed is False
        assert decision.decision_code == AccessDecisionCode.ZONE_NOT_ALLOWED_FOR_STAGE

    def test_pair_discovery_denied_for_final_unseen_zone(self, guard, run):
        run = self._init(guard, run)
        decision = guard.can_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.FINAL_UNSEEN)
        assert decision.allowed is False
        assert decision.decision_code == AccessDecisionCode.ZONE_NOT_ALLOWED_FOR_STAGE

    # ── DEVELOP-only consumers (Research Experiment, Hyperopt, Sensitivity) ──

    def test_research_experiment_allowed_for_develop_only(self, guard, run):
        run = self._init(guard, run)
        assert guard.can_access(run, ResearchStage.RESEARCH_EXPERIMENT, ResearchZone.DEVELOP).allowed is True
        assert guard.can_access(run, ResearchStage.RESEARCH_EXPERIMENT, ResearchZone.CONFIRMATION).allowed is False
        assert guard.can_access(run, ResearchStage.RESEARCH_EXPERIMENT, ResearchZone.FINAL_UNSEEN).allowed is False

    def test_hyperopt_allowed_for_develop_only(self, guard, run):
        run = self._init(guard, run)
        assert guard.can_access(run, ResearchStage.HYPEROPT, ResearchZone.DEVELOP).allowed is True
        assert guard.can_access(run, ResearchStage.HYPEROPT, ResearchZone.CONFIRMATION).allowed is False
        assert guard.can_access(run, ResearchStage.HYPEROPT, ResearchZone.FINAL_UNSEEN).allowed is False

    def test_sensitivity_allowed_for_develop_only(self, guard, run):
        run = self._init(guard, run)
        assert guard.can_access(run, ResearchStage.SENSITIVITY, ResearchZone.DEVELOP).allowed is True
        assert guard.can_access(run, ResearchStage.SENSITIVITY, ResearchZone.CONFIRMATION).allowed is False
        assert guard.can_access(run, ResearchStage.SENSITIVITY, ResearchZone.FINAL_UNSEEN).allowed is False

    # ── Confirmation stage ────────────────────────────────────────────────────

    def test_confirmation_stage_denied_for_develop_zone(self, guard, run):
        run = self._init(guard, run)
        decision = guard.can_access(run, ResearchStage.CONFIRMATION, ResearchZone.DEVELOP)
        assert decision.allowed is False
        assert decision.decision_code == AccessDecisionCode.ZONE_NOT_ALLOWED_FOR_STAGE

    def test_confirmation_stage_denied_for_final_unseen_zone(self, guard, run):
        run = self._init(guard, run)
        decision = guard.can_access(run, ResearchStage.CONFIRMATION, ResearchZone.FINAL_UNSEEN)
        assert decision.allowed is False
        assert decision.decision_code == AccessDecisionCode.ZONE_NOT_ALLOWED_FOR_STAGE

    def test_confirmation_stage_denied_until_boundaries_frozen(self, guard, run):
        run = self._init(guard, run)
        decision = guard.can_access(run, ResearchStage.CONFIRMATION, ResearchZone.CONFIRMATION)
        assert decision.allowed is False
        assert decision.decision_code == AccessDecisionCode.BOUNDARIES_NOT_FROZEN

    def test_confirmation_stage_allowed_after_boundaries_frozen(self, guard, run):
        run = self._freeze(guard, run)
        decision = guard.can_access(run, ResearchStage.CONFIRMATION, ResearchZone.CONFIRMATION)
        # Confirmation stage may access CONFIRMATION zone once boundaries are frozen.
        assert decision.allowed is True

    # ── FINAL_UNSEEN stage ────────────────────────────────────────────────────

    def test_final_unseen_stage_denied_for_develop_zone(self, guard, run):
        run = self._init(guard, run)
        decision = guard.can_access(run, ResearchStage.FINAL_UNSEEN, ResearchZone.DEVELOP)
        assert decision.allowed is False
        assert decision.decision_code == AccessDecisionCode.ZONE_NOT_ALLOWED_FOR_STAGE

    def test_final_unseen_stage_denied_for_confirmation_zone(self, guard, run):
        run = self._init(guard, run)
        decision = guard.can_access(run, ResearchStage.FINAL_UNSEEN, ResearchZone.CONFIRMATION)
        assert decision.allowed is False
        assert decision.decision_code == AccessDecisionCode.ZONE_NOT_ALLOWED_FOR_STAGE

    def test_final_unseen_denied_until_confirmation_passed(self, guard, run):
        run = self._init(guard, run)
        # Freeze boundaries via a granted DEVELOP access first.
        _, run = guard.request_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)
        decision = guard.can_access(run, ResearchStage.FINAL_UNSEEN, ResearchZone.FINAL_UNSEEN)
        assert decision.allowed is False
        assert decision.decision_code == AccessDecisionCode.CONFIRMATION_NOT_PASSED


class TestFreezeOnFirstDevelopAccess:
    def test_boundaries_unfrozen_before_first_access(self, guard, run):
        run = guard.initialize_boundaries(
            run,
            develop_timerange="20240101-20240301",
            confirmation_timerange="20240305-20240401",
            final_unseen_timerange="20240405-20240501",
        )
        assert run.research_protocol.boundaries.is_frozen is False

    def test_first_allowed_develop_access_freezes_boundaries(self, guard, run):
        run = guard.initialize_boundaries(
            run,
            develop_timerange="20240101-20240301",
            confirmation_timerange="20240305-20240401",
            final_unseen_timerange="20240405-20240501",
        )
        decision, run = guard.request_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)
        assert decision.allowed is True
        assert run.research_protocol.boundaries.is_frozen is True

    def test_denied_access_does_not_freeze(self, guard, run):
        # No boundaries initialized + confirmation stage → denied (zone not allowed).
        decision, run = guard.request_access(run, ResearchStage.CONFIRMATION, ResearchZone.DEVELOP)
        assert decision.allowed is False
        assert run.research_protocol is None or run.research_protocol.boundaries is None

    def test_freeze_persists_across_reload(self, guard, run, state_store):
        run = guard.initialize_boundaries(
            run,
            develop_timerange="20240101-20240301",
            confirmation_timerange="20240305-20240401",
            final_unseen_timerange="20240405-20240501",
        )
        guard.request_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)

        reloaded = state_store.load_run(run.run_id)
        assert reloaded.research_protocol.boundaries.is_frozen is True


class TestFinalUnseenSingleUse:
    def _prepared_run(self, guard, run):
        run = guard.initialize_boundaries(
            run,
            develop_timerange="20240101-20240301",
            confirmation_timerange="20240305-20240401",
            final_unseen_timerange="20240405-20240501",
        )
        _, run = guard.request_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)
        run = guard.set_confirmation_passed(run, True)
        return run

    def test_first_final_unseen_access_allowed(self, guard, run):
        run = self._prepared_run(guard, run)
        decision, run = guard.request_access(run, ResearchStage.FINAL_UNSEEN, ResearchZone.FINAL_UNSEEN)
        assert decision.allowed is True

    def test_second_final_unseen_access_denied(self, guard, run):
        run = self._prepared_run(guard, run)
        guard.request_access(run, ResearchStage.FINAL_UNSEEN, ResearchZone.FINAL_UNSEEN)
        decision, run = guard.request_access(run, ResearchStage.FINAL_UNSEEN, ResearchZone.FINAL_UNSEEN)
        assert decision.allowed is False
        assert decision.decision_code == AccessDecisionCode.FINAL_UNSEEN_ALREADY_CONSUMED


class TestProtocolVersionMismatch:
    def test_mismatched_frozen_protocol_version_denies_access(self, guard, run, monkeypatch):
        run = guard.initialize_boundaries(
            run,
            develop_timerange="20240101-20240301",
            confirmation_timerange="20240305-20240401",
            final_unseen_timerange="20240405-20240501",
        )
        # Simulate an already-frozen run recorded under an older protocol version.
        old_boundaries = run.research_protocol.boundaries.model_copy(
            update={"protocol_version": "0.9.0"}
        )
        run.research_protocol = run.research_protocol.model_copy(
            update={"boundaries": old_boundaries}
        )
        decision = guard.can_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)
        assert decision.allowed is False
        assert decision.decision_code == AccessDecisionCode.PROTOCOL_VERSION_MISMATCH


class TestBoundaryManagerLifecycle:
    def test_initialize_is_idempotent_for_same_explicit_input(self, guard, run):
        run = guard.initialize_boundaries(
            run,
            develop_timerange="20240101-20240301",
            confirmation_timerange="20240305-20240401",
            final_unseen_timerange="20240405-20240501",
        )
        first_hash = run.research_protocol.boundaries.boundary_hash
        run = guard.initialize_boundaries(
            run,
            develop_timerange="20240101-20240301",
            confirmation_timerange="20240305-20240401",
            final_unseen_timerange="20240405-20240501",
        )
        assert run.research_protocol.boundaries.boundary_hash == first_hash

    def test_initialize_allows_correction_before_freeze(self, guard, run):
        run = guard.initialize_boundaries(
            run,
            develop_timerange="20240101-20240301",
            confirmation_timerange="20240305-20240401",
            final_unseen_timerange="20240405-20240501",
        )
        run = guard.initialize_boundaries(
            run,
            develop_timerange="20240101-20240315",
            confirmation_timerange="20240320-20240401",
            final_unseen_timerange="20240405-20240501",
        )
        assert run.research_protocol.boundaries.develop_timerange == "20240101-20240315"

    def test_initialize_rejects_change_after_freeze(self, guard, run):
        run = guard.initialize_boundaries(
            run,
            develop_timerange="20240101-20240301",
            confirmation_timerange="20240305-20240401",
            final_unseen_timerange="20240405-20240501",
        )
        guard.request_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)
        run = guard.state_store.load_run(run.run_id)

        with pytest.raises(BoundaryFrozenError):
            guard.initialize_boundaries(
                run,
                develop_timerange="20240101-20240315",
                confirmation_timerange="20240320-20240401",
                final_unseen_timerange="20240405-20240501",
            )

    def test_derived_mode_persists_concrete_boundaries(self, guard, run):
        run = guard.initialize_boundaries(run, research_timerange="20240101-20240630")
        boundaries = run.research_protocol.boundaries
        assert boundaries.boundary_source == BoundarySource.DERIVED
        assert boundaries.derivation_source_timerange == "20240101-20240630"

    def test_derived_mode_idempotent_for_same_source(self, guard, run):
        run = guard.initialize_boundaries(run, research_timerange="20240101-20240630")
        first_hash = run.research_protocol.boundaries.boundary_hash
        run = guard.initialize_boundaries(run, research_timerange="20240101-20240630")
        assert run.research_protocol.boundaries.boundary_hash == first_hash

    def test_ambiguous_input_raises(self, guard, run):
        from backend.services.aeroing4.research.errors import BoundaryValidationError

        with pytest.raises(BoundaryValidationError):
            guard.initialize_boundaries(
                run,
                develop_timerange="20240101-20240301",
                research_timerange="20240101-20240630",
            )

    def test_no_input_raises(self, guard, run):
        from backend.services.aeroing4.research.errors import BoundaryValidationError

        with pytest.raises(BoundaryValidationError):
            guard.initialize_boundaries(run)


class TestProtocolSummary:
    def test_summary_reflects_boundaries_and_ledger(self, guard, run):
        run = guard.initialize_boundaries(
            run,
            develop_timerange="20240101-20240301",
            confirmation_timerange="20240305-20240401",
            final_unseen_timerange="20240405-20240501",
        )
        decision, run = guard.request_access(run, ResearchStage.PAIR_DISCOVERY, ResearchZone.DEVELOP)
        summary = guard.get_protocol_summary(run)

        assert summary.boundaries_frozen is True
        assert summary.protocol_version == RESEARCH_PROTOCOL_VERSION
        assert summary.access_counts["allowed"] == 1
        assert summary.access_counts["denied"] == 0
        assert summary.latest_violation is None

    def test_summary_surfaces_latest_violation(self, guard, run):
        guard.request_access(run, ResearchStage.CONFIRMATION, ResearchZone.DEVELOP)
        run = guard.state_store.load_run(run.run_id) or run
        summary = guard.get_protocol_summary(run)
        assert summary.latest_violation is not None
        assert summary.latest_violation.decision_code == AccessDecisionCode.ZONE_NOT_ALLOWED_FOR_STAGE
