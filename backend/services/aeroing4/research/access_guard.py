"""Data Zone Guard — the standalone Research Protocol access-control service.

Answers "can this stage access this zone for this run right now?" with a
typed `AccessDecision` (never a bare boolean), persists every attempt
(allowed and denied) to the `AccessLedger`, and owns the one moment
research boundaries transition from mutable to frozen: the first granted
DEVELOP access for a run (see `request_access`).

This module must be *consulted by* step/orchestrator call sites, not merge
into them — it never touches Freqtrade execution mechanics, and it never
recomputes Metrics SSOT values.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .data_zones import (
    RESEARCH_PROTOCOL_VERSION,
    BOUNDARY_DERIVATION_POLICY_VERSION,
    BoundarySource,
    ResearchBoundaries,
    ResearchZone,
    compute_boundary_hash,
    derive_boundaries,
    validate_boundary_set,
)
from .errors import BoundaryErrorCode, BoundaryFrozenError, BoundaryValidationError, LedgerIntegrityError
from .ledger import AccessDecision, AccessDecisionCode, AccessLedger
from .stages import ResearchStage, allowed_zones_for_stage
from .state import ResearchProtocolState, ResearchProtocolSummary


class BoundaryManager:
    """Owns the lifecycle of a run's `ResearchBoundaries`: initialize, allow
    pre-freeze corrections, reject post-freeze mutation, never silently
    re-derive.
    """

    def __init__(self, state_store):
        self.state_store = state_store

    def initialize_boundaries(
        self,
        run,
        *,
        develop_timerange: str | None = None,
        confirmation_timerange: str | None = None,
        final_unseen_timerange: str | None = None,
        research_timerange: str | None = None,
        derivation_policy_version: str = BOUNDARY_DERIVATION_POLICY_VERSION,
    ):
        """Ensure `run` has concrete, persisted `ResearchBoundaries`.

        Explicit mode: pass all three zone timeranges.
        Derived mode: pass only `research_timerange` (optionally with a
          non-default `derivation_policy_version`); the three zones are
          split deterministically via `derive_boundaries` and persisted as
          concrete values — never re-derived dynamically afterwards.

        Idempotent: calling again with the *same* input returns the run
        unchanged. Calling with *different* input on an unfrozen run
        overwrites (pre-active-research correction). Calling with different
        input on a *frozen* run raises `BoundaryFrozenError`.
        """
        explicit_mode = any(
            v is not None
            for v in (develop_timerange, confirmation_timerange, final_unseen_timerange)
        )
        derived_mode = research_timerange is not None

        if explicit_mode and derived_mode:
            raise BoundaryValidationError(
                "Provide either explicit zone timeranges or a single "
                "research_timerange to derive from, not both",
                code=BoundaryErrorCode.AMBIGUOUS_INPUT,
            )
        if not explicit_mode and not derived_mode:
            raise BoundaryValidationError(
                "Must provide explicit zone timeranges or a research_timerange",
                code=BoundaryErrorCode.AMBIGUOUS_INPUT,
            )

        if explicit_mode:
            if not (develop_timerange and confirmation_timerange and final_unseen_timerange):
                raise BoundaryValidationError(
                    "Explicit boundary mode requires develop_timerange, "
                    "confirmation_timerange, and final_unseen_timerange",
                    code=BoundaryErrorCode.AMBIGUOUS_INPUT,
                )
            new_source = BoundarySource.EXPLICIT
            new_signature = (develop_timerange, confirmation_timerange, final_unseen_timerange)
            candidate = (develop_timerange, confirmation_timerange, final_unseen_timerange)
            derivation_source_timerange = None
            derivation_policy_version_used = None
        else:
            new_source = BoundarySource.DERIVED
            candidate = derive_boundaries(research_timerange, derivation_policy_version)
            new_signature = (research_timerange, derivation_policy_version)
            derivation_source_timerange = research_timerange
            derivation_policy_version_used = derivation_policy_version

        existing = run.research_protocol.boundaries if run.research_protocol else None

        if existing is not None:
            existing_signature = (
                (
                    existing.develop_timerange,
                    existing.confirmation_timerange,
                    existing.final_unseen_timerange,
                )
                if existing.boundary_source == BoundarySource.EXPLICIT
                else (existing.derivation_source_timerange, existing.derivation_policy_version)
            )
            if existing.boundary_source == new_source and existing_signature == new_signature:
                return run  # idempotent — no recompute, no mutation

            if existing.is_frozen:
                raise BoundaryFrozenError(
                    "Research boundaries are frozen for this run and cannot "
                    "be changed (attempted different boundary input)",
                    run_id=run.run_id,
                )
            # Not yet frozen: fall through and persist the corrected boundaries.

        develop_tr, confirmation_tr, final_unseen_tr = candidate
        validate_boundary_set(develop_tr, confirmation_tr, final_unseen_tr)
        boundary_hash = compute_boundary_hash(
            develop_tr, confirmation_tr, final_unseen_tr, RESEARCH_PROTOCOL_VERSION
        )
        boundaries = ResearchBoundaries(
            develop_timerange=develop_tr,
            confirmation_timerange=confirmation_tr,
            final_unseen_timerange=final_unseen_tr,
            protocol_version=RESEARCH_PROTOCOL_VERSION,
            boundary_source=new_source,
            boundary_hash=boundary_hash,
            derivation_source_timerange=derivation_source_timerange,
            derivation_policy_version=derivation_policy_version_used,
        )

        state = run.research_protocol or ResearchProtocolState()
        run.research_protocol = state.model_copy(update={"boundaries": boundaries})
        self.state_store.save_run(run)
        return run

    def freeze_if_needed(self, run):
        """Freeze `run`'s boundaries in place if not already frozen. Returns run."""
        state = run.research_protocol
        if state is None or state.boundaries is None or state.boundaries.is_frozen:
            return run
        frozen = state.boundaries.frozen_copy()
        run.research_protocol = state.model_copy(update={"boundaries": frozen})
        self.state_store.save_run(run)
        return run


