"""Integration tests for AeRoing4 Pair Discovery (Milestone 2A).

These tests verify the boundary between AeRoing4 and real PairExplorerService
infrastructure without mocking the PairDiscoveryStep class itself.

Tests:
  - PairDiscoveryStep → real PairExplorerService / session boundary
  - Real result parsing into PairDiscoveryResult schema
  - Persisted discovery result reload from AeRoing4 state
  - One failed pair does not fail entire discovery
  - All unusable pairs produce clear terminal result
  - Valid pairs are ranked and persisted
"""

import asyncio
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from backend.services.aeroing4.models import (
    AeRoing4StepStatus,
    PairCandidateStatus,
    PairEvaluationRecord,
)
from backend.services.aeroing4.scoring import RANKING_POLICY_VERSION, get_min_trades
from backend.services.aeroing4.steps.pair_discovery import (
    DEFAULT_DISCOVERY_UNIVERSE,
    PairDiscoveryStep,
)
from backend.services.aeroing4.state_store import AeRoing4StateStore


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_runs_root():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_services():
    """Mock services with minimal interface needed for PairDiscoveryStep."""
    services = Mock()
    settings = Mock()
    settings.user_data_directory_path = "/tmp/test_user_data"
    settings.default_config_file_path = "/tmp/test_config.json"
    settings.freqtrade_executable_path = "freqtrade"
    settings.strategies_directory_path = "/tmp/strategies"
    services.settings_store.load.return_value = settings
    services.data_download_runner = Mock()
    services.pair_selector = Mock()
    services.pair_selector.get_all_pairs.return_value = set()
    return services


def _make_completed_session(pairs: list[str], strategy_name: str, timeframe: str) -> dict:
    """Build a fake completed pair-explorer session."""
    min_trades = get_min_trades(timeframe)
    results = {}
    for pair in pairs:
        results[pair] = {
            "group": pair,
            "pairs": [pair],
            "status": "completed",
            "total_trades": min_trades * 6,
            "total_profit_pct": 8.5,
            "max_drawdown": 12.0,
            "win_rate": 55.0,
            "trades_by_pair": {
                pair: {
                    "total_trades": min_trades * 6,
                    "net_profit": 85.0,
                    "wins": int(min_trades * 6 * 0.55),
                    "win_rate": 55.0,
                    "trades": [
                        {"profit_abs": 1.0} for _ in range(int(min_trades * 6 * 0.55))
                    ] + [
                        {"profit_abs": -0.5} for _ in range(int(min_trades * 6 * 0.45))
                    ],
                }
            },
        }
    return {
        "session_id": "test-session-id",
        "status": "completed",
        "total": len(pairs),
        "completed": len(pairs),
        "results": results,
        "strategy_name": strategy_name,
        "timeframe": timeframe,
        "timerange": "20240101-20240630",
        "created_at": datetime.now(UTC).isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
    }


def _make_failed_pair_session(
    good_pairs: list[str],
    bad_pairs: list[str],
    strategy_name: str,
    timeframe: str,
) -> dict:
    """Build a session where some pairs succeeded and some failed."""
    min_trades = get_min_trades(timeframe)
    results = {}
    for pair in good_pairs:
        results[pair] = {
            "group": pair,
            "pairs": [pair],
            "status": "completed",
            "total_trades": min_trades * 5,
            "total_profit_pct": 7.0,
            "max_drawdown": 10.0,
            "win_rate": 52.0,
            "trades_by_pair": {
                pair: {
                    "total_trades": min_trades * 5,
                    "net_profit": 70.0,
                    "wins": int(min_trades * 5 * 0.52),
                    "win_rate": 52.0,
                    "trades": [{"profit_abs": 0.8}] * int(min_trades * 5),
                }
            },
        }
    for pair in bad_pairs:
        results[pair] = {
            "group": pair,
            "pairs": [pair],
            "status": "failed",
            "error": "Freqtrade exited with code 1",
        }
    return {
        "session_id": "mixed-session-id",
        "status": "completed",
        "total": len(good_pairs) + len(bad_pairs),
        "completed": len(good_pairs) + len(bad_pairs),
        "results": results,
        "strategy_name": strategy_name,
        "timeframe": timeframe,
        "timerange": "20240101-20240630",
        "created_at": datetime.now(UTC).isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
    }


# ── PairDiscoveryStep boundary tests ─────────────────────────────────────────

