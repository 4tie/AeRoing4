"""Stage 5 implementation: Multi-Pair Stress Test."""

from __future__ import annotations

import logging
from pathlib import Path

from ..filters import _analyze_trading_windows, _filter_winning_pairs
from ..helpers import (
    _backtest_cmd,
    _classify_subprocess_error,
    _emit,
    _extract_backtest_summary,
    _extract_per_pair_results,
    _fail_stage,
    _find_backtest_result,
    _pass_stage,
    _run_subprocess,
    _start_stage,
)
from ..logging import _rlog
from ..state import PipelineState, _Cancelled, _cancelled


async def _stage_stress_test(
    run_id: str, state: PipelineState, out_dir: Path, optimized_path: Path
) -> dict | None:
    _start_stage(run_id, state, 5)
    strategy_name = optimized_path.stem
    # Use configured pair universe (default BROAD_UNIVERSE_PAIRS for Omni-Strategy)
    pairs_to_test = state.pair_universe
    _rlog(run_id, 5, logging.INFO,
          f"Stage 5 | Multi-Pair Stress Test | strategy={strategy_name}"
          f" | pairs={len(pairs_to_test)} | range={state.in_sample_range}")
    _emit(run_id, 5, "running",
          f"Running multi-pair stress test across {len(pairs_to_test)} USDT pairs...", 65)

    result_prefix = str(out_dir / "stage5_result")
    cmd = _backtest_cmd(
        state,
        strategy=strategy_name,
        timerange=state.in_sample_range,
        result_prefix=result_prefix,
        pairs=pairs_to_test,
    )
    _rlog(run_id, 5, logging.DEBUG,
          f"Stage 5 | Pairs: {', '.join(pairs_to_test)}")
    _rlog(run_id, 5, logging.DEBUG, f"Stage 5 | Spawning subprocess: {' '.join(cmd)}")

    rc, stdout, stderr = await _run_subprocess(run_id, cmd, stage=5)
    _rlog(run_id, 5, logging.DEBUG, f"Stage 5 | Subprocess exited with rc={rc}")

    if _cancelled(run_id):
        raise _Cancelled()

    if rc != 0:
        msg = _classify_subprocess_error(rc, stdout, "Stage 5 (Multi-Pair Stress Test)")
        _rlog(run_id, 5, logging.ERROR, f"Stage 5 | FAIL | {msg}")
        _fail_stage(run_id, state, 5, msg)
        return None

    result_data = _find_backtest_result(out_dir, "stage5_result", state.user_data_dir)
    per_pair = _extract_per_pair_results(result_data, strategy_name)

    # Apply dynamic pair filtering based on timeframe-specific thresholds
    winning_pairs = _filter_winning_pairs(per_pair, state.timeframe)
    failing_pairs = [p for p in per_pair if p not in winning_pairs]

    # Store winning pairs in state for later use in strategy generation
    state.winning_pairs = winning_pairs
    _rlog(run_id, 5, logging.INFO,
          f"Stage 5 | Filtered {len(winning_pairs)}/{len(per_pair)} winning pairs based on timeframe thresholds")

    # Analyze trading windows to identify losing time blocks
    trading_windows = _analyze_trading_windows(per_pair)
    state.excluded_time_windows = {
        "excluded_hours": trading_windows["excluded_hours"],
        "excluded_days": trading_windows["excluded_days"],
    }
    if trading_windows["excluded_hours"] or trading_windows["excluded_days"]:
        _rlog(run_id, 5, logging.INFO,
              f"Stage 5 | Trading window analysis: excluded_hours={trading_windows['excluded_hours']}, "
              f"excluded_days={trading_windows['excluded_days']}")

    # Check minimum profitable pairs requirement (at least 3)
    if len(winning_pairs) < 3:
        msg = (f"Insufficient profitable pairs ({len(winning_pairs)} < 3). "
               f"Strategy may not be generalizable. Consider adjusting parameters or timeframe.")
        _rlog(run_id, 5, logging.WARNING, f"Stage 5 | {msg}")
        # Note: This will trigger self-healing in the main pipeline loop
        summary = _extract_backtest_summary(result_data, strategy_name)
        summary["per_pair"] = per_pair
        summary["winning_pairs"] = [p["key"] for p in winning_pairs]
        summary["failing_pairs"] = [p["key"] for p in failing_pairs]
        summary["insufficient_pairs"] = True
        _fail_stage(run_id, state, 5, msg, summary)
        return None

    summary = _extract_backtest_summary(result_data, strategy_name)
    summary["per_pair"] = per_pair
    summary["winning_pairs"] = [p["key"] for p in winning_pairs]
    summary["failing_pairs"] = [p["key"] for p in failing_pairs]

    _rlog(run_id, 5, logging.INFO,
          f"Stage 5 | Stress result: {len(winning_pairs)}/{len(per_pair)} pairs passed filtering"
          f"  winning={[p['key'] for p in winning_pairs]}")
    _emit(run_id, 5, "running",
          f"Stress test: {len(winning_pairs)} winning pairs, {len(failing_pairs)} filtered out.", 72)

    _rlog(run_id, 5, logging.INFO,
          f"Stage 5 | PASS | winning={len(winning_pairs)} filtered={len(failing_pairs)} total={len(per_pair)}")
    _pass_stage(run_id, state, 5,
                f"Stress test complete — {len(winning_pairs)}/{len(per_pair)} pairs passed filtering.",
                summary)
    return summary