class DataZoneGuard:
    """The Research Protocol access-control service.

    Owns a `BoundaryManager` and an `AccessLedger`, both scoped to the same
    `runs_root` the `AeRoing4StateStore` uses, so the ledger lives as a
    sibling file under `user_data/aeroing4/runs/{run_id}/` per the frozen
    architecture (one canonical run-state owner, no competing store).
    """

    def __init__(self, state_store, runs_root: Path):
        self.state_store = state_store
        self.boundaries = BoundaryManager(state_store)
        self.ledger = AccessLedger(runs_root)

    # ── Boundary lifecycle passthroughs ─────────────────────────────────────

    def initialize_boundaries(self, run, **kwargs):
        return self.boundaries.initialize_boundaries(run, **kwargs)

    def set_confirmation_passed(self, run, passed: bool = True):
        """Record the Confirmation pass/fail gate for FINAL_UNSEEN access.

        Confirmation *execution* itself is out of scope for this milestone;
        this setter exists so the future Confirmation stage (and tests) have
        a concrete, persisted place to record the outcome.
        """
        state = run.research_protocol or ResearchProtocolState()
        run.research_protocol = state.model_copy(
            update={
                "confirmation_passed": passed,
                "confirmation_passed_at": datetime.now(UTC) if passed else None,
            }
        )
        self.state_store.save_run(run)
        return run

    # ── Access decisions ─────────────────────────────────────────────────────

    def can_access(
        self,
        run,
        stage: ResearchStage,
        zone: ResearchZone,
        strategy_hash: str | None = None,
        parameter_hash: str | None = None,
        experiment_id: str | None = None,
    ) -> AccessDecision:
        """Pure decision function — never mutates state, never writes the ledger.

        Use `request_access` at real call sites; use `can_access` directly
        for isolated permission tests.
        """

        def deny(code: AccessDecisionCode, reason: str) -> AccessDecision:
            return AccessDecision(
                allowed=False,
                decision_code=code,
                reason=reason,
                run_id=run.run_id,
                stage=stage,
                zone=zone,
                protocol_version=RESEARCH_PROTOCOL_VERSION,
                strategy_hash=strategy_hash,
                parameter_hash=parameter_hash,
                experiment_id=experiment_id,
            )

        allowed_zones = allowed_zones_for_stage(stage)
        if zone not in allowed_zones:
            return deny(
                AccessDecisionCode.ZONE_NOT_ALLOWED_FOR_STAGE,
                f"Stage '{stage.value}' is not permitted to access zone "
                f"'{zone.value}' (allowed: "
                f"{sorted(z.value for z in allowed_zones) or 'none'})",
            )

        protocol_state = run.research_protocol
        boundaries = protocol_state.boundaries if protocol_state else None

        if boundaries is None:
            # Migration compatibility: runs created before the guard existed
            # (or before boundaries were ever initialized for this run) have
            # no concept of zones at all. Per the additive migration
            # strategy, treat this as "guard not applicable" rather than a
            # hard failure, so pre-protocol runs keep working unchanged.
            return AccessDecision(
                allowed=True,
                decision_code=AccessDecisionCode.BOUNDARIES_NOT_INITIALIZED,
                reason=(
                    "No research boundaries are initialized for this run; "
                    "Data Zone Guard is not applicable (legacy/uninitialized run)"
                ),
                run_id=run.run_id,
                stage=stage,
                zone=zone,
                protocol_version=RESEARCH_PROTOCOL_VERSION,
                strategy_hash=strategy_hash,
                parameter_hash=parameter_hash,
                experiment_id=experiment_id,
            )

        if boundaries.protocol_version != RESEARCH_PROTOCOL_VERSION:
            return deny(
                AccessDecisionCode.PROTOCOL_VERSION_MISMATCH,
                f"Run's frozen protocol_version '{boundaries.protocol_version}' "
                f"does not match the current RESEARCH_PROTOCOL_VERSION "
                f"'{RESEARCH_PROTOCOL_VERSION}'",
            )

        # CONFIRMATION / FINAL_UNSEEN may only be entered once boundaries are
        # already frozen — freezing itself only happens via a DEVELOP access.
        if zone in (ResearchZone.CONFIRMATION, ResearchZone.FINAL_UNSEEN) and not boundaries.is_frozen:
            return deny(
                AccessDecisionCode.BOUNDARIES_NOT_FROZEN,
                "Research boundaries are not frozen yet; DEVELOP research "
                "must run (and grant the first protected access) before "
                f"{zone.value} can be entered",
            )

        if zone is ResearchZone.FINAL_UNSEEN:
            if not (protocol_state and protocol_state.confirmation_passed):
                return deny(
                    AccessDecisionCode.CONFIRMATION_NOT_PASSED,
                    "FINAL_UNSEEN cannot be accessed until Confirmation has passed",
                )
            # Check FINAL_UNSEEN consumed status — fail-closed on ledger corruption.
            try:
                already_consumed = self.ledger.has_allowed_access(
                    run.run_id, zone=ResearchZone.FINAL_UNSEEN
                )
            except LedgerIntegrityError as exc:
                return deny(
                    AccessDecisionCode.INVALID_BOUNDARY_STATE,
                    f"Access ledger integrity failure prevents FINAL_UNSEEN check: {exc}",
                )
            if already_consumed:
                return deny(
                    AccessDecisionCode.FINAL_UNSEEN_ALREADY_CONSUMED,
                    "FINAL_UNSEEN has already been consumed for this run; "
                    "it is single-use and terminal",
                )

        return AccessDecision(
            allowed=True,
            decision_code=AccessDecisionCode.ALLOWED,
            reason=f"Stage '{stage.value}' is permitted to access '{zone.value}'",
            run_id=run.run_id,
            stage=stage,
            zone=zone,
            protocol_version=RESEARCH_PROTOCOL_VERSION,
            strategy_hash=strategy_hash,
            parameter_hash=parameter_hash,
            experiment_id=experiment_id,
        )

    def request_access(
        self,
        run,
        stage: ResearchStage,
        zone: ResearchZone,
        strategy_hash: str | None = None,
        parameter_hash: str | None = None,
        experiment_id: str | None = None,
        pair_set_hash: str | None = None,
        underlying_result_id: str | None = None,
    ) -> tuple[AccessDecision, "object"]:
        """Decide, freeze-on-first-grant, and record to the ledger.

        Returns `(decision, run)` — `run` is returned (possibly with freshly
        frozen boundaries persisted) so callers keep working with the
        authoritative in-memory object rather than reloading separately.
        """
        decision = self.can_access(
            run,
            stage,
            zone,
            strategy_hash=strategy_hash,
            parameter_hash=parameter_hash,
            experiment_id=experiment_id,
        )

        if decision.allowed and zone is ResearchZone.DEVELOP:
            run = self.boundaries.freeze_if_needed(run)

        if zone is ResearchZone.FINAL_UNSEEN and decision.allowed:
            # FINAL_UNSEEN is single-use and terminal.  The check in can_access
            # (has_allowed_access) is not atomic with the subsequent append, so
            # a concurrent second call could see an un-consumed ledger and also
            # be granted access before either write lands.  Use the ledger's
            # atomic check-and-append primitive to make the check + record a
            # single critical section.
            denied_decision = AccessDecision(
                allowed=False,
                decision_code=AccessDecisionCode.FINAL_UNSEEN_ALREADY_CONSUMED,
                reason=(
                    "FINAL_UNSEEN has already been consumed for this run; "
                    "it is single-use and terminal (concurrent access detected)"
                ),
                run_id=run.run_id,
                stage=stage,
                zone=zone,
                protocol_version=decision.protocol_version,
                strategy_hash=strategy_hash,
                parameter_hash=parameter_hash,
                experiment_id=experiment_id,
            )
            decision, _ = self.ledger.atomic_final_unseen_append(
                run_id=run.run_id,
                stage=stage,
                pre_check_decision=decision,
                denied_decision=denied_decision,
                pair_set_hash=pair_set_hash,
                underlying_result_id=underlying_result_id,
            )
        else:
            self.ledger.append(
                run_id=run.run_id,
                stage=stage,
                zone=zone,
                decision=decision,
                pair_set_hash=pair_set_hash,
                underlying_result_id=underlying_result_id,
            )

        return decision, run

    def get_protocol_summary(self, run) -> ResearchProtocolSummary:
        """Typed summary combining boundary state + ledger-derived access info."""
        entries = self.ledger.load_entries(run.run_id)
        return ResearchProtocolSummary.build(
            run_id=run.run_id,
            state=run.research_protocol,
            ledger_entries=entries,
        )
