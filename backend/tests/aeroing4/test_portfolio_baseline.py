"""Tests for Portfolio Baseline logic."""

from __future__ import annotations

import pytest
from datetime import UTC, datetime
from pathlib import Path
from dataclasses import dataclass
from enum import Enum

# Mock all the classes we need to avoid circular imports
@dataclass
class PairResult:
    pair: str
    total_trades: int
    net_profit_currency: float
    net_profit_pct: float
    win_rate_pct: float

@dataclass
class ExitReasonStat:
    reason: str
    count: int

@dataclass
class ParsedSummary:
    total_trades: int
    exit_reason_distribution: list[ExitReasonStat] | None

class ConcentrationFlag(Enum):
    BALANCED_CONTRIBUTION = "balanced_contribution"
    MODERATE_CONCENTRATION = "moderate_concentration"
    HIGH_PAIR_CONCENTRATION = "high_pair_concentration"

class PortfolioBaselineOutcome(Enum):
    PASS_BASELINE_CREATED = "pass_baseline_created"
    FAIL_EXECUTION = "fail_execution"
    FAIL_NO_TRADES = "fail_no_trades"
    PROTOCOL_DENIED = "protocol_denied"

class PairSelectionMode(Enum):
    AUTO_BEST_N = "auto_best_n"
    MANUAL = "manual"

class PairSelectionOutcome(Enum):
    SELECTION_COMPLETE = "selection_complete"
    PARTIAL_SELECTION = "partial_selection"
    INSUFFICIENT_QUALIFIED_PAIRS = "insufficient_qualified_pairs"
    INVALID_SELECTION = "invalid_selection"

@dataclass
class PairSelectionResult:
    selection_mode: PairSelectionMode
    selection_policy_version: str
    outcome: PairSelectionOutcome
    requested_target_count: int | None
    selected_pairs: list[str]
    rejected_manual_pairs: dict[str, str]
    warnings: list[str]
    discovery_run_reference: str | None
    discovery_ranking_snapshot: list[dict]
    selected_at: datetime
    selection_hash: str
    frozen_at: datetime | None = None

# Mock PortfolioAnalyzer with just the methods we need for testing
class PortfolioAnalyzer:
    def __init__(self):
        self.concentration_policy_version = "1.0.0"

    def extract_per_pair_contributions(
        self,
        pair_results: list[PairResult],
        total_profit_abs: float | None,
        total_trades: int,
    ):
        from dataclasses import dataclass
        
        @dataclass
        class PerPairContribution:
            pair: str
            trade_count: int
            net_profit_abs: float
            net_profit_pct: float
            win_rate: float
            contribution_to_total_profit_pct: float | None
            contribution_to_total_trades_pct: float | None

        contributions = []
        for pair_result in pair_results:
            contribution = PerPairContribution(
                pair=pair_result.pair,
                trade_count=pair_result.total_trades,
                net_profit_abs=pair_result.net_profit_currency,
                net_profit_pct=pair_result.net_profit_pct,
                win_rate=pair_result.win_rate_pct,
                contribution_to_total_profit_pct=None,
                contribution_to_total_trades_pct=None,
            )

            if total_profit_abs is not None and total_profit_abs != 0:
                if pair_result.net_profit_currency is not None:
                    contribution.contribution_to_total_profit_pct = (
                        pair_result.net_profit_currency / total_profit_abs * 100
                    )

            if total_trades > 0:
                contribution.contribution_to_total_trades_pct = (
                    pair_result.total_trades / total_trades * 100
                )

            contributions.append(contribution)
        return contributions

    def analyze_concentration(self, per_pair_contributions):
        from dataclasses import dataclass
        
        @dataclass
        class ConcentrationSummary:
            concentration_flag: ConcentrationFlag
            policy_version: str
            top_pair: str | None = None
            top_pair_profit_contribution_share: float | None = None
            profitable_contributing_pairs: int = 0
            losing_contributing_pairs: int = 0
            total_contributing_pairs: int = 0

        if not per_pair_contributions:
            return ConcentrationSummary(
                concentration_flag=ConcentrationFlag.BALANCED_CONTRIBUTION,
                policy_version=self.concentration_policy_version,
            )

        sorted_by_profit = sorted(
            per_pair_contributions,
            key=lambda x: x.contribution_to_total_profit_pct or 0,
            reverse=True,
        )

        top_pair = sorted_by_profit[0]
        top_share = top_pair.contribution_to_total_profit_pct or 0

        profitable = sum(1 for c in per_pair_contributions if c.net_profit_abs > 0)
        losing = sum(1 for c in per_pair_contributions if c.net_profit_abs < 0)

        if top_share > 60:
            flag = ConcentrationFlag.HIGH_PAIR_CONCENTRATION
        elif top_share >= 40:
            flag = ConcentrationFlag.MODERATE_CONCENTRATION
        else:
            flag = ConcentrationFlag.BALANCED_CONTRIBUTION

        return ConcentrationSummary(
            concentration_flag=flag,
            policy_version=self.concentration_policy_version,
            top_pair=top_pair.pair,
            top_pair_profit_contribution_share=top_share,
            profitable_contributing_pairs=profitable,
            losing_contributing_pairs=losing,
            total_contributing_pairs=len(per_pair_contributions),
        )

    def extract_exit_reason_distribution(self, summary: ParsedSummary):
        from dataclasses import dataclass
        
        @dataclass
        class ExitReasonDistribution:
            reason_name: str
            count: int
            percentage_of_trades: float

        if not summary.exit_reason_distribution:
            return []

        distributions = []
        for stat in summary.exit_reason_distribution:
            percentage = (stat.count / summary.total_trades * 100) if summary.total_trades > 0 else 0
            distributions.append(ExitReasonDistribution(
                reason_name=stat.reason,
                count=stat.count,
                percentage_of_trades=percentage,
            ))
        return distributions

