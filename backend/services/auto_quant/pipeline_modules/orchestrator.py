"""Orchestrator for the Auto-Quant pipeline - main run_pipeline function and pre-stage data download."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..sensitivity import run_sensitivity_check
from ..ai_suggestions import create_pending_suggestion, optimization_stage_index
from ..ollama_service import ask_ollama_for_sensitivity_fix
from ..policy import load_policy
from ..variants import ensure_working_copy
from .config import (
    DEFAULT_STRESS_PAIRS,
    AUTOQUANT_SELF_HEALING_ENABLED,
    AUTOQUANT_REGIME_DETECTION_ENABLED,
    AUTOQUANT_GENETIC_ALGORITHM_ENABLED,
    AUTOQUANT_REINFORCEMENT_LEARNING_ENABLED,
    AUTOQUANT_WFO_ENABLED,
)
from .discovery import apply_discovery_results, run_discovery
from .helpers import _emit, _run_subprocess
from .logging import _rlog, logger, get_queues
from .stages_assessment import _stage_joint_portfolio_backtest
from .stages_optimization import _stage_hyperopt, _stage_patch
from .stages_genetic import _stage_genetic_evolution
from .stages_regime import _stage_regime_detection
from .stages_rl import _stage_rl_deployment, _stage_rl_training
from .stages_validation import _stage_oos_validation, _stage_portfolio_baseline, _stage_robustness_feature_injection, _stage_pre_flight_filtering, _stage_sanity_backtest, _stage_stress_test
from .helpers import _fail_stage, _pass_stage
from .stage_runtime import ensure_validation_attempt, is_validate_existing, update_validation_attempt
from .state import (
    PipelineState,
    _Cancelled,
    _cancelled,
    _save_state_to_disk,
    _now,
    get_states,
)

# Tracks the currently in-flight orchestrator asyncio.Task per run_id so
# start/resume endpoints can never double-launch run_pipeline() for the same
# run — a duplicate launch would spawn a second set of freqtrade subprocesses
# against the same output directory and corrupt shared state.
_active_run_tasks: dict[str, "asyncio.Task"] = {}


def launch_pipeline_task(run_id: str):
    """Schedule run_pipeline(run_id) as a background task, unless one is
    already running for this run_id. Returns the (possibly pre-existing)
    asyncio.Task, or None if a task is already active."""
    import asyncio

    existing = _active_run_tasks.get(run_id)
    if existing is not None and not existing.done():
        logger.warning(
            "launch_pipeline_task: run %s already has an active orchestrator "
            "task — ignoring duplicate launch request.",
            run_id,
        )
        return None

    task = asyncio.create_task(run_pipeline(run_id))
    _active_run_tasks[run_id] = task
    task.add_done_callback(lambda t, rid=run_id: _active_run_tasks.pop(rid, None))
    return task


def _merge_timeranges(r1: str, r2: str) -> str:
    """Return the smallest YYYYMMDD-YYYYMMDD bounding range covering r1 and r2.

    Silently falls back to r1 if either range cannot be parsed.
    """
    try:
        s1, e1 = r1.split("-", 1)
        s2, e2 = r2.split("-", 1)
        start = min(s for s in (s1, s2) if s) if any((s1, s2)) else ""
        end   = max(e for e in (e1, e2) if e) if any((e1, e2)) else ""
        if start and end:
            return f"{start}-{end}"
    except Exception as exc:
        logger.warning("Orchestrator | failed to merge date ranges %s and %s: %s", r1, r2, exc)
    return r1


async def run_pipeline(run_id: str) -> None:
    """Main async pipeline entry point. Runs all 6 stages sequentially with pause/resume support."""
    state = get_states().get(run_id)
    if state is None:
        logger.error("run_pipeline called with unknown run_id=%s — aborting.", run_id)
        return
    if state.status == "awaiting_user_approval" and getattr(state, "pending_ai_suggestion_id", None):
        logger.info(
            "run_pipeline: run %s is awaiting AI suggestion approval (%s); not resuming.",
            run_id,
            state.pending_ai_suggestion_id,
        )
        return

    # If resuming from user approval, continue from where we left off
    if state.status == "awaiting_user_approval":
        logger.info("run_pipeline: resuming from user approval checkpoint at stage %d", state.current_stage)
        state.status = "running"
        
        # Transfer user_approved_pairs to selected_pairs if they exist.
        # Strip any freqtrade aggregate summary rows (e.g. "TOTAL") that are
        # not real trading pairs and must never be forwarded to freqtrade.
        if state.user_approved_pairs and not state.selected_pairs:
            real_pairs = [p for p in state.user_approved_pairs if p.strip().upper() != "TOTAL"]
            if len(real_pairs) < len(state.user_approved_pairs):
                logger.warning(
                    "run_pipeline: stripped %d non-pair summary row(s) from user_approved_pairs "
                    "(e.g. 'TOTAL'); proceeding with %d real pairs.",
                    len(state.user_approved_pairs) - len(real_pairs),
                    len(real_pairs),
                )
            state.selected_pairs = [{"key": pair} for pair in real_pairs]
            logger.info("run_pipeline: transferred %d user_approved_pairs to selected_pairs", len(real_pairs))
        
        _save_state_to_disk(state)
    else:
        state.status = "running"
    
    out_dir = Path(state.user_data_dir) / "auto_quant" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    policy = load_policy()
    ensure_working_copy(state, out_dir)
    if is_validate_existing(state):
        ensure_validation_attempt(
            state,
            reason="initial" if state.retry_count == 0 else "approved_ai_retry",
            trigger="approved_ai_retry" if state.retry_count else "initial",
        )
    state.selected_timeframe = state.selected_timeframe or state.timeframe
    state.selected_pair_universe = state.selected_pair_universe or state.pair_universe
    state.policy_versions = state.policy_versions or policy.versions
    
    # Run discovery phase if enabled and no results exist
    if state.auto_discovery_enabled and not state.discovery_results:
        _rlog(run_id, 0, logging.INFO, "── Running Discovery Phase ──")
        _emit(run_id, 0, "running", "Running discovery to select optimal timeframe and pair universe...", 2)
        
        discovery_result = await run_discovery(run_id, state, out_dir)
        apply_discovery_results(state, discovery_result)
        
        _rlog(run_id, 0, logging.INFO,
              f"Discovery Complete | Selected timeframe: {state.selected_timeframe}, "
              f"Pairs: {len(state.selected_pair_universe)}, Notes: {len(state.validation_notes)}")
    
    _save_state_to_disk(state)

    _rlog(run_id, 0, logging.INFO,
          f"══ AUTO-QUANT FACTORY STARTED ══  run={run_id}  strategy={state.strategy}"
          f"  timeframe={state.timeframe}  IS={state.in_sample_range}"
          f"  OOS={state.out_sample_range}  exchange={state.exchange}")
    _rlog(run_id, 0, logging.DEBUG,
          f"Config file : {state.config_file}")
    _rlog(run_id, 0, logging.DEBUG,
          f"Freqtrade   : {state.freqtrade_path}")
    _rlog(run_id, 0, logging.DEBUG,
          f"Output dir  : {out_dir}")
    _emit(run_id, 0, "running", "Pipeline started.", 0)

    try:
        # ── Stage 1: Pre-Flight Filtering (Data Healing + Baseline Backtest) ──
        # Skip if already completed (current_stage > 1)
        if state.current_stage < 1:
            _rlog(run_id, 1, logging.INFO, "── ENTERING Stage 1: Pre-Flight Filtering ──")
            s1_result = await _stage_pre_flight_filtering(run_id, state, out_dir)
            if s1_result is None:
                _rlog(run_id, 1, logging.ERROR, "Stage 1 FAILED — pipeline halted.")
                return  # pipeline already marked failed
            
            # Check if Stage 1 paused for user approval
            if state.status == "awaiting_user_approval":
                _rlog(run_id, 1, logging.INFO, "Stage 1 PAUSED awaiting user approval")
                _save_state_to_disk(state)
                return
        else:
            # Resume: load Stage 1 result from state and set selected_pairs from user approval
            s1_result = state.stages[0].data if state.stages else {}
            _rlog(run_id, 1, logging.INFO, "── RESUMING: Stage 1 already completed")
            
            # Set selected_pairs from user_approved_pairs (set by resume endpoint).
            # Strip freqtrade aggregate summary rows (e.g. "TOTAL") — these are
            # not real trading pairs and must not be forwarded to freqtrade.
            if state.user_approved_pairs:
                real_pairs = [p for p in state.user_approved_pairs if p.strip().upper() != "TOTAL"]
                if len(real_pairs) < len(state.user_approved_pairs):
                    _rlog(run_id, 1, logging.WARNING,
                          f"Stage 1 | Stripped {len(state.user_approved_pairs) - len(real_pairs)} "
                          f"non-pair summary row(s) (e.g. 'TOTAL') from user_approved_pairs.")
                state.selected_pairs = [{"key": pair} for pair in real_pairs]
                _rlog(run_id, 1, logging.INFO,
                      f"Stage 1 | User approved {len(real_pairs)} pairs")
            else:
                # Fallback to passing_pairs from Stage 1 result
                passing_pairs = s1_result.get("passing_pairs", [])
                if passing_pairs:
                    state.selected_pairs = [{"key": pair} for pair in passing_pairs]
                    _rlog(run_id, 1, logging.INFO,
                          f"Stage 1 | Using {len(passing_pairs)} pairs from Stage 1 result")
                else:
                    # Final fallback: use discovery selected pairs or pair_universe
                    fallback_pairs = state.selected_pair_universe or state.pair_universe or []
                    if fallback_pairs:
                        state.selected_pairs = [{"key": pair} for pair in fallback_pairs]
                        _rlog(run_id, 1, logging.WARNING,
                              f"Stage 1 | No passing pairs found, using {len(fallback_pairs)} discovery/universe pairs as fallback")
                    else:
                        _rlog(run_id, 1, logging.ERROR,
                              "Stage 1 | No pairs available for continuation - pipeline cannot proceed")
                        _fail_stage(run_id, state, 1, "No pairs available - all pairs failed filtering or no pairs provided")
                        return
            
            # Mark Stage 1 as passed now that we have user approval
            state.stages[0].status = "passed"
            _pass_stage(run_id, state, 1,
                        f"Pre-flight filtering complete — {len(state.selected_pairs)} pairs approved.",
                        s1_result)

        # ── Stage 1.5: Regime Detection ─────────────────────────────────────
        # Run regime detection if enabled (controlled by feature flag)
        if AUTOQUANT_REGIME_DETECTION_ENABLED and state.regime_detection_enabled:
            _rlog(run_id, 1, logging.INFO, "── ENTERING Stage 1.5: Regime Detection ──")
            regime_result = await _stage_regime_detection(run_id, state, out_dir)
            if regime_result:
                _rlog(run_id, 1, logging.INFO,
                      f"Regime Detection Complete | Regime={state.current_regime}")
            else:
                _rlog(run_id, 1, logging.WARNING, "Regime detection failed, using defaults")
        elif not AUTOQUANT_REGIME_DETECTION_ENABLED:
            _rlog(run_id, 1, logging.INFO, "── SKIPPING Stage 1.5: Regime Detection (disabled by feature flag)")

        # ── Stage 2: Portfolio Baseline Backtest ───────────────────────────
        # Check if Stage 2 needs to run based on both current_stage and individual stage status
        # Stage 2 corresponds to index 1 in the stages array (0-indexed: stages[1] = Stage 2)
        stage2_needs_run = (state.current_stage < 2) or (len(state.stages) > 1 and state.stages[1].status != "passed")
        
        if stage2_needs_run:
            _rlog(run_id, 2, logging.INFO, "── ENTERING Stage 2: Portfolio Baseline Backtest ──")
            s2_result = await _stage_portfolio_baseline(run_id, state, out_dir)
            if s2_result is None:
                _rlog(run_id, 2, logging.ERROR, "Stage 2 FAILED — pipeline halted.")
                return  # pipeline already marked failed
            
            # Check if Stage 2 paused for user approval
            if state.status == "awaiting_user_approval":
                _rlog(run_id, 2, logging.INFO, "Stage 2 PAUSED awaiting user approval")
                _save_state_to_disk(state)
                return
        elif state.current_stage == 2:
            # Resume: load Stage 2 result from state
            s2_result = state.stages[1].data if len(state.stages) > 1 else {}
            _rlog(run_id, 2, logging.INFO, "── RESUMING: Stage 2 already completed")
            
            # Ensure selected_pairs is populated
            if not state.selected_pairs:
                fallback_pairs = state.selected_pair_universe or state.pair_universe or []
                if fallback_pairs:
                    state.selected_pairs = [{"key": pair} for pair in fallback_pairs]
                    _rlog(run_id, 2, logging.WARNING,
                          f"Stage 2 | Auto-populated {len(fallback_pairs)} pairs from discovery/universe")
                else:
                    _rlog(run_id, 2, logging.ERROR,
                          "Stage 2 | No pairs available - pipeline cannot proceed")
                    _fail_stage(run_id, state, 2, "No pairs available for continuation")
                    return
            
            # Mark Stage 2 as passed now that we have user approval
            state.stages[1].status = "passed"
            _pass_stage(run_id, state, 2,
                        f"Portfolio baseline complete — {len(state.selected_pairs)} pairs confirmed.",
                        s2_result)
            
            # Advance to next stage
            state.current_stage = optimization_stage_index()
            _save_state_to_disk(state)
        else:
            # Stage 2 already completed and current_stage > 2, skip to next stage
            _rlog(run_id, 2, logging.INFO, "── SKIPPING: Stage 2 already completed (current_stage=%d)", state.current_stage)
            s2_result = state.stages[1].data if len(state.stages) > 1 else {}

        # ── Stage 2.5: Genetic Algorithm Evolution ─────────────────────────
        # Run genetic evolution if enabled (controlled by feature flag)
        if AUTOQUANT_GENETIC_ALGORITHM_ENABLED and state.genetic_evolution_enabled:
            _rlog(run_id, 2, logging.INFO, "── ENTERING Stage 2.5: Genetic Algorithm Evolution ──")
            ga_result = await _stage_genetic_evolution(run_id, state, out_dir)
            if ga_result:
                _rlog(run_id, 2, logging.INFO,
                      f"Genetic Evolution Complete | Best fitness: {ga_result.get('best_fitness', 0):.4f}")
            else:
                _rlog(run_id, 2, logging.WARNING, "Genetic evolution failed, using default parameters")
        elif not AUTOQUANT_GENETIC_ALGORITHM_ENABLED:
            _rlog(run_id, 2, logging.INFO, "── SKIPPING Stage 2.5: Genetic Algorithm Evolution (disabled by feature flag)")

        # ── Stage 3.5: RL Training ─────────────────────────────────────────
        # Run RL training if enabled (controlled by feature flag)
        if AUTOQUANT_REINFORCEMENT_LEARNING_ENABLED and state.rl_training_enabled:
            _rlog(run_id, 3, logging.INFO, "── ENTERING Stage 3.5: RL Training ──")
            rl_result = await _stage_rl_training(run_id, state, out_dir)
            if rl_result:
                _rlog(run_id, 3, logging.INFO,
                      f"RL Training Complete | Final reward: {rl_result.get('final_reward', 0):.4f}")
            else:
                _rlog(run_id, 3, logging.WARNING, "RL training failed, using default strategy")
        elif not AUTOQUANT_REINFORCEMENT_LEARNING_ENABLED:
            _rlog(run_id, 3, logging.INFO, "── SKIPPING Stage 3.5: RL Training (disabled by feature flag)")

        # ── Stages 3-4: Self-healing retry loop (renumbered from 2-3) ───────
        oos_result: dict | None = None
        optimized_path: Path | None = None
        best_params: dict | None = None
        _relaxed_gate_attempted: bool = False

        while True:
            # ── Stage 3: Standard Hyperopt (renumbered from Stage 2) ───────────────
            # Check if Stage 3 needs to run based on both current_stage and individual stage status
            # Stage 3 corresponds to index 2 in the stages array (0-indexed: stages[2] = Stage 3)
            stage3_needs_run = (state.current_stage < 3) or (len(state.stages) > 2 and state.stages[2].status != "passed")
            
            if not stage3_needs_run:
                _rlog(run_id, 3, logging.INFO, "── RESUMING: Stage 3 already completed")
                # Load optimized_path from state if available (needed for subsequent stages)
                if not optimized_path and state.stages and len(state.stages) >= 3:
                    stage3_data = state.stages[2].data if state.stages[2].data else {}
                    if "optimized_file" in stage3_data:
                        optimized_path = Path(stage3_data["optimized_file"])
                        _rlog(run_id, 3, logging.INFO, f"Loaded optimized_path from state: {optimized_path}")
                break  # Exit the retry loop and continue to Stage 4
            
            _rlog(run_id, 3, logging.INFO, "── ENTERING Stage 3: Standard Hyperopt ──")
            # Pass selected_pairs from Stage 1 pre-flight filtering
            selected_pairs_list = [p["key"] for p in state.selected_pairs] if state.selected_pairs else None
            best_params = await _stage_hyperopt(run_id, state, out_dir, selected_pairs_list)
            if best_params is None:
                _rlog(run_id, 3, logging.ERROR, "Stage 3 FAILED — pipeline halted.")
                return

            # ── Sub-step: Sensitivity / Robustness Check ──────────────────
            _rlog(run_id, 3, logging.INFO,
                  "── Sub-step: Sensitivity / Robustness Check ──")
            _emit(run_id, 3, "running",
                  "Running robustness check (±5% parameter perturbation)…", -1)
            sensitivity_result = await run_sensitivity_check(
                best_params, out_dir, run_id, state
            )
            state.sensitivity = sensitivity_result
            _save_state_to_disk(state)

            _rlog(run_id, 3,
                  logging.INFO if sensitivity_result["passed"] else logging.WARNING,
                  f"Sensitivity | {sensitivity_result['label']}"
                  f"  score={sensitivity_result['score']}"
                  f"  passed={sensitivity_result['passed']}"
                  f"  param={sensitivity_result.get('param')}"
                  f"  p_best={sensitivity_result.get('p_best')}"
                  f"  p_minus={sensitivity_result.get('p_minus')}"
                  f"  p_plus={sensitivity_result.get('p_plus')}")

            _emit(run_id, 3, "running",
                  f"Robustness: {sensitivity_result['label']} (score={sensitivity_result['score']})",
                  -1,
                  {"sensitivity": sensitivity_result},
                  msg_type="sensitivity_result")

            if not sensitivity_result["passed"]:
                failure_reason = sensitivity_result.get("failure_reason")
                
                if failure_reason == "FAIL_NEGATIVE_BASELINE":
                    _rlog(run_id, 3, logging.WARNING,
                          "Sensitivity check FAILED (Negative Baseline) — "
                          f"p_best={sensitivity_result.get('p_best')}")
                else:
                    _rlog(run_id, 3, logging.WARNING,
                          "Sensitivity check FAILED (Sharp Peak) — "
                          f"p_best={sensitivity_result.get('p_best')}  "
                          f"p_minus={sensitivity_result.get('p_minus')}  "
                          f"p_plus={sensitivity_result.get('p_plus')}")

                # Self-healing retry loop disabled by feature flag - fail immediately
                if not AUTOQUANT_SELF_HEALING_ENABLED:
                    failure_label = "Negative Baseline" if failure_reason == "FAIL_NEGATIVE_BASELINE" else "Sharp Peak"
                    state.generalization_failure = {
                        "thresholds": {
                            "min_oos_profit": state.min_oos_profit,
                            "max_drawdown_threshold": state.max_drawdown_threshold,
                        },
                        "attempts": state.retry_history,
                        "best_attempt": max(state.retry_history, key=lambda a: a.get("profit") or -999.0)
                        if state.retry_history else None,
                        "best_attempt_file": None,
                        "best_attempt_strategy_name": None,
                        "suggestions": [
                            "Strategy failed robustness check. Self-healing is disabled. "
                            "Start a new run with different pairs, timeframe, strategy, or parameters."
                        ],
                    }
                    msg = (
                        f"Strategy failed robustness check ({failure_label} detected). "
                        "Self-healing is disabled - pipeline halted."
                    )
                    _rlog(run_id, 3, logging.ERROR, f"Sensitivity | {msg}")
                    _fail_stage(run_id, state, 3, msg, state.generalization_failure)
                    return

                # Self-healing enabled - proceed with retry logic
                if state.retry_count >= state.max_retries:
                    failure_label = "Negative Baseline" if failure_reason == "FAIL_NEGATIVE_BASELINE" else "Sharp Peak"
                    state.generalization_failure = {
                        "thresholds": {
                            "min_oos_profit": state.min_oos_profit,
                            "max_drawdown_threshold": state.max_drawdown_threshold,
                        },
                        "attempts": state.retry_history,
                        "best_attempt": max(state.retry_history, key=lambda a: a.get("profit") or -999.0)
                        if state.retry_history else None,
                        "best_attempt_file": None,
                        "best_attempt_strategy_name": None,
                        "suggestions": [
                            "Strategy failed robustness after approved retry attempts. "
                            "Start a new run with different pairs, timeframe, strategy, or WFO settings."
                        ],
                    }
                    msg = (
                        f"Strategy failed robustness check after "
                        f"{state.max_retries} approved retry attempts ({failure_label} detected)."
                    )
                    _rlog(run_id, 3, logging.ERROR, f"Sensitivity | {msg}")
                    _fail_stage(run_id, state, 3, msg, state.generalization_failure)
                    return

                ollama_suggestions = None
                source = "deterministic"
                try:
                    import json
                    settings_file = Path(state.user_data_dir).parent / "data" / "strategy_lab_settings.json"
                    if settings_file.exists():
                        with open(settings_file, "r", encoding="utf-8") as f:
                            settings = json.load(f)
                        ollama_enabled = settings.get("ollama_self_healing_enabled", False)
                        if ollama_enabled:
                            _rlog(run_id, 3, logging.INFO,
                                  "Ollama self-healing enabled — requesting AI suggestions")
                            ollama_suggestions = await ask_ollama_for_sensitivity_fix(
                                sensitivity_result,
                                state.retry_history,
                                state
                            )
                            if ollama_suggestions:
                                source = "ollama"
                                _rlog(run_id, 3, logging.INFO,
                                      f"Ollama suggestions: {ollama_suggestions.get('reasoning', 'N/A')}")
                            else:
                                _rlog(run_id, 3, logging.WARNING,
                                      "Ollama unavailable or failed — using fallback logic")
                except Exception as exc:
                    _rlog(run_id, 3, logging.WARNING,
                          f"Failed to check Ollama settings or get suggestions: {exc}")

                trigger = "negative_baseline" if failure_reason == "FAIL_NEGATIVE_BASELINE" else "sharp_peak"
                proposed_changes = ollama_suggestions if ollama_suggestions else None
                suggestion = create_pending_suggestion(
                    state=state,
                    trigger=trigger,
                    failure_reason=failure_reason or "sensitivity",
                    retry_attempt=state.retry_count + 1,
                    source=source,
                    proposed_changes=proposed_changes,
                    explanation=ollama_suggestions.get("reasoning") if ollama_suggestions else None,
                    evidence={"sensitivity": sensitivity_result},
                )
                state.status = "awaiting_user_approval"
                state.current_stage = optimization_stage_index()
                stage_idx = optimization_stage_index()
                if 0 < stage_idx <= len(state.stages):
                    state.stages[stage_idx - 1].status = "warning"
                    state.stages[stage_idx - 1].message = suggestion["summary"]
                    state.stages[stage_idx - 1].data = {
                        **(state.stages[stage_idx - 1].data or {}),
                        "ai_suggestion_id": suggestion["id"],
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
                return

            # ── Auto-Patching (merged into Stage 3) ───────────────────────
            _rlog(run_id, 3, logging.INFO, "── Sub-step: Auto-Patching ──")
            optimized_path = await _stage_patch(run_id, state, out_dir, best_params)
            if optimized_path is None:
                _rlog(run_id, 3, logging.ERROR, "Auto-Patching FAILED — pipeline halted.")
                return

            if is_validate_existing(state):
                _rlog(run_id, 4, logging.INFO, "── Validate Existing Gate: OOS Validation ──")
                _emit(run_id, 4, "running", "Running required out-of-sample validation gate...", 52)
                oos_gate_result = await _stage_oos_validation(
                    run_id,
                    state,
                    out_dir,
                    optimized_path,
                    record_stage=False,
                    stage_idx=4,
                )
                if oos_gate_result is None:
                    msg = "OOS validation failed before robustness checks could continue."
                    update_validation_attempt(
                        state,
                        status="rejected",
                        stage_idx=4,
                        reason=msg,
                        metrics=(state.generalization_failure or {}),
                    )
                    _fail_stage(run_id, state, 4, msg, state.generalization_failure or {})
                    return

                if oos_gate_result == "retry":
                    failure = state.generalization_failure or {}
                    failed_metrics = failure.get("failed_metrics", {})
                    update_validation_attempt(
                        state,
                        status="awaiting_retry",
                        stage_idx=4,
                        reason=f"OOS validation did not pass: {failed_metrics.get('reason', 'unknown')}",
                        metrics=failed_metrics,
                    )
                    
                    # Self-healing disabled - fail immediately on OOS validation failure
                    if not AUTOQUANT_SELF_HEALING_ENABLED:
                        msg = (
                            "Selected strategy failed OOS validation. "
                            "Self-healing is disabled - pipeline halted."
                        )
                        _rlog(run_id, 4, logging.ERROR, "Validate Existing | %s", msg)
                        _fail_stage(run_id, state, 4, msg, failure)
                        return
                    
                    if state.retry_count >= state.max_retries:
                        msg = (
                            "Selected strategy failed OOS validation after "
                            f"{state.max_attempts} full validation attempt(s)."
                        )
                        _rlog(run_id, 4, logging.ERROR, "Validate Existing | %s", msg)
                        _fail_stage(run_id, state, 4, msg, failure)
                        return

                    suggestion = create_pending_suggestion(
                        state=state,
                        trigger="oos_validation",
                        failure_reason=failed_metrics.get("reason") or "oos_validation",
                        retry_attempt=state.retry_count + 1,
                        source="deterministic",
                        proposed_changes=None,
                        summary="OOS validation failed; review a safer retry configuration.",
                        explanation=(
                            "The strategy did not pass the out-of-sample gate. "
                            "Approval schedules another full validation attempt through the existing AutoQuant flow."
                        ),
                        evidence={"oos_validation": failure},
                    )
                    state.status = "awaiting_user_approval"
                    state.current_stage = optimization_stage_index()
                    stage_idx = optimization_stage_index()
                    if 0 < stage_idx <= len(state.stages):
                        state.stages[stage_idx - 1].status = "warning"
                        state.stages[stage_idx - 1].message = suggestion["summary"]
                        state.stages[stage_idx - 1].data = {
                            **(state.stages[stage_idx - 1].data or {}),
                            "ai_suggestion_id": suggestion["id"],
                            "oos_validation": failure,
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
                    return

                oos_result = oos_gate_result
                update_validation_attempt(
                    state,
                    status="running",
                    stage_idx=4,
                    reason="OOS validation passed; continuing robustness and portfolio gates.",
                    metrics={
                        "oos_profit": oos_result.get("profit_total"),
                        "oos_total_trades": oos_result.get("total_trades"),
                        "oos_drawdown": oos_result.get("max_drawdown_account"),
                        "profit_factor": oos_result.get("profit_factor"),
                    },
                )

            # Stage 3 complete — exit the retry loop and continue to Stage 4
            break

        # ── Stage 4: Robustness & Feature Injection (if not already completed) ──
        # Check if Stage 4 needs to run based on both current_stage and individual stage status
        # Stage 4 corresponds to index 3 in the stages array (0-indexed: stages[3] = Stage 4)
        stage4_needs_run = (state.current_stage < 4) or (len(state.stages) > 3 and state.stages[3].status != "passed")
        
        if stage4_needs_run:
            _rlog(run_id, 4, logging.INFO, "── ENTERING Stage 4: Robustness & Feature Injection ──")
            state.current_stage = 4
            _save_state_to_disk(state)
            
            # Ensure optimized_path is available
            # If resuming after Stage 3 was completed, retrieve it from state
            if not optimized_path and len(state.stages) > 2:
                stage3_data = state.stages[2].data
                if stage3_data and "optimized_file" in stage3_data:
                    optimized_path = Path(stage3_data["optimized_file"])
                    _rlog(run_id, 4, logging.INFO, f"Retrieved optimized_path from Stage 3: {optimized_path}")
                else:
                    _rlog(run_id, 4, logging.WARNING, "Stage 3 data missing or no optimized_file found")
                    _rlog(run_id, 4, logging.DEBUG, f"Stage 3 status: {state.stages[2].status if len(state.stages) > 2 else 'N/A'}")
                    _rlog(run_id, 4, logging.DEBUG, f"Stage 3 data keys: {list(stage3_data.keys()) if stage3_data else 'N/A'}")
            
            if not optimized_path:
                _rlog(run_id, 4, logging.ERROR, "Stage 4 cannot proceed: optimized_path is None")
                _rlog(run_id, 4, logging.ERROR, "This indicates Stage 3 (Auto-Patching) was not properly completed.")
                _rlog(run_id, 4, logging.ERROR, f"Current stage: {state.current_stage}, Stage 3 status: {state.stages[2].status if len(state.stages) > 2 else 'N/A'}")
                _fail_stage(run_id, state, 4, "optimized_path is None - cannot run robustness & feature injection")
                return
            
            stage4_result = await _stage_robustness_feature_injection(run_id, state, out_dir, optimized_path)

            if stage4_result is None:
                # Stage 4 failed (bad exit code, missing data, etc.)
                _rlog(run_id, 4, logging.ERROR, "Stage 4 FAILED — pipeline halted.")
                return
        else:
            _rlog(run_id, 4, logging.INFO, "── RESUMING: Stage 4 already completed")
            # Load Stage 4 result from state if available
            stage4_result = state.stages[3].data if len(state.stages) > 3 else {}

        # ── Stage 4.5: RL Deployment ───────────────────────────────────────
        # Run RL deployment if enabled (controlled by feature flag)
        if AUTOQUANT_REINFORCEMENT_LEARNING_ENABLED and state.rl_deployment_enabled:
            _rlog(run_id, 4, logging.INFO, "── ENTERING Stage 4.5: RL Deployment ──")
            rl_deploy_result = await _stage_rl_deployment(run_id, state, out_dir)
            if rl_deploy_result:
                _rlog(run_id, 4, logging.INFO,
                      f"RL Deployment Complete | Signals: {rl_deploy_result.get('trades_count', 0)}")
            else:
                _rlog(run_id, 4, logging.WARNING, "RL deployment failed, using default signals")
        elif not AUTOQUANT_REINFORCEMENT_LEARNING_ENABLED:
            _rlog(run_id, 4, logging.INFO, "── SKIPPING Stage 4.5: RL Deployment (disabled by feature flag)")

        # ── Stage 5: Portfolio Competition (Joint Portfolio Backtest) ──────────────────────
        _rlog(run_id, 5, logging.INFO, "── ENTERING Stage 5: Portfolio Competition ──")
        
        # Ensure optimized_path is available (may be None if resuming after Stage 3)
        if not optimized_path and len(state.stages) > 2:
            stage3_data = state.stages[2].data
            if stage3_data and "optimized_file" in stage3_data:
                optimized_path = Path(stage3_data["optimized_file"])
                _rlog(run_id, 5, logging.INFO, f"Retrieved optimized_path from Stage 3: {optimized_path}")
        
        if not optimized_path:
            _rlog(run_id, 5, logging.ERROR, "Stage 5 cannot proceed: optimized_path is None")
            _fail_stage(run_id, state, 5, "optimized_path is None - cannot run portfolio competition")
            return
        
        # Run joint portfolio backtest with capital constraints
        portfolio_result = await _stage_joint_portfolio_backtest(run_id, state, out_dir, optimized_path)
        if portfolio_result is None:
            _rlog(run_id, 5, logging.ERROR, "Stage 5 FAILED — portfolio backtest did not pass.")
            return

        # ── Stage 6: Delivery ─────────────────────────────────────────────
        _rlog(run_id, 6, logging.INFO, "── ENTERING Stage 6: Delivery ──")
        
        # Ensure optimized_path is available (may be None if resuming after Stage 3)
        if not optimized_path and len(state.stages) > 2:
            stage3_data = state.stages[2].data
            if stage3_data and "optimized_file" in stage3_data:
                optimized_path = Path(stage3_data["optimized_file"])
                _rlog(run_id, 6, logging.INFO, f"Retrieved optimized_path from Stage 3: {optimized_path}")
        
        if not optimized_path:
            _rlog(run_id, 6, logging.ERROR, "Stage 6 cannot proceed: optimized_path is None")
            _fail_stage(run_id, state, 6, "optimized_path is None - cannot run delivery")
            return
        
        delivery_oos_result = oos_result if is_validate_existing(state) else (stage4_result or {})
        await _stage_delivery(run_id, state, out_dir, optimized_path, best_params,
                              s1_result, delivery_oos_result or {}, stage4_result or {}, portfolio_result)

        state.status = "completed"
        state.completed_at = _now()
        if is_validate_existing(state) and state.final_verdict == "rejected":
            state.status = "failed"
        _save_state_to_disk(state)
        _rlog(run_id, 6, logging.INFO,
              f"══ PIPELINE COMPLETED SUCCESSFULLY ══  run={run_id}  "
              f"strategy={state.strategy}  completed_at={state.completed_at}")
        _emit(run_id, 6, "passed", "Pipeline completed successfully.", 100,
              {"report": state.report})

    except _Cancelled:
        state.status = "cancelled"
        state.completed_at = _now()
        _save_state_to_disk(state)
        _rlog(run_id, state.current_stage, logging.WARNING,
              f"Pipeline CANCELLED by user at stage {state.current_stage}.")
        _emit(run_id, state.current_stage, "failed", "Pipeline cancelled by user.", -1)
    except Exception as exc:
        state.status = "failed"
        state.error = str(exc)
        state.completed_at = _now()
        _save_state_to_disk(state)
        _rlog(run_id, state.current_stage, logging.ERROR,
              f"UNEXPECTED EXCEPTION at stage {state.current_stage}: {exc}",
              exc_info=True)
        _emit(run_id, state.current_stage, "failed", f"Unexpected error: {exc}", -1)
    finally:
        _rlog(run_id, state.current_stage if state else 0, logging.DEBUG,
              "Sending sentinel to all WebSocket subscribers.")
        # Send sentinel to close all WebSocket connections
        for q in list(get_queues().get(run_id, [])):
            try:
                q.put_nowait(None)
            except Exception as exc:
                logger.warning("Orchestrator | failed to send sentinel to queue: %s", exc)
