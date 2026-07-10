"""
backend/tests/test_pipeline_smoke.py — End-to-end smoke tests for the 7-stage
Auto-Quant pipeline using a minimal mock strategy and a patched _run_subprocess.

Coverage
--------
  • All 7 stages transition correctly  (pending → running → passed)
  • Self-healing retry loop fires and terminates when OOS improves
  • Retry loop exhausts max_retries and terminates with a failed stage
  • state.json is written at the right checkpoints (create_run + every _pass_stage)
  • WS queue receives expected events including the final None sentinel

Run from project root:
    pytest backend/tests/test_pipeline_smoke.py -v
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Make project root importable ───────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.services.auto_quant.pipeline as pipeline
from backend.services.auto_quant.pipeline_modules import orchestrator
from backend.services.auto_quant.pipeline import (
    PipelineState,
    StageState,
    STAGE_NAMES,
    _states,
    _queues,
    _cancel_flags,
)

# ── Minimal freqtrade-style strategy source ────────────────────────────────────

_MOCK_STRATEGY_SOURCE = """\
from freqtrade.strategy import IStrategy

class MockStrategy(IStrategy):
    stoploss = -0.10
    minimal_roi = {"0": 0.10, "30": 0.05, "60": 0.02}
    trailing_stop = False
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = False

    def populate_indicators(self, dataframe, metadata):
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe["enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe["exit_long"] = 0
        return dataframe
"""

_MOCK_CONFIG = {
    "exchange": {"name": "binance", "key": "", "secret": ""},
    "stake_currency": "USDT",
    "stake_amount": 100,
    "pair_whitelist": ["BTC/USDT"],
    "dry_run": True,
}

# ── Synthetic freqtrade backtest result format ─────────────────────────────────

def _make_backtest_result(strategy_name: str, *, profit: float = 0.10) -> dict:
    """Minimal freqtrade backtest JSON that every stage helper can parse."""
    trades = [
        {"profit_ratio": profit / 30, "close_date": f"2023-07-{i+1:02d} 12:00:00"}
        for i in range(30)
    ]
    return {
        "strategy": {
            strategy_name: {
                "profit_total": profit,
                "profit_total_abs": profit * 1000,
                "profit_mean": profit / 30,
                "max_drawdown_account": 0.08,
                "total_trades": 30,
                "wins": 20,
                "losses": 8,
                "draws": 2,
                "win_rate": 66.7,
                "profit_factor": 1.8,
                "sharpe_ratio": 1.2,
                "calmar_ratio": 0.9,
                "sortino_ratio": 1.1,
                "stake_currency": "USDT",
                "trades": trades,
                "results_per_pair": [
                    {
                        "key": "BTC/USDT",
                        "profit_total": profit,
                        "profit_mean": profit / 30,
                        "trades": 30,
                        "wins": 20,
                        "losses": 8,
                    }
                ],
            }
        }
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _setup_fs(tmp_path: Path) -> tuple[Path, Path]:
    """Create the minimal on-disk layout the pipeline expects.

    Returns (user_data_dir, config_path).
    """
    user_data_dir = tmp_path / "user_data"
    strategies_dir = user_data_dir / "strategies"
    strategies_dir.mkdir(parents=True)

    (strategies_dir / "MockStrategy.py").write_text(
        _MOCK_STRATEGY_SOURCE, encoding="utf-8"
    )

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_MOCK_CONFIG, indent=2), encoding="utf-8")

    return user_data_dir, config_path


def _register_run(user_data_dir: Path, config_path: Path) -> str:
    """Register a fresh pipeline run and return its run_id."""
    return pipeline.create_run(
        strategy="MockStrategy",
        timeframe="1h",
        in_sample_range="20230101-20230601",
        out_sample_range="20230601-20231201",
        exchange="binance",
        config_file=str(config_path),
        freqtrade_path="freqtrade",
        user_data_dir=str(user_data_dir),
    )


def _make_subprocess_mock(
    user_data_dir: Path,
    *,
    oos_profits: list[float] | None = None,
) -> Any:
    """Return an async callable that replaces ``_run_subprocess``.

    For every ``backtesting`` subprocess call the mock writes a synthetic
    result JSON to the path given by ``--export-filename``.  ``oos_profits``
    lets callers supply per-call OOS profit values to simulate overfitting on
    the first attempt(s).  ``hyperopt`` and ``download-data`` calls just
    return success immediately.
    """
    oos_call_counter = [0]
    oos_profits_list = oos_profits or [0.10]

    async def fake_run(run_id, cmd, *, stage, stream=False):
        if not cmd:
            return (0, "", "")

        subcommand = cmd[1] if len(cmd) > 1 else ""

        if subcommand == "backtesting":
            # Determine output path from --export-filename flag
            try:
                idx = cmd.index("--export-filename")
                out_path = Path(cmd[idx + 1])
                out_path.parent.mkdir(parents=True, exist_ok=True)
            except (ValueError, IndexError):
                return (0, "", "")

            # Infer strategy name from --strategy flag
            try:
                strat_idx = cmd.index("--strategy")
                strat_name = cmd[strat_idx + 1]
            except (ValueError, IndexError):
                strat_name = "MockStrategy"

            # Use per-call OOS profit for stage 4 calls
            if stage == 4:
                idx_oos = oos_call_counter[0]
                profit = oos_profits_list[min(idx_oos, len(oos_profits_list) - 1)]
                oos_call_counter[0] += 1
            else:
                profit = 0.10

            result = _make_backtest_result(strat_name, profit=profit)
            out_path.write_text(json.dumps(result), encoding="utf-8")

        # hyperopt / download-data: just succeed silently
        return (0, "", "")

    return fake_run


_BEST_PARAMS: dict = {
    "loss": -0.5,
    "params_dict": {"stoploss": -0.05, "minimal_roi": {"0": 0.10, "60": 0.02}},
}

MOD = "backend.services.auto_quant.pipeline"


def test_stage4_missing_optimized_path_fails_without_unboundlocal(tmp_path):
    """A Stage 3 resume without an optimized path should fail Stage 4 cleanly."""
    user_data_dir, config_path = _setup_fs(tmp_path)
    run_id = _register_run(user_data_dir, config_path)
    state = _states[run_id]
    state.current_stage = 3
    state.stages[0].status = "passed"
    state.stages[1].status = "passed"
    state.stages[2].status = "passed"
    state.stages[2].data = {}

    fail_stage_mock = MagicMock()
    policy = MagicMock()
    policy.versions = {}

    with (
        patch.object(orchestrator, "load_policy", return_value=policy),
        patch.object(orchestrator, "ensure_working_copy"),
        patch.object(orchestrator, "_fail_stage", fail_stage_mock),
    ):
        _run(orchestrator.run_pipeline(run_id))

    fail_stage_mock.assert_called_once()
    assert fail_stage_mock.call_args.args[2] == 4
    assert "optimized_path is None" in fail_stage_mock.call_args.args[3]


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class TestPipelineSmokeE2E:
    """End-to-end smoke tests for run_pipeline with a patched _run_subprocess."""

    # ── Happy path — all 7 stages pass ────────────────────────────────────────

    def test_all_7_stages_transition_to_passed(self, tmp_path):
        """All 7 StageState entries must end with status='passed'."""
        user_data_dir, config_path = _setup_fs(tmp_path)
        run_id = _register_run(user_data_dir, config_path)
        state = _states[run_id]

        with (
            patch(f"{MOD}._run_subprocess",
                  new=_make_subprocess_mock(user_data_dir)),
            patch(f"{MOD}._extract_hyperopt_best",
                  new=AsyncMock(return_value=_BEST_PARAMS)),
        ):
            _run(pipeline.run_pipeline(run_id))

        for stage in state.stages:
            assert stage.status == "passed", (
                f"Stage {stage.index} ({stage.name}) expected 'passed' "
                f"but got {stage.status!r}  message={stage.message!r}"
            )

    def test_pipeline_status_completed_on_success(self, tmp_path):
        """PipelineState.status must be 'completed' after a successful run."""
        user_data_dir, config_path = _setup_fs(tmp_path)
        run_id = _register_run(user_data_dir, config_path)
        state = _states[run_id]

        with (
            patch(f"{MOD}._run_subprocess",
                  new=_make_subprocess_mock(user_data_dir)),
            patch(f"{MOD}._extract_hyperopt_best",
                  new=AsyncMock(return_value=_BEST_PARAMS)),
        ):
            _run(pipeline.run_pipeline(run_id))

        assert state.status == "completed", (
            f"Expected 'completed', got {state.status!r}  error={state.error!r}"
        )

    def test_stage_current_stage_ends_at_7(self, tmp_path):
        """current_stage must equal 7 after a full successful run."""
        user_data_dir, config_path = _setup_fs(tmp_path)
        run_id = _register_run(user_data_dir, config_path)
        state = _states[run_id]

        with (
            patch(f"{MOD}._run_subprocess",
                  new=_make_subprocess_mock(user_data_dir)),
            patch(f"{MOD}._extract_hyperopt_best",
                  new=AsyncMock(return_value=_BEST_PARAMS)),
        ):
            _run(pipeline.run_pipeline(run_id))

        assert state.current_stage == 7, (
            f"Expected current_stage=7 on completion, got {state.current_stage}"
        )

    # ── state.json persistence ─────────────────────────────────────────────────

    def test_state_json_written_at_create_run(self, tmp_path):
        """create_run must persist state.json immediately."""
        user_data_dir, config_path = _setup_fs(tmp_path)
        run_id = _register_run(user_data_dir, config_path)
        state = _states[run_id]

        state_file = (
            Path(str(user_data_dir)) / "auto_quant" / run_id / "state.json"
        )
        assert state_file.exists(), (
            "state.json was not written by create_run"
        )
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["run_id"] == run_id

    def test_state_json_updated_after_each_stage(self, tmp_path):
        """_save_state_to_disk is called at least once per stage pass."""
        user_data_dir, config_path = _setup_fs(tmp_path)
        run_id = _register_run(user_data_dir, config_path)

        save_calls: list[Any] = []
        real_save = pipeline._save_state_to_disk

        def counting_save(s):
            save_calls.append(s.current_stage)
            real_save(s)

        with (
            patch(f"{MOD}._run_subprocess",
                  new=_make_subprocess_mock(user_data_dir)),
            patch(f"{MOD}._extract_hyperopt_best",
                  new=AsyncMock(return_value=_BEST_PARAMS)),
            patch(f"{MOD}._save_state_to_disk", side_effect=counting_save),
        ):
            _run(pipeline.run_pipeline(run_id))

        # At minimum, one save per stage (7) plus create_run save (counted
        # separately before run_pipeline) — we only count run_pipeline saves here.
        # _pass_stage calls _save_state_to_disk, so expect ≥ 7 calls.
        assert len(save_calls) >= 7, (
            f"Expected ≥7 _save_state_to_disk calls (one per stage pass), "
            f"got {len(save_calls)}: stages={save_calls}"
        )

    def test_state_json_final_content_on_disk(self, tmp_path):
        """After completion, state.json on disk must reflect the completed status."""
        user_data_dir, config_path = _setup_fs(tmp_path)
        run_id = _register_run(user_data_dir, config_path)

        with (
            patch(f"{MOD}._run_subprocess",
                  new=_make_subprocess_mock(user_data_dir)),
            patch(f"{MOD}._extract_hyperopt_best",
                  new=AsyncMock(return_value=_BEST_PARAMS)),
        ):
            _run(pipeline.run_pipeline(run_id))

        state_file = (
            Path(str(user_data_dir)) / "auto_quant" / run_id / "state.json"
        )
        assert state_file.exists(), "state.json missing after pipeline completion"
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["status"] == "completed"
        assert data["current_stage"] == 7
        for s in data["stages"]:
            assert s["status"] == "passed", (
                f"Stage {s['index']} not 'passed' in state.json: {s}"
            )

    # ── WS queue events ────────────────────────────────────────────────────────

    def test_ws_queue_receives_events_and_sentinel(self, tmp_path):
        """The WS queue must receive ≥1 event per stage and end with a None sentinel."""
        user_data_dir, config_path = _setup_fs(tmp_path)
        run_id = _register_run(user_data_dir, config_path)

        # Subscribe before the run starts
        q = pipeline.get_queue(run_id)

        with (
            patch(f"{MOD}._run_subprocess",
                  new=_make_subprocess_mock(user_data_dir)),
            patch(f"{MOD}._extract_hyperopt_best",
                  new=AsyncMock(return_value=_BEST_PARAMS)),
        ):
            _run(pipeline.run_pipeline(run_id))

        # Drain the queue
        events: list[Any] = []
        while not q.empty():
            events.append(q.get_nowait())

        # Sentinel must be the final item
        assert events, "WS queue received no events"
        assert events[-1] is None, (
            f"Last WS event must be None (sentinel), got {events[-1]!r}"
        )

        # At least one status='passed' event per stage (stages 1-7)
        passed_stages = {
            e["stage"] for e in events
            if isinstance(e, dict) and e.get("status") == "passed"
        }
        for stage_idx in range(1, 8):
            assert stage_idx in passed_stages, (
                f"No 'passed' WS event received for stage {stage_idx}"
            )

    def test_ws_sentinel_sent_even_on_stage1_failure(self, tmp_path):
        """Sentinel must be sent even when Stage 1 fails (finally block fires)."""
        user_data_dir, config_path = _setup_fs(tmp_path)
        run_id = _register_run(user_data_dir, config_path)
        q = pipeline.get_queue(run_id)

        async def failing_subprocess(run_id, cmd, *, stage, stream=False):
            return (1, "no data found for MockStrategy", "")

        with patch(f"{MOD}._run_subprocess", new=failing_subprocess):
            _run(pipeline.run_pipeline(run_id))

        events: list[Any] = []
        while not q.empty():
            events.append(q.get_nowait())

        assert events, "No events received at all"
        assert events[-1] is None, (
            "Sentinel not sent after Stage 1 failure"
        )

    # ── Self-healing retry loop ────────────────────────────────────────────────

    def test_retry_fires_once_then_succeeds(self, tmp_path):
        """OOS negative profit on attempt 1 must trigger one retry; attempt 2 passes."""
        user_data_dir, config_path = _setup_fs(tmp_path)
        run_id = _register_run(user_data_dir, config_path)
        state = _states[run_id]

        # First OOS call: negative profit → retry.  Second: positive → pass.
        subprocess_mock = _make_subprocess_mock(
            user_data_dir, oos_profits=[-0.05, 0.10]
        )

        with (
            patch(f"{MOD}._run_subprocess", new=subprocess_mock),
            patch(f"{MOD}._extract_hyperopt_best",
                  new=AsyncMock(return_value=_BEST_PARAMS)),
        ):
            _run(pipeline.run_pipeline(run_id))

        assert state.retry_count == 1, (
            f"Expected retry_count=1 after one retry, got {state.retry_count}"
        )
        assert state.status == "completed", (
            f"Pipeline should complete after one retry, got {state.status!r}"
        )

    def test_retry_count_increments_correctly(self, tmp_path):
        """retry_count must equal the number of OOS overfitting signals received."""
        user_data_dir, config_path = _setup_fs(tmp_path)
        run_id = _register_run(user_data_dir, config_path)
        state = _states[run_id]

        # Two negative OOS attempts, then pass
        subprocess_mock = _make_subprocess_mock(
            user_data_dir, oos_profits=[-0.05, -0.02, 0.10]
        )

        with (
            patch(f"{MOD}._run_subprocess", new=subprocess_mock),
            patch(f"{MOD}._extract_hyperopt_best",
                  new=AsyncMock(return_value=_BEST_PARAMS)),
        ):
            _run(pipeline.run_pipeline(run_id))

        assert state.retry_count == 2, (
            f"Expected retry_count=2, got {state.retry_count}"
        )
        assert state.status == "completed"

    def test_retry_loop_exhausted_pipeline_fails(self, tmp_path):
        """When OOS never passes (> max_retries), pipeline must end in 'failed'."""
        user_data_dir, config_path = _setup_fs(tmp_path)
        run_id = _register_run(user_data_dir, config_path)
        state = _states[run_id]

        # Always negative profit — exceeds max_retries=3
        subprocess_mock = _make_subprocess_mock(
            user_data_dir, oos_profits=[-0.05, -0.05, -0.05, -0.05, -0.05]
        )

        with (
            patch(f"{MOD}._run_subprocess", new=subprocess_mock),
            patch(f"{MOD}._extract_hyperopt_best",
                  new=AsyncMock(return_value=_BEST_PARAMS)),
        ):
            _run(pipeline.run_pipeline(run_id))

        assert state.status == "failed", (
            f"Expected 'failed' after exhausting retries, got {state.status!r}"
        )
        assert state.retry_count > state.max_retries, (
            f"retry_count={state.retry_count} should exceed max_retries={state.max_retries}"
        )

    def test_retry_exhaustion_stage4_marked_failed(self, tmp_path):
        """Stage 4 must be marked 'failed' when the retry loop is exhausted."""
        user_data_dir, config_path = _setup_fs(tmp_path)
        run_id = _register_run(user_data_dir, config_path)
        state = _states[run_id]

        subprocess_mock = _make_subprocess_mock(
            user_data_dir, oos_profits=[-0.05, -0.05, -0.05, -0.05, -0.05]
        )

        with (
            patch(f"{MOD}._run_subprocess", new=subprocess_mock),
            patch(f"{MOD}._extract_hyperopt_best",
                  new=AsyncMock(return_value=_BEST_PARAMS)),
        ):
            _run(pipeline.run_pipeline(run_id))

        stage4 = state.stages[3]  # 0-indexed, stage index 4
        assert stage4.status == "failed", (
            f"Stage 4 expected 'failed' after retry exhaustion, got {stage4.status!r}"
        )

    def test_retry_applies_param_overrides_accumulate(self, tmp_path):
        """All three per-retry overrides must accumulate across 3 retries."""
        user_data_dir, config_path = _setup_fs(tmp_path)
        run_id = _register_run(user_data_dir, config_path)
        state = _states[run_id]
        state.hyperopt_loss = "OnlyProfitHyperOptLoss"
        state.hyperopt_spaces = ["buy", "sell"]
        state.hyperopt_epochs = 80

        # Always negative — exhaust all retries
        subprocess_mock = _make_subprocess_mock(
            user_data_dir, oos_profits=[-0.05] * 5
        )

        with (
            patch(f"{MOD}._run_subprocess", new=subprocess_mock),
            patch(f"{MOD}._extract_hyperopt_best",
                  new=AsyncMock(return_value=_BEST_PARAMS)),
        ):
            _run(pipeline.run_pipeline(run_id))

        # Retry 1 → SharpeHyperOptLoss
        assert state.hyperopt_loss == "SharpeHyperOptLoss"
        # Retry 2 → ["roi", "stoploss"]
        assert state.hyperopt_spaces == ["roi", "stoploss"]
        # Retry 3 → 80 * 1.5 = 120
        assert state.hyperopt_epochs == int(80 * 1.5)

    def test_stages_2_3_4_reset_on_retry(self, tmp_path):
        """Stages 2/3/4 must be reset to 'pending' before each retry attempt."""
        user_data_dir, config_path = _setup_fs(tmp_path)
        run_id = _register_run(user_data_dir, config_path)
        state = _states[run_id]

        captured_stage_statuses: list[list[str]] = []
        real_extract = pipeline._extract_hyperopt_best

        async def capturing_extract(s, out_dir):
            # Record stage 2/3/4 statuses each time hyperopt-show is called
            captured_stage_statuses.append(
                [state.stages[i - 1].status for i in (2, 3, 4)]
            )
            return _BEST_PARAMS

        subprocess_mock = _make_subprocess_mock(
            user_data_dir, oos_profits=[-0.05, 0.10]
        )

        with (
            patch(f"{MOD}._run_subprocess", new=subprocess_mock),
            patch(f"{MOD}._extract_hyperopt_best", new=capturing_extract),
        ):
            _run(pipeline.run_pipeline(run_id))

        assert len(captured_stage_statuses) >= 2, (
            "Expected _extract_hyperopt_best called at least twice "
            f"(initial + 1 retry), got {len(captured_stage_statuses)}"
        )

        # After the retry, the statuses captured at hyperopt-show call time
        # must show stages 2/3/4 reset to running/pending (not 'passed').
        # At the exact moment _extract_hyperopt_best runs, stage 2 is 'running'.
        # What matters is they are NOT 'passed' from the previous attempt.
        second_call_statuses = captured_stage_statuses[1]
        assert "passed" not in second_call_statuses, (
            f"Stages 2/3/4 still show 'passed' at retry entry: {second_call_statuses}"
        )

    # ── WS event content ───────────────────────────────────────────────────────

    def test_ws_events_contain_stage_and_status_fields(self, tmp_path):
        """Every non-sentinel WS event must have 'stage' and 'status' fields."""
        user_data_dir, config_path = _setup_fs(tmp_path)
        run_id = _register_run(user_data_dir, config_path)
        q = pipeline.get_queue(run_id)

        with (
            patch(f"{MOD}._run_subprocess",
                  new=_make_subprocess_mock(user_data_dir)),
            patch(f"{MOD}._extract_hyperopt_best",
                  new=AsyncMock(return_value=_BEST_PARAMS)),
        ):
            _run(pipeline.run_pipeline(run_id))

        events: list[Any] = []
        while not q.empty():
            events.append(q.get_nowait())

        for ev in events:
            if ev is None:
                continue
            assert "stage" in ev, f"Event missing 'stage' field: {ev}"
            assert "status" in ev, f"Event missing 'status' field: {ev}"

    def test_ws_report_included_in_final_event(self, tmp_path):
        """The final 'passed' event for stage 7 must carry a 'report' in data."""
        user_data_dir, config_path = _setup_fs(tmp_path)
        run_id = _register_run(user_data_dir, config_path)
        q = pipeline.get_queue(run_id)

        with (
            patch(f"{MOD}._run_subprocess",
                  new=_make_subprocess_mock(user_data_dir)),
            patch(f"{MOD}._extract_hyperopt_best",
                  new=AsyncMock(return_value=_BEST_PARAMS)),
        ):
            _run(pipeline.run_pipeline(run_id))

        events: list[Any] = []
        while not q.empty():
            events.append(q.get_nowait())

        # Look for the stage-7 passed event that carries the report
        stage7_passed = [
            e for e in events
            if isinstance(e, dict)
            and e.get("stage") == 7
            and e.get("status") == "passed"
        ]
        assert stage7_passed, "No stage-7 'passed' event found in WS queue"
        assert "report" in stage7_passed[-1].get("data", {}), (
            "Stage-7 'passed' event must include 'report' in data"
        )
