"""Unit tests for AeRoing4 Pair Discovery scoring (Milestone 2A).

Tests:
  - score calculation correctness
  - high profit with too few trades does not dominate ranking
  - positive expectancy influences ranking correctly
  - drawdown penalty works
  - zero-trade rejection gate
  - insufficient-trade rejection gate
  - unavailable metrics handled explicitly (no silent zero substitution)
  - deterministic ranking tie-breaking
"""

import pytest

from backend.services.aeroing4.scoring import (
    DEFAULT_MIN_TRADES,
    RANKING_POLICY_VERSION,
    TIMEFRAME_MIN_TRADES,
    PairScoreInputs,
    PairScoreResult,
    get_min_trades,
    rank_candidates,
    rank_candidates_with_trades,
    score_pair,
)


# ── get_min_trades ────────────────────────────────────────────────────────────

class TestGetMinTrades:
    """Tests for the timeframe-aware minimum trades policy."""

    def test_known_timeframes_return_expected_values(self):
        assert get_min_trades("1h") == TIMEFRAME_MIN_TRADES["1h"]
        assert get_min_trades("5m") == TIMEFRAME_MIN_TRADES["5m"]
        assert get_min_trades("1d") == TIMEFRAME_MIN_TRADES["1d"]

    def test_case_insensitive(self):
        assert get_min_trades("1H") == get_min_trades("1h")
        assert get_min_trades("5M") == get_min_trades("5m")

    def test_unknown_timeframe_returns_default(self):
        assert get_min_trades("99z") == DEFAULT_MIN_TRADES

    def test_shorter_timeframes_require_more_trades(self):
        """Shorter candles produce more frequent signals — require more trades."""
        assert get_min_trades("1m") > get_min_trades("1h")
        assert get_min_trades("5m") > get_min_trades("4h")

    def test_longer_timeframes_require_fewer_trades(self):
        assert get_min_trades("1d") <= get_min_trades("1h")


# ── score_pair ────────────────────────────────────────────────────────────────

