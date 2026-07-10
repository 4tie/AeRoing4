"""Stage 3 implementation: Out-of-Sample Validation."""

from __future__ import annotations

import logging
from pathlib import Path

from ...profit_lockin import compute_profit_giveback_metrics, extract_strategy_trades
from ..helpers import (
    _backtest_cmd,
    _classify_subprocess_error,
    _emit,
    _extract_backtest_summary,
    _extract_per_pair_results,
    _extract_trade_count,
    _extract_trade_distribution,
    _fail_stage,
    _find_backtest_result,
    _pass_stage,
    _run_subprocess,
    _start_stage,
)
from ..logging import _rlog
from ..state import PipelineState, _Cancelled, _cancelled


async def _stage_oos_validation(
    run_id: str,
    state: PipelineState,
    out_dir: Path,
    optimized_path: Path,
    *,
    record_stage: bool = True,
    stage_idx: int = 3,
) -> dict | None:
    if record_stage:
        _start_stage(run_id, state, stage_idx)
    strategy_name = optimized_path.stem
    # Use selected_pairs from Stage 1 pre-selection
    pairs_to_test = [p["key"] for p in state.selected_pairs] if state.selected_pairs else ([state.pair] if state.pair else None)
    _rlog(run_id, 3, logging.INFO,
          f"Stage 3 | OOS Validation | strategy={strategy_name} | range={state.out_sample_range}"
          f" | pairs={len(pairs_to_test) if pairs_to_test else 'all'}"
          f" | min_profit_threshold={state.min_oos_profit} | max_dd_threshold={state.max_drawdown_threshold:.2f}")
    _emit(run_id, stage_idx, "running",
          f"Running out-of-sample validation on {state.out_sample_range}...", 55)

    result_prefix = str(out_dir / "stage3_result")
    cmd = _backtest_cmd(
        state,
        strategy=strategy_name,
        timerange=state.out_sample_range,
        result_prefix=result_prefix,
        pairs=pairs_to_test,
    )
    _rlog(run_id, 3, logging.DEBUG, f"Stage 3 | Spawning subprocess: {' '.join(cmd)}")

    rc, stdout, stderr = await _run_subprocess(run_id, cmd, stage=3)
    _rlog(run_id, 3, logging.DEBUG, f"Stage 3 | Subprocess exited with rc={rc}")

    if _cancelled(run_id):
        raise _Cancelled()

    if rc != 0:
        msg = _classify_subprocess_error(rc, stdout, "Stage 3 (OOS Validation)")
        _rlog(run_id, 3, logging.ERROR, f"Stage 3 | FAIL | {msg}")
        if record_stage:
            _fail_stage(run_id, state, stage_idx, msg)
        else:
            state.generalization_failure = {
                "stage": "oos_validation",
                "reason": "subprocess_failed",
                "message": msg,
            }
        return None

    result_data = _find_backtest_result(out_dir, "stage3_result", state.user_data_dir)
    summary = _extract_backtest_summary(result_data, strategy_name)
    trade_dist = _extract_trade_distribution(result_data, strategy_name)
    summary["trade_distribution"] = trade_dist
    profit_giveback = compute_profit_giveback_metrics(
        extract_strategy_trades(result_data, strategy_name)
    )
    summary["profit_giveback"] = profit_giveback

    profit_total = summary.get("profit_total", 0.0)
    max_dd = summary.get("max_drawdown_account", 0.0) * 100
    trade_count = _extract_trade_count(result_data, strategy_name)
    _rlog(run_id, 3, logging.DEBUG,
          f"Stage 3 | Parsed OOS result: profit={profit_total:.4f} max_dd={max_dd:.2f}% trades={trade_count}")

    if trade_count == 0:
        _rlog(run_id, 3, logging.WARNING,
              "Stage 3 | NO TRADES | OOS backtest produced zero trades — signalling retry loop")
        _record_oos_retry_failure(
            state,
            {"profit": profit_total, "drawdown": max_dd, "trades": trade_count, "reason": "no_trades"},
            record_stage=record_stage,
            stage_idx=stage_idx,
        )
        return "retry"  # type: ignore[return-value]

    if profit_giveback["peak_to_loss_count"] > 0:
        _rlog(run_id, 3, logging.WARNING,
              "Stage 3 | PROFIT GIVEBACK | "
              f"{profit_giveback['peak_to_loss_count']} trade(s) reached tier-1 profit "
              "then closed negative — signalling retry loop")
        _record_oos_retry_failure(
            state,
            {
                "profit": profit_total,
                "drawdown": max_dd,
                "trades": trade_count,
                "reason": "profit_giveback",
                "profit_giveback": profit_giveback,
            },
            record_stage=record_stage,
            stage_idx=stage_idx,
        )
        return "retry"  # type: ignore[return-value]

    max_drawdown_threshold_pct = (
        state.max_drawdown_threshold * 100
        if state.max_drawdown_threshold <= 1
        else state.max_drawdown_threshold
    )
    _profit_fail = profit_total < state.min_oos_profit
    _dd_fail = max_dd > max_drawdown_threshold_pct

    if _profit_fail and _dd_fail:
        _rlog(run_id, 3, logging.WARNING,
              f"Stage 3 | COMPOUND FAIL | profit={profit_total:.4f} < {state.min_oos_profit} AND "
              f"max_dd={max_dd:.2f} > {max_drawdown_threshold_pct:.2f} — signalling retry loop")
        _record_oos_retry_failure(
            state,
            {"profit": profit_total, "drawdown": max_dd, "trades": trade_count, "reason": "both"},
            record_stage=record_stage,
            stage_idx=stage_idx,
        )
        return "retry"  # type: ignore[return-value]

    if _profit_fail:
        _rlog(run_id, 3, logging.WARNING,
              f"Stage 3 | OVERFIT | profit={profit_total:.4f} < threshold={state.min_oos_profit}"
              f" — signalling retry loop")
        _record_oos_retry_failure(
            state,
            {"profit": profit_total, "drawdown": max_dd, "trades": trade_count, "reason": "profit"},
            record_stage=record_stage,
            stage_idx=stage_idx,
        )
        return "retry"  # type: ignore[return-value]

    if _dd_fail:
        _rlog(run_id, 3, logging.WARNING,
              f"Stage 3 | HIGH DD | max_dd={max_dd:.2f} > threshold={max_drawdown_threshold_pct:.2f}"
              f" — signalling retry loop")
        _record_oos_retry_failure(
            state,
            {"profit": profit_total, "drawdown": max_dd, "trades": trade_count, "reason": "drawdown"},
            record_stage=record_stage,
            stage_idx=stage_idx,
        )
        return "retry"  # type: ignore[return-value]

    _rlog(run_id, 3, logging.INFO,
          f"Stage 3 | PASS | profit={profit_total:.4f}  max_dd={max_dd:.2f}  trades={trade_count}")
    state.oos_validation_result = summary
    if record_stage:
        _pass_stage(run_id, state, stage_idx,
                    f"OOS validation passed — profit {profit_total:.4f}, "
                    f"drawdown {max_dd:.2f}, trades {trade_count}",
                    summary)
    return summary


def _record_oos_retry_failure(
    state: PipelineState,
    failed_metrics: dict,
    *,
    record_stage: bool,
    stage_idx: int,
) -> None:
    payload = {"_failed_metrics": failed_metrics}
    if record_stage and 0 < stage_idx <= len(state.stages):
        state.stages[stage_idx - 1].data = payload
    state.generalization_failure = {
        "stage": "oos_validation",
        "reason": failed_metrics.get("reason"),
        "failed_metrics": failed_metrics,
        "attempts": state.retry_history,
        "best_attempt": max(state.retry_history, key=lambda a: a.get("profit") or -999.0)
        if state.retry_history else None,
    }
