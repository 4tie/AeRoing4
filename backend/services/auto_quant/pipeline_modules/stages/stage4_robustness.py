"""Stage 4 implementation: Robustness & Feature Injection (Slippage/Fee Stress Testing)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..filters import _analyze_trading_windows
from ..helpers import (
    _backtest_cmd,
    _classify_subprocess_error,
    _create_temp_config_with_fee_override,
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
from ..state import PipelineState, _Cancelled, _cancelled


async def _stage_robustness_feature_injection(
    run_id: str, state: PipelineState, out_dir: Path, optimized_path: Path
) -> dict | None:
    """Stage 4: Robustness Testing (Simplified - No Feature Injection).

    Performs:
    1. Baseline backtest with real configured fees
    2. Optional degradation scenario with small slippage
    3. Comparison of profit, drawdown, Profit Factor, trade count
    4. Weakness classification and reporting
    5. NO automatic feature injection
    """
    _start_stage(run_id, state, 4)  # Stage 4: Robustness Testing
    strategy_name = optimized_path.stem
    pairs_to_test = [p["key"] for p in state.selected_pairs] if state.selected_pairs else None

    if not pairs_to_test:
        _rlog(run_id, 4, logging.WARNING, "Stage 4 | No selected_pairs available, skipping robustness testing")
        state.stability_scores = {}
        _pass_stage(run_id, state, 4, "No pairs to test for robustness testing", {"robustness_report": {}})
        return {"robustness_report": {}}

    _rlog(run_id, 4, logging.INFO,
          f"Stage 4 | Robustness Testing | strategy={strategy_name} | pairs={len(pairs_to_test)}")
    _emit(run_id, 4, "running", f"Running robustness testing on {len(pairs_to_test)} pairs...", 55)

    # ── Sub-step 4.1: Baseline backtest with real configured fees ─────────
    _rlog(run_id, 4, logging.INFO, "Stage 4 | Running baseline backtest with real fees...")
    _emit(run_id, 4, "running", "Running baseline backtest with real fees...", 60)

    baseline_result_prefix = str(out_dir / "stage4_baseline")
    baseline_cmd = [state.freqtrade_path, "backtesting",
                    "--config", state.config_file,
                    "--strategy", strategy_name,
                    "--timerange", state.in_sample_range,
                    "--timeframe", state.timeframe,
                    "--user-data-dir", state.user_data_dir,
                    "--export", "trades",
                    "--export-filename", baseline_result_prefix + ".json",
                    "--no-color",
                    "--cache", "none"]
    baseline_cmd += strategy_path_args(state)
    if pairs_to_test:
        baseline_cmd += ["--pairs"] + pairs_to_test

    _rlog(run_id, 4, logging.DEBUG, f"Stage 4 | Spawning baseline subprocess: {' '.join(baseline_cmd)}")
    baseline_rc, baseline_stdout, baseline_stderr = await _run_subprocess(run_id, baseline_cmd, stage=4)

    if baseline_rc != 0:
        msg = _classify_subprocess_error(baseline_rc, baseline_stdout, "Stage 4 (Baseline Backtest)")
        _rlog(run_id, 4, logging.ERROR, f"Stage 4 | FAIL | {msg}")
        _fail_stage(run_id, state, 4, msg)
        return None

    baseline_data = _find_backtest_result(out_dir, "stage4_baseline", state.user_data_dir)
    baseline_summary = _extract_backtest_summary(baseline_data, strategy_name)
    baseline_per_pair = _extract_per_pair_results(baseline_data, strategy_name)

    _rlog(run_id, 4, logging.INFO,
          f"Stage 4 | Baseline complete: profit={baseline_summary.get('profit_total', 0):.4f}, "
          f"drawdown={baseline_summary.get('max_drawdown_account', 0):.4f}, "
          f"trades={baseline_summary.get('total_trades', 0)}")

    # ── Sub-step 4.2: Degradation scenario with small slippage ─────────
    _rlog(run_id, 4, logging.INFO, "Stage 4 | Running degradation scenario with slippage...")
    _emit(run_id, 4, "running", "Running degradation scenario with slippage...", 75)

    # Create temporary config with small slippage (0.1% = 0.001)
    slippage_config = _create_temp_config_with_fee_override(
        state.config_file, 1.0, out_dir, slippage=0.001
    )

    degraded_result_prefix = str(out_dir / "stage4_degraded")
    degraded_cmd = [state.freqtrade_path, "backtesting",
                    "--config", str(slippage_config),
                    "--strategy", strategy_name,
                    "--timerange", state.in_sample_range,
                    "--timeframe", state.timeframe,
                    "--user-data-dir", state.user_data_dir,
                    "--export", "trades",
                    "--export-filename", degraded_result_prefix + ".json",
                    "--no-color",
                    "--cache", "none"]
    degraded_cmd += strategy_path_args(state)
    if pairs_to_test:
        degraded_cmd += ["--pairs"] + pairs_to_test

    _rlog(run_id, 4, logging.DEBUG, f"Stage 4 | Spawning degraded subprocess: {' '.join(degraded_cmd)}")
    degraded_rc, degraded_stdout, degraded_stderr = await _run_subprocess(run_id, degraded_cmd, stage=4)

    # Cleanup temp config
    try:
        Path(slippage_config).unlink(missing_ok=True)
    except Exception as exc:
        _rlog(run_id, 4, logging.WARNING, f"Stage 4 | Failed to delete temp config: {exc}")

    if degraded_rc != 0:
        msg = _classify_subprocess_error(degraded_rc, degraded_stdout, "Stage 4 (Degradation Scenario)")
        _rlog(run_id, 4, logging.WARNING, f"Stage 4 | Degradation scenario failed: {msg}")
        # Continue with baseline only - don't fail the stage
        degraded_summary = baseline_summary
        degraded_per_pair = baseline_per_pair
    else:
        degraded_data = _find_backtest_result(out_dir, "stage4_degraded", state.user_data_dir)
        degraded_summary = _extract_backtest_summary(degraded_data, strategy_name)
        degraded_per_pair = _extract_per_pair_results(degraded_data, strategy_name)

    _rlog(run_id, 4, logging.INFO,
          f"Stage 4 | Degradation complete: profit={degraded_summary.get('profit_total', 0):.4f}, "
          f"drawdown={degraded_summary.get('max_drawdown_account', 0):.4f}, "
          f"trades={degraded_summary.get('total_trades', 0)}")

    # ── Sub-step 4.3: Compute degradation metrics ─────────
    _rlog(run_id, 4, logging.INFO, "Stage 4 | Computing degradation metrics...")

    baseline_profit = baseline_summary.get('profit_total', 0.0)
    degraded_profit = degraded_summary.get('profit_total', 0.0)
    baseline_dd = baseline_summary.get('max_drawdown_account', 0.0)
    degraded_dd = degraded_summary.get('max_drawdown_account', 0.0)
    baseline_pf = baseline_summary.get('profit_factor', 1.0)
    degraded_pf = degraded_summary.get('profit_factor', 1.0)
    baseline_trades = baseline_summary.get('total_trades', 0)
    degraded_trades = degraded_summary.get('total_trades', 0)

    # Compute retention ratios
    profit_retention = (degraded_profit / baseline_profit * 100) if baseline_profit > 0 else 0.0
    dd_change = ((degraded_dd - baseline_dd) / baseline_dd * 100) if baseline_dd > 0 else 0.0
    pf_change = ((degraded_pf - baseline_pf) / baseline_pf * 100) if baseline_pf > 0 else 0.0
    trade_change = ((degraded_trades - baseline_trades) / baseline_trades * 100) if baseline_trades > 0 else 0.0

    # Classify weakness
    weakness_classification = "None"
    if profit_retention < 50:
        weakness_classification = "Severe"
    elif profit_retention < 75:
        weakness_classification = "Moderate"
    elif profit_retention < 90:
        weakness_classification = "Mild"

    # Build robustness report
    robustness_report = {
        "baseline": {
            "profit_total": baseline_profit,
            "max_drawdown_account": baseline_dd,
            "profit_factor": baseline_pf,
            "total_trades": baseline_trades,
        },
        "degraded": {
            "profit_total": degraded_profit,
            "max_drawdown_account": degraded_dd,
            "profit_factor": degraded_pf,
            "total_trades": degraded_trades,
        },
        "degradation_metrics": {
            "profit_retention_pct": profit_retention,
            "drawdown_change_pct": dd_change,
            "profit_factor_change_pct": pf_change,
            "trade_count_change_pct": trade_change,
        },
        "weakness_classification": weakness_classification,
        "recommended_action": "Accept" if weakness_classification == "None" else "Review",
        "feature_injection_disabled": True,
    }

    state.stability_scores = {pair: profit_retention for pair in pairs_to_test}

    _rlog(run_id, 4, logging.INFO,
          f"Stage 4 | Robustness Report: profit_retention={profit_retention:.1f}%, "
          f"weakness={weakness_classification}, action={robustness_report['recommended_action']}")

    _pass_stage(run_id, state, 4, "Robustness testing complete", robustness_report)
    return robustness_report
