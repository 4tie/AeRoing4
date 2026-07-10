"""Tests for decide_final_pair_set()."""

from backend.services.execution.pair_sweep_runner import decide_final_pair_set


def _passed_result(pair: str, score: float = 10.0, max_drawdown: float = 10.0,
                   profit_factor: float = 1.5, total_trades: int = 30) -> dict:
    return {
        "pair": pair,
        "status": "passed",
        "score": score,
        "max_drawdown": max_drawdown,
        "profit_factor": profit_factor,
        "total_trades": total_trades,
        "win_rate": 55.0,
        "expectancy": 0.03,
        "profit_total": 12.0,
        "rejection_reason": None,
    }


def _failed_result(pair: str) -> dict:
    return {
        "pair": pair,
        "status": "failed",
        "score": 0.0,
        "max_drawdown": 40.0,
        "profit_factor": 0.8,
        "total_trades": 5,
        "win_rate": 30.0,
        "expectancy": -0.01,
        "profit_total": -5.0,
        "rejection_reason": "Profit factor 0.80 below 1.0",
    }


def _portfolio_passed(pairs: list[str] | None = None) -> dict:
    if pairs is None:
        pairs = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    return {
        "status": "passed",
        "failure_reasons": [],
        "run_id": "portfolio_test",
        "portfolio_summary": {
            "total_trades": 100,
            "profit_factor": 1.8,
            "win_rate_pct": 55.0,
            "max_drawdown_pct": 18.0,
            "sharpe_ratio": 1.2,
            "expectancy": 2.0,
            "profit_total_pct": 12.0,
            "profit_total_abs": 120.0,
        },
        "per_pair_metrics": [
            {"pair": p, "trades": 30, "profit_factor": 5.0, "win_rate_pct": 58.0}
            for p in pairs
        ],
        "config_used": {
            "pairs_count": len(pairs),
            "max_open_trades": 5,
            "timerange": "20240101-20240131",
            "timeframe": "5m",
        },
    }


def _portfolio_failed(reasons: list[str] | None = None) -> dict:
    if reasons is None:
        reasons = ["MIN_TRADES"]
    return {
        "status": "failed",
        "failure_reasons": reasons,
        "run_id": "portfolio_test",
        "portfolio_summary": {
            "total_trades": 5,
            "profit_factor": 0.8,
            "win_rate_pct": 35.0,
            "max_drawdown_pct": 40.0,
            "sharpe_ratio": 0.3,
            "expectancy": -1.0,
            "profit_total_pct": -5.0,
            "profit_total_abs": -50.0,
        },
        "per_pair_metrics": [],
        "config_used": {
            "pairs_count": 3,
            "max_open_trades": 5,
            "timerange": "20240101-20240131",
            "timeframe": "5m",
        },
    }


def _portfolio_backtest_failed() -> dict:
    return {
        "status": "backtest_failed",
        "failure_reasons": ["Freqtrade exited with code 1"],
        "run_id": None,
        "portfolio_summary": {},
        "per_pair_metrics": [],
        "config_used": {},
    }


def _low_dd_portfolio() -> dict:
    return {
        "status": "passed",
        "failure_reasons": [],
        "run_id": "portfolio_low_dd",
        "portfolio_summary": {
            "total_trades": 60,
            "profit_factor": 1.5,
            "win_rate_pct": 52.0,
            "max_drawdown_pct": 12.0,
            "sharpe_ratio": 1.0,
            "expectancy": 1.5,
            "profit_total_pct": 8.0,
            "profit_total_abs": 80.0,
        },
        "per_pair_metrics": [
            {"pair": "BTC/USDT", "trades": 20, "profit_factor": 3.0, "win_rate_pct": 55.0},
            {"pair": "ETH/USDT", "trades": 15, "profit_factor": 2.0, "win_rate_pct": 50.0},
            {"pair": "SOL/USDT", "trades": 25, "profit_factor": 1.5, "win_rate_pct": 48.0},
            {"pair": "DOT/USDT", "trades": 10, "profit_factor": 0.5, "win_rate_pct": 40.0},
        ],
        "config_used": {
            "pairs_count": 4,
            "max_open_trades": 5,
            "timerange": "20240101-20240131",
            "timeframe": "5m",
        },
    }


