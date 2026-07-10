"""Stage 2 implementation: Portfolio Baseline Backtest with capital constraints."""

from __future__ import annotations

import logging
from pathlib import Path

from ..helpers import (
    _backtest_cmd,
    _classify_subprocess_error,
    _create_temp_config_with_max_open_trades,
    _emit,
    _extract_backtest_summary,
    _extract_per_pair_results,
    _fail_stage,
    _find_backtest_result,
    _pass_stage,
    _run_subprocess,
    _start_stage,
    strategy_path_args,
)
from ..logging import _rlog
from ..state import PipelineState, _Cancelled, _cancelled, _save_state_to_disk


async def _stage_portfolio_baseline(
    run_id: str,
    state: PipelineState,
    out_dir: Path,
) -> dict | None:
    """Stage 2: Portfolio Baseline Backtest with capital constraints.

    Performs:
    1. Joint portfolio backtest with max_open_trades constraint on user-approved pairs
    2. Portfolio and per-pair metrics extraction
    3. Store baseline trade counts for capital starvation detection later
    4. Pause for second user approval to review portfolio baseline results
    """
    _start_stage(run_id, state, 2)
    strategy_name = state.strategy
    pairs_to_test = [p["key"] for p in state.selected_pairs] if state.selected_pairs else None

    if not pairs_to_test:
        _rlog(run_id, 2, logging.WARNING, "Stage 2 | No selected_pairs available, skipping portfolio baseline")
        state.portfolio_weights = {}
        _pass_stage(run_id, state, 2, "No pairs to test for portfolio baseline", {"portfolio_weights": {}})
        return {"portfolio_weights": {}}

    _rlog(run_id, 2, logging.INFO,
          f"Stage 2 | Portfolio Baseline | strategy={strategy_name} | pairs={len(pairs_to_test)} | "
          f"max_open_trades={state.max_open_trades}")
    _emit(run_id, 2, "running",
          f"Running portfolio baseline backtest with {state.max_open_trades} max open trades...",
          20)

    # ── Sub-step 2.1: Joint Portfolio Backtest Execution ───────────────────────
    try:
        # Create temporary config with max_open_trades constraint
        temp_config = _create_temp_config_with_max_open_trades(
            state.config_file, state.max_open_trades, out_dir
        )

        result_prefix = str(out_dir / "stage2_portfolio_baseline")
        cmd = [state.freqtrade_path, "backtesting",
                "--config", str(temp_config),
                "--strategy", strategy_name,
                "--timerange", state.in_sample_range,
                "--timeframe", state.timeframe,
                "--user-data-dir", state.user_data_dir,
                "--export", "trades",
                "--export-filename", result_prefix + ".json",
                "--no-color",
                "--cache", "none"]
        cmd += strategy_path_args(state)
        if pairs_to_test:
            cmd += ["--pairs"] + pairs_to_test

        _rlog(run_id, 2, logging.DEBUG, f"Stage 2 | Spawning subprocess: {' '.join(cmd)}")
        rc, stdout, stderr = await _run_subprocess(run_id, cmd, stage=2)

        # Cleanup temp config
        try:
            Path(temp_config).unlink(missing_ok=True)
        except Exception as exc:
            _rlog(run_id, 2, logging.WARNING, f"Stage 2 | Failed to delete temp config: {exc}")

        if _cancelled(run_id):
            raise _Cancelled()

        if rc != 0:
            msg = _classify_subprocess_error(rc, stdout, "Stage 2 (Portfolio Baseline)")
            _rlog(run_id, 2, logging.ERROR, f"Stage 2 | FAIL | {msg}")
            _fail_stage(run_id, state, 2, msg)
            return None

    except Exception as exc:
        msg = f"Portfolio baseline backtest failed: {exc}"
        _rlog(run_id, 2, logging.ERROR, f"Stage 2 | FAIL | {msg}")
        _fail_stage(run_id, state, 2, msg)
        return None

    # ── Sub-step 2.2: Portfolio Metrics Extraction ───────────────────────────
    result_data = _find_backtest_result(out_dir, "stage2_portfolio_baseline", state.user_data_dir)
    portfolio_summary = _extract_backtest_summary(result_data, strategy_name)
    per_pair = _extract_per_pair_results(result_data, strategy_name)

    portfolio_profit = portfolio_summary.get("profit_total_abs", 0.0)
    portfolio_max_dd = portfolio_summary.get("max_drawdown_account", 0.0)
    portfolio_trades = portfolio_summary.get("total_trades", 0)

    _rlog(run_id, 2, logging.INFO,
          f"Stage 2 | Portfolio baseline metrics: profit={portfolio_profit:.4f} max_dd={portfolio_max_dd:.4f} trades={portfolio_trades}")

    # Store baseline trade counts for capital starvation detection later
    for pair_data in per_pair:
        pair_key = pair_data.get("key", "")
        trade_count = pair_data.get("trades", 0)
        state.baseline_trade_counts[pair_key] = trade_count

    # Store portfolio baseline result in state
    state.portfolio_baseline_result = {
        "portfolio_summary": portfolio_summary,
        "per_pair": per_pair,
        "portfolio_profit": portfolio_profit,
        "portfolio_max_dd": portfolio_max_dd,
        "portfolio_trades": portfolio_trades,
    }

    # ── Sub-step 2.3: Pause for second user approval ─────────────────────────
    summary = {
        "portfolio_summary": portfolio_summary,
        "per_pair": per_pair,
        "portfolio_profit": portfolio_profit,
        "portfolio_max_dd": portfolio_max_dd,
        "portfolio_trades": portfolio_trades,
        "baseline_trade_counts": state.baseline_trade_counts,
    }
    
    # Emit WebSocket event with portfolio baseline results for user review
    _emit(run_id, 2, "running",
          f"Portfolio baseline complete: profit={portfolio_profit:.2f}, max_dd={portfolio_max_dd:.2%}. Please review and confirm pair selection.",
          25,
          {
              "type": "portfolio_baseline_review",
              "portfolio_summary": portfolio_summary,
              "per_pair": per_pair,
              "current_pairs": pairs_to_test,
              "portfolio_profit": portfolio_profit,
              "portfolio_max_dd": portfolio_max_dd,
              "portfolio_trades": portfolio_trades,
          },
          msg_type="portfolio_baseline_review")
    
    # Set status to awaiting user approval and save state
    state.status = "awaiting_user_approval"
    state.current_stage = 2
    state.stages[1].data = summary
    state.stages[1].status = "running"  # Keep as running, not passed
    _save_state_to_disk(state)
    
    _rlog(run_id, 2, logging.INFO,
          f"Stage 2 | PAUSED: Awaiting user approval for portfolio baseline review")
    return summary
