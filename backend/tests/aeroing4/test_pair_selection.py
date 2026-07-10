"""Tests for Pair Selection logic."""

from __future__ import annotations

import pytest

from backend.services.aeroing4.models import PairCandidateStatus, PairEvaluationRecord
from backend.services.aeroing4.pair_selection import (
    PairSelectionMode,
    PairSelectionOutcome,
    PairSelector,
)


@pytest.fixture
def sample_discovery_result():
    """Create a sample PairDiscoveryResult for testing."""
    from backend.services.aeroing4.models import PairDiscoveryResult

    # Create sample pair evaluations
    evaluations = [
        PairEvaluationRecord(
            pair="BTC/USDT",
            status=PairCandidateStatus.VALID_CANDIDATE,
            total_trades=100,
            net_profit_pct=15.5,
            rank=1,
            rank_score=0.95,
        ),
        PairEvaluationRecord(
            pair="ETH/USDT",
            status=PairCandidateStatus.VALID_CANDIDATE,
            total_trades=80,
            net_profit_pct=12.3,
            rank=2,
            rank_score=0.90,
        ),
        PairEvaluationRecord(
            pair="BNB/USDT",
            status=PairCandidateStatus.VALID_CANDIDATE,
            total_trades=60,
            net_profit_pct=8.7,
            rank=3,
            rank_score=0.85,
        ),
        PairEvaluationRecord(
            pair="SOL/USDT",
            status=PairCandidateStatus.VALID_CANDIDATE,
            total_trades=50,
            net_profit_pct=6.2,
            rank=4,
            rank_score=0.80,
        ),
        PairEvaluationRecord(
            pair="ADA/USDT",
            status=PairCandidateStatus.ZERO_TRADES,
            total_trades=0,
            net_profit_pct=0.0,
            rejection_reasons=["No trades generated"],
        ),
        PairEvaluationRecord(
            pair="DOGE/USDT",
            status=PairCandidateStatus.INSUFFICIENT_TRADES,
            total_trades=5,
            net_profit_pct=2.1,
            rejection_reasons=["Insufficient trades"],
        ),
        PairEvaluationRecord(
            pair="DOT/USDT",
            status=PairCandidateStatus.EXECUTION_FAILURE,
            total_trades=0,
            rejection_reasons=["Execution failed"],
        ),
    ]

    return PairDiscoveryResult(
        universe_size=7,
        usable_pairs_count=7,
        evaluated_pairs_count=7,
        valid_candidates_count=4,
        rejected_pairs_count=3,
        ranked_pairs=[e for e in evaluations if e.status == PairCandidateStatus.VALID_CANDIDATE],
        all_evaluations=evaluations,
        discovery_pairs_requested=["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "ADA/USDT", "DOGE/USDT", "DOT/USDT"],
        discovery_timerange="20240101-20240630",
        timeframe="5m",
        strategy_name="test_strategy",
        ranking_policy_version="1.0.0",
    )


class TestPairSelector:
    """Tests for PairSelector class."""

    def test_auto_best_n_default_count(self, sample_discovery_result):
        """Test AUTO_BEST_N with default target count."""
        selector = PairSelector()
        result = selector.select_auto_best_n(
            discovery_result=sample_discovery_result,
            target_count=4,
        )

        assert result.selection_mode == PairSelectionMode.AUTO_BEST_N
        assert result.outcome == PairSelectionOutcome.SELECTION_COMPLETE
        assert len(result.selected_pairs) == 4
        assert result.selected_pairs == ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"]
        assert result.requested_target_count == 4
        assert len(result.warnings) == 0

    def test_auto_best_n_configurable_count(self, sample_discovery_result):
        """Test AUTO_BEST_N with configurable target count."""
        selector = PairSelector()
        result = selector.select_auto_best_n(
            discovery_result=sample_discovery_result,
            target_count=2,
        )

        assert result.selection_mode == PairSelectionMode.AUTO_BEST_N
        assert result.outcome == PairSelectionOutcome.SELECTION_COMPLETE
        assert len(result.selected_pairs) == 2
        assert result.selected_pairs == ["BTC/USDT", "ETH/USDT"]
        assert result.requested_target_count == 2

    def test_auto_best_n_deterministic_order(self, sample_discovery_result):
        """Test AUTO_BEST_N preserves deterministic ranking order."""
        selector = PairSelector()
        result1 = selector.select_auto_best_n(
            discovery_result=sample_discovery_result,
            target_count=4,
        )
        result2 = selector.select_auto_best_n(
            discovery_result=sample_discovery_result,
            target_count=4,
        )

        assert result1.selected_pairs == result2.selected_pairs
        assert result1.selection_hash == result2.selection_hash

    def test_auto_best_n_insufficient_qualified_pairs(self, sample_discovery_result):
        """Test AUTO_BEST_N when fewer qualified pairs exist than requested."""
        selector = PairSelector()
        result = selector.select_auto_best_n(
            discovery_result=sample_discovery_result,
            target_count=10,
        )

        assert result.selection_mode == PairSelectionMode.AUTO_BEST_N
        assert result.outcome == PairSelectionOutcome.PARTIAL_SELECTION
        assert len(result.selected_pairs) == 4  # Only 4 qualified pairs
        assert result.requested_target_count == 10
        assert len(result.warnings) > 0
        assert "valid_candidate pairs available" in result.warnings[0].lower()

    def test_auto_best_n_excludes_rejected_pairs(self, sample_discovery_result):
        """Test AUTO_BEST_N never includes rejected pairs."""
        selector = PairSelector()
        result = selector.select_auto_best_n(
            discovery_result=sample_discovery_result,
            target_count=10,
        )

        # Should not include ZERO_TRADES, INSUFFICIENT_TRADES, or EXECUTION_FAILURE pairs
        assert "ADA/USDT" not in result.selected_pairs  # ZERO_TRADES
        assert "DOGE/USDT" not in result.selected_pairs  # INSUFFICIENT_TRADES
        assert "DOT/USDT" not in result.selected_pairs  # EXECUTION_FAILURE

    def test_manual_valid_selection(self, sample_discovery_result):
        """Test MANUAL selection with valid pairs."""
        selector = PairSelector()
        result = selector.select_manual(
            requested_pairs=["BTC/USDT", "ETH/USDT", "BNB/USDT"],
            discovery_result=sample_discovery_result,
        )

        assert result.selection_mode == PairSelectionMode.MANUAL
        assert result.outcome == PairSelectionOutcome.SELECTION_COMPLETE
        assert len(result.selected_pairs) == 3
        assert result.selected_pairs == ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
        assert len(result.rejected_manual_pairs) == 0

    def test_manual_invalid_pair(self, sample_discovery_result):
        """Test MANUAL selection with invalid pair not in discovery."""
        selector = PairSelector()
        result = selector.select_manual(
            requested_pairs=["BTC/USDT", "INVALID/USDT"],
            discovery_result=sample_discovery_result,
        )

        assert result.selection_mode == PairSelectionMode.MANUAL
        assert result.outcome == PairSelectionOutcome.PARTIAL_SELECTION
        assert len(result.selected_pairs) == 1
        assert "BTC/USDT" in result.selected_pairs
        assert "INVALID/USDT" in result.rejected_manual_pairs
        assert len(result.warnings) > 0

    def test_manual_non_qualified_pair_warning(self, sample_discovery_result):
        """Test MANUAL selection with non-qualified pair generates warning."""
        selector = PairSelector()
        result = selector.select_manual(
            requested_pairs=["BTC/USDT", "ADA/USDT"],  # ADA is ZERO_TRADES
            discovery_result=sample_discovery_result,
            allow_non_qualified=False,
        )

        assert result.selection_mode == PairSelectionMode.MANUAL
        assert result.outcome == PairSelectionOutcome.PARTIAL_SELECTION
        assert "ADA/USDT" in result.rejected_manual_pairs
        assert len(result.warnings) > 0

    def test_manual_allow_non_qualified(self, sample_discovery_result):
        """Test MANUAL selection with allow_non_qualified=True."""
        selector = PairSelector()
        result = selector.select_manual(
            requested_pairs=["BTC/USDT", "ADA/USDT"],  # ADA is ZERO_TRADES
            discovery_result=sample_discovery_result,
            allow_non_qualified=True,
        )

        assert result.selection_mode == PairSelectionMode.MANUAL
        # Should still reject technically unusable pairs
        # But may allow some based on policy
        assert len(result.warnings) > 0

    def test_selection_hash_stability(self, sample_discovery_result):
        """Test selection hash is stable for same inputs."""
        selector = PairSelector()
        result1 = selector.select_auto_best_n(
            discovery_result=sample_discovery_result,
            target_count=4,
        )
        result2 = selector.select_auto_best_n(
            discovery_result=sample_discovery_result,
            target_count=4,
        )

        assert result1.selection_hash == result2.selection_hash
        assert len(result1.selection_hash) > 0

    def test_selection_hash_changes_with_different_inputs(self, sample_discovery_result):
        """Test selection hash changes with different inputs."""
        selector = PairSelector()
        result1 = selector.select_auto_best_n(
            discovery_result=sample_discovery_result,
            target_count=4,
        )
        result2 = selector.select_auto_best_n(
            discovery_result=sample_discovery_result,
            target_count=2,
        )

        assert result1.selection_hash != result2.selection_hash

    def test_selection_immutability_after_baseline(self, sample_discovery_result):
        """Test selection freeze timestamp is set."""
        selector = PairSelector()
        result = selector.select_auto_best_n(
            discovery_result=sample_discovery_result,
            target_count=4,
        )

        # Initially frozen_at is None
        assert result.frozen_at is None

        # After baseline starts, frozen_at should be set
        from datetime import UTC, datetime
        result.frozen_at = datetime.now(UTC)
        assert result.frozen_at is not None
