"""backend/tests/test_monte_carlo.py — Monte Carlo simulation tests.

Tests for the Monte Carlo simulation engine and Stage 6 gate logic, including:
- run_monte_carlo() correctness
- Stage 6 Monte Carlo gate integration
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.auto_quant.monte_carlo import run_monte_carlo
import backend.services.auto_quant.pipeline as pl

from .test_helpers import _make_state, _run

MOD = "backend.services.auto_quant.pipeline"


class TestMonteCarloBehavior:
    """Verify run_monte_carlo() correctness and Stage 6 gate logic."""

    # ── run_monte_carlo() unit tests ──────────────────────────────────────────

    def test_empty_ratios_returns_passed_true(self):
        """Empty profit_ratios must return passed=True (no data to penalise)."""
        result = run_monte_carlo([], n=100)
        assert result["passed"] is True
        assert result["simulations"] == 0
        assert result["p95_drawdown"] == 0.0

    def test_strongly_positive_ratios_pass_gate(self):
        """Uniformly +5% per trade must keep p95 drawdown well below 35%."""
        ratios = [0.05] * 50
        result = run_monte_carlo(ratios, n=500)
        assert result["passed"] is True
        assert result["p95_drawdown"] < 0.35

    def test_catastrophic_losses_fail_gate(self):
        """Very large per-trade losses must push p95 drawdown above 35%."""
        ratios = [-0.30] * 20 + [0.01] * 10
        result = run_monte_carlo(ratios, n=500)
        assert result["passed"] is False, (
            f"Expected failure with catastrophic losses, p95={result['p95_drawdown']:.2%}"
        )
        assert result["p95_drawdown"] >= 0.35

    def test_threshold_is_35_percent(self):
        """Verify the gate threshold is exactly 0.35."""
        ratios_pass = [0.02] * 80
        result_pass = run_monte_carlo(ratios_pass, n=300)
        assert result_pass["passed"] == (result_pass["p95_drawdown"] < 0.35)

    def test_result_keys_are_complete(self):
        """Result dict must have all five required keys."""
        result = run_monte_carlo([0.01, -0.005, 0.02], n=50)
        assert "simulations" in result
        assert "p5_drawdown" in result
        assert "p95_drawdown" in result
        assert "median_final_return" in result
        assert "passed" in result

    def test_simulation_count_matches_n(self):
        """simulations must equal the requested n."""
        for n in (10, 100, 500):
            result = run_monte_carlo([0.01] * 20, n=n)
            assert result["simulations"] == n

    def test_p95_is_greater_than_or_equal_to_p5(self):
        """p95_drawdown must always be >= p5_drawdown (worst-case >= best-case)."""
        ratios = [0.01, -0.02, 0.03, -0.01, 0.005] * 10
        result = run_monte_carlo(ratios, n=200)
        assert result["p95_drawdown"] >= result["p5_drawdown"], (
            f"p95 {result['p95_drawdown']:.4f} < p5 {result['p5_drawdown']:.4f}"
        )

    def test_drawdowns_are_non_negative(self):
        """Drawdown values must always be >= 0."""
        result = run_monte_carlo([0.05] * 30, n=200)
        assert result["p5_drawdown"] >= 0.0
        assert result["p95_drawdown"] >= 0.0

    def test_single_trade_no_drawdown_on_profit(self):
        """A single profitable trade has a peak that equals the final equity — dd = 0."""
        result = run_monte_carlo([0.10], n=100)
        assert result["p95_drawdown"] == pytest.approx(0.0, abs=1e-6)

    def test_p95_greater_than_35_means_failed(self):
        """Explicitly verify the boolean: p95 > 35% → passed=False."""
        large_losses = [-0.40] * 15 + [0.01] * 5
        result = run_monte_carlo(large_losses, n=300)
        if result["p95_drawdown"] >= 0.35:
            assert result["passed"] is False
        else:
            assert result["passed"] is True

    # ── Stage 6 Monte Carlo gate integration tests ────────────────────────────

    def test_stage6_fails_when_mc_p95_exceeds_35_percent(self, tmp_path):
        """Stage 6 must call _fail_stage when Monte Carlo p95 >= 35%."""
        state = _make_state(str(tmp_path))
        out_dir = tmp_path / "auto_quant" / state.run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        stress_result = {
            "max_drawdown_account": 0.10,
            "wins": 22, "losses": 18, "draws": 0,
            "profit_factor": 1.4, "sharpe_ratio": 1.2,
            "per_pair": [], "passing_pairs": [], "failing_pairs": [],
        }

        mc_fail = {
            "simulations": 1000,
            "p5_drawdown": 0.05,
            "p95_drawdown": 0.50,
            "median_final_return": -0.20,
            "passed": False,
        }

        fail_mock = MagicMock()

        with (
            patch(f"{MOD}._start_stage"),
            patch(f"{MOD}._cancelled", return_value=False),
            patch(f"{MOD}._extract_oos_profit_ratios", return_value=[-0.3] * 20),
            patch("backend.services.auto_quant.pipeline.run_monte_carlo", return_value=mc_fail),
            patch(f"{MOD}._fail_stage", fail_mock),
            patch(f"{MOD}._pass_stage"),
            patch(f"{MOD}._save_state_to_disk"),
        ):
            result = _run(pl._stage_risk_assessment(state.run_id, state, out_dir, stress_result))

        assert result is None, "Stage 6 must return None when MC gate fails"
        assert fail_mock.called, "_fail_stage was not called on MC gate failure"

        call_args = fail_mock.call_args_list[0].args
        fail_message = call_args[3]
        assert "35" in fail_message or "monte carlo" in fail_message.lower(), (
            f"Failure message should reference 35% threshold: {fail_message!r}"
        )

    def test_stage6_passes_when_mc_p95_below_35_percent(self, tmp_path):
        """Stage 6 must call _pass_stage and return risk_data when MC gate passes."""
        state = _make_state(str(tmp_path))
        out_dir = tmp_path / "auto_quant" / state.run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        stress_result = {
            "max_drawdown_account": 0.10,
            "wins": 22, "losses": 18, "draws": 0,
            "profit_factor": 1.4, "sharpe_ratio": 1.2,
            "per_pair": [], "passing_pairs": [], "failing_pairs": [],
        }

        mc_pass = {
            "simulations": 1000,
            "p5_drawdown": 0.02,
            "p95_drawdown": 0.12,
            "median_final_return": 0.15,
            "passed": True,
        }

        pass_mock = MagicMock()

        with (
            patch(f"{MOD}._start_stage"),
            patch(f"{MOD}._cancelled", return_value=False),
            patch(f"{MOD}._extract_oos_profit_ratios", return_value=[0.01] * 50),
            patch("backend.services.auto_quant.pipeline.run_monte_carlo", return_value=mc_pass),
            patch(f"{MOD}._fail_stage"),
            patch(f"{MOD}._pass_stage", pass_mock),
            patch(f"{MOD}._save_state_to_disk"),
        ):
            result = _run(pl._stage_risk_assessment(state.run_id, state, out_dir, stress_result))

        assert result is not None, "Stage 6 must return risk_data when MC gate passes"
        assert "monte_carlo" in result
        assert result["monte_carlo"]["passed"] is True
        assert pass_mock.called

    def test_stage6_fails_on_risk_checks_before_mc_runs(self, tmp_path):
        """Stage 6 must fail on metric checks before MC simulation is attempted."""
        state = _make_state(
            str(tmp_path),
            max_drawdown_threshold=5.0,  # Impossibly tight threshold
        )
        out_dir = tmp_path / "auto_quant" / state.run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        stress_result = {
            "max_drawdown_account": 0.30,  # 30% >> 5% threshold
            "wins": 22, "losses": 18, "draws": 0,
            "profit_factor": 1.4, "sharpe_ratio": 1.2,
        }

        mc_mock = MagicMock()

        with (
            patch(f"{MOD}._start_stage"),
            patch(f"{MOD}._cancelled", return_value=False),
            patch("backend.services.auto_quant.pipeline.run_monte_carlo", mc_mock),
            patch(f"{MOD}._fail_stage"),
            patch(f"{MOD}._pass_stage"),
            patch(f"{MOD}._save_state_to_disk"),
        ):
            result = _run(pl._stage_risk_assessment(state.run_id, state, out_dir, stress_result))

        assert result is None
        mc_mock.assert_not_called(), "Monte Carlo must not run if risk checks already failed"
