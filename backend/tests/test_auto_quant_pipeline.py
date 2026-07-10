"""
backend/tests/test_auto_quant_pipeline.py — Automated tests for the Stage 4 self-healing retry loop.

Covers:
  - Unit tests for _stage_oos_validation returning "retry" / None / dict
  - Integration tests for run_pipeline verifying:
      • retry_count increments correctly
      • Per-retry parameter overrides (retry 1 → loss, retry 2 → spaces, retry 3 → epochs)
      • _fail_stage called with the correct message after max retries exceeded
      • Stale artifact cleanup triggered on re-entry to Stage 2

Run from project root:
    pytest backend/tests/test_auto_quant_pipeline.py -v
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

# ── Make project root importable ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.services.auto_quant.pipeline as pipeline
from backend.services.auto_quant.pipeline import (
    PipelineState,
    StageState,
    STAGE_NAMES,
    _states,
    _queues,
    _cancel_flags,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_state(tmp_dir: str, **overrides) -> PipelineState:
    """Build a minimal PipelineState registered in the global registry."""
    run_id = str(uuid.uuid4())
    stages = [StageState(index=i + 1, name=STAGE_NAMES[i]) for i in range(len(STAGE_NAMES))]
    
    # Create strategies directory and strategy file
    strategies_dir = Path(tmp_dir) / "strategies"
    strategies_dir.mkdir(parents=True, exist_ok=True)
    strategy_name = overrides.get("strategy", "TestStrategy")
    strategy_file = strategies_dir / f"{strategy_name}.py"
    strategy_file.write_text("# fake strategy", encoding="utf-8")
    
    state = PipelineState(
        run_id=run_id,
        strategy=strategy_name,
        timeframe="1h",
        in_sample_range="20230101-20230601",
        out_sample_range="20230601-20231201",
        exchange="binance",
        config_file="/fake/config.json",
        freqtrade_path="freqtrade",
        user_data_dir=tmp_dir,
        stages=stages,
        created_at="2024-01-01T00:00:00+00:00",
    )
    for k, v in overrides.items():
        setattr(state, k, v)

    _states[run_id] = state
    _queues[run_id] = []
    _cancel_flags[run_id] = False
    return state


def _fake_optimized_path(tmp_dir: str, name: str = "TestStrategy_Optimized") -> Path:
    p = Path(tmp_dir) / f"{name}.py"
    p.write_text("# fake strategy", encoding="utf-8")
    return p


# ═══════════════════════════════════════════════════════════════════════════════
# UNIT TESTS — _stage_oos_validation return values
# ═══════════════════════════════════════════════════════════════════════════════

class TestStageOosValidationUnit:
    """Unit tests for _stage_oos_validation return-value branches."""

    MOD = "backend.services.auto_quant.pipeline"

    def _run_oos(self, state: PipelineState, optimized_path: Path,
                 rc: int = 0,
                 profit: float = 0.05,
                 max_dd_account: float = 0.10,
                 trade_count: int = 20) -> object:
        """Helper: patch all subprocess + IO deps and call _stage_oos_validation."""
        result_data = {"strategy": {optimized_path.stem: {}}}
        summary = {
            "profit_total": profit,
            "max_drawdown_account": max_dd_account,
        }
        out_dir = optimized_path.parent

        with (
            patch(f"{self.MOD}._start_stage"),
            patch(f"{self.MOD}._cancelled", return_value=False),
            patch(f"{self.MOD}._run_subprocess",
                  new=AsyncMock(return_value=(rc, "stdout", "stderr"))),
            patch(f"{self.MOD}._find_backtest_result", return_value=result_data),
            patch(f"{self.MOD}._extract_backtest_summary", return_value=summary),
            patch(f"{self.MOD}._extract_trade_count", return_value=trade_count),
            patch(f"{self.MOD}._fail_stage"),
            patch(f"{self.MOD}._pass_stage"),
            patch(f"{self.MOD}._classify_subprocess_error",
                  return_value="mocked error"),
        ):
            return _run(pipeline._stage_oos_validation(
                state.run_id, state, out_dir, optimized_path
            ))

    def test_returns_dict_when_profit_ok_and_dd_ok(self, tmp_path):
        """Should return a summary dict when profit ≥ 0 and DD ≤ threshold."""
        state = _make_state(str(tmp_path))
        opt = _fake_optimized_path(str(tmp_path))
        result = self._run_oos(state, opt, profit=0.05, max_dd_account=0.10)
        assert isinstance(result, dict), f"Expected dict, got {type(result)}: {result}"

    def test_returns_retry_when_profit_negative(self, tmp_path):
        """Should return 'retry' when profit_total < MIN_OOS_PROFIT (0.0)."""
        state = _make_state(str(tmp_path))
        opt = _fake_optimized_path(str(tmp_path))
        result = self._run_oos(state, opt, profit=-0.01, max_dd_account=0.10)
        assert result == "retry", f"Expected 'retry', got {result!r}"

    def test_returns_retry_when_profit_exactly_zero_is_ok(self, tmp_path):
        """Profit == MIN_OOS_PROFIT (0.0) should PASS, not retry."""
        state = _make_state(str(tmp_path))
        opt = _fake_optimized_path(str(tmp_path))
        result = self._run_oos(state, opt, profit=0.0, max_dd_account=0.10)
        assert result != "retry", f"Profit=0.0 should pass but got {result!r}"
        assert isinstance(result, dict)

    def test_returns_retry_when_drawdown_exceeds_threshold(self, tmp_path):
        """Should return 'retry' when max_drawdown_account > threshold."""
        state = _make_state(str(tmp_path), max_drawdown_threshold=30.0)
        opt = _fake_optimized_path(str(tmp_path))
        # max_dd_account=0.31 → 31% > 30% threshold
        result = self._run_oos(state, opt, profit=0.05, max_dd_account=0.31)
        assert result == "retry", f"Expected 'retry' for high DD, got {result!r}"

    def test_returns_retry_when_profit_negative_and_dd_high(self, tmp_path):
        """Both bad profit and high DD should still return 'retry' (not None)."""
        state = _make_state(str(tmp_path), max_drawdown_threshold=30.0)
        opt = _fake_optimized_path(str(tmp_path))
        result = self._run_oos(state, opt, profit=-0.05, max_dd_account=0.40)
        assert result == "retry"

    def test_returns_none_when_subprocess_fails(self, tmp_path):
        """Should return None (hard failure) when subprocess exits non-zero."""
        state = _make_state(str(tmp_path))
        opt = _fake_optimized_path(str(tmp_path))
        result = self._run_oos(state, opt, rc=1, profit=0.05, max_dd_account=0.10)
        assert result is None, f"Expected None on rc=1, got {result!r}"

    def test_custom_drawdown_threshold_respected(self, tmp_path):
        """Per-run max_drawdown_threshold should override module default."""
        # 25% threshold — a 26% DD should trigger retry
        state = _make_state(str(tmp_path), max_drawdown_threshold=25.0)
        opt = _fake_optimized_path(str(tmp_path))
        result = self._run_oos(state, opt, profit=0.05, max_dd_account=0.26)
        assert result == "retry"

        # Same DD (26%) with 30% threshold should pass
        state2 = _make_state(str(tmp_path), max_drawdown_threshold=30.0)
        opt2 = _fake_optimized_path(str(tmp_path))
        result2 = self._run_oos(state2, opt2, profit=0.05, max_dd_account=0.26)
        assert isinstance(result2, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — AI approval retry loop
# ═══════════════════════════════════════════════════════════════════════════════

class TestAiApprovalRetryLoop:
    """Current retry behavior: AI suggestions pause until approved."""

    def test_pending_suggestion_does_not_increment_retry_count(self, tmp_path):
        from backend.services.auto_quant.ai_suggestions import create_pending_suggestion

        state = _make_state(str(tmp_path), retry_count=0, hyperopt_epochs=100)
        suggestion = create_pending_suggestion(
            state=state,
            trigger="wfo_pass_rate",
            failure_reason="segment_pass_rate_below_50%",
            retry_attempt=1,
            source="deterministic",
        )

        assert state.pending_ai_suggestion_id == suggestion["id"]
        assert state.retry_count == 0
        assert state.hyperopt_epochs == 100
        assert suggestion["original_config"]["hyperopt_epochs"] == 100

    def test_approved_suggestion_resolves_stage_by_name_and_records_retry(self, tmp_path):
        from backend.services.auto_quant.ai_suggestions import (
            approve_suggestion,
            create_pending_suggestion,
            optimization_stage_index,
        )

        state = _make_state(
            str(tmp_path),
            current_stage=6,
            retry_count=0,
            hyperopt_loss="ProfitLockinHyperOptLoss",
            hyperopt_spaces=["buy", "stoploss", "roi"],
            hyperopt_epochs=100,
        )
        for stage in state.stages:
            stage.status = "passed"
        suggestion = create_pending_suggestion(
            state=state,
            trigger="wfo_pass_rate",
            failure_reason="segment_pass_rate_below_50%",
            retry_attempt=1,
            source="deterministic",
            proposed_changes={
                "hyperopt_loss": "SharpeHyperOptLoss",
                "hyperopt_spaces": ["roi", "stoploss"],
                "hyperopt_epochs": 150,
            },
        )

        approve_suggestion(state, suggestion["id"])

        assert state.current_stage == optimization_stage_index()
        assert state.stages[optimization_stage_index() - 1].name == "Standard Hyperopt"
        assert state.retry_count == 1
        assert state.retry_history[-1]["ai_suggestion_id"] == suggestion["id"]
        assert state.hyperopt_loss == "SharpeHyperOptLoss"
        assert state.hyperopt_spaces == ["roi", "stoploss"]
        assert state.hyperopt_epochs == 150

    def test_rejected_suggestion_keeps_retry_configuration_unchanged(self, tmp_path):
        from backend.services.auto_quant.ai_suggestions import create_pending_suggestion, reject_suggestion

        state = _make_state(
            str(tmp_path),
            retry_count=0,
            hyperopt_loss="ProfitLockinHyperOptLoss",
            hyperopt_spaces=["buy", "stoploss", "roi"],
            hyperopt_epochs=100,
        )
        suggestion = create_pending_suggestion(
            state=state,
            trigger="sharp_peak",
            failure_reason="FAIL_SHARP_PEAK",
            retry_attempt=1,
            source="deterministic",
        )

        reject_suggestion(state, suggestion["id"])

        assert state.pending_ai_suggestion_id is None
        assert state.retry_count == 0
        assert state.hyperopt_loss == "ProfitLockinHyperOptLoss"
        assert state.hyperopt_spaces == ["buy", "stoploss", "roi"]
        assert state.hyperopt_epochs == 100
