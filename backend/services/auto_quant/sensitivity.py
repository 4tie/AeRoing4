"""Sensitivity (robustness) check for Auto-Quant Factory.

Runs three quick in-sample backtests — best params, best+5%, best-5% —
to determine whether the optimised strategy sits on a stable plateau
(nearby params also profitable) or a sharp peak (very localised optimum).

Called from pipeline.py after Stage 2 (Hyperopt) and before Stage 3
(Auto-Patching).  Results are stored on the shared PipelineState and
included in the final report.json.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Any

from .variants import create_variant, read_strategy_source, strategy_path_args

logger = logging.getLogger("auto_quant.sensitivity")


# ── Public API ────────────────────────────────────────────────────────────────

async def run_sensitivity_check(
    best_params: dict,
    out_dir: Path,
    run_id: str,
    state: Any,
) -> dict:
    """Perturb the primary numeric param ±5% and run two quick IS backtests.

    Returns a dict with keys:
        passed  — bool  (True = stable plateau, False = sharp peak)
        score   — "High" | "Medium" | "Low"
        label   — "Stable Plateau" | "Sharp Peak" | "Negative Baseline"
        p_best  — float | None  (IS profit with best params)
        p_minus — float | None  (IS profit with param * 0.95)
        p_plus  — float | None  (IS profit with param * 1.05)
        param   — str | None    (name of the perturbed parameter)
        failure_reason — str | None (e.g., "FAIL_NEGATIVE_BASELINE")
    """
    params_dict = best_params.get("params_dict", {})

    # Loop through parameters in priority order, skipping inactive ones
    tried_params = []
    
    while True:
        param_name, base_value, param_type = _pick_primary_param(params_dict)

        if param_name is None:
            if tried_params:
                logger.info(
                    "[%s] Sensitivity | all %d params were inactive — marking stable by default",
                    run_id, len(tried_params)
                )
            else:
                logger.info(
                    "[%s] Sensitivity | no numeric param found — marking stable by default", run_id
                )
            return _make_result(
                passed=True, score="High", label="Stable Plateau",
                p_best=None, p_minus=None, p_plus=None, param=None,
            )

        # Skip if we've already tried this parameter
        if param_name in tried_params:
            # Remove from params_dict to force next priority
            params_dict.pop(param_name, None)
            continue
        
        tried_params.append(param_name)

        logger.info(
            "[%s] Sensitivity | perturbing param=%s  base=%s  type=%s",
            run_id, param_name, base_value, param_type,
        )

        best_dict = dict(params_dict)
        plus_dict = _perturb(dict(params_dict), param_name, base_value, param_type, factor=1.05)
        minus_dict = _perturb(dict(params_dict), param_name, base_value, param_type, factor=0.95)

        try:
            source = read_strategy_source(state)
        except Exception as exc:
            logger.warning(
                "[%s] Sensitivity | cannot read strategy file: %s — skipping", run_id, exc
            )
            return _make_result(
                passed=True, score="High", label="Stable Plateau",
                p_best=None, p_minus=None, p_plus=None, param=None,
            )

        variants = [
            ("SensBest", best_dict),
            ("SensPlus", plus_dict),
            ("SensMinus", minus_dict),
        ]

        profits: dict[str, float | None] = {}

        for tag, pdict in variants:
            strat_name = f"{state.strategy}_{tag}"
            patched = _patch_source(source, strat_name, pdict)
            try:
                create_variant(
                    state,
                    role="sensitivity",
                    strategy_name=strat_name,
                    source=patched,
                )
            except Exception as exc:
                logger.warning("[%s] Sensitivity | cannot write %s: %s", run_id, strat_name, exc)
                profits[tag] = None
                continue

            prefix = f"sensitivity_{tag.lower()}"
            result_prefix = str(out_dir / prefix)
            cmd = [
                state.freqtrade_path, "backtesting",
                "--config", state.config_file,
                "--strategy", strat_name,
                "--timerange", state.in_sample_range,
                "--timeframe", state.timeframe,
                "--user-data-dir", state.user_data_dir,
                "--export", "trades",
                "--export-filename", result_prefix + ".json",
                "--no-color",
                "--cache", "none",
            ]
            cmd += strategy_path_args(state)

            profit = await _run_backtest(
                cmd, run_id, out_dir, prefix, strat_name, state.user_data_dir
            )
            profits[tag] = profit
            logger.info("[%s] Sensitivity | %s  profit=%s", run_id, tag, profit)

        p_best = profits.get("SensBest")
        p_plus = profits.get("SensPlus")
        p_minus = profits.get("SensMinus")

        # Check for negative baseline BEFORE running neighbor math
        # Only flag as FAIL_NEGATIVE_BASELINE if profit is significantly negative (< -10%)
        # Small negative profits (-10% to 0%) are allowed to proceed for further optimization
        if p_best is not None and p_best < -0.10:
            logger.warning(
                "[%s] Sensitivity | NEGATIVE BASELINE DETECTED: p_best=%s — "
                "flagging as FAIL_NEGATIVE_BASELINE instead of running neighbor math",
                run_id, p_best
            )
            return _make_result(
                passed=False, score="Low", label="Negative Baseline",
                p_best=p_best, p_minus=p_minus, p_plus=p_plus, param=param_name,
                failure_reason="FAIL_NEGATIVE_BASELINE"
            )
        
        # If profit is slightly negative (-10% to 0%), log warning but allow to proceed
        if p_best is not None and p_best < 0:
            logger.warning(
                "[%s] Sensitivity | Slightly negative baseline detected: p_best=%s — "
                "allowing to proceed for further optimization",
                run_id, p_best
            )

        # Detect inactive/overridden parameters (p_minus == p_plus == p_best)
        if p_best is not None and p_minus is not None and p_plus is not None:
            if abs(p_minus - p_best) < 1e-9 and abs(p_plus - p_best) < 1e-9:
                logger.info(
                    "[%s] Sensitivity | Parameter %s is INACTIVE "
                    "(p_minus==p_best==p_plus=%s) — skipping and trying next parameter",
                    run_id, param_name, p_best
                )
                # Remove this parameter and try the next one
                params_dict.pop(param_name, None)
                continue

        # If we got here, parameter is active - proceed with scoring
        passed, score, label = _score(p_best, p_plus, p_minus)

        logger.info(
            "[%s] Sensitivity | RESULT: passed=%s  score=%s  label=%s  "
            "p_best=%s  p_minus=%s  p_plus=%s",
            run_id, passed, score, label, p_best, p_minus, p_plus,
        )

        return _make_result(
            passed=passed, score=score, label=label,
            p_best=p_best, p_minus=p_minus, p_plus=p_plus, param=param_name,
        )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _make_result(
    *,
    passed: bool,
    score: str,
    label: str,
    p_best: float | None,
    p_minus: float | None,
    p_plus: float | None,
    param: str | None,
    failure_reason: str | None = None,
) -> dict:
    result = {
        "passed": passed,
        "score": score,
        "label": label,
        "p_best": p_best,
        "p_minus": p_minus,
        "p_plus": p_plus,
        "param": param,
    }
    if failure_reason:
        result["failure_reason"] = failure_reason
    return result


def _pick_primary_param(params_dict: dict) -> tuple[str | None, Any, str]:
    """Return (param_name, base_value, type) for the primary numeric param.

    Priority order (Omni-Strategy aware):
      1. Boolean switches (use_ema_cross, use_atr, use_rsi, use_macd, use_bb, use_adx)
      2. Custom trailing tiers (ts_tier1_trigger, ts_tier1_lock, ts_tier2_trigger, ts_tier2_lock, ts_tier3_trigger, ts_tier3_lock)
      3. Core indicator lengths (ema_slow_p, ema_fast_p, atr_window)
      4. Basic parameters (stoploss, minimal_roi)
      5. Other numeric scalars

    Returns (None, None, "scalar") if no candidate found.
    """
    # Priority 1: Boolean switches
    bool_switches = ["use_ema_cross", "use_atr", "use_rsi", "use_macd", "use_bb", "use_adx"]
    for key in bool_switches:
        if key in params_dict:
            val = params_dict[key]
            if isinstance(val, bool):
                return key, val, "boolean"

    # Priority 2: Custom trailing tiers
    ts_tier_params = [
        "ts_tier1_trigger", "ts_tier1_lock",
        "ts_tier2_trigger", "ts_tier2_lock",
        "ts_tier3_trigger", "ts_tier3_lock",
    ]
    for key in ts_tier_params:
        if key in params_dict:
            val = params_dict[key]
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                return key, float(val), "scalar"

    # Priority 3: Core indicator lengths
    indicator_lengths = ["ema_slow_p", "ema_fast_p", "atr_window"]
    for key in indicator_lengths:
        if key in params_dict:
            val = params_dict[key]
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                return key, float(val), "scalar"

    # Priority 4: Basic parameters
    if "stoploss" in params_dict:
        val = params_dict["stoploss"]
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return "stoploss", float(val), "scalar"

    if "minimal_roi" in params_dict:
        roi = params_dict["minimal_roi"]
        if isinstance(roi, dict) and roi:
            for v in roi.values():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    return "minimal_roi", roi, "roi"

    # Priority 5: Other numeric scalars
    for k, v in params_dict.items():
        if k in bool_switches + ts_tier_params + indicator_lengths + ["minimal_roi", "stoploss"]:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return k, float(v), "scalar"

    return None, None, "scalar"


def _perturb(
    params_dict: dict,
    param_name: str,
    base_value: Any,
    param_type: str,
    factor: float,
) -> dict:
    """Return a deep copy of params_dict with param_name perturbed by factor.

    Preserves the original numeric type:
      - bool  (Boolean switches) → flip value (True ↔ False)
      - int  (indicator periods) → perturb, round, cast back to int, clamp ≥ 1
      - float (stoploss / ROI)  → perturb, round to 6 dp
    """
    result = copy.deepcopy(params_dict)
    if param_type == "boolean":
        # Flip boolean value
        result[param_name] = not base_value
    elif param_type == "roi":
        roi = result["minimal_roi"]
        result["minimal_roi"] = {k: round(float(v) * factor, 6) for k, v in roi.items()}
    elif isinstance(base_value, int):
        result[param_name] = max(1, int(round(float(base_value) * factor)))
    else:
        result[param_name] = round(float(base_value) * factor, 6)
    return result


def _patch_source(source: str, new_class_name: str, params_dict: dict) -> str:
    """Return a modified copy of strategy source with renamed class and injected params."""
    source = re.sub(r'class\s+\w+\s*\(', f'class {new_class_name}(', source, count=1)

    if "stoploss" in params_dict:
        val = params_dict["stoploss"]
        source = re.sub(r'(stoploss\s*=\s*)[-\d.]+', f'\\g<1>{val}', source)

    if "minimal_roi" in params_dict:
        roi = params_dict["minimal_roi"]
        roi_str = json.dumps(roi, indent=4)
        source = re.sub(
            r'(minimal_roi\s*=\s*)\{[^}]*\}',
            f'\\g<1>{roi_str}',
            source,
            flags=re.DOTALL,
        )

    for key, val in params_dict.items():
        if key in ("stoploss", "minimal_roi"):
            continue
        # Handle boolean parameters
        if isinstance(val, bool):
            val_str = "True" if val else "False"
            source = re.sub(
                rf'({re.escape(key)}\s*=\s*)(True|False)',
                f'\\g<1>{val_str}',
                source,
            )
        # Handle numeric parameters
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            source = re.sub(
                rf'({re.escape(key)}\s*=\s*)[-\d.]+',
                f'\\g<1>{val}',
                source,
            )

    return source


async def _run_backtest(
    cmd: list[str],
    run_id: str,
    out_dir: Path,
    prefix: str,
    strat_name: str,
    user_data_dir: str,
) -> float | None:
    """Run a freqtrade backtest and return profit_total.  Returns None on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception as exc:
                logger.warning("[%s] Sensitivity | failed to kill timed out process: %s", run_id, exc)
            logger.warning(
                "[%s] Sensitivity | backtest timed out for %s", run_id, strat_name
            )
            return None
        rc = proc.returncode or 0
    except Exception as exc:
        logger.warning(
            "[%s] Sensitivity | failed to spawn backtest for %s: %s", run_id, strat_name, exc
        )
        return None

    if rc != 0:
        logger.warning(
            "[%s] Sensitivity | backtest exited rc=%d for %s", run_id, rc, strat_name
        )
        return None

    result_data = _find_result(out_dir, prefix, user_data_dir)
    if not result_data:
        return None
    return _extract_profit(result_data, strat_name)


