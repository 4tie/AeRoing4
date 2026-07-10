"""Regression tests: Pair Discovery ranking must not change after migrating
profit_factor/expectancy to the canonical Metrics SSOT (Prompt 2 §9).

These fixtures encode the exact pre-migration formulas
(`PairDiscoveryStep._compute_profit_factor` / `_compute_expectancy`, as they
existed before this milestone) as hardcoded "golden" expected values, and
assert the new canonical-metrics-backed code path in
`PairDiscoveryStep._scoring_expectancy` + `metrics.adapters.from_pair_discovery_group`
reproduces them exactly, then confirms `scoring.score_pair()` output
(rank_score, components) is unchanged for the same evidence.
"""

from backend.services.aeroing4.metrics.adapters import from_pair_discovery_group
from backend.services.aeroing4.scoring import PairScoreInputs, score_pair
from backend.services.aeroing4.steps.pair_discovery import PairDiscoveryStep


def _legacy_profit_factor(pair_data: dict) -> float | None:
    """Exact pre-migration formula, kept here only as a golden baseline."""
    trades = pair_data.get("trades", []) if pair_data else []
    if not trades:
        return None
    gross_profit = sum(
        float(t.get("profit_abs", 0) or 0) for t in trades if float(t.get("profit_abs", 0) or 0) > 0
    )
    gross_loss = abs(
        sum(float(t.get("profit_abs", 0) or 0) for t in trades if float(t.get("profit_abs", 0) or 0) < 0)
    )
    if gross_loss == 0:
        return None if gross_profit == 0 else 999.0
    return round(gross_profit / gross_loss, 4)


def _legacy_expectancy(pair_data: dict, total_trades: int) -> float | None:
    """Exact pre-migration formula, kept here only as a golden baseline."""
    trades = pair_data.get("trades", []) if pair_data else []
    if not trades or total_trades == 0:
        return None
    total_profit = sum(float(t.get("profit_abs", 0) or 0) for t in trades)
    return round(total_profit / total_trades / 1000.0, 6)


FIXTURES = [
    {  # normal mixed win/loss pair
        "trades": [
            {"profit_abs": 12.5}, {"profit_abs": -4.0}, {"profit_abs": 8.0},
            {"profit_abs": -2.5}, {"profit_abs": 15.0}, {"profit_abs": -6.0},
        ],
    },
    {  # all winning trades -> profit factor sentinel
        "trades": [{"profit_abs": 5.0}, {"profit_abs": 3.0}, {"profit_abs": 7.0}],
    },
    {  # all losing trades
        "trades": [{"profit_abs": -5.0}, {"profit_abs": -3.0}],
    },
    {  # single trade
        "trades": [{"profit_abs": 9.0}],
    },
]


class TestMetricSourceSwapPreservesValues:
    def test_profit_factor_matches_legacy_formula(self):
        step = PairDiscoveryStep.__new__(PairDiscoveryStep)
        for pair_data in FIXTURES:
            legacy = _legacy_profit_factor(pair_data)
            snapshot = from_pair_discovery_group(pair_data, pair="TEST/USDT")
            new_value = (
                snapshot.profit_factor.value
                if snapshot.profit_factor.availability.value == "available"
                else None
            )
            assert new_value == legacy, f"profit_factor mismatch for {pair_data}"

    def test_expectancy_matches_legacy_formula(self):
        step = PairDiscoveryStep.__new__(PairDiscoveryStep)
        for pair_data in FIXTURES:
            total_trades = len(pair_data["trades"])
            legacy = _legacy_expectancy(pair_data, total_trades)
            snapshot = from_pair_discovery_group(pair_data, pair="TEST/USDT")
            new_value = step._scoring_expectancy(snapshot, total_trades)
            assert new_value == legacy, f"expectancy mismatch for {pair_data}"


class TestRankingScoreUnchanged:
    """End-to-end: same evidence -> same score_pair() output, via the new
    canonical-metrics code path."""

    def test_rank_score_and_components_stable(self):
        step = PairDiscoveryStep.__new__(PairDiscoveryStep)
        for i, pair_data in enumerate(FIXTURES):
            total_trades = len(pair_data["trades"])
            snapshot = from_pair_discovery_group(pair_data, pair=f"PAIR{i}/USDT")
            profit_factor = (
                snapshot.profit_factor.value
                if snapshot.profit_factor.availability.value == "available"
                else None
            )
            expectancy = step._scoring_expectancy(snapshot, total_trades)

            legacy_pf = _legacy_profit_factor(pair_data)
            legacy_exp = _legacy_expectancy(pair_data, total_trades)

            new_result = score_pair(
                PairScoreInputs(
                    pair=f"PAIR{i}/USDT",
                    total_trades=total_trades,
                    timeframe="1h",
                    profit_factor=profit_factor,
                    net_profit_pct=10.0,
                    expectancy=expectancy,
                    max_drawdown_pct=5.0,
                )
            )
            legacy_result = score_pair(
                PairScoreInputs(
                    pair=f"PAIR{i}/USDT",
                    total_trades=total_trades,
                    timeframe="1h",
                    profit_factor=legacy_pf,
                    net_profit_pct=10.0,
                    expectancy=legacy_exp,
                    max_drawdown_pct=5.0,
                )
            )
            assert new_result.rank_score == legacy_result.rank_score
            assert new_result.components == legacy_result.components
            assert new_result.metrics_available == legacy_result.metrics_available