class TestPairDiscoveryStepBoundary:
    """Integration boundary tests for PairDiscoveryStep with real parsing."""

    @pytest.mark.asyncio
    async def test_valid_pairs_produce_ranked_discovery_result(self, mock_services, tmp_path):
        """Real result parsing: completed session → valid candidates → ranked output."""
        pairs = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
        timeframe = "1h"
        session = _make_completed_session(pairs, "TestStrategy", timeframe)

        mock_services.settings_store.load.return_value.user_data_directory_path = str(tmp_path)

        step = PairDiscoveryStep(mock_services)

        with (
            patch(
                "backend.services.aeroing4.steps.pair_discovery.pair_explorer_api.ensure_data",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "backend.services.aeroing4.steps.pair_discovery.start_pair_explorer_job",
                new=AsyncMock(return_value=("test-session-id", "running")),
            ),
            patch(
                "backend.services.aeroing4.steps.pair_discovery.pair_explorer_api.get_session",
                return_value=session,
            ),
        ):
            result = await step.execute(
                strategy_name="TestStrategy",
                timeframe=timeframe,
                discovery_timerange="20240101-20240630",
                discovery_pairs=pairs,
            )

        assert result.step_name == "pair_discovery"
        assert result.status == AeRoing4StepStatus.PASSED
        assert result.data["outcome"] == "valid_candidates_found"

        dr = result.data["discovery_result"]
        assert dr["universe_size"] == 3
        assert dr["valid_candidates_count"] == 3
        assert dr["rejected_pairs_count"] == 0

        ranked = dr["ranked_pairs"]
        assert len(ranked) == 3
        # Verify ranks are assigned
        ranks = [r["rank"] for r in ranked]
        assert set(ranks) == {1, 2, 3}
        # Verify ranking_policy_version is present
        assert dr["ranking_policy_version"] == RANKING_POLICY_VERSION

    @pytest.mark.asyncio
    async def test_one_failed_pair_does_not_fail_entire_discovery(
        self, mock_services, tmp_path
    ):
        """When one pair fails execution, remaining valid pairs are still ranked."""
        good_pairs = ["BTC/USDT", "ETH/USDT"]
        bad_pairs = ["XRP/USDT"]
        timeframe = "1h"
        session = _make_failed_pair_session(good_pairs, bad_pairs, "TestStrategy", timeframe)

        mock_services.settings_store.load.return_value.user_data_directory_path = str(tmp_path)

        step = PairDiscoveryStep(mock_services)

        with (
            patch(
                "backend.services.aeroing4.steps.pair_discovery.pair_explorer_api.ensure_data",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "backend.services.aeroing4.steps.pair_discovery.start_pair_explorer_job",
                new=AsyncMock(return_value=("mixed-session-id", "running")),
            ),
            patch(
                "backend.services.aeroing4.steps.pair_discovery.pair_explorer_api.get_session",
                return_value=session,
            ),
        ):
            result = await step.execute(
                strategy_name="TestStrategy",
                timeframe=timeframe,
                discovery_timerange="20240101-20240630",
                discovery_pairs=good_pairs + bad_pairs,
            )

        assert result.status == AeRoing4StepStatus.PASSED
        assert result.data["outcome"] in ("valid_candidates_found", "no_pair_candidates")

        dr = result.data["discovery_result"]
        assert dr["universe_size"] == 3

        # Find XRP/USDT in all_evaluations — must be EXECUTION_FAILURE
        all_evals = {e["pair"]: e for e in dr["all_evaluations"]}
        assert "XRP/USDT" in all_evals
        assert all_evals["XRP/USDT"]["status"] == PairCandidateStatus.EXECUTION_FAILURE.value

        # BTC and ETH must be valid candidates
        assert all_evals["BTC/USDT"]["status"] == PairCandidateStatus.VALID_CANDIDATE.value
        assert all_evals["ETH/USDT"]["status"] == PairCandidateStatus.VALID_CANDIDATE.value

    @pytest.mark.asyncio
    async def test_all_unusable_data_produces_clear_failure(self, mock_services, tmp_path):
        """When no pairs have data, step fails with explicit outcome."""
        pairs = ["BTC/USDT", "ETH/USDT"]
        mock_services.settings_store.load.return_value.user_data_directory_path = str(tmp_path)

        step = PairDiscoveryStep(mock_services)

        # All pairs return data errors
        with patch(
            "backend.services.aeroing4.steps.pair_discovery.pair_explorer_api.ensure_data",
            new=AsyncMock(return_value="Data not available"),
        ):
            result = await step.execute(
                strategy_name="TestStrategy",
                timeframe="1h",
                discovery_timerange="20240101-20240630",
                discovery_pairs=pairs,
            )

        assert result.status == AeRoing4StepStatus.FAILED
        assert result.data["outcome"] == "no_usable_data"

        dr = result.data["discovery_result"]
        assert dr["usable_pairs_count"] == 0
        all_statuses = [e["status"] for e in dr["all_evaluations"]]
        assert all(s == PairCandidateStatus.DATA_UNAVAILABLE.value for s in all_statuses)

    @pytest.mark.asyncio
    async def test_zero_trade_pairs_classified_as_zero_trades(
        self, mock_services, tmp_path
    ):
        """Pairs with zero trades must be classified as ZERO_TRADES, not VALID_CANDIDATE."""
        timeframe = "1h"
        pairs = ["BTC/USDT"]
        zero_session = {
            "session_id": "zero-session",
            "status": "completed",
            "total": 1,
            "completed": 1,
            "results": {
                "BTC/USDT": {
                    "group": "BTC/USDT",
                    "pairs": ["BTC/USDT"],
                    "status": "completed",
                    "total_trades": 0,
                    "total_profit_pct": 0.0,
                    "max_drawdown": 0.0,
                    "win_rate": 0.0,
                    "trades_by_pair": {},
                }
            },
        }

        mock_services.settings_store.load.return_value.user_data_directory_path = str(tmp_path)
        step = PairDiscoveryStep(mock_services)

        with (
            patch(
                "backend.services.aeroing4.steps.pair_discovery.pair_explorer_api.ensure_data",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "backend.services.aeroing4.steps.pair_discovery.start_pair_explorer_job",
                new=AsyncMock(return_value=("zero-session", "running")),
            ),
            patch(
                "backend.services.aeroing4.steps.pair_discovery.pair_explorer_api.get_session",
                return_value=zero_session,
            ),
        ):
            result = await step.execute(
                strategy_name="TestStrategy",
                timeframe=timeframe,
                discovery_timerange="20240101-20240630",
                discovery_pairs=pairs,
            )

        assert result.status == AeRoing4StepStatus.PASSED
        assert result.data["outcome"] == "no_pair_candidates"
        dr = result.data["discovery_result"]
        evals = {e["pair"]: e for e in dr["all_evaluations"]}
        assert evals["BTC/USDT"]["status"] == PairCandidateStatus.ZERO_TRADES.value

    @pytest.mark.asyncio
    async def test_insufficient_trades_classified_correctly(
        self, mock_services, tmp_path
    ):
        """Pairs with trades below minimum threshold → INSUFFICIENT_TRADES."""
        timeframe = "1h"
        min_t = get_min_trades(timeframe)
        pairs = ["BTC/USDT"]

        low_session = {
            "session_id": "low-session",
            "status": "completed",
            "total": 1,
            "completed": 1,
            "results": {
                "BTC/USDT": {
                    "group": "BTC/USDT",
                    "pairs": ["BTC/USDT"],
                    "status": "completed",
                    "total_trades": min_t - 1,  # just below threshold
                    "total_profit_pct": 5.0,
                    "max_drawdown": 8.0,
                    "win_rate": 55.0,
                    "trades_by_pair": {
                        "BTC/USDT": {
                            "total_trades": min_t - 1,
                            "net_profit": 50.0,
                            "wins": 3,
                            "win_rate": 60.0,
                            "trades": [],
                        }
                    },
                }
            },
        }

        mock_services.settings_store.load.return_value.user_data_directory_path = str(tmp_path)
        step = PairDiscoveryStep(mock_services)

        with (
            patch(
                "backend.services.aeroing4.steps.pair_discovery.pair_explorer_api.ensure_data",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "backend.services.aeroing4.steps.pair_discovery.start_pair_explorer_job",
                new=AsyncMock(return_value=("low-session", "running")),
            ),
            patch(
                "backend.services.aeroing4.steps.pair_discovery.pair_explorer_api.get_session",
                return_value=low_session,
            ),
        ):
            result = await step.execute(
                strategy_name="TestStrategy",
                timeframe=timeframe,
                discovery_timerange="20240101-20240630",
                discovery_pairs=pairs,
            )

        dr = result.data["discovery_result"]
        evals = {e["pair"]: e for e in dr["all_evaluations"]}
        assert evals["BTC/USDT"]["status"] == PairCandidateStatus.INSUFFICIENT_TRADES.value
        reasons = evals["BTC/USDT"]["rejection_reasons"]
        assert any(str(min_t) in r for r in reasons), (
            f"rejection reason should mention threshold {min_t}: {reasons}"
        )

    @pytest.mark.asyncio
    async def test_valid_pairs_are_ranked_with_evidence_preserved(
        self, mock_services, tmp_path
    ):
        """Each valid pair must retain full evidence in the ranked output."""
        pairs = ["BTC/USDT", "ETH/USDT"]
        timeframe = "1h"
        session = _make_completed_session(pairs, "TestStrategy", timeframe)

        mock_services.settings_store.load.return_value.user_data_directory_path = str(tmp_path)
        step = PairDiscoveryStep(mock_services)

        with (
            patch(
                "backend.services.aeroing4.steps.pair_discovery.pair_explorer_api.ensure_data",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "backend.services.aeroing4.steps.pair_discovery.start_pair_explorer_job",
                new=AsyncMock(return_value=("test-session-id", "running")),
            ),
            patch(
                "backend.services.aeroing4.steps.pair_discovery.pair_explorer_api.get_session",
                return_value=session,
            ),
        ):
            result = await step.execute(
                strategy_name="TestStrategy",
                timeframe=timeframe,
                discovery_timerange="20240101-20240630",
                discovery_pairs=pairs,
            )

        dr = result.data["discovery_result"]
        for ranked_pair in dr["ranked_pairs"]:
            # Every valid candidate must have real evidence fields
            assert ranked_pair["total_trades"] > 0
            assert ranked_pair["rank"] is not None
            assert ranked_pair["rank_score"] is not None
            assert ranked_pair["status"] == PairCandidateStatus.VALID_CANDIDATE.value
            # metrics_available must be present (explicit — not assumed)
            assert "metrics_available" in ranked_pair