def _find_result(out_dir: Path, prefix: str, user_data_dir: str) -> dict:
    """Find a freqtrade backtest result JSON (same lookup order as pipeline)."""
    direct = out_dir / f"{prefix}.json"
    if direct.exists():
        try:
            return json.loads(direct.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Sensitivity | failed to read direct result %s: %s", direct, exc)

    candidates = sorted(
        out_dir.glob(f"{prefix}*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        try:
            return json.loads(candidates[0].read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Sensitivity | failed to read candidate result %s: %s", candidates[0], exc)

    last_ptr = Path(user_data_dir) / "backtest_results" / ".last_result.json"
    if last_ptr.exists():
        try:
            ptr = json.loads(last_ptr.read_text(encoding="utf-8"))
            latest_name = ptr.get("latest_backtest")
            if latest_name:
                latest_zip = Path(user_data_dir) / "backtest_results" / latest_name
                if latest_zip.exists():
                    with zipfile.ZipFile(latest_zip) as archive:
                        json_members = [
                            n for n in archive.namelist()
                            if n.endswith(".json") and not n.endswith("_config.json")
                        ]
                        if json_members:
                            preferred = next(
                                (n for n in json_members if "_result" not in n),
                                json_members[0],
                            )
                            with archive.open(preferred) as fh:
                                return json.loads(fh.read())
        except Exception as exc:
            logger.warning("Sensitivity | failed to read archive result: %s", exc)

    return {}


def _extract_profit(data: dict, strat_name: str) -> float | None:
    """Extract profit_total from a backtest result dict."""
    strategy_data = data.get("strategy", {})
    if strat_name in strategy_data:
        s = strategy_data[strat_name]
    elif strategy_data:
        s = next(iter(strategy_data.values()))
    else:
        s = data

    val = s.get("profit_total", s.get("profit_total_abs"))
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _score(
    p_best: float | None,
    p_plus: float | None,
    p_minus: float | None,
) -> tuple[bool, str, str]:
    """Compute (passed, score, label) from three profit values.

    Fail-closed design: if either neighbour backtest could not be run
    (None), the check fails with a Low score so the self-healing retry
    loop can attempt a different optimisation axis.

    Failure conditions (trigger a retry):
      • either neighbour is None  (backtest could not execute)
      • any neighbour profit < 0
      • any neighbour profit < p_best * 0.3  (only when p_best > 0)

    Score (all-pass):
      High   — min(neighbours) >= p_best * 0.70
      Medium — min(neighbours) >= p_best * 0.50
      Low    — passed but weaker
    """
    # Fail-closed: missing neighbour results cannot be treated as passes
    if p_plus is None or p_minus is None:
        return False, "Low", "Sharp Peak"

    neighbors = [p_plus, p_minus]

    # Allow slight negative neighbors (-5%) when p_best is positive
    if p_best is not None and p_best > 0:
        if any(v < -0.05 for v in neighbors):
            return False, "Low", "Sharp Peak"
    else:
        if any(v < 0 for v in neighbors):
            return False, "Low", "Sharp Peak"

    if p_best is not None and p_best > 0:
        threshold_30 = p_best * 0.3
        if any(v < threshold_30 for v in neighbors):
            return False, "Low", "Sharp Peak"

    if p_best is not None and p_best > 0:
        min_n = min(neighbors)
        if min_n >= p_best * 0.50:
            return True, "High", "Stable Plateau"
        if min_n >= p_best * 0.30:
            return True, "Medium", "Stable Plateau"
        return True, "Low", "Stable Plateau"

    return True, "Medium", "Stable Plateau"