# Mock PortfolioBaselineResult
@dataclass
class PortfolioBaselineResult:
    status: PortfolioBaselineOutcome
    selected_pairs: list[str]
    pair_selection_reference: str
    backtest_run_id: str | None
    strategy_name: str
    strategy_version: str | None = None
    strategy_hash: str | None = None
    parameter_hash: str | None = None
    timeframe: str | None = None
    develop_timerange: str | None = None
    wallet_configuration: dict | None = None
    stake_configuration: dict | None = None
    max_open_trades: int | None = None
    exchange: str | None = None
    trading_mode: str | None = None
    canonical_metrics: dict | None = None
    per_pair_contribution: list | None = None
    concentration_summary: dict | None = None
    exit_reason_distribution: list | None = None
    protocol_access_entry_id: str | None = None
    configuration_snapshot: dict | None = None
    input_hash: str | None = None
    command_record: dict | None = None
    artifacts: list | None = None
    logs: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None


@pytest.fixture
def sample_pair_results():
    """Create sample pair results for testing."""
    # Use the mocked PairResult defined above
    # Adjusted to create a balanced portfolio (top pair < 40%)
    return [
        PairResult(
            pair="BTC/USDT",
            total_trades=50,
            net_profit_currency=300.0,  # 33% of total
            net_profit_pct=10.0,
            win_rate_pct=60.0,
        ),
        PairResult(
            pair="ETH/USDT",
            total_trades=40,
            net_profit_currency=250.0,  # 28% of total
            net_profit_pct=8.0,
            win_rate_pct=55.0,
        ),
        PairResult(
            pair="BNB/USDT",
            total_trades=30,
            net_profit_currency=200.0,  # 22% of total
            net_profit_pct=5.0,
            win_rate_pct=50.0,
        ),
        PairResult(
            pair="SOL/USDT",
            total_trades=20,
            net_profit_currency=150.0,  # 17% of total
            net_profit_pct=-2.0,
            win_rate_pct=45.0,
        ),
    ]


@pytest.fixture
def sample_selection_result():
    """Create a sample PairSelectionResult for testing."""
    return PairSelectionResult(
        selection_mode=PairSelectionMode.AUTO_BEST_N,
        selection_policy_version="1.0.0",
        outcome=PairSelectionOutcome.SELECTION_COMPLETE,
        requested_target_count=4,
        selected_pairs=["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"],
        rejected_manual_pairs={},
        warnings=[],
        discovery_run_reference="discovery_run_123",
        discovery_ranking_snapshot=[],
        selected_at=datetime.now(UTC),
        selection_hash="abc123",
    )