# ── State persistence tests ───────────────────────────────────────────────────

class TestDiscoveryResultPersistence:
    """Tests that discovery results survive state serialise/deserialise."""

    def test_pair_evaluation_record_serialises_cleanly(self):
        """PairEvaluationRecord with all fields serialises to dict and back."""
        record = PairEvaluationRecord(
            pair="ETH/USDT",
            status=PairCandidateStatus.VALID_CANDIDATE,
            total_trades=120,
            net_profit_pct=9.5,
            profit_factor=1.45,
            expectancy=0.002,
            max_drawdown_pct=11.0,
            win_rate=54.0,
            rank=1,
            rank_score=38.5,
            score_components={"pf_score": 15.75, "np_score": 7.92},
            explorer_session_id="test-session",
            metrics_available={
                "profit_factor": True,
                "net_profit_pct": True,
                "expectancy": True,
                "max_drawdown_pct": True,
            },
        )
        dumped = record.model_dump()
        restored = PairEvaluationRecord.model_validate(dumped)
        assert restored.pair == record.pair
        assert restored.rank_score == record.rank_score
        assert restored.metrics_available == record.metrics_available

    def test_null_metrics_survive_round_trip(self):
        """Null metrics must remain null, not become zero after serialisation."""
        record = PairEvaluationRecord(
            pair="XRP/USDT",
            status=PairCandidateStatus.VALID_CANDIDATE,
            total_trades=50,
            net_profit_pct=None,  # explicitly null
            profit_factor=None,
            expectancy=None,
            max_drawdown_pct=None,
            rank=2,
            rank_score=12.0,
        )
        dumped = record.model_dump()
        restored = PairEvaluationRecord.model_validate(dumped)
        assert restored.net_profit_pct is None
        assert restored.profit_factor is None
        assert restored.expectancy is None
        assert restored.max_drawdown_pct is None

    def test_step_result_with_discovery_data_saves_and_reloads(self, temp_runs_root):
        """Full run state including discovery result round-trips through AeRoing4StateStore."""
        from backend.services.aeroing4.models import (
            PairDiscoveryResult,
            StepResult,
        )

        store = AeRoing4StateStore(temp_runs_root)
        run = store.create_run(
            strategy_name="TestStrategy",
            enable_pair_discovery=True,
            discovery_timerange="20240101-20240630",
        )

        # Build a fake discovery result
        ranked = [
            PairEvaluationRecord(
                pair="BTC/USDT",
                status=PairCandidateStatus.VALID_CANDIDATE,
                total_trades=100,
                net_profit_pct=10.0,
                rank=1,
                rank_score=55.0,
                explorer_session_id="sess-123",
            )
        ]
        dr = PairDiscoveryResult(
            universe_size=5,
            usable_pairs_count=4,
            evaluated_pairs_count=4,
            valid_candidates_count=1,
            rejected_pairs_count=3,
            ranked_pairs=ranked,
            all_evaluations=ranked,
            discovery_pairs_requested=["BTC/USDT", "ETH/USDT"],
            discovery_timerange="20240101-20240630",
            timeframe="1h",
            strategy_name="TestStrategy",
            ranking_policy_version=RANKING_POLICY_VERSION,
        )

        from backend.services.aeroing4.models import AeRoing4StepStatus
        step_result = StepResult(
            step_name="pair_discovery",
            status=AeRoing4StepStatus.PASSED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            data={"outcome": "valid_candidates_found", "discovery_result": dr.model_dump()},
        )

        run.update_step("pair_discovery", step_result)
        store.save_run(run)

        # Reload and verify
        reloaded = store.load_run(run.run_id)
        assert reloaded is not None
        assert "pair_discovery" in reloaded.steps

        disc_data = reloaded.steps["pair_discovery"].data
        assert disc_data["outcome"] == "valid_candidates_found"
        dr_reloaded = disc_data["discovery_result"]
        assert dr_reloaded["ranking_policy_version"] == RANKING_POLICY_VERSION
        assert len(dr_reloaded["ranked_pairs"]) == 1
        assert dr_reloaded["ranked_pairs"][0]["pair"] == "BTC/USDT"
        assert dr_reloaded["ranked_pairs"][0]["rank_score"] == 55.0
        assert dr_reloaded["ranked_pairs"][0]["net_profit_pct"] == 10.0


