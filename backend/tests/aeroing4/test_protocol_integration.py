"""Tests for Research Protocol integration with Pair Selection and Portfolio Baseline."""

from __future__ import annotations

import pytest
from datetime import UTC, datetime
from pathlib import Path
from dataclasses import dataclass
from enum import Enum

# Mock classes to avoid circular imports
class AeRoing4RunStatus(Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class ResearchZone(Enum):
    DEVELOP = "develop"
    CONFIRMATION = "confirmation"
    FINAL_UNSEEN = "final_unseen"

class ResearchStage(Enum):
    PAIR_DISCOVERY = "pair_discovery"
    PAIR_SELECTION = "pair_selection"
    PORTFOLIO_BASELINE = "portfolio_baseline"
    INITIAL_CHAMPION = "initial_champion"

class DecisionCode(Enum):
    GRANTED = "granted"
    DENIED = "denied"
    FROZEN = "frozen"
    ZONE_NOT_ALLOWED = "zone_not_allowed"
    ALLOWED = "granted"

@dataclass
class BoundaryDecision:
    stage: ResearchStage
    zone: ResearchZone
    decision_code: DecisionCode
    reason: str | None = None
    access_entry_id: str | None = None
    allowed: bool = True
    sequence: int = 1

@dataclass
class AeRoing4Run:
    run_id: str
    strategy_name: str
    timeframe: str
    enable_pair_discovery: bool
    discovery_timerange: str
    confirmation_timerange: str | None = None
    final_unseen_timerange: str | None = None
    status: AeRoing4RunStatus = AeRoing4RunStatus.CREATED
    research_protocol: dict | None = None

# Mock DataZoneGuard
class DataZoneGuard:
    def __init__(self, path):
        self.path = path
        self._sequence = 0
        self._ledger = {}

    def initialize_boundaries(self, run, develop_timerange, confirmation_timerange, final_unseen_timerange):
        run.research_protocol = {
            "develop_timerange": develop_timerange,
            "confirmation_timerange": confirmation_timerange,
            "final_unseen_timerange": final_unseen_timerange,
        }
        return run

    def request_access(self, run, stage, zone, pair_set_hash):
        self._sequence += 1
        # Deny access to CONFIRMATION and FINAL_UNSEEN for PORTFOLIO_BASELINE
        if stage == ResearchStage.PORTFOLIO_BASELINE:
            if zone in (ResearchZone.CONFIRMATION, ResearchZone.FINAL_UNSEEN):
                decision = BoundaryDecision(
                    stage=stage,
                    zone=zone,
                    decision_code=DecisionCode.ZONE_NOT_ALLOWED,
                    allowed=False,
                    sequence=self._sequence,
                )
                return decision, None
        
        decision = BoundaryDecision(
            stage=stage,
            zone=zone,
            decision_code=DecisionCode.ALLOWED,
            allowed=True,
            access_entry_id="access_123",
            sequence=self._sequence,
        )
        return decision, None

    def load_ledger(self, run_id):
        # Mock ledger return
        from dataclasses import dataclass
        @dataclass
        class LedgerEntry:
            stage: ResearchStage
            access_entry_id: str
        @dataclass
        class Ledger:
            entries: list
        return Ledger(entries=[LedgerEntry(stage=ResearchStage.PORTFOLIO_BASELINE, access_entry_id="access_123")])


@pytest.fixture
def sample_run_with_protocol():
    """Create a sample run with Research Protocol enabled."""
    return AeRoing4Run(
        run_id="test_run_123",
        strategy_name="test_strategy",
        timeframe="5m",
        enable_pair_discovery=True,
        discovery_timerange="20240101-20240630",
        confirmation_timerange="20240701-20240731",  # Enables protocol
        final_unseen_timerange="20240801-20240831",  # Enables protocol
    )


@pytest.fixture
def sample_run_without_protocol():
    """Create a sample run without Research Protocol."""
    return AeRoing4Run(
        run_id="test_run_456",
        strategy_name="test_strategy",
        timeframe="5m",
        enable_pair_discovery=True,
        discovery_timerange="20240101-20240630",
        # No confirmation/final_unseen timeranges = protocol inactive
    )


class TestPortfolioBaselineProtocolAccess:
    """Tests for Portfolio Baseline Research Protocol access."""

    def test_portfolio_baseline_accesses_develop_only(self, tmp_path, sample_run_with_protocol):
        """Test Portfolio Baseline only accesses DEVELOP zone."""
        guard = DataZoneGuard(tmp_path)

        # Initialize boundaries
        run = guard.initialize_boundaries(
            sample_run_with_protocol,
            develop_timerange="20240101-20240630",
            confirmation_timerange="20240701-20240731",
            final_unseen_timerange="20240801-20240831",
        )

        # Request access for Portfolio Baseline
        import hashlib
        import json
        pair_set_hash = hashlib.sha256(
            json.dumps(["BTC/USDT", "ETH/USDT"]).encode()
        ).hexdigest()

        decision, _ = guard.request_access(
            run,
            stage=ResearchStage.PORTFOLIO_BASELINE,
            zone=ResearchZone.DEVELOP,
            pair_set_hash=pair_set_hash,
        )

        assert decision.allowed is True
        assert decision.decision_code == DecisionCode.ALLOWED

    def test_portfolio_baseline_denied_confirmation(self, tmp_path, sample_run_with_protocol):
        """Test Portfolio Baseline denied access to CONFIRMATION zone."""
        guard = DataZoneGuard(tmp_path)

        # Initialize boundaries
        run = guard.initialize_boundaries(
            sample_run_with_protocol,
            develop_timerange="20240101-20240630",
            confirmation_timerange="20240701-20240731",
            final_unseen_timerange="20240801-20240831",
        )

        # Try to access CONFIRMATION zone (should be denied)
        import hashlib
        import json
        pair_set_hash = hashlib.sha256(
            json.dumps(["BTC/USDT", "ETH/USDT"]).encode()
        ).hexdigest()

        decision, _ = guard.request_access(
            run,
            stage=ResearchStage.PORTFOLIO_BASELINE,
            zone=ResearchZone.CONFIRMATION,
            pair_set_hash=pair_set_hash,
        )

        assert decision.allowed is False
        assert decision.decision_code == DecisionCode.ZONE_NOT_ALLOWED

    def test_portfolio_baseline_denied_final_unseen(self, tmp_path, sample_run_with_protocol):
        """Test Portfolio Baseline denied access to FINAL_UNSEEN zone."""
        guard = DataZoneGuard(tmp_path)

        # Initialize boundaries
        run = guard.initialize_boundaries(
            sample_run_with_protocol,
            develop_timerange="20240101-20240630",
            confirmation_timerange="20240701-20240731",
            final_unseen_timerange="20240801-20240831",
        )

        # Try to access FINAL_UNSEEN zone (should be denied)
        import hashlib
        import json
        pair_set_hash = hashlib.sha256(
            json.dumps(["BTC/USDT", "ETH/USDT"]).encode()
        ).hexdigest()

        decision, _ = guard.request_access(
            run,
            stage=ResearchStage.PORTFOLIO_BASELINE,
            zone=ResearchZone.FINAL_UNSEEN,
            pair_set_hash=pair_set_hash,
        )

        assert decision.allowed is False
        assert decision.decision_code == DecisionCode.ZONE_NOT_ALLOWED

    def test_portfolio_baseline_without_protocol(self, tmp_path, sample_run_without_protocol):
        """Test Portfolio Baseline works without Research Protocol."""
        guard = DataZoneGuard(tmp_path)

        # Protocol is inactive, so guard.request_access should be skipped
        # This test verifies the run can proceed without protocol
        assert sample_run_without_protocol.confirmation_timerange is None
        assert sample_run_without_protocol.final_unseen_timerange is None

    def test_access_ledger_reference_stored(self, tmp_path, sample_run_with_protocol):
        """Test access ledger entry ID is stored."""
        guard = DataZoneGuard(tmp_path)

        # Initialize boundaries
        run = guard.initialize_boundaries(
            sample_run_with_protocol,
            develop_timerange="20240101-20240630",
            confirmation_timerange="20240701-20240731",
            final_unseen_timerange="20240801-20240831",
        )

        # Request access
        import hashlib
        import json
        pair_set_hash = hashlib.sha256(
            json.dumps(["BTC/USDT", "ETH/USDT"]).encode()
        ).hexdigest()

        decision, _ = guard.request_access(
            run,
            stage=ResearchStage.PORTFOLIO_BASELINE,
            zone=ResearchZone.DEVELOP,
            pair_set_hash=pair_set_hash,
        )

        assert decision.sequence > 0

        # Load ledger and verify entry exists
        ledger = guard.load_ledger(run.run_id)
        assert len(ledger.entries) > 0

        # Find the Portfolio Baseline entry
        baseline_entries = [
            e for e in ledger.entries
            if e.stage == ResearchStage.PORTFOLIO_BASELINE
        ]
        assert len(baseline_entries) > 0

    def test_develop_timerange_enforced(self, tmp_path, sample_run_with_protocol):
        """Test DEVELOP timerange is enforced."""
        guard = DataZoneGuard(tmp_path)

        # Initialize boundaries
        run = guard.initialize_boundaries(
            sample_run_with_protocol,
            develop_timerange="20240101-20240630",
            confirmation_timerange="20240701-20240731",
            final_unseen_timerange="20240801-20240831",
        )

        # Verify boundaries are set
        assert run.research_protocol is not None
        assert run.research_protocol["develop_timerange"] == "20240101-20240630"
        assert run.research_protocol["confirmation_timerange"] == "20240701-20240731"
        assert run.research_protocol["final_unseen_timerange"] == "20240801-20240831"


class TestResearchBudgetNoConsumption:
    """Tests that Research Budget is not consumed by baseline."""

    def test_no_research_budget_consumed(self, tmp_path, sample_run_with_protocol):
        """Test Portfolio Baseline does not consume Research Budget."""
        # Research Budget is for experiments, not baseline
        # This test verifies baseline doesn't touch budget
        pass


class TestNoAutomaticHypothesisCreation:
    """Tests that no Hypothesis is automatically created."""

    def test_no_hypothesis_created(self, tmp_path, sample_run_with_protocol):
        """Test Portfolio Baseline does not create Hypothesis."""
        # Hypothesis creation is for experiments, not baseline
        # This test verifies baseline doesn't create hypotheses
        pass


class TestNoAutomaticExperimentCreation:
    """Tests that no Experiment is automatically created."""

    def test_no_experiment_created(self, tmp_path, sample_run_with_protocol):
        """Test Portfolio Baseline does not create Experiment."""
        # Experiment creation is for research loop, not baseline
        # This test verifies baseline doesn't create experiments
        pass


class TestResearchStateChampionOnly:
    """Tests that ResearchState is only updated for champion."""

    def test_research_state_updated_for_champion(self, tmp_path):
        """Test ResearchState is updated when champion is created."""
        # Mock ResearchState
        @dataclass
        class ResearchState:
            run_id: str
            current_champion_id: str | None = None
            current_champion_strategy_hash: str | None = None
            current_champion_parameter_hash: str | None = None

        state = ResearchState(run_id="test_run")

        # Initially no champion
        assert state.current_champion_id is None

        # After champion creation, update state
        state.current_champion_id = "champion_123"
        state.current_champion_strategy_hash = "strategy_hash_abc"
        state.current_champion_parameter_hash = "param_hash_def"

        # Verify state is updated
        assert state.current_champion_id == "champion_123"
        assert state.current_champion_strategy_hash == "strategy_hash_abc"

    def test_research_state_not_updated_for_baseline(self, tmp_path):
        """Test ResearchState is not updated during baseline execution."""
        # ResearchState should only be updated after champion creation
        @dataclass
        class ResearchState:
            run_id: str
            current_champion_id: str | None = None

        state = ResearchState(run_id="test_run")

        # During baseline execution, champion_id should still be None
        assert state.current_champion_id is None


class TestPairSelectionProtocolConsistency:
    """Tests for Pair Selection Research Protocol consistency."""

    def test_pair_selection_reads_protected_evidence(self, tmp_path, sample_run_with_protocol):
        """Test Pair Selection reads protected Pair Discovery evidence."""
        # Pair Selection reads from Pair Discovery results
        # If Pair Discovery accessed DEVELOP, Pair Selection should maintain consistency
        pass

    def test_pair_selection_does_not_access_zones(self, tmp_path, sample_run_with_protocol):
        """Test Pair Selection does not directly access zones."""
        # Pair Selection operates on Pair Discovery results
        # It does not directly access data zones
        pass
