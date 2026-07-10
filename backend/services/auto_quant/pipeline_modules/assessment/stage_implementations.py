"""Stage implementations for assessment stages (4, 5)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ...monte_carlo import run_monte_carlo
from ...profit_lockin import compute_profit_giveback_metrics, extract_strategy_trades
from ...variants import strategy_path_args
from ..helpers import (
    _backtest_cmd,
    _classify_subprocess_error,
    _create_temp_config_with_max_open_trades,
    _emit,
    _extract_backtest_summary,
    _extract_last_close_price,
    _extract_per_pair_results,
    _fail_stage,
    _find_backtest_result,
    _pass_stage,
    _run_subprocess,
    _start_stage,
)
from ..logging import _rlog
from ..state import PipelineState, _Cancelled, _cancelled
from .data_helpers import _extract_oos_profit_ratios, _extract_oos_trades


async def _stage_risk_assessment(
    run_id: str, state: PipelineState, out_dir: Path, stress_result: dict
) -> dict | None:
    _start_stage(run_id, state, 4)  # Stage 4 in new workflow
    # Use selected_pairs from Stage 1 for context
    pairs_count = len(state.selected_pairs) if state.selected_pairs else 0
    _rlog(run_id, 4, logging.INFO,
          f"Stage 4 | Risk Assessment | pairs={pairs_count} | thresholds: "
          f"max_dd<{state.max_drawdown_threshold:.2f}  "
          f"win_rate>={state.min_win_rate:.2f}  "
          f"profit_factor>={state.min_profit_factor}  "
          f"sharpe>={state.min_sharpe}")
    _emit(run_id, 4, "running", "Computing risk metrics...", 80)

    await asyncio.sleep(0.5)  # small yield for WS flush

    if _cancelled(run_id):
        raise _Cancelled()

    max_dd_pct = stress_result.get("max_drawdown_account", 0.0)  # Already in decimal format
    wins = stress_result.get("wins", 0)
    losses = stress_result.get("losses", 0)
    draws = stress_result.get("draws", 0)
    total_trades = wins + losses + draws
    win_rate = (wins / total_trades) if total_trades > 0 else 0.0  # Already in decimal format
    profit_factor = stress_result.get("profit_factor", 0.0)
    sharpe = stress_result.get("sharpe_ratio", 0.0)
    _rlog(run_id, 4, logging.DEBUG,
          f"Stage 4 | Raw metrics: max_dd={max_dd_pct:.4f}  wins={wins}  losses={losses}"
          f"  draws={draws}  win_rate={win_rate:.4f}  profit_factor={profit_factor:.4f}"
          f"  sharpe={sharpe:.4f}")

    checks = {
        "max_drawdown": {"value": round(max_dd_pct, 4), "threshold": f"< {state.max_drawdown_threshold:.2f}",
                         "passed": max_dd_pct < state.max_drawdown_threshold},
        "win_rate": {"value": round(win_rate, 4), "threshold": f">= {state.min_win_rate:.2f}",
                     "passed": win_rate >= state.min_win_rate},
        "profit_factor": {"value": round(profit_factor, 4), "threshold": f">= {state.min_profit_factor}",
                          "passed": profit_factor >= state.min_profit_factor},
        "sharpe_ratio": {"value": round(sharpe, 4), "threshold": f">= {state.min_sharpe}",
                         "passed": sharpe >= state.min_sharpe or sharpe == 0.0},  # 0 = not computed
    }

    risk_data = {
        "max_drawdown_pct": round(max_dd_pct, 4),
        "win_rate_pct": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "sharpe_ratio": round(sharpe, 4),
        "total_trades": total_trades,
        "checks": checks,
    }

    optimized_strategy_name = f"{state.strategy}_Optimized"
    profit_giveback = compute_profit_giveback_metrics(
        _extract_oos_trades(out_dir, optimized_strategy_name)
    )
    risk_data["profit_giveback"] = profit_giveback

    failed_checks = [k for k, v in checks.items() if not v["passed"]]

    lines = []
    for k, v in checks.items():
        icon = "✓" if v["passed"] else "✗"
        lines.append(f"  {icon} {k}: {v['value']} (threshold: {v['threshold']})")
    check_summary = "Risk checks:\n" + "\n".join(lines)
    _rlog(run_id, 4, logging.INFO, f"Stage 4 | {check_summary}")
    _emit(run_id, 4, "running", check_summary, 85)

    if failed_checks:
        msg = f"Risk checks failed: {', '.join(failed_checks)}. Review metrics before deployment."
        _failed_vals = ", ".join(f"{k}={checks[k]['value']}" for k in failed_checks)
        _rlog(run_id, 4, logging.ERROR,
              f"Stage 4 | FAIL | failed_checks={failed_checks}  values={{ {_failed_vals} }}")
        _fail_stage(run_id, state, 4, msg, risk_data)
        return None

    if profit_giveback["peak_to_loss_count"] > 0:
        msg = (
            "Profit giveback failed: "
            f"{profit_giveback['peak_to_loss_count']} trade(s) reached tier-1 profit "
            "then closed negative."
        )
        _rlog(run_id, 4, logging.ERROR, f"Stage 4 | FAIL | {msg}")
        _fail_stage(run_id, state, 4, msg, risk_data)
        return None

    # ── Monte Carlo simulation ─────────────────────────────────────────────
    _rlog(run_id, 4, logging.INFO,
          "Stage 4 | Monte Carlo — extracting OOS trade profit series…")
    _emit(run_id, 4, "running", "Running Monte Carlo simulation (1 000 shuffles)…", 87)

    profit_ratios = _extract_oos_profit_ratios(out_dir, optimized_strategy_name)
    _rlog(run_id, 4, logging.DEBUG,
          f"Stage 4 | Monte Carlo | OOS trades extracted: {len(profit_ratios)}")

    mc_result = run_monte_carlo(profit_ratios, n=1000, threshold=state.monte_carlo_threshold)
    p95 = mc_result["p95_drawdown"]
    _rlog(run_id, 4, logging.INFO,
          f"Stage 4 | Monte Carlo | simulations={mc_result['simulations']}"
          f"  p5_dd={mc_result['p5_drawdown']:.2%}"
          f"  p95_dd={p95:.2%}"
          f"  median_return={mc_result['median_final_return']:.2%}"
          f"  passed={mc_result['passed']}"
          f"  threshold={state.monte_carlo_threshold:.2%}")

    risk_data["monte_carlo"] = mc_result

    if not mc_result["passed"]:
        p95_pct = round(p95 * 100, 1)
        threshold_pct = round(state.monte_carlo_threshold * 100, 1)
        msg = (
            f"Monte Carlo 95th-percentile drawdown of {p95_pct}% "
            f"exceeds {threshold_pct}% threshold."
        )
        _rlog(run_id, 4, logging.ERROR, f"Stage 4 | FAIL | {msg}")
        _fail_stage(run_id, state, 4, msg, risk_data)
        return None

    _rlog(run_id, 4, logging.INFO,
          f"Stage 4 | PASS | max_dd={max_dd_pct:.1f}%  win_rate={win_rate:.1f}%"
          f"  profit_factor={profit_factor:.2f}  sharpe={sharpe:.2f}"
          f"  mc_p95_dd={p95:.2%}")
    _pass_stage(run_id, state, 4,
                f"All risk checks passed — DD {max_dd_pct:.1f}%, "
                f"WR {win_rate:.1f}%, PF {profit_factor:.2f}, "
                f"MC p95 DD {round(p95 * 100, 1)}%",
                risk_data)
    return risk_data


async def _stage_joint_portfolio_backtest(
    run_id: str,
    state: PipelineState,
    out_dir: Path,
    optimized_path: Path,
) -> dict | None:
    """Stage 5: Portfolio Competition Backtest with capital constraints and balanced scoring.

    Performs:
    1. Joint portfolio backtest with max_open_trades constraint
    2. Portfolio and per-pair metrics extraction
    3. Capital starvation detection (70% trade count drop vs baseline)
    4. Dual-factor sizing calculation with division-by-zero guards
    5. Integrated risk assessment (Monte Carlo + Profit Giveback on portfolio)
    6. Non-blocking drawdown gateway with WebSocket events
    7. Balanced scoring: profit factor (30%), drawdown (20%), expectancy (15%), WFA stability (15%), trade count (10%), stress survival (10%)
    """
    _start_stage(run_id, state, 5)  # Stage 5: Portfolio Competition
    strategy_name = optimized_path.stem
    pairs_to_test = [p["key"] for p in state.selected_pairs] if state.selected_pairs else None

    if not pairs_to_test:
        _rlog(run_id, 5, logging.WARNING, "Stage 5 | No selected_pairs available, skipping portfolio backtest")
        state.portfolio_weights = {}
        _pass_stage(run_id, state, 5, "No pairs to test for portfolio backtest", {"portfolio_weights": {}})
        return {"portfolio_weights": {}}

    _rlog(run_id, 5, logging.INFO,
          f"Stage 5 | Joint Portfolio Competition | strategy={strategy_name} | pairs={len(pairs_to_test)} | "
          f"max_open_trades={state.max_open_trades}")
    _emit(run_id, 5, "running",
          f"Running joint portfolio backtest with {state.max_open_trades} max open trades...",
          75)

    # ── Sub-step 5.1: Joint Portfolio Backtest Execution ───────────────────────
    try:
        # Create temporary config with max_open_trades constraint
        temp_config = _create_temp_config_with_max_open_trades(
            state.config_file, state.max_open_trades, out_dir
        )

        result_prefix = str(out_dir / "stage5_portfolio")
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

        _rlog(run_id, 5, logging.DEBUG, f"Stage 5 | Spawning subprocess: {' '.join(cmd)}")
        rc, stdout, stderr = await _run_subprocess(run_id, cmd, stage=5)

        # Cleanup temp config
        try:
            Path(temp_config).unlink(missing_ok=True)
        except Exception as exc:
            _rlog(run_id, 5, logging.WARNING, f"Stage 5 | Failed to delete temp config: {exc}")

        if _cancelled(run_id):
            raise _Cancelled()

        if rc != 0:
            msg = _classify_subprocess_error(rc, stdout, "Stage 5 (Joint Portfolio Backtest)")
            _rlog(run_id, 5, logging.ERROR, f"Stage 5 | FAIL | {msg}")
            _fail_stage(run_id, state, 5, msg)
            return None

    except Exception as exc:
        msg = f"Joint portfolio backtest failed: {exc}"
        _rlog(run_id, 5, logging.ERROR, f"Stage 5 | FAIL | {msg}")
        _fail_stage(run_id, state, 5, msg)
        return None

    # ── Sub-step 5.2: Portfolio Metrics Extraction ───────────────────────────
    result_data = _find_backtest_result(out_dir, "stage5_portfolio", state.user_data_dir)
    portfolio_summary = _extract_backtest_summary(result_data, strategy_name)
    per_pair = _extract_per_pair_results(result_data, strategy_name)

    portfolio_profit = portfolio_summary.get("profit_total_abs", 0.0)
    portfolio_max_dd = portfolio_summary.get("max_drawdown_account", 0.0)
    portfolio_trades = portfolio_summary.get("total_trades", 0)

    _rlog(run_id, 5, logging.INFO,
          f"Stage 5 | Portfolio metrics: profit={portfolio_profit:.4f} max_dd={portfolio_max_dd:.4f} trades={portfolio_trades}")

    # Extract last close price for each pair
    pair_prices = {}
    for pair_data in per_pair:
        pair_key = pair_data.get("key", "")
        current_price = _extract_last_close_price(pair_key, state.user_data_dir, state.in_sample_range)
        pair_prices[pair_key] = current_price
        pair_data["current_price"] = current_price

    # CAPITAL STARVATION ALERT: Compare trade counts vs baseline
    starvation_warnings = []
    for pair_data in per_pair:
        pair_key = pair_data.get("key", "")
        competition_trades = pair_data.get("trades", 0)
        baseline_trades = state.baseline_trade_counts.get(pair_key, 0)

        if baseline_trades > 0:
            drop_pct = (baseline_trades - competition_trades) / baseline_trades
            if drop_pct > 0.70:  # More than 70% drop
                warning = f"CAPITAL STARVATION: {pair_key} trade count dropped {drop_pct:.1%} " \
                          f"({baseline_trades} → {competition_trades})"
                starvation_warnings.append(warning)
                _rlog(run_id, 5, logging.WARNING, f"Stage 5 | {warning}")

    # ── Sub-step 5.3: Dual-Factor Sizing Calculation ───────────────────────────
    target_risk_pct = 0.02  # 2% risk per trade
    raw_weights = {}
    state.portfolio_weights = {}

    for pair_data in per_pair:
        pair_key = pair_data.get("key", "")
        atr_value = pair_data.get("atr", 0.01)
        current_price = pair_prices.get(pair_key, 1.0)
        stability_score = state.stability_scores.get(pair_key, 50.0)

        # Division-by-zero guards
        atr_pct = atr_value / current_price if current_price > 0 else 0.01
        if atr_pct <= 0:
            atr_pct = 0.01

        raw_weight = (target_risk_pct / atr_pct) * (stability_score / 100.0)
        raw_weights[pair_key] = raw_weight

    # NORMALIZATION BUG GUARD: If sum is 0, fallback to equal weights
    sum_raw_weights = sum(raw_weights.values())
    if sum_raw_weights == 0:
        _rlog(run_id, 5, logging.WARNING,
              "Stage 5 | Sum of raw weights is 0, falling back to equal weight distribution")
        equal_weight = 1.0 / len(per_pair)
        for pair_data in per_pair:
            pair_key = pair_data.get("key", "")
            state.portfolio_weights[pair_key] = equal_weight
    else:
        for pair_key, raw_weight in raw_weights.items():
            normalized_weight = raw_weight / sum_raw_weights
            state.portfolio_weights[pair_key] = normalized_weight

    _rlog(run_id, 5, logging.INFO,
          f"Stage 5 | Portfolio weights computed for {len(state.portfolio_weights)} pairs")

    # ── Sub-step 5.4: Non-Blocking Drawdown Gateway ───────────────────────────
    if portfolio_max_dd > state.max_drawdown_threshold:
        warning_msg = (f"Portfolio max drawdown {portfolio_max_dd:.2%} exceeds threshold "
                      f"{state.max_drawdown_threshold:.2%}")
        _rlog(run_id, 5, logging.WARNING, f"Stage 5 | {warning_msg}")
        _emit(run_id, 5, "running", warning_msg, 80,
              msg_type="portfolio_drawdown_warning",
              data={
                  "current_drawdown": round(portfolio_max_dd, 4),
                  "threshold": state.max_drawdown_threshold,
                  "exceeds_threshold": True,
              })

    # ── Sub-step 5.5: Integrated Risk Assessment (Monte Carlo + Profit Giveback) ──
    _rlog(run_id, 5, logging.INFO,
          "Stage 5 | Running integrated risk assessment on portfolio trades...")
    _emit(run_id, 5, "running", "Running Monte Carlo simulation on portfolio trades...", 85)

    # Extract all portfolio trades
    portfolio_trades_list = extract_strategy_trades(result_data, strategy_name)
    profit_ratios = []
    for trade in portfolio_trades_list:
        pr = trade.get("profit_ratio", trade.get("profit_abs"))
        if pr is not None:
            profit_ratios.append(float(pr))

    # Monte Carlo simulation
    mc_result = run_monte_carlo(profit_ratios, n=1000, threshold=state.monte_carlo_threshold)
    p95 = mc_result["p95_drawdown"]

    # Profit Giveback metrics
    profit_giveback = compute_profit_giveback_metrics(portfolio_trades_list)

    # ── Sub-step 5.6: Balanced Scoring with Specific Weights ─────────────────────
    _rlog(run_id, 5, logging.INFO, "Stage 5 | Computing balanced portfolio score...")
    
    # Extract metrics for scoring
    profit_factor = portfolio_summary.get("profit_factor", 1.0)
    max_drawdown = portfolio_max_dd
    expectancy = portfolio_summary.get("profit_mean_pct", 0.0)
    trade_count = portfolio_trades
    
    # WFA stability score — the real Walk-Forward Analysis pass rate computed
    # in Stage 3 (stored on state.stages[2].data["wfo_pass_rate"] by
    # stages_optimization.py), expressed on a 0-100 scale. Falls back to a
    # neutral midpoint only if Stage 3 genuinely produced no WFO result
    # (e.g. WFA was skipped for this run).
    stage3_data = state.stages[2].data if len(state.stages) > 2 and state.stages[2].data else {}
    wfo_pass_rate = stage3_data.get("wfo_pass_rate")
    wfa_stability = (wfo_pass_rate * 100.0) if wfo_pass_rate is not None else 50.0

    # Stress survival score — the real fee-stress degradation score computed
    # in Stage 4 (state.stability_scores, derived from 1x/2x/3x fee-multiplier
    # backtests), averaged across pairs.
    stability_values = list((state.stability_scores or {}).values())
    stress_survival = sum(stability_values) / len(stability_values) if stability_values else 50.0
    
    # Normalize metrics to 0-100 scale
    # Profit factor: higher is better, normalize around 1.5
    pf_score = min(100, max(0, (profit_factor - 0.5) / 2.0 * 100))
    
    # Drawdown: lower is better, normalize around 20%
    dd_score = min(100, max(0, (0.25 - max_drawdown) / 0.25 * 100))
    
    # Expectancy: higher is better, normalize around 1%
    exp_score = min(100, max(0, expectancy / 0.02 * 100))
    
    # WFA stability: already 0-100
    wfa_score = wfa_stability
    
    # Trade count: normalize around 100 trades
    tc_score = min(100, max(0, trade_count / 200 * 100))
    
    # Stress survival: already 0-100
    stress_score = stress_survival
    
    # Apply weights: PF 30%, DD 20%, Expectancy 15%, WFA 15%, Trade Count 10%, Stress 10%
    balanced_score = (
        pf_score * 0.30 +
        dd_score * 0.20 +
        exp_score * 0.15 +
        wfa_score * 0.15 +
        tc_score * 0.10 +
        stress_score * 0.10
    )
    
    _rlog(run_id, 5, logging.INFO,
          f"Stage 5 | Balanced score: {balanced_score:.1f} "
          f"(PF={pf_score:.1f}, DD={dd_score:.1f}, Exp={exp_score:.1f}, "
          f"WFA={wfa_score:.1f}, TC={tc_score:.1f}, Stress={stress_score:.1f})")
    
    # ── Sub-step 5.7: Winner Selection and Ranking ───────────────────────────────
    # For now, since we only have one strategy, it's the winner
    # In a multi-candidate scenario, we would compare multiple strategies
    winner = {
        "strategy": strategy_name,
        "score": round(balanced_score, 1),
        "reason": f"Best balance of PF ({profit_factor:.2f}), drawdown ({max_drawdown:.2%}), WFA stability ({wfa_stability:.1f})"
    }
    
    ranking = [winner]  # Single candidate
    
    _rlog(run_id, 5, logging.INFO, f"Stage 5 | Winner: {winner['strategy']} with score {winner['score']}")

    # ── Sub-step 5.8: WebSocket Event Emission ───────────────────────────────────
    portfolio_result_data = {
        "portfolio_metrics": {
            "profit_total_abs": round(portfolio_profit, 4),
            "max_drawdown_account": round(portfolio_max_dd, 4),
            "total_trades": portfolio_trades,
        },
        "per_pair_metrics": per_pair,
        "portfolio_weights": state.portfolio_weights,
        "capital_starvation_warnings": starvation_warnings,
        "monte_carlo": mc_result,
        "profit_giveback": profit_giveback,
        "balanced_score": round(balanced_score, 1),
        "score_breakdown": {
            "profit_factor_score": round(pf_score, 1),
            "drawdown_score": round(dd_score, 1),
            "expectancy_score": round(exp_score, 1),
            "wfa_stability_score": round(wfa_score, 1),
            "trade_count_score": round(tc_score, 1),
            "stress_survival_score": round(stress_score, 1),
        },
        "winner": winner,
        "ranking": ranking,
    }
    
    _emit(run_id, 5, "running",
          f"Portfolio competition complete. Winner: {winner['strategy']} with score {winner['score']}",
          95,
          msg_type="portfolio_competition_result",
          data=portfolio_result_data)

    _rlog(run_id, 5, logging.INFO,
          f"Stage 5 | PASS | portfolio_profit={portfolio_profit:.4f} "
          f"max_dd={portfolio_max_dd:.4f} trades={portfolio_trades} "
          f"balanced_score={balanced_score:.1f}")
    _pass_stage(run_id, state, 5,
                f"Portfolio competition complete — profit {portfolio_profit:.4f}, "
                f"DD {portfolio_max_dd:.4f}, score {balanced_score:.1f}",
                portfolio_result_data)
    return portfolio_result_data