class TestDecideFinalPairSet:
    """Tests for decide_final_pair_set."""

    def test_full_approval_path(self):
        """Balanced profile with enough qualified pairs approves."""
        individuals = [
            _passed_result("BTC/USDT", score=15.0),
            _passed_result("ETH/USDT", score=12.0),
            _passed_result("SOL/USDT", score=10.0),
        ]
        portfolio = _portfolio_passed()

        result = decide_final_pair_set(
            individuals, portfolio,
            risk_profile="balanced",
            min_approved_pairs=2,
            max_approved_pairs=3,
        )

        assert result["verdict"] == "approved"
        assert len(result["approved_pairs"]) == 3
        assert result["approved_count"] == 3
        assert result["approved_pairs"] == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
        assert result["rejection_reason"] is None

    def test_low_risk_filter_drops_high_drawdown(self):
        """Low profile rejects pairs with max_drawdown >= 15."""
        individuals = [
            _passed_result("BTC/USDT", score=15.0, max_drawdown=5.0),
            _passed_result("ETH/USDT", score=12.0, max_drawdown=12.0),
            _passed_result("SOL/USDT", score=10.0, max_drawdown=20.0),
        ]
        portfolio = _portfolio_passed()

        result = decide_final_pair_set(
            individuals, portfolio,
            risk_profile="low",
            min_approved_pairs=2,
            max_approved_pairs=5,
        )

        assert result["verdict"] == "approved"
        assert result["approved_pairs"] == ["BTC/USDT", "ETH/USDT"]
        assert len(result["approved_pairs"]) == 2

        # SOL should be in combined_scores but not approved
        sol_scores = [s for s in result["combined_scores"] if s["pair"] == "SOL/USDT"]
        assert sol_scores[0]["survived_risk_filter"] is False

    def test_balanced_risk_accepts_moderate_drawdown(self):
        """Balanced profile accepts pairs with max_drawdown < 25."""
        individuals = [
            _passed_result("BTC/USDT", score=15.0, max_drawdown=5.0),
            _passed_result("ETH/USDT", score=12.0, max_drawdown=20.0),
        ]
        portfolio = _portfolio_passed()

        result = decide_final_pair_set(
            individuals, portfolio,
            risk_profile="balanced",
            min_approved_pairs=2,
            max_approved_pairs=5,
        )

        assert result["verdict"] == "approved"
        assert len(result["approved_pairs"]) == 2
        assert "ETH/USDT" in result["approved_pairs"]

    def test_aggressive_allows_higher_drawdown(self):
        """Aggressive profile allows max_drawdown up to 35."""
        individuals = [
            _passed_result("BTC/USDT", score=15.0, max_drawdown=5.0),
            _passed_result("ETH/USDT", score=12.0, max_drawdown=30.0),
            _passed_result("SOL/USDT", score=10.0, max_drawdown=40.0),
        ]
        portfolio = _portfolio_passed(pairs=["BTC/USDT", "ETH/USDT", "SOL/USDT"])

        result = decide_final_pair_set(
            individuals, portfolio,
            risk_profile="aggressive",
            min_approved_pairs=2,
            max_approved_pairs=5,
        )

        assert result["verdict"] == "approved"
        assert "ETH/USDT" in result["approved_pairs"]
        assert "SOL/USDT" not in result["approved_pairs"]

    def test_portfolio_backtest_failed_rejects(self):
        """backtest_failed portfolio status rejects immediately."""
        individuals = [_passed_result("BTC/USDT")]
        portfolio = _portfolio_backtest_failed()

        result = decide_final_pair_set(
            individuals, portfolio,
            min_approved_pairs=1,
        )

        assert result["verdict"] == "rejected"
        assert result["approved_pairs"] == []
        assert "backtest failed" in result["rejection_reason"].lower()

    def test_portfolio_max_drawdown_failure_rejects(self):
        """Portfolio MAX_DRAWDOWN failure rejects the entire set."""
        individuals = [
            _passed_result("BTC/USDT", score=15.0),
            _passed_result("ETH/USDT", score=12.0),
        ]
        portfolio = _portfolio_failed(reasons=["MAX_DRAWDOWN"])

        result = decide_final_pair_set(
            individuals, portfolio,
            min_approved_pairs=1,
        )

        assert result["verdict"] == "rejected"
        assert result["approved_pairs"] == []
        assert "critical thresholds" in result["rejection_reason"].lower()

    def test_portfolio_min_profit_factor_failure_rejects(self):
        """Portfolio MIN_PROFIT_FACTOR failure rejects the entire set."""
        individuals = [_passed_result("BTC/USDT")]
        portfolio = _portfolio_failed(reasons=["MIN_PROFIT_FACTOR"])

        result = decide_final_pair_set(
            individuals, portfolio,
            min_approved_pairs=1,
        )

        assert result["verdict"] == "rejected"
        assert "critical thresholds" in result["rejection_reason"].lower()

    def test_not_enough_survivors_rejects(self):
        """Fewer survivors than min_approved_pairs rejects."""
        individuals = [
            _passed_result("BTC/USDT", score=15.0, max_drawdown=5.0),
        ]
        portfolio = _portfolio_passed()

        result = decide_final_pair_set(
            individuals, portfolio,
            risk_profile="balanced",
            min_approved_pairs=3,
            max_approved_pairs=5,
        )

        assert result["verdict"] == "rejected"
        assert "minimum 3" in result["rejection_reason"]

    def test_max_approved_pairs_limits_output(self):
        """Approved pairs are capped by max_approved_pairs."""
        individuals = [
            _passed_result("BTC/USDT", score=15.0),
            _passed_result("ETH/USDT", score=12.0),
            _passed_result("SOL/USDT", score=10.0),
            _passed_result("DOT/USDT", score=8.0),
        ]
        portfolio = _portfolio_passed(pairs=["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOT/USDT"])

        result = decide_final_pair_set(
            individuals, portfolio,
            risk_profile="balanced",
            min_approved_pairs=2,
            max_approved_pairs=2,
        )

        assert result["verdict"] == "approved"
        assert len(result["approved_pairs"]) == 2
        assert result["approved_pairs"] == ["BTC/USDT", "ETH/USDT"]

    def test_filters_non_passed_individual_results(self):
        """Only passed individual results are considered."""
        individuals = [
            _passed_result("BTC/USDT", score=15.0),
            _failed_result("ETH/USDT"),
            _passed_result("SOL/USDT", score=10.0),
        ]
        portfolio = _portfolio_passed(pairs=["BTC/USDT", "SOL/USDT"])

        result = decide_final_pair_set(
            individuals, portfolio,
            min_approved_pairs=2,
            max_approved_pairs=5,
        )

        assert result["verdict"] == "approved"
        assert "ETH/USDT" not in result["approved_pairs"]
        assert result["approved_pairs"] == ["BTC/USDT", "SOL/USDT"]

    def test_all_non_passed_rejects(self):
        """If all individual results are non-passed, reject."""
        individuals = [
            _failed_result("ETH/USDT"),
            _failed_result("SOL/USDT"),
        ]
        portfolio = _portfolio_passed()

        result = decide_final_pair_set(
            individuals, portfolio,
            min_approved_pairs=1,
        )

        assert result["verdict"] == "rejected"
        assert "No individual pairs passed" in result["rejection_reason"]

    def test_invalid_risk_profile_falls_back_to_balanced(self):
        """Invalid risk_profile falls back to balanced."""
        individuals = [
            _passed_result("BTC/USDT", score=15.0, max_drawdown=20.0),
        ]
        portfolio = _portfolio_passed()

        result = decide_final_pair_set(
            individuals, portfolio,
            risk_profile="nonexistent",
            min_approved_pairs=1,
        )

        assert result["risk_profile"] == "balanced"
        assert result["verdict"] == "approved"

    def test_low_risk_rejects_no_portfolio_trades(self):
        """Low profile rejects a pair with zero portfolio trades."""
        individuals = [_passed_result("XRP/USDT", score=10.0, max_drawdown=8.0)]
        portfolio = {
            "status": "passed",
            "failure_reasons": [],
            "run_id": "test",
            "portfolio_summary": {
                "total_trades": 10, "profit_factor": 1.0,
                "win_rate_pct": 50.0, "max_drawdown_pct": 10.0,
                "sharpe_ratio": 0.8, "expectancy": 0.5,
                "profit_total_pct": 3.0, "profit_total_abs": 30.0,
            },
            "per_pair_metrics": [
                {"pair": "XRP/USDT", "trades": 0, "profit_factor": -1.0, "win_rate_pct": 0.0},
            ],
            "config_used": {"pairs_count": 1, "max_open_trades": 5,
                            "timerange": "20240101-20240131", "timeframe": "5m"},
        }

        result = decide_final_pair_set(
            individuals, portfolio,
            risk_profile="low",
            min_approved_pairs=1,
        )

        assert result["verdict"] == "rejected"
        xrp_scores = [s for s in result["combined_scores"] if s["pair"] == "XRP/USDT"]
        assert xrp_scores[0]["survived_risk_filter"] is False

    def test_combined_socres_includes_all_candidates(self):
        """All passed pairs appear in combined_scores regardless of filter."""
        individuals = [
            _passed_result("BTC/USDT", score=15.0, max_drawdown=5.0),
            _passed_result("SOL/USDT", score=10.0, max_drawdown=20.0),
        ]
        portfolio = _portfolio_passed()

        result = decide_final_pair_set(
            individuals, portfolio,
            risk_profile="low",
            min_approved_pairs=1,
        )

        pair_names = {s["pair"] for s in result["combined_scores"]}
        assert pair_names == {"BTC/USDT", "SOL/USDT"}