# ── Discovery universe tests ──────────────────────────────────────────────────

class TestDiscoveryUniverse:
    """Tests for universe resolution logic."""

    def test_explicit_discovery_pairs_are_used_verbatim(
        self, mock_services, tmp_path
    ):
        """When discovery_pairs is provided, it must be the exact universe."""
        step = PairDiscoveryStep(mock_services)
        explicit = ["BTC/USDT", "ETH/USDT"]
        universe = step._resolve_universe(explicit)
        assert universe == ["BTC/USDT", "ETH/USDT"]

    def test_none_discovery_pairs_falls_back_to_default(
        self, mock_services, tmp_path
    ):
        """When discovery_pairs is None and pair_selector is empty, use default universe."""
        mock_services.pair_selector.get_all_pairs.return_value = set()
        step = PairDiscoveryStep(mock_services)
        universe = step._resolve_universe(None)
        assert universe == list(DEFAULT_DISCOVERY_UNIVERSE)

    def test_empty_discovery_pairs_falls_back_to_default(
        self, mock_services, tmp_path
    ):
        """Empty list is treated the same as None."""
        mock_services.pair_selector.get_all_pairs.return_value = set()
        step = PairDiscoveryStep(mock_services)
        universe = step._resolve_universe([])
        assert universe == list(DEFAULT_DISCOVERY_UNIVERSE)

    def test_pair_selector_universe_used_when_available(self, mock_services, tmp_path):
        """When pair_selector has pairs, use those (capped at 25)."""
        selector_pairs = {f"PAIR{i}/USDT" for i in range(30)}
        mock_services.pair_selector.get_all_pairs.return_value = selector_pairs
        step = PairDiscoveryStep(mock_services)
        universe = step._resolve_universe(None)
        assert len(universe) <= 25
        assert all(p.endswith("/USDT") for p in universe)

    def test_default_universe_has_at_most_25_pairs(self, mock_services):
        assert len(DEFAULT_DISCOVERY_UNIVERSE) <= 25

    def test_default_universe_has_liquid_major_pairs(self, mock_services):
        assert "BTC/USDT" in DEFAULT_DISCOVERY_UNIVERSE
        assert "ETH/USDT" in DEFAULT_DISCOVERY_UNIVERSE
