"""Stage 1 implementation: Pre-Selection, Pre-Flight Filtering, and Sanity Backtest."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ...policy import load_policy
from ...variants import (
    clone_with_class_name,
    create_variant,
    read_strategy_source,
)
from ..data_healer import _stage_data_healing
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


async def _stage_pre_flight_filtering(
    run_id: str, state: PipelineState, out_dir: Path
) -> dict | None:
    """Stage 1: Pre-Flight Filtering - Data Healing + Baseline Backtest & Pre-Filtering.
    
    This unified stage combines:
    - Sub-step 1: Data Healing (validate and auto-download historical data)
    - Sub-step 2: Baseline Backtest with strict filtering and self-healing
    
    Implements defensive filtering with profit_factor and total_trades checks,
    and self-healing logic with Hard Mutation when insufficient pairs pass.
    """
    _start_stage(run_id, state, 1)
    
    # OOS Isolation Check - ensure OOS never contaminates validation
    from ..oos_guard import log_oos_contamination_warning
    log_oos_contamination_warning(run_id, state, "validation")
    
    # ── Sub-step 1: Data Healing ─────────────────────────────────────────────
    _rlog(run_id, 1, logging.INFO, "── Stage 1 Sub-step 1: Data Healing ──")
    _emit(run_id, 1, "running", "Validating and downloading historical data...", 5)
    
    try:
        data_healing_result = await _stage_data_healing(run_id, state, out_dir)
    except Exception as exc:
        msg = f"Data Healing failed: {exc}"
        _rlog(run_id, 1, logging.ERROR, f"Stage 1 | FAIL | {msg}")
        _fail_stage(run_id, state, 1, msg)
        return None
    
    if _cancelled(run_id):
        raise _Cancelled()
    
    # Get surviving pairs from data healing
    surviving_pairs = state.pair_universe or []
    _rlog(run_id, 1, logging.INFO,
          f"Stage 1 | Data Healing complete: {len(surviving_pairs)} pairs survived")
    
    # ── Sub-step 2: Baseline Backtest & Pre-Filtering ───────────────────────
    _rlog(run_id, 1, logging.INFO, "── Stage 1 Sub-step 2: Baseline Backtest & Pre-Filtering ──")
    _emit(run_id, 1, "running", f"Running baseline backtest on {len(surviving_pairs)} pairs...", 10)
    
    # Self-healing loop for baseline backtest
    max_baseline_retries = 3
    baseline_attempt = 0
    policy = load_policy()
    discovery_gates = policy.thresholds_for(
        state.trading_style,
        state.risk_profile,
        "discovery",
        timerange=state.in_sample_range,
    )
    min_discovery_trades = int(discovery_gates["min_trades"])
    min_discovery_pf = float(discovery_gates["min_profit_factor"])
    min_pairs_required = min(3, max(1, len(surviving_pairs)))
    
    while baseline_attempt <= max_baseline_retries:
        baseline_attempt += 1
        state.phase1_heal_attempts = baseline_attempt - 1
        
        # Build backtest command with comma-separated pairs
        result_prefix = str(out_dir / f"stage1_baseline_attempt{baseline_attempt}")
        cmd = _backtest_cmd(
            state,
            strategy=state.strategy,
            timerange=state.in_sample_range,
            result_prefix=result_prefix,
            pairs=surviving_pairs,
        )
        _rlog(run_id, 1, logging.DEBUG, f"Stage 1 | Spawning baseline backtest subprocess: {' '.join(cmd)}")
        
        rc, stdout, stderr = await _run_subprocess(run_id, cmd, stage=1)
        _rlog(run_id, 1, logging.DEBUG, f"Stage 1 | Baseline backtest exited with rc={rc}")
        
        if _cancelled(run_id):
            raise _Cancelled()
        
        if rc != 0:
            msg = _classify_subprocess_error(rc, stdout, "Stage 1 (Baseline Backtest)")
            _rlog(run_id, 1, logging.ERROR, f"Stage 1 | FAIL | {msg}")
            _fail_stage(run_id, state, 1, msg)
            return None
        
        # Parse backtest results
        result_data = _find_backtest_result(out_dir, f"stage1_baseline_attempt{baseline_attempt}", state.user_data_dir)
        per_pair = _extract_per_pair_results(result_data, state.strategy)
        _rlog(run_id, 1, logging.DEBUG,
              f"Stage 1 | parsed {len(per_pair)} per-pair results: "
              f"{[(p.get('key'), p.get('profit_factor')) for p in per_pair]}")
        
        # ── Defensive Filtering & Division-by-Zero Guard ───────────────────
        passing_pairs = []
        filtered_pairs = []
        
        for pair_data in per_pair:
            pair_key = pair_data.get("key", "")
            profit_factor = pair_data.get("profit_factor", 0.0)
            total_trades = pair_data.get("trades", 0)
            
            # Discovery gates are sourced from policy and are intentionally permissive.
            if total_trades < min_discovery_trades:
                _rlog(run_id, 1, logging.DEBUG,
                      f"Stage 1 | {pair_key}: evicted (insufficient trades: {total_trades} < {min_discovery_trades})")
                filtered_pairs.append({
                    "key": pair_key,
                    "reason": "insufficient_trades",
                    "total_trades": total_trades,
                    "profit_factor": profit_factor,
                })
                continue
            
            # Division-by-zero guard: handle cases where total losses are 0
            # profit_factor is already calculated by freqtrade, but we validate it
            if profit_factor < min_discovery_pf:
                _rlog(run_id, 1, logging.DEBUG,
                      f"Stage 1 | {pair_key}: evicted (profit_factor {profit_factor:.2f} < {min_discovery_pf})")
                filtered_pairs.append({
                    "key": pair_key,
                    "reason": "low_profit_factor",
                    "total_trades": total_trades,
                    "profit_factor": profit_factor,
                })
                continue
            
            # Pair passed all filters
            passing_pairs.append(pair_data)
            _rlog(run_id, 1, logging.DEBUG,
                  f"Stage 1 | {pair_key}: passed (trades={total_trades}, profit_factor={profit_factor:.2f})")
        
        _rlog(run_id, 1, logging.INFO,
              f"Stage 1 | Baseline filtering: {len(passing_pairs)}/{len(per_pair)} pairs passed")
        
        # ── Fail-Safe Gateway & Self-Healing Restart ───────────────────────
        if len(passing_pairs) >= min_pairs_required or state.auto_discovery_enabled:
            if len(passing_pairs) < min_pairs_required:
                fallback_pairs = sorted(
                    per_pair,
                    key=lambda p: (
                        p.get("profit_factor", 0.0),
                        p.get("profit_total", 0.0),
                        p.get("trades", 0),
                    ),
                    reverse=True,
                )[:min_pairs_required]
                passing_pairs = passing_pairs or fallback_pairs
                note = (
                    f"Discovery found {len(passing_pairs)} candidate pair(s), below the "
                    f"{min_pairs_required} pair target; validation will continue with notes."
                )
                state.validation_notes.append(note)
                _rlog(run_id, 1, logging.WARNING, f"Stage 1 | {note}")
            # Success: emit pair selection request and pause for user approval
            _rlog(run_id, 1, logging.INFO,
                  f"Stage 1 | Baseline complete: {len(per_pair)} pairs tested, {len(passing_pairs)} passed thresholds")
            
            # Pre-select pairs that pass thresholds for user convenience
            pre_selected = [p["key"] for p in passing_pairs]

            # Defensive fallback: if the backtest result parsed with zero
            # per-pair rows (e.g. freqtrade omits results_per_pair entirely
            # when there were no trades at all), the review screen would
            # otherwise show "Tested: 0 / Recommended: 0" with nothing to
            # select and no way to proceed. In that case, surface every pair
            # that was actually attempted (including losers/untraded ones)
            # with placeholder metrics so the user can still hand-pick pairs
            # and continue the run.
            review_pairs = per_pair
            if not review_pairs:
                _rlog(run_id, 1, logging.WARNING,
                      f"Stage 1 | Baseline backtest produced 0 per-pair results "
                      f"(likely no trades for any pair); falling back to showing "
                      f"all {len(surviving_pairs)} attempted pairs for manual selection.")
                review_pairs = [
                    {
                        "key": pair,
                        "profit_total": 0.0,
                        "profit_total_abs": 0.0,
                        "profit_factor": 0.0,
                        "trades": 0,
                        "win_rate": 0.0,
                        "max_drawdown": 0.0,
                        "no_trades": True,
                    }
                    for pair in surviving_pairs
                ]

            summary = _extract_backtest_summary(result_data, state.strategy)
            summary["per_pair"] = per_pair
            summary["passing_pairs"] = [p["key"] for p in passing_pairs]
            summary["filtered_pairs"] = filtered_pairs
            summary["baseline_attempts"] = baseline_attempt
            summary["discovery_gates"] = discovery_gates
            summary["validation_notes"] = state.validation_notes
            # Persisted so the review UI (rows + counts) always matches this
            # stage's own data instead of a stale/unrelated discovery run.
            summary["all_pairs"] = review_pairs
            summary["pre_selected"] = pre_selected
            summary["total_tested"] = len(per_pair)
            summary["total_passed"] = len(passing_pairs)
            summary["no_trade_fallback"] = not per_pair
            
            # Emit WebSocket event with all pair results for user selection
            _emit(run_id, 1, "running",
                  f"Baseline complete: {len(per_pair)} pairs tested. Please select pairs to continue.",
                  15,
                  {
                      "type": "pair_selection_request",
                      "all_pairs": review_pairs,
                      "pre_selected": pre_selected,
                      "min_trades": min_discovery_trades,
                      "min_profit_factor": min_discovery_pf,
                      "total_tested": len(per_pair),
                      "total_passed": len(passing_pairs),
                  },
                  msg_type="pair_selection_request")
            
            # Set status to awaiting user approval and save state
            from ..state import _save_state_to_disk
            state.status = "awaiting_user_approval"
            state.current_stage = 1
            state.stages[0].data = summary
            state.stages[0].status = "running"  # Keep as running, not passed
            _save_state_to_disk(state)
            
            _rlog(run_id, 1, logging.INFO,
                  f"Stage 1 | PAUSED: Awaiting user approval for pair selection")
            return summary
        
        # Insufficient pairs - trigger self-healing
        if baseline_attempt < max_baseline_retries:
            _rlog(run_id, 1, logging.WARNING,
                  f"Stage 1 | Only {len(passing_pairs)} pairs passed (< {min_pairs_required}). "
                  f"Triggering self-healing attempt {baseline_attempt}/{max_baseline_retries}")

            # Apply Hard Mutation: force core boolean switches to True
            try:
                source = read_strategy_source(state)
                mutation_name = f"{state.original_strategy or state.strategy}_BaselineMutation{baseline_attempt}"
                source = clone_with_class_name(source, mutation_name)
                
                # Force boolean indicators to True
                mutations = {
                    "use_ema_cross": False,
                    "use_atr": False,
                    "use_adx": False,
                    "use_rsi": False,
                    "use_macd": False,
                    "use_bollinger": False,
                }
                
                # Check which indicators exist and force them to True
                for indicator in mutations:
                    if f"{indicator} = " in source:
                        source = re.sub(
                            rf"{indicator}\s*=\s*(True|False)",
                            f"{indicator} = True",
                            source
                        )
                        mutations[indicator] = True
                
                mutation_path = create_variant(
                    state,
                    role="mutation",
                    strategy_name=mutation_name,
                    source=source,
                )
                state.strategy = mutation_name
                _rlog(run_id, 1, logging.INFO,
                      f"Stage 1 | Hard Mutation variant applied: {mutation_path.name}")
                
                # Emit WebSocket event
                _emit(run_id, 1, "running",
                      f"Self-healing attempt {baseline_attempt}/{max_baseline_retries}: "
                      f"Applying Hard Mutation to strategy...",
                      -1,
                      {
                          "type": "phase1_self_heal",
                          "attempt": baseline_attempt,
                          "surviving_count": len(passing_pairs),
                          "mutation_applied": "Hard Mutation Framework",
                          "mutations_applied": [k for k, v in mutations.items() if v],
                          "variant_path": str(mutation_path),
                      },
                      msg_type="phase1_self_heal")
                
                # Restart from Sub-step 1 (Data Healing) with mutated strategy
                _rlog(run_id, 1, logging.INFO,
                      f"Stage 1 | Restarting from Data Healing with mutated strategy...")
                continue
                
            except Exception as exc:
                _rlog(run_id, 1, logging.ERROR,
                      f"Stage 1 | Failed to apply Hard Mutation: {exc}")
                # Fall through to failure
                break
        else:
            # Max retries exceeded - fail the pipeline
            _rlog(run_id, 1, logging.ERROR,
                  f"Stage 1 | FAIL: Strategy failed to find 3 viable trading pairs after "
                  f"{max_baseline_retries} self-healing attempts")
            
            summary = _extract_backtest_summary(result_data, state.strategy)
            summary["per_pair"] = per_pair
            summary["passing_pairs"] = [p["key"] for p in passing_pairs]
            summary["filtered_pairs"] = filtered_pairs
            summary["baseline_attempts"] = baseline_attempt
            summary["healing_exhausted"] = True
            
            msg = (f"Strategy failed to find 3 viable trading pairs after "
                   f"{max_baseline_retries} self-healing attempts. "
                   f"Only {len(passing_pairs)} pairs passed baseline filtering.")
            _fail_stage(run_id, state, 1, msg, summary)
            return None
    
    # Should not reach here, but handle gracefully
    msg = "Stage 1: Unexpected exit from baseline backtest loop"
    _rlog(run_id, 1, logging.ERROR, msg)
    _fail_stage(run_id, state, 1, msg)
    return None


# Legacy function for backward compatibility
async def _stage_sanity_backtest(
    run_id: str, state: PipelineState, out_dir: Path
) -> dict | None:
    _start_stage(run_id, state, 1)
    _rlog(run_id, 1, logging.INFO,
          f"Stage 1 | Sanity Backtest (Legacy) | strategy={state.strategy} | range={state.in_sample_range} | tf={state.timeframe}")
    _emit(run_id, 1, "running", f"Running sanity backtest for {state.strategy} on {state.in_sample_range}...", 5)

    result_prefix = str(out_dir / "stage1_result")
    cmd = _backtest_cmd(
        state,
        strategy=state.strategy,
        timerange=state.in_sample_range,
        result_prefix=result_prefix,
        pairs=[state.pair] if state.pair else None,
    )
    _rlog(run_id, 1, logging.DEBUG, f"Stage 1 | Spawning subprocess: {' '.join(cmd)}")

    rc, stdout, stderr = await _run_subprocess(run_id, cmd, stage=1)
    _rlog(run_id, 1, logging.DEBUG, f"Stage 1 | Subprocess exited with rc={rc}")

    if _cancelled(run_id):
        raise _Cancelled()

    if rc != 0:
        msg = _classify_subprocess_error(rc, stdout, "Stage 1 (Sanity Backtest)")
        _rlog(run_id, 1, logging.ERROR, f"Stage 1 | FAIL | {msg}")
        _fail_stage(run_id, state, 1, msg)
        return None

    # Look for a result file
    result_data = _find_backtest_result(out_dir, "stage1_result", state.user_data_dir)
    trade_count = _extract_trade_count(result_data, state.strategy)
    _rlog(run_id, 1, logging.DEBUG, f"Stage 1 | Parsed result file: trade_count={trade_count}")

    if trade_count == 0:
        msg = "Sanity backtest produced 0 trades. Strategy has no signals in this timerange."
        _rlog(run_id, 1, logging.ERROR, f"Stage 1 | FAIL | {msg}")
        _fail_stage(run_id, state, 1, msg)
        return None

    summary = _extract_backtest_summary(result_data, state.strategy)
    trade_dist = _extract_trade_distribution(result_data, state.strategy)
    summary["trade_distribution"] = trade_dist
    _rlog(run_id, 1, logging.INFO,
          f"Stage 1 | PASS | trades={trade_count}  profit_abs={summary.get('profit_total_abs', 0):.4f}"
          f"  max_dd={summary.get('max_drawdown_account', 0) * 100:.1f}%")
    _pass_stage(run_id, state, 1,
                f"Sanity backtest passed — {trade_count} trades, "
                f"profit {summary.get('profit_total_abs', 0):.2f}",
                summary)
    return summary
