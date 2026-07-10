"""Stage implementations for optimization stages (2)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..ai_suggestions import create_pending_suggestion, optimization_stage_index
from ..ollama_service import ask_ollama_for_wfa_fix
from ..policy import load_policy, walk_forward_windows_for_depth
from ..profit_lockin import ensure_profit_lockin_hyperopt_loss
from ..variants import active_strategy_path, create_variant, read_strategy_source, strategy_path_args
from .config import _generate_wfo_windows, AUTOQUANT_WFO_ENABLED
from .helpers import (
    _aggregate_wfa_parameters,
    _backtest_cmd,
    _classify_subprocess_error,
    _emit,
    _extract_backtest_summary,
    _extract_hyperopt_best,
    _extract_per_pair_results,
    _fail_stage,
    _find_backtest_result,
    _inject_params,
    _pass_stage,
    _run_subprocess,
    _start_stage,
)
from .logging import _rlog
from .oos_guard import extract_pure_is_range, log_oos_contamination_warning
from .state import PipelineState, _Cancelled, _cancelled, _save_state_to_disk


def _strategy_has_profit_lockin_tiers(state: PipelineState) -> bool:
    """Return True when the source strategy contains optimized lock-in tiers."""
    strategy_path = active_strategy_path(state)
    try:
        source = strategy_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Stage Optimization | failed to read strategy file %s: %s", strategy_path, exc)
        return False
    return any(
        token in source
        for token in (
            "ts_tier1_trigger",
            "ts_tier1_lock",
            "ts_tier2_trigger",
            "ts_tier2_lock",
            "ts_tier3_trigger",
            "ts_tier3_lock",
        )
    )


def _strategy_has_buy_space_params(state: PipelineState) -> bool:
    """Return True when the source strategy defines parameters in the buy space."""
    strategy_path = active_strategy_path(state)
    try:
        source = strategy_path.read_text(encoding="utf-8")
    except Exception as exc:
        logging.warning("Stage Optimization | failed to read strategy file %s: %s", strategy_path, exc)
        return False

    return bool(re.search(r"\bspace\s*=\s*['\"]buy['\"]", source))


def _prepare_hyperopt_loss(state: PipelineState) -> None:
    if state.hyperopt_loss == "ProfitLockinHyperOptLoss":
        ensure_profit_lockin_hyperopt_loss(state.user_data_dir)


async def _stage_hyperopt(
    run_id: str, state: PipelineState, out_dir: Path, pairs: list | None = None
) -> dict | None:
    """Dispatcher: routes to WFO or standard hyperopt based on feature flag and state.wfo_enabled."""
    _start_stage(run_id, state, 3)  # Stage 3: Standard Hyperopt (1-based indexing)
    
    # Force Standard Hyperopt when WFO is disabled by feature flag
    if not AUTOQUANT_WFO_ENABLED:
        from .logging import _rlog
        import logging
        _rlog(run_id, 3, logging.INFO, "WFO disabled by feature flag - using Standard Hyperopt")
        state.wfo_enabled = False  # Ensure state reflects the feature flag
        return await _stage_hyperopt_standard(run_id, state, out_dir, pairs)
    
    if state.wfo_enabled:
        return await _stage_hyperopt_wfo(run_id, state, out_dir, pairs)
    return await _stage_hyperopt_standard(run_id, state, out_dir, pairs)


async def _stage_hyperopt_standard(
    run_id: str, state: PipelineState, out_dir: Path, pairs: list | None = None
) -> dict | None:
    """Standard (non-WFO) hyperopt over the full in-sample range."""
    _prepare_hyperopt_loss(state)

    # OOS Isolation Check - ensure OOS never contaminates hyperopt
    log_oos_contamination_warning(run_id, state, "hyperopt")
    
    # Use pure IS range to prevent any OOS contamination
    pure_is_range = extract_pure_is_range(state)

    # Use selected_pairs from Stage 1 if not provided
    if pairs is None and state.selected_pairs:
        pairs = [p["key"] for p in state.selected_pairs]

    # On retry runs, delete stale hyperopt artifacts so the new attempt starts clean.
    if state.retry_count > 0:
        for stale in [
            out_dir / "hyperopt_best.json",
            out_dir / "stage4_result.json",
        ]:
            if stale.exists():
                try:
                    stale.unlink()
                    _rlog(run_id, 2, logging.DEBUG,
                          f"Stage 2 | Deleted stale artifact: {stale.name}")
                except Exception as exc:
                    _rlog(run_id, 2, logging.WARNING,
                          f"Stage 2 | Failed to delete stale artifact {stale.name}: {exc}")

    # Apply hard mutation parameter overrides if present
    original_strategy = state.strategy
    if hasattr(state, 'param_overrides') and state.param_overrides:
        _rlog(run_id, 2, logging.INFO,
              f"Stage 2 | Applying parameter overrides: {list(state.param_overrides.keys())}")
        try:
            source = read_strategy_source(state, original_strategy)
            # Create a temporary strategy with overrides applied
            temp_strat_name = f"{original_strategy}_HardMutation"
            from .helpers import _inject_params
            # Create a minimal best_params dict to carry the overrides
            override_params = {"params_dict": state.param_overrides}
            patched = _inject_params(source, temp_strat_name, override_params, state.param_overrides)
            temp_path = create_variant(
                state,
                role="mutation",
                strategy_name=temp_strat_name,
                source=patched,
            )
            # Use the temp strategy for this hyperopt run
            state.strategy = temp_strat_name
            _rlog(run_id, 2, logging.DEBUG,
                  f"Stage 2 | Created temporary strategy with overrides: {temp_strat_name}")
        except Exception as exc:
            _rlog(run_id, 2, logging.WARNING,
                  f"Stage 2 | Failed to apply parameter overrides: {exc}")

    # Always include 'buy' on the first run so entry parameters are optimized.
    # For generated Omni lock-in strategies, keep 'buy' even on retries so the
    # custom stoploss tier net remains part of the search.
    effective_spaces = [space for space in state.hyperopt_spaces]
    has_buy_space = _strategy_has_buy_space_params(state)
    if "buy" in effective_spaces and not has_buy_space:
        effective_spaces = [space for space in effective_spaces if space != "buy"]
        _rlog(run_id, 2, logging.WARNING,
              "Stage 2 | Removing explicit 'buy' space because the strategy defines no buy-space parameters.")

    needs_buy_space = state.retry_count == 0 or _strategy_has_profit_lockin_tiers(state)
    if needs_buy_space and "buy" not in effective_spaces:
        if has_buy_space:
            effective_spaces.insert(0, "buy")
            _rlog(run_id, 2, logging.INFO,
                  "Stage 2 | Injecting 'buy' space so strategy buy-space parameters are optimized.")
        else:
            _rlog(run_id, 2, logging.INFO,
                  "Stage 2 | Strategy has no buy-space parameters; skipping implicit 'buy' optimization.")

    _rlog(run_id, 3, logging.INFO,
          f"Stage 3 | Hyperopt Execution | epochs={state.hyperopt_epochs}"
          f" | loss={state.hyperopt_loss}"
          f" | spaces={','.join(effective_spaces)} | range={pure_is_range}"
          f" | pairs={len(pairs) if pairs else 'all'}")
    _emit(run_id, 3, "running", "Starting hyperopt — this may take several minutes...", 20)

    cmd = [
        state.freqtrade_path, "hyperopt",
        "--config", state.config_file,
        "--strategy", state.strategy,
        "--hyperopt-loss", state.hyperopt_loss,
        "--spaces", *effective_spaces,
        "--epochs", str(state.hyperopt_epochs),
        "--timerange", pure_is_range,
        "--timeframe", state.timeframe,
        "--user-data-dir", state.user_data_dir,
        "--no-color",
        "-j", str(state.hyperopt_workers),
    ]
    cmd += strategy_path_args(state)

    # Add pairs to command if provided
    if pairs:
        cmd.extend(["--pairs", *pairs])
    _rlog(run_id, 2, logging.DEBUG, f"Stage 2 | Spawning subprocess: {' '.join(cmd)}")

    rc, stdout, stderr = await _run_subprocess(run_id, cmd, stage=2, stream=True)
    _rlog(run_id, 2, logging.DEBUG, f"Stage 2 | Subprocess exited with rc={rc}")

    if _cancelled(run_id):
        raise _Cancelled()

    if rc != 0:
        msg = _classify_subprocess_error(rc, stdout, "Stage 3 (Hyperopt Execution)")
        _rlog(run_id, 3, logging.ERROR, f"Stage 3 | FAIL | {msg}")
        _fail_stage(run_id, state, 3, msg)
        return None

    # Try to extract best params using hyperopt-show
    # IMPORTANT: Extract BEFORE restoring original strategy name, because hyperopt
    # results are stored under the mutated strategy name (e.g., AIStrategy_HardMutation)
    _rlog(run_id, 2, logging.DEBUG, "Stage 2 | Extracting best params via hyperopt-show…")
    best_params = await _extract_hyperopt_best(state, out_dir)
    
    # Restore original strategy name and clean up temp file if we used one
    if hasattr(state, 'param_overrides') and state.param_overrides and state.strategy != original_strategy:
        _rlog(run_id, 2, logging.DEBUG,
              f"Stage 2 | Restoring original strategy name: {original_strategy} (was {state.strategy})")
        state.strategy = original_strategy
        # Clear param_overrides after use
        state.param_overrides = {}
    
    if best_params is None:
        msg = (
            "```\n"
            "ERROR: Hyperopt completed but could not extract best parameters\n"
            "```\n\n"
            "Root cause: Hyperopt produced 0 trades across all epochs\n\n"
            "Common causes:\n"
            "- Strategy configuration prevents trading\n"
            "- Timerange has insufficient data\n"
            "- Hyperopt spaces are misconfigured"
        )
        _rlog(run_id, 3, logging.ERROR, f"Stage 3 | FAIL | {msg}")
        _fail_stage(run_id, state, 3, msg)
        return None

    # ── Store baseline trade counts for Phase 4 capital starvation detection ──
    _rlog(run_id, 2, logging.INFO, "Stage 2 | Running baseline backtest to capture trade counts...")
    result_prefix = str(out_dir / "stage2_baseline")
    cmd = _backtest_cmd(
        state,
        strategy=state.strategy,
        timerange=state.in_sample_range,
        result_prefix=result_prefix,
        pairs=pairs,
    )
    rc, stdout, stderr = await _run_subprocess(run_id, cmd, stage=2)
    
    if rc == 0:
        result_data = _find_backtest_result(out_dir, "stage2_baseline", state.user_data_dir)
        per_pair = _extract_per_pair_results(result_data, state.strategy)
        # Store baseline trade counts in state for Phase 4
        state.baseline_trade_counts = {p["key"]: p.get("trades", 0) for p in per_pair}
        _rlog(run_id, 2, logging.INFO,
              f"Stage 2 | Stored baseline trade counts for {len(state.baseline_trade_counts)} pairs")
        _save_state_to_disk(state)
    else:
        _rlog(run_id, 2, logging.WARNING,
              "Stage 2 | Failed to run baseline backtest for trade counts, continuing without baseline data")
        state.baseline_trade_counts = {}

    _rlog(run_id, 3, logging.INFO,
          f"Stage 3 | PASS | best_loss={best_params.get('loss', 'N/A')}  params_keys={list(best_params.get('params_dict', {}).keys())}")
    _pass_stage(run_id, state, 3,
                f"Hyperopt completed — best loss: {best_params.get('loss', 'N/A')}",
                {"best_params": best_params})
    return best_params


async def _stage_hyperopt_wfo(
    run_id: str, state: PipelineState, out_dir: Path, pairs: list | None = None
) -> dict | None:
    """Walk-Forward Optimization: roll (IS, OOS) windows over in_sample_range.

    For each window:
      1. Run hyperopt on IS sub-period.
      2. Patch a temp strategy with the window's best params.
      3. Validate on OOS sub-period.
      4. Emit a wfo_window WS event with per-window metrics.

    The most recent window's params become the final best_params handed to
    Stage 3 (patch) and Stage 4 (full OOS).  The full out_sample_range
    remains pristine as the held-out test set.
    """
    _prepare_hyperopt_loss(state)

    # OOS Isolation Check - ensure OOS never contaminates WFO
    log_oos_contamination_warning(run_id, state, "wfo")

    # Use selected_pairs from Stage 1 if not provided
    if pairs is None and state.selected_pairs:
        pairs = [p["key"] for p in state.selected_pairs]

    # Use policy-based WFO windows for depth-aware window generation
    policy_windows = walk_forward_windows_for_depth(state.analysis_depth)
    n = len(policy_windows)
    
    # Convert policy windows to tuple format for compatibility
    windows = [(w["train"], w["test"]) for w in policy_windows]

    policy = load_policy()
    min_windows = policy.min_wfo_windows()

    # Skip WFO with validation note if insufficient windows
    if n < min_windows:
        skip_note = policy.wfo_skip_note(n)
        state.validation_notes.append(skip_note)
        state.wfo_windows = []
        # Store skip reason for report
        if not hasattr(state, 'wfo_skip_reason'):
            state.wfo_skip_reason = skip_note
        _rlog(run_id, 3, logging.WARNING,
              f"WFO: {skip_note}")
        _emit(run_id, 3, "running",
              f"WFO skipped (insufficient windows: {n} < {min_windows}) — falling back to standard hyperopt.", 18)
        return await _stage_hyperopt_standard(run_id, state, out_dir, pairs)

    _rlog(run_id, 3, logging.INFO,
          f"WFO | {n} windows | IS={state.wfo_is_months}m OOS={state.wfo_oos_months}m "
          f"recency_weight={state.wfo_recency_weight}")
    _emit(run_id, 3, "running",
          f"Walk-Forward Optimization: {n} windows "
          f"(IS={state.wfo_is_months}m / OOS={state.wfo_oos_months}m)…", 18)

    # Always include 'buy' so CategoricalParameter / adaptive params are optimised
    effective_spaces = list(state.hyperopt_spaces)
    has_buy_space = _strategy_has_buy_space_params(state)
    if "buy" in effective_spaces and not has_buy_space:
        effective_spaces = [space for space in effective_spaces if space != "buy"]
        _rlog(run_id, 3, logging.WARNING,
              "Stage 3 WFO | Removing explicit 'buy' space because the strategy defines no buy-space parameters.")
    if "buy" not in effective_spaces and has_buy_space:
        effective_spaces.insert(0, "buy")

    wfo_results: list[dict] = []
    passing_window_params: list[dict] = []  # Track params from passing segments
    passing_window_weights: list[float] = []  # Track recency weights for aggregation
    last_good_params: dict | None = None
    last_good_window: int | None = None

    for i, (is_range, oos_range) in enumerate(windows):
        wnum = i + 1

        if _cancelled(run_id):
            raise _Cancelled()

        # ── Hyperopt on IS window ──────────────────────────────────────────
        _rlog(run_id, 3, logging.INFO,
              f"WFO W{wnum}/{n} | Hyperopt IS={is_range}")
        _emit(run_id, 3, "running",
              f"WFO Window {wnum}/{n}: hyperopt IS={is_range}…",
              20 + int(i / n * 30))

        hp_cmd = [
            state.freqtrade_path, "hyperopt",
            "--config", state.config_file,
            "--strategy", state.strategy,
            "--hyperopt-loss", state.hyperopt_loss,
            "--spaces", *effective_spaces,
            "--epochs", str(state.hyperopt_epochs),
            "--timerange", is_range,
            "--timeframe", state.timeframe,
            "--user-data-dir", state.user_data_dir,
            "--no-color", "-j", str(state.hyperopt_workers),
        ]
        hp_cmd += strategy_path_args(state)

        # Add pairs to command if provided
        if pairs:
            hp_cmd.extend(["--pairs", *pairs])
        rc, stdout, _ = await _run_subprocess(run_id, hp_cmd, stage=3, stream=True, timeout=3600)

        if _cancelled(run_id):
            raise _Cancelled()

        if rc != 0:
            _rlog(run_id, 3, logging.WARNING,
                  f"WFO W{wnum}/{n} | Hyperopt failed (rc={rc}) — skipping window.")
            _emit(run_id, 3, "running",
                  f"WFO Window {wnum}/{n}: hyperopt failed (rc={rc}), skipping.",
                  -1,
                  {
                      "segment_id": wnum, "total_windows": n,
                      "is_range": is_range, "oos_range": oos_range,
                      "oos_profit": None, "passed": False,
                      "max_dd": None, "trades": 0,
                      "recency_weight": round(state.wfo_recency_weight ** (wnum - 1), 3),
                  },
                  msg_type="wfa_segment_result")
            continue

        win_params = await _extract_hyperopt_best(state, out_dir)
        if win_params is None:
            _rlog(run_id, 3, logging.WARNING,
                  f"WFO W{wnum}/{n} | Could not extract best params — skipping.")
            continue

        # ── Patch temp strategy for OOS backtest ──────────────────────────
        win_strat = f"{state.strategy}_WFO_W{wnum}"
        try:
            source = read_strategy_source(state)
            patched = _inject_params(source, win_strat, win_params)
            win_path = create_variant(
                state,
                role="validation",
                strategy_name=win_strat,
                source=patched,
            )
        except Exception as exc:
            _rlog(run_id, 3, logging.WARNING, f"WFO W{wnum}/{n} | Patch error: {exc}")
            continue

        # ── OOS backtest ───────────────────────────────────────────────────
        _rlog(run_id, 3, logging.INFO,
              f"WFO W{wnum}/{n} | OOS Validate OOS={oos_range}")
        _emit(run_id, 3, "running",
              f"WFO Window {wnum}/{n}: validating OOS={oos_range}…",
              20 + int(i / n * 30) + 2)

        oos_prefix = str(out_dir / f"wfo_w{wnum}_oos")
        oos_cmd = _backtest_cmd(state, strategy=win_strat, timerange=oos_range,
                                result_prefix=oos_prefix, pairs=pairs)
        oos_rc, _, _ = await _run_subprocess(run_id, oos_cmd, stage=3)

        _rlog(run_id, 3, logging.DEBUG,
              f"Stage 3 | Preserved WFO validation variant: {win_path}")

        if _cancelled(run_id):
            raise _Cancelled()

        oos_profit = 0.0
        oos_max_dd = 0.0
        oos_trades = 0
        oos_status = "failed"

        if oos_rc == 0:
            oos_data = _find_backtest_result(out_dir, f"wfo_w{wnum}_oos", state.user_data_dir)
            oos_sum  = _extract_backtest_summary(oos_data, win_strat)
            oos_profit  = oos_sum.get("profit_total", 0.0)
            oos_max_dd  = oos_sum.get("max_drawdown_account", 0.0) * 100
            oos_trades  = oos_sum.get("total_trades", 0)
            oos_status  = "passed" if oos_profit >= 0 else "warning"
            last_good_params = win_params
            last_good_window = wnum

            # Track passing segment parameters for aggregation
            if oos_profit >= 0:
                passing_window_params.append(win_params.get("params_dict", win_params))
                passing_window_weights.append(state.wfo_recency_weight ** (wnum - 1))

        recency_w = state.wfo_recency_weight ** (wnum - 1)
        result = {
            "segment_id": wnum,
            "total_windows": n,
            "is_range": is_range,
            "oos_range": oos_range,
            "oos_profit": round(oos_profit * 100, 2),
            "max_dd": round(oos_max_dd, 2),
            "trades": oos_trades,
            "recency_weight": round(recency_w, 3),
            "passed": oos_profit >= 0,
        }
        wfo_results.append(result)
        state.wfo_windows = wfo_results[:]
        _save_state_to_disk(state)

        _rlog(run_id, 3, logging.INFO,
              f"WFO W{wnum}/{n} | profit={oos_profit*100:.2f}% "
              f"max_dd={oos_max_dd:.1f}% trades={oos_trades} w={recency_w:.3f}")
        _emit(run_id, 3, "running",
              f"WFO Window {wnum}/{n}: profit {oos_profit*100:.2f}%",
              -1,
              result,
              msg_type="wfa_segment_result")

    if last_good_params is None:
        msg = "WFO: all windows failed — no valid parameters obtained."
        _rlog(run_id, 3, logging.ERROR, msg)
        _fail_stage(run_id, state, 3, msg)
        return None

    valid = [r for r in wfo_results if r["passed"]]
    pass_rate = len(valid) / n if n > 0 else 0.0
    avg_profit = sum(r["oos_profit"] for r in valid) / len(valid) if valid else 0.0

    # ── 50% Pass Rate Check ───────────────────────────────────────────────
    if pass_rate < 0.5:
        _rlog(run_id, 3, logging.WARNING,
              f"WFO FAILED: Pass rate {pass_rate:.1%} ({len(valid)}/{n}) below 50% threshold")
        _emit(run_id, 3, "running",
              f"WFO Pass rate {pass_rate:.1%} below 50% threshold — awaiting suggestion approval...",
              -1)

        if state.retry_count >= state.max_retries:
            # All retries exhausted
            msg = (
                f"WFO failed after {state.max_retries} approved retry attempts. "
                f"Pass rate remained below 50% ({pass_rate:.1%})."
            )
            _rlog(run_id, 3, logging.ERROR, msg)
            _fail_stage(run_id, state, 3, msg, {
                "wfo_windows": wfo_results,
                "pass_rate": pass_rate,
                "retry_history": state.retry_history,
            })
            return None

        # Try AI suggestions if enabled
        ai_suggestions = None
        source = "deterministic"
        if state.ai_enabled:
            try:
                _rlog(run_id, 3, logging.INFO,
                      "WFO self-healing: requesting AI suggestions for parameter mutations")
                ai_suggestions = await ask_ollama_for_wfa_fix(wfo_results, state)
                if ai_suggestions:
                    source = "ollama"
                    _rlog(run_id, 3, logging.INFO,
                          f"AI suggestions received: {ai_suggestions.get('reasoning', 'N/A')}")
            except Exception as exc:
                _rlog(run_id, 3, logging.WARNING,
                      f"AI suggestion request failed: {exc}")

        suggestion = create_pending_suggestion(
            state=state,
            trigger="wfo_pass_rate",
            failure_reason="segment_pass_rate_below_50%",
            retry_attempt=state.retry_count + 1,
            source=source,
            proposed_changes=ai_suggestions,
            explanation=ai_suggestions.get("reasoning") if ai_suggestions else None,
            evidence={
                "wfo_windows": wfo_results,
                "pass_rate": pass_rate,
                "segment_pass_rate": f"{len(valid)}/{n}",
            },
        )
        state.status = "awaiting_user_approval"
        stage_idx = optimization_stage_index()
        state.current_stage = stage_idx
        if 0 < stage_idx <= len(state.stages):
            state.stages[stage_idx - 1].status = "warning"
            state.stages[stage_idx - 1].message = suggestion["summary"]
            state.stages[stage_idx - 1].data = {
                **(state.stages[stage_idx - 1].data or {}),
                "ai_suggestion_id": suggestion["id"],
                "wfo_windows": wfo_results,
                "wfo_pass_rate": pass_rate,
            }
        _emit(
            run_id,
            stage_idx,
            "awaiting_user_approval",
            suggestion["summary"],
            -1,
            {"suggestion": suggestion},
            msg_type="ai_suggestion_ready",
        )
        _save_state_to_disk(state)
        return None

    # ── Pass Rate >= 50%: Aggregate Parameters ───────────────────────────
    _rlog(run_id, 3, logging.INFO,
          f"WFO complete | Pass rate {pass_rate:.1%} ({len(valid)}/{n}) meets 50% threshold")

    # Aggregate parameters using Recency-Weighted Average
    if passing_window_params and passing_window_weights:
        try:
            aggregated_params_dict = _aggregate_wfa_parameters(
                passing_window_params, passing_window_weights
            )
            best_params = {"params_dict": aggregated_params_dict, "loss": None}
            _rlog(run_id, 3, logging.INFO,
                  f"Aggregated parameters from {len(passing_window_params)} passing segments "
                  f"using recency-weighted average")
        except Exception as exc:
            _rlog(run_id, 3, logging.WARNING,
                  f"Parameter aggregation failed: {exc} — using most recent window")
            best_params = last_good_params
    else:
        best_params = last_good_params

    _rlog(run_id, 3, logging.INFO,
          f"WFO complete | {len(valid)}/{n} windows passed | "
          f"avg profit {avg_profit:.2f}% | using aggregated parameters")
    _pass_stage(run_id, state, 3,
                f"WFO: {len(valid)}/{n} windows passed — avg {avg_profit:.2f}% OOS profit, "
                f"parameters aggregated from passing segments",
                {
                    "best_params": best_params,
                    "wfo_windows": wfo_results,
                    "wfo_avg_profit": round(avg_profit, 2),
                    "wfo_pass_rate": pass_rate,
                    "wfo_aggregated": True,
                })
    return best_params


async def _stage_patch(
    run_id: str, state: PipelineState, out_dir: Path, best_params: dict
) -> Path | None:
    _start_stage(run_id, state, 3)
    _rlog(run_id, 3, logging.INFO,
          f"Stage 3 | Auto-Patching | strategy={state.strategy}")
    _emit(run_id, 3, "running", "Cloning strategy and injecting optimized parameters...", 45)

    src_path = active_strategy_path(state)
    _rlog(run_id, 3, logging.DEBUG, f"Stage 3 | Reading source strategy: {src_path}")

    if not src_path.exists():
        msg = f"Strategy file not found: {src_path}"
        _rlog(run_id, 3, logging.ERROR, f"Stage 3 | FAIL | {msg}")
        _fail_stage(run_id, state, 3, msg)
        return None

    optimized_name = f"{state.strategy}_Optimized"
    try:
        source = src_path.read_text(encoding="utf-8")
        _rlog(run_id, 3, logging.DEBUG,
              f"Stage 3 | Injecting params: {list(best_params.get('params_dict', {}).keys())}")
        # Pass param_overrides if present (from hard mutation)
        param_overrides = getattr(state, 'param_overrides', None)
        patched = _inject_params(source, optimized_name, best_params, param_overrides)
        dst_path = create_variant(
            state,
            role="validation",
            strategy_name=optimized_name,
            source=patched,
        )
        _rlog(run_id, 3, logging.DEBUG, f"Stage 3 | Written optimized strategy → {dst_path}")
    except Exception as exc:
        msg = f"Failed to patch strategy: {exc}"
        _rlog(run_id, 3, logging.ERROR, f"Stage 3 | FAIL | {msg}", exc_info=True)
        _fail_stage(run_id, state, 3, msg)
        return None

    # Save a copy in the pipeline output dir
    copy_path = out_dir / f"{optimized_name}.py"
    copy_path.write_text(patched, encoding="utf-8")
    _rlog(run_id, 3, logging.DEBUG, f"Stage 3 | Saved output copy → {copy_path}")

    if _cancelled(run_id):
        raise _Cancelled()

    _rlog(run_id, 3, logging.INFO,
          f"Stage 3 | PASS | Created {optimized_name}.py  ({len(patched)} chars)")
    _pass_stage(run_id, state, 3,
                f"Created {optimized_name}.py with injected parameters.",
                {"optimized_file": str(dst_path)})
    return dst_path