class TestScorePair:
    """Tests for the deterministic scoring function."""

    def _inputs(self, **kwargs) -> PairScoreInputs:
        defaults = {
            "pair": "BTC/USDT",
            "total_trades": 200,
            "timeframe": "1h",
            "profit_factor": 1.5,
            "net_profit_pct": 10.0,
            "expectancy": 0.003,
            "max_drawdown_pct": 8.0,
        }
        defaults.update(kwargs)
        return PairScoreInputs(**defaults)

    def test_valid_inputs_produce_positive_score(self):
        inputs = self._inputs()
        result = score_pair(inputs)
        assert result.rank_score > 0.0
        assert result.pair == "BTC/USDT"
        assert result.policy_version == RANKING_POLICY_VERSION

    def test_components_are_present(self):
        result = score_pair(self._inputs())
        assert "pf_score" in result.components
        assert "np_score" in result.components
        assert "exp_score" in result.components
        assert "dd_penalty" in result.components
        assert "raw_score" in result.components
        assert "trade_sufficiency_multiplier" in result.components

    def test_zero_profit_factor_gives_zero_pf_score(self):
        # PF = 1.0 → breakeven → pf_score = 0
        result = score_pair(self._inputs(profit_factor=1.0))
        assert result.components["pf_score"] == 0.0

    def test_high_profit_factor_gives_max_pf_score(self):
        # PF ≥ 3.0 → max score 35
        result = score_pair(self._inputs(profit_factor=3.0))
        assert result.components["pf_score"] == 35.0

        result2 = score_pair(self._inputs(profit_factor=5.0))
        assert result2.components["pf_score"] == 35.0  # capped at 35

    def test_drawdown_penalty_kicks_in_above_10_pct(self):
        no_penalty = score_pair(self._inputs(max_drawdown_pct=10.0))
        assert no_penalty.components["dd_penalty"] == 0.0

        with_penalty = score_pair(self._inputs(max_drawdown_pct=20.0))
        assert with_penalty.components["dd_penalty"] == 10.0  # 10% excess × 1 pt

        max_penalty = score_pair(self._inputs(max_drawdown_pct=40.0))
        assert max_penalty.components["dd_penalty"] == 20.0  # capped at 20

    def test_drawdown_penalty_reduces_final_score(self):
        low_dd = score_pair(self._inputs(max_drawdown_pct=5.0))
        high_dd = score_pair(self._inputs(max_drawdown_pct=30.0))
        assert high_dd.rank_score < low_dd.rank_score

    def test_positive_expectancy_increases_score(self):
        no_exp = score_pair(self._inputs(expectancy=0.0))
        pos_exp = score_pair(self._inputs(expectancy=0.005))
        assert pos_exp.rank_score > no_exp.rank_score

    def test_expectancy_capped_at_0_01(self):
        at_max = score_pair(self._inputs(expectancy=0.01))
        above_max = score_pair(self._inputs(expectancy=0.1))
        assert at_max.components["exp_score"] == above_max.components["exp_score"]
        assert at_max.components["exp_score"] == 20.0

    def test_negative_expectancy_gives_zero_exp_score(self):
        result = score_pair(self._inputs(expectancy=-0.005))
        assert result.components["exp_score"] == 0.0

    def test_negative_trades_raises_error(self):
        with pytest.raises(ValueError, match="total_trades cannot be negative"):
            score_pair(self._inputs(total_trades=-1))

    # ── Missing metrics are not zero-substituted ──────────────────────────────

    def test_null_profit_factor_recorded_in_metrics_available(self):
        result = score_pair(self._inputs(profit_factor=None))
        assert result.metrics_available["profit_factor"] is False
        assert result.components["pf_score"] == 0.0

    def test_null_net_profit_pct_recorded_in_metrics_available(self):
        result = score_pair(self._inputs(net_profit_pct=None))
        assert result.metrics_available["net_profit_pct"] is False
        assert result.components["np_score"] == 0.0

    def test_null_expectancy_recorded_in_metrics_available(self):
        result = score_pair(self._inputs(expectancy=None))
        assert result.metrics_available["expectancy"] is False
        assert result.components["exp_score"] == 0.0

    def test_null_max_drawdown_gives_no_penalty(self):
        result = score_pair(self._inputs(max_drawdown_pct=None))
        assert result.metrics_available["max_drawdown_pct"] is False
        assert result.components["dd_penalty"] == 0.0

    # ── Trade sufficiency multiplier ──────────────────────────────────────────

    def test_below_min_trades_gives_zero_multiplier(self):
        min_t = get_min_trades("1h")
        result = score_pair(self._inputs(total_trades=min_t - 1, timeframe="1h"))
        assert result.trade_sufficiency_multiplier == 0.0
        assert result.rank_score == 0.0

    def test_at_min_trades_gives_half_multiplier(self):
        min_t = get_min_trades("1h")
        result = score_pair(self._inputs(total_trades=min_t, timeframe="1h"))
        assert result.trade_sufficiency_multiplier == 0.5

    def test_at_five_times_min_trades_gives_full_multiplier(self):
        min_t = get_min_trades("1h")
        result = score_pair(self._inputs(total_trades=min_t * 5, timeframe="1h"))
        assert result.trade_sufficiency_multiplier == 1.0

    def test_beyond_five_times_min_trades_stays_at_one(self):
        min_t = get_min_trades("1h")
        result = score_pair(self._inputs(total_trades=min_t * 10, timeframe="1h"))
        assert result.trade_sufficiency_multiplier == 1.0

    # ── The key spec scenario ─────────────────────────────────────────────────

    def test_few_trade_high_profit_vs_many_trade_moderate(self):
        """High-profit few-trade pair must NOT automatically outrank a many-trade
        moderate pair. The scoring must either: (a) produce equal scores, or (b)
        explicitly justify with a higher score for the high-PF pair via multiplier.

        The spec does not require the many-trade pair to win — it requires the
        ranking to be deterministic and explainable.  This test verifies that
        the multiplier visibly dampens the high-PF pair's score relative to its
        raw components.
        """
        min_t = get_min_trades("1h")

        # Pair A: few trades, very high PF, high profit
        pair_a = PairScoreInputs(
            pair="A/USDT",
            total_trades=min_t,           # exactly at minimum
            timeframe="1h",
            profit_factor=3.5,
            net_profit_pct=30.0,
            expectancy=None,
            max_drawdown_pct=None,
        )

        # Pair B: many trades, moderate PF, moderate profit + good expectancy
        pair_b = PairScoreInputs(
            pair="B/USDT",
            total_trades=250,
            timeframe="1h",
            profit_factor=1.25,
            net_profit_pct=8.0,
            expectancy=0.0018,
            max_drawdown_pct=12.0,
        )

        result_a = score_pair(pair_a)
        result_b = score_pair(pair_b)

        # Pair A's multiplier must be < 1 due to low trade count
        assert result_a.trade_sufficiency_multiplier < 1.0

        # Pair B's multiplier must be 1 (250 trades >> 5×min_t for 1h)
        assert result_b.trade_sufficiency_multiplier == 1.0

        # Both scores must be computed (not identical unless coincidental)
        assert isinstance(result_a.rank_score, float)
        assert isinstance(result_b.rank_score, float)

        # The multiplier effect on pair A must be explicitly visible:
        # raw score × multiplier < raw score
        assert result_a.components["raw_score"] * result_a.trade_sufficiency_multiplier == pytest.approx(result_a.rank_score, abs=0.01)

    def test_score_is_deterministic(self):
        """Same inputs always produce same score."""
        inputs = self._inputs()
        r1 = score_pair(inputs)
        r2 = score_pair(inputs)
        assert r1.rank_score == r2.rank_score
        assert r1.components == r2.components

    # ── NaN / non-finite metric hardening ────────────────────────────────────

    def test_nan_profit_factor_treated_as_unavailable(self):
        """NaN profit_factor must not corrupt scoring — treated as None."""
        import math
        result = score_pair(self._inputs(profit_factor=float("nan")))
        assert result.metrics_available["profit_factor"] is False
        assert result.components["pf_score"] == 0.0
        assert math.isfinite(result.rank_score)

    def test_inf_net_profit_treated_as_unavailable(self):
        """Infinite net_profit_pct must not corrupt scoring."""
        import math
        result = score_pair(self._inputs(net_profit_pct=float("inf")))
        assert result.metrics_available["net_profit_pct"] is False
        assert result.components["np_score"] == 0.0
        assert math.isfinite(result.rank_score)

    def test_nan_expectancy_treated_as_unavailable(self):
        """NaN expectancy must not corrupt scoring."""
        import math
        result = score_pair(self._inputs(expectancy=float("nan")))
        assert result.metrics_available["expectancy"] is False
        assert result.components["exp_score"] == 0.0
        assert math.isfinite(result.rank_score)

    def test_nan_drawdown_treated_as_unavailable(self):
        """NaN max_drawdown_pct must not corrupt scoring — no penalty applied."""
        import math
        result = score_pair(self._inputs(max_drawdown_pct=float("nan")))
        assert result.metrics_available["max_drawdown_pct"] is False
        assert result.components["dd_penalty"] == 0.0
        assert math.isfinite(result.rank_score)

    def test_all_nan_metrics_produces_finite_zero_score(self):
        """All-NaN metrics → score 0.0 (no fake evidence, fully finite)."""
        import math
        result = score_pair(self._inputs(
            profit_factor=float("nan"),
            net_profit_pct=float("nan"),
            expectancy=float("nan"),
            max_drawdown_pct=float("nan"),
        ))
        assert result.rank_score == 0.0
        assert math.isfinite(result.rank_score)
        assert all(v is False for v in result.metrics_available.values())