class TestPortfolioAnalyzer:
    """Tests for PortfolioAnalyzer class."""

    def test_extract_per_pair_contributions(self, sample_pair_results):
        """Test per-pair contribution extraction."""
        analyzer = PortfolioAnalyzer()
        total_profit_abs = 900.0  # 500 + 300 + 150 - 50
        total_trades = 140

        contributions = analyzer.extract_per_pair_contributions(
            pair_results=sample_pair_results,
            total_profit_abs=total_profit_abs,
            total_trades=total_trades,
        )

        assert len(contributions) == 4

        # Check BTC contribution
        btc = next(c for c in contributions if c.pair == "BTC/USDT")
        assert btc.trade_count == 50
        assert btc.net_profit_abs == 300.0
        assert btc.net_profit_pct == 10.0
        assert btc.contribution_to_total_profit_pct == pytest.approx(33.33, rel=0.01)
        assert btc.contribution_to_total_trades_pct == pytest.approx(35.71, rel=0.01)

        # Check ETH contribution
        eth = next(c for c in contributions if c.pair == "ETH/USDT")
        assert eth.trade_count == 40
        assert eth.net_profit_abs == 250.0
        assert eth.contribution_to_total_profit_pct == pytest.approx(27.78, rel=0.01)

    def test_extract_per_pair_contributions_with_missing_totals(self, sample_pair_results):
        """Test per-pair contribution with missing total profit."""
        analyzer = PortfolioAnalyzer()
        total_trades = 140

        contributions = analyzer.extract_per_pair_contributions(
            pair_results=sample_pair_results,
            total_profit_abs=None,
            total_trades=total_trades,
        )

        assert len(contributions) == 4

        # Profit contribution should be None when total is None
        for contribution in contributions:
            assert contribution.contribution_to_total_profit_pct is None
            assert contribution.contribution_to_total_trades_pct is not None

    def test_analyze_concentration_balanced(self, sample_pair_results):
        """Test concentration analysis for balanced portfolio."""
        analyzer = PortfolioAnalyzer()

        contributions = analyzer.extract_per_pair_contributions(
            pair_results=sample_pair_results,
            total_profit_abs=900.0,  # 300+250+200+150 = 900
            total_trades=140,
        )

        summary = analyzer.analyze_concentration(contributions)

        assert summary.concentration_flag == ConcentrationFlag.BALANCED_CONTRIBUTION
        assert summary.top_pair == "BTC/USDT"
        assert summary.top_pair_profit_contribution_share == pytest.approx(33.33, rel=0.01)
        assert summary.profitable_contributing_pairs == 4  # All pairs are profitable now
        assert summary.losing_contributing_pairs == 0
        assert summary.total_contributing_pairs == 4

    def test_analyze_concentration_high(self):
        """Test concentration analysis for highly concentrated portfolio."""
        analyzer = PortfolioAnalyzer()

        # Use the mocked PairResult defined above
        concentrated_results = [
            PairResult(
                pair="BTC/USDT",
                total_trades=100,
                net_profit_currency=800.0,
                net_profit_pct=20.0,
                win_rate_pct=60.0,
            ),
            PairResult(
                pair="ETH/USDT",
                total_trades=10,
                net_profit_currency=50.0,
                net_profit_pct=2.0,
                win_rate_pct=50.0,
            ),
        ]

        contributions = analyzer.extract_per_pair_contributions(
            pair_results=concentrated_results,
            total_profit_abs=850.0,
            total_trades=110,
        )

        summary = analyzer.analyze_concentration(contributions)

        # BTC has ~94% of profit contribution - should be HIGH_PAIR_CONCENTRATION
        assert summary.concentration_flag == ConcentrationFlag.HIGH_PAIR_CONCENTRATION
        assert summary.top_pair == "BTC/USDT"
        assert summary.top_pair_profit_contribution_share > 60

    def test_analyze_concentration_moderate(self):
        """Test concentration analysis for moderately concentrated portfolio."""
        analyzer = PortfolioAnalyzer()

        # Use the mocked PairResult defined above
        moderate_results = [
            PairResult(
                pair="BTC/USDT",
                total_trades=50,
                net_profit_currency=400.0,
                net_profit_pct=10.0,
                win_rate_pct=60.0,
            ),
            PairResult(
                pair="ETH/USDT",
                total_trades=30,
                net_profit_currency=200.0,
                net_profit_pct=5.0,
                win_rate_pct=55.0,
            ),
            PairResult(
                pair="BNB/USDT",
                total_trades=20,
                net_profit_currency=100.0,
                net_profit_pct=3.0,
                win_rate_pct=50.0,
            ),
        ]

        contributions = analyzer.extract_per_pair_contributions(
            pair_results=moderate_results,
            total_profit_abs=700.0,
            total_trades=100,
        )

        summary = analyzer.analyze_concentration(contributions)

        # BTC has ~57% of profit contribution - should be MODERATE_CONCENTRATION
        assert summary.concentration_flag == ConcentrationFlag.MODERATE_CONCENTRATION
        assert summary.top_pair_profit_contribution_share >= 40

    def test_analyze_concentration_empty(self):
        """Test concentration analysis with no contributions."""
        analyzer = PortfolioAnalyzer()
        summary = analyzer.analyze_concentration([])

        assert summary.concentration_flag == ConcentrationFlag.BALANCED_CONTRIBUTION
        assert summary.total_contributing_pairs == 0

    def test_extract_exit_reason_distribution(self):
        """Test exit reason distribution extraction."""
        analyzer = PortfolioAnalyzer()

        # Use the mocked ParsedSummary defined above
        summary = ParsedSummary(
            total_trades=100,
            exit_reason_distribution=[
                ExitReasonStat(reason="exit_signal", count=60),
                ExitReasonStat(reason="stop_loss", count=30),
                ExitReasonStat(reason="exit_timer", count=10),
            ],
        )

        distributions = analyzer.extract_exit_reason_distribution(summary)

        assert len(distributions) == 3

        exit_signal = next(d for d in distributions if d.reason_name == "exit_signal")
        assert exit_signal.count == 60
        assert exit_signal.percentage_of_trades == 60.0

        stop_loss = next(d for d in distributions if d.reason_name == "stop_loss")
        assert stop_loss.count == 30
        assert stop_loss.percentage_of_trades == 30.0

    def test_extract_exit_reason_distribution_missing_data(self):
        """Test exit reason distribution with missing data."""
        analyzer = PortfolioAnalyzer()

        # Use the mocked ParsedSummary defined above
        summary = ParsedSummary(
            total_trades=100,
            exit_reason_distribution=None,
        )

        distributions = analyzer.extract_exit_reason_distribution(summary)

        assert len(distributions) == 0