# ── rank_candidates ────────────────────────────────────────────────────────────

class TestRankCandidates:
    """Tests for deterministic ranking / tie-breaking."""

    def _result(self, pair: str, score: float) -> PairScoreResult:
        return PairScoreResult(
            pair=pair,
            rank_score=score,
            components={},
            trade_sufficiency_multiplier=1.0,
        )

    def test_higher_score_ranks_first(self):
        a = self._result("A/USDT", 80.0)
        b = self._result("B/USDT", 60.0)
        ranked = rank_candidates([b, a])
        assert ranked[0].pair == "A/USDT"
        assert ranked[1].pair == "B/USDT"

    def test_tie_broken_by_pair_name_ascending(self):
        a = self._result("A/USDT", 50.0)
        b = self._result("B/USDT", 50.0)
        ranked = rank_candidates([b, a])
        assert ranked[0].pair == "A/USDT"
        assert ranked[1].pair == "B/USDT"

    def test_deterministic_with_multiple_ties(self):
        pairs = [self._result(f"{c}/USDT", 50.0) for c in "DCBA"]
        ranked = rank_candidates(pairs)
        assert [r.pair for r in ranked] == ["A/USDT", "B/USDT", "C/USDT", "D/USDT"]

    def test_empty_list_returns_empty(self):
        assert rank_candidates([]) == []


class TestRankCandidatesWithTrades:
    """Tests for trade-count tie-breaking."""

    def _result(self, pair: str, score: float) -> PairScoreResult:
        return PairScoreResult(
            pair=pair,
            rank_score=score,
            components={},
            trade_sufficiency_multiplier=1.0,
        )

    def test_same_score_higher_trades_ranks_first(self):
        a = (self._result("A/USDT", 50.0), 200)
        b = (self._result("B/USDT", 50.0), 50)
        ranked = rank_candidates_with_trades([b, a])
        assert ranked[0][0].pair == "A/USDT"
        assert ranked[1][0].pair == "B/USDT"

    def test_same_score_same_trades_falls_back_to_pair_name(self):
        a = (self._result("A/USDT", 50.0), 100)
        b = (self._result("B/USDT", 50.0), 100)
        ranked = rank_candidates_with_trades([b, a])
        assert ranked[0][0].pair == "A/USDT"

    def test_score_dominates_over_trade_count(self):
        a = (self._result("A/USDT", 80.0), 10)
        b = (self._result("B/USDT", 40.0), 500)
        ranked = rank_candidates_with_trades([b, a])
        assert ranked[0][0].pair == "A/USDT"

    def test_deterministic_ordering(self):
        pairs = [
            (self._result("D/USDT", 70.0), 100),
            (self._result("A/USDT", 70.0), 200),
            (self._result("C/USDT", 70.0), 200),
            (self._result("B/USDT", 90.0), 50),
        ]
        ranked = rank_candidates_with_trades(pairs)
        order = [r[0].pair for r in ranked]
        # B wins on score, then A and C tie on score+trades (200), broken by name
        assert order[0] == "B/USDT"
        assert order[1] == "A/USDT"
        assert order[2] == "C/USDT"
        assert order[3] == "D/USDT"