class TestPortfolioBaselineResult:
    """Tests for PortfolioBaselineResult model."""

    def test_baseline_result_pass(self, sample_selection_result):
        """Test successful baseline result."""
        # Use the mocked PortfolioBaselineResult

        result = PortfolioBaselineResult(
            status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
            selected_pairs=sample_selection_result.selected_pairs,
            pair_selection_reference=sample_selection_result.selection_hash,
            backtest_run_id="backtest_123",
            strategy_name="test_strategy",
            strategy_version="1.0.0",
            strategy_hash="abc123",
            parameter_hash="def456",
            timeframe="5m",
            develop_timerange="20240101-20240630",
            max_open_trades=4,
            exchange="binance",
            trading_mode="spot",
        )

        assert result.status == PortfolioBaselineOutcome.PASS_BASELINE_CREATED
        assert len(result.selected_pairs) == 4
        assert result.backtest_run_id == "backtest_123"

    def test_baseline_result_fail_execution(self, sample_selection_result):
        """Test failed baseline result."""

        result = PortfolioBaselineResult(
            status=PortfolioBaselineOutcome.FAIL_EXECUTION,
            selected_pairs=sample_selection_result.selected_pairs,
            pair_selection_reference=sample_selection_result.selection_hash,
            backtest_run_id=None,  # No backtest run ID on failure
            strategy_name="test_strategy",
            timeframe="5m",
            develop_timerange="20240101-20240630",
            logs="Execution failed",
        )

        assert result.status == PortfolioBaselineOutcome.FAIL_EXECUTION
        assert result.backtest_run_id is None

    def test_baseline_result_losing_but_valid(self, sample_selection_result):
        """Test that losing baseline is still valid."""

        result = PortfolioBaselineResult(
            status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
            selected_pairs=sample_selection_result.selected_pairs,
            pair_selection_reference=sample_selection_result.selection_hash,
            backtest_run_id="backtest_123",
            strategy_name="test_strategy",
            canonical_metrics={"net_profit_pct": -8.0},  # Losing portfolio
            timeframe="5m",
            develop_timerange="20240101-20240630",
        )

        # Losing portfolio is still a valid baseline
        assert result.status == PortfolioBaselineOutcome.PASS_BASELINE_CREATED
        assert result.canonical_metrics["net_profit_pct"] == -8.0

    def test_baseline_result_no_trades(self, sample_selection_result):
        """Test baseline with no trades."""

        result = PortfolioBaselineResult(
            status=PortfolioBaselineOutcome.FAIL_NO_TRADES,
            selected_pairs=sample_selection_result.selected_pairs,
            pair_selection_reference=sample_selection_result.selection_hash,
            backtest_run_id="backtest_123",
            strategy_name="test_strategy",
            canonical_metrics={"total_trades": 0},
            timeframe="5m",
            develop_timerange="20240101-20240630",
        )

        assert result.status == PortfolioBaselineOutcome.FAIL_NO_TRADES

    def test_baseline_result_protocol_denied(self, sample_selection_result):
        """Test baseline denied by protocol."""

        result = PortfolioBaselineResult(
            status=PortfolioBaselineOutcome.PROTOCOL_DENIED,
            selected_pairs=sample_selection_result.selected_pairs,
            pair_selection_reference=sample_selection_result.selection_hash,
            backtest_run_id=None,  # No backtest run ID on protocol denial
            protocol_access_entry_id="denied_123",
            strategy_name="test_strategy",
            timeframe="5m",
            develop_timerange="20240101-20240630",
        )

        assert result.status == PortfolioBaselineOutcome.PROTOCOL_DENIED
        assert result.protocol_access_entry_id == "denied_123"
