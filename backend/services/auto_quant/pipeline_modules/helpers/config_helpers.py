"""Configuration and command building helpers."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from ..logging import logger
from ..state import PipelineState


def _backtest_cmd(
    state: PipelineState,
    *,
    strategy: str,
    timerange: str,
    result_prefix: str,
    pairs: list[str] | None = None,
) -> list[str]:
    # Handle "py -m freqtrade" command by splitting it
    if state.freqtrade_path == "py -m freqtrade":
        cmd = [
            "py", "-m", "freqtrade", "backtesting",
            "--config", state.config_file,
            "--strategy", strategy,
            "--timerange", timerange,
            "--timeframe", state.timeframe,
            "--user-data-dir", state.user_data_dir,
            "--export", "trades",
            "--export-filename", result_prefix + ".json",
            "--no-color",
            "--cache", "none",
        ]
    else:
        cmd = [
            state.freqtrade_path, "backtesting",
            "--config", state.config_file,
            "--strategy", strategy,
            "--timerange", timerange,
            "--timeframe", state.timeframe,
            "--user-data-dir", state.user_data_dir,
            "--export", "trades",
            "--export-filename", result_prefix + ".json",
            "--no-color",
            "--cache", "none",
        ]
    try:
        from ...variants import strategy_path_args

        cmd += strategy_path_args(state)
    except Exception:
        pass
    if pairs:
        cmd += ["--pairs"] + pairs
    return cmd


def _parse_fthypt_file(filepath: Path) -> dict | None:
    """Parse a freqtrade 2024+ hyperopt result file (``*.fthypt``).

    Modern freqtrade writes JSON-lines (one epoch per line). Each line is a
    complete JSON object carrying ``params_dict``, ``loss`` and (optionally)
    ``is_best``. We pick the epoch flagged ``is_best`` or, if none is flagged,
    the one with the lowest ``loss``.
    """
    try:
        with open(filepath, encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    except Exception as exc:
        logger.warning("Helpers | failed to read hyperopt file %s: %s", filepath, exc)
        return None

    # Some versions store a single JSON object with a "results" array instead.
    if len(lines) == 1:
        try:
            single = json.loads(lines[0])
            if isinstance(single, dict) and "results" in single:
                lines = [json.dumps(r) for r in single["results"]]
        except Exception:
            pass

    epochs = []
    for ln in lines:
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if isinstance(obj, dict) and ("params_dict" in obj or "loss" in obj):
            epochs.append(obj)

    if not epochs:
        logger.warning("Helpers | no valid hyperopt epochs found in %s", filepath)
        return None

    # Only short-circuit when a trade-count field is genuinely present AND zero
    # everywhere. freqtrade 2026.6 .fthypt epochs omit the top-level
    # "total_trades" key (trades live under results_metrics), so its absence
    # must NOT be interpreted as "no trades".
    trades_present = [e["total_trades"] for e in epochs if "total_trades" in e]
    if trades_present and all(t == 0 for t in trades_present):
        logger.warning(
            "Helpers | hyperopt produced 0 trades across %d epochs - no parameters to extract. "
            "Check strategy config, timerange, or hyperopt spaces.",
            len(epochs)
        )
        return None

    best = next((e for e in epochs if e.get("is_best")), None)
    if best is None:
        best = min(epochs, key=lambda e: e.get("loss", float("inf")))

    params_dict = best.get("params_dict") or {}
    
    # If we still have no params_dict but have a valid epoch, log a warning
    if not params_dict:
        logger.warning(
            "Helpers | best epoch has no params_dict field - "
            "hyperopt may have failed to optimize parameters"
        )
    
    return {"params_dict": params_dict, "loss": best.get("loss")}


async def _extract_hyperopt_best(
    state: PipelineState, out_dir: Path
) -> dict | None:
    """Extract best hyperopt result using multiple methods in order of reliability."""

    def _save_and_return(obj: dict) -> dict:
        try:
            (out_dir / "hyperopt_best.json").write_text(
                json.dumps(obj, indent=2, default=str), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("Helpers | failed to save hyperopt_best.json: %s", exc)
        return obj

    logger.info("Helpers | Attempting to extract best hyperopt parameters")

    # ── Method 1: Parse the on-disk .fthypt result file directly ────────────
    # Modern freqtrade (2024+) stores results as ``*.fthypt`` in the
    # user_data/hyperopt_results directory — NOT the legacy ``hyperopt_results.json``.
    # Reading the file directly is version-proof and avoids spawning a subprocess.
    logger.info("Helpers | Method 1: Parsing .fthypt result file")
    hyperopt_dir = Path(state.user_data_dir) / "hyperopt_results"
    try:
        candidates = sorted(
            hyperopt_dir.glob("*.fthypt"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except Exception as exc:
        logger.warning("Helpers | failed to list hyperopt_results dir: %s", exc)
        candidates = []
    for path in candidates:
        # Skip ticker data pickle leftovers that share the extension pattern.
        if path.name == "hyperopt_tickerdata.pkl":
            continue
        result = _parse_fthypt_file(path)
        if result and result.get("params_dict"):
            logger.info(
                "Helpers | Method 1 succeeded: parsed %s (params=%d)",
                path.name, len(result["params_dict"]),
            )
            return _save_and_return(result)

    # ── Method 2: freqtrade hyperopt-show --print-json ─────────────────────
    # NOTE: modern ``hyperopt-show`` does NOT accept ``--strategy`` (it reads the
    # latest result automatically), so we must omit it — otherwise the command
    # aborts with "unrecognized arguments: --strategy".
    logger.info("Helpers | Method 2: Running hyperopt-show")
    cmd = [
        state.freqtrade_path, "hyperopt-show",
        "--config", state.config_file,
        "--user-data-dir", state.user_data_dir,
        "--best",
        "--print-json",
        "--no-color",
    ]
    import shlex
    logger.info("Helpers | Method 2: Running hyperopt-show command: %s", shlex.join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        output = (result.stdout + result.stderr).strip()
        logger.info("Helpers | hyperopt-show stdout length: %d, stderr length: %d", len(result.stdout), len(result.stderr))
        logger.debug("Helpers | hyperopt-show stdout: %s", result.stdout[:500] if result.stdout else "empty")
        logger.debug("Helpers | hyperopt-show stderr: %s", result.stderr[:500] if result.stderr else "empty")

        if not output:
            logger.warning("Helpers | hyperopt-show produced no output")
        else:
            decoder = json.JSONDecoder()
            for i, ch in enumerate(output):
                if ch == "{":
                    try:
                        obj, _ = decoder.raw_decode(output, i)
                        # Check for various possible structures from freqtrade
                        if isinstance(obj, dict):
                            # Direct params_dict or loss
                            if "params_dict" in obj or "loss" in obj:
                                logger.info("Helpers | Method 2 succeeded: found direct params_dict or loss in output")
                                return _save_and_return(obj)
                            # Nested params structure (from hyperopt-show)
                            if "params" in obj:
                                params_dict: dict = {}
                                nested = obj["params"]
                                for space, vals in nested.items():
                                    if not isinstance(vals, dict):
                                        continue
                                    if space == "roi":
                                        # ROI is special - it's a dict of time:profit pairs
                                        params_dict["minimal_roi"] = vals
                                    else:
                                        params_dict.update(vals)
                                logger.info("Helpers | Method 2 succeeded: extracted params from nested structure")
                                return _save_and_return({"params_dict": params_dict, "loss": obj.get("loss")})
                    except json.JSONDecodeError:
                        continue
    except subprocess.TimeoutExpired:
        logger.warning("Helpers | hyperopt-show timed out after 60s")
    except Exception as exc:
        logger.warning("Helpers | hyperopt-show failed: %s", exc)

    # ── Method 3: Legacy hyperopt_results.json fallback ─────────────────────
    logger.info("Helpers | Method 3: Parsing legacy hyperopt_results.json")
    hyperopt_results_file = Path(state.user_data_dir) / "hyperopt_results" / "hyperopt_results.json"
    if hyperopt_results_file.exists():
        try:
            with open(hyperopt_results_file, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "best_result" in data:
                best = data["best_result"]
                if isinstance(best, dict):
                    logger.info("Helpers | Method 3 succeeded: found best_result in hyperopt_results.json")
                    return _save_and_return(best)
        except Exception as exc:
            logger.warning("Helpers | Failed to parse hyperopt_results.json: %s", exc)

    logger.warning("Helpers | All methods failed: no valid hyperopt result found")
    return None


def _inject_params(source: str, new_class_name: str, best_params: dict, param_overrides: dict | None = None) -> str:
    """Clone strategy source, rename the class, and inject best hyperopt params.
    
    Args:
        source: Strategy source code
        new_class_name: Name for the cloned class
        best_params: Hyperopt best params dict
        param_overrides: Optional dict of forced parameter overrides (e.g., from hard mutation)
    """
    # Rename class
    source = re.sub(
        r'class\s+\w+\s*\(',
        f'class {new_class_name}(',
        source,
        count=1,
    )

    params_dict = best_params.get("params_dict", {})
    if not params_dict and "params_details" in best_params:
        # Some freqtrade versions nest params differently
        params_dict = {}
        for space_params in best_params["params_details"].values():
            if isinstance(space_params, dict):
                params_dict.update(space_params)
    
    # Apply param_overrides first (they take precedence)
    if param_overrides:
        params_dict = dict(params_dict)  # Make a copy
        params_dict.update(param_overrides)

    def _format_parameter_default(value: Any) -> str:
        if isinstance(value, bool):
            return "True" if value else "False"
        if isinstance(value, str):
            return json.dumps(value)
        if value is None:
            return "None"
        return str(value)

    def _inject_parameter_default(param_name: str, value: Any, current_source: str) -> str:
        parameter_classes = "DecimalParameter|IntParameter|CategoricalParameter"
        pattern = re.compile(
            rf'(\b{re.escape(param_name)}\s*=\s*(?:{parameter_classes})\s*\(.*?\bdefault\s*=\s*)'
            r'([^,\)]+)',
            flags=re.DOTALL,
        )
        return pattern.sub(
            lambda m: f"{m.group(1)}{_format_parameter_default(value)}",
            current_source,
            count=1,
        )

    # Inject stoploss
    if "stoploss" in params_dict:
        val = params_dict["stoploss"]
        source = re.sub(
            r'(stoploss\s*=\s*)[-\d.]+',
            f'\\g<1>{val}',
            source,
        )

    # Inject minimal_roi (may be nested)
    if "minimal_roi" in params_dict:
        roi = params_dict["minimal_roi"]
        roi_str = json.dumps(roi, indent=4)
        source = re.sub(
            r'(minimal_roi\s*=\s*)\{[^}]*\}',
            f'\\g<1>{roi_str}',
            source,
            flags=re.DOTALL,
        )

    # Inject trailing stop params
    for key, attr in [
        ("trailing_stop", "trailing_stop"),
        ("trailing_stop_positive", "trailing_stop_positive"),
        ("trailing_stop_positive_offset", "trailing_stop_positive_offset"),
        ("trailing_only_offset_is_reached", "trailing_only_offset_is_reached"),
    ]:
        if key in params_dict:
            val = params_dict[key]
            if isinstance(val, bool):
                val_str = "True" if val else "False"
            else:
                val_str = str(val)
            source = re.sub(
                rf'({re.escape(attr)}\s*=\s*)(\S+)',
                f'\\g<1>{val_str}',
                source,
            )

    special_keys = {
        "stoploss",
        "minimal_roi",
        "trailing_stop",
        "trailing_stop_positive",
        "trailing_stop_positive_offset",
        "trailing_only_offset_is_reached",
    }

    # Inject remaining parameters
    for param_name, value in params_dict.items():
        if param_name in special_keys:
            continue
        source = _inject_parameter_default(param_name, value, source)

    return source


def _aggregate_wfa_parameters(
    window_params: list[dict],
    recency_weights: list[float],
) -> dict:
    """Aggregate Walk-Forward Analysis parameters across windows with recency weighting.
    
    Args:
        window_params: List of parameter dicts from each WFA window
        recency_weights: List of weights for each window (should sum to 1.0)
    
    Returns:
        Aggregated parameter dict with weighted averages for numeric params
        and most-recent values for categorical params
    """
    if not window_params:
        return {}
    
    if len(window_params) != len(recency_weights):
        logger.warning("Helpers | window_params length %d != recency_weights length %d, using equal weights",
                      len(window_params), len(recency_weights))
        recency_weights = [1.0 / len(window_params)] * len(window_params)
    
    aggregated = {}
    param_types = {}  # Track param types (numeric vs categorical)
    
    # First pass: determine parameter types
    for params in window_params:
        for key, value in params.items():
            if key not in param_types:
                param_types[key] = isinstance(value, (int, float))
    
    # Second pass: aggregate based on type
    for key, is_numeric in param_types.items():
        if is_numeric:
            # Weighted average for numeric params
            weighted_sum = 0.0
            total_weight = 0.0
            for params, weight in zip(window_params, recency_weights):
                if key in params:
                    weighted_sum += params[key] * weight
                    total_weight += weight
            if total_weight > 0:
                aggregated[key] = weighted_sum / total_weight
        else:
            # Most recent value for categorical params
            aggregated[key] = window_params[-1].get(key)
    
    return aggregated


def _create_temp_config_with_fee_override(
    base_config_path: str | Path,
    fee_multiplier: float,
    out_dir: Path,
) -> Path:
    """Create a temporary config file with fee multiplier override for stress testing.
    
    Args:
        base_config_path: Path to the base freqtrade config file
        fee_multiplier: Multiplier for fees (e.g., 2.0 for 2x fees)
        out_dir: Directory to write the temporary config
    
    Returns:
        Path to the temporary config file
    """
    import json
    from pathlib import Path
    
    base_config_path = Path(base_config_path)
    with open(base_config_path, encoding="utf-8") as f:
        config = json.load(f)
    
    # Override fee settings
    if "trading_mode" in config:
        config["trading_mode"] = "spot"  # Force spot mode for stress testing
    
    # Apply fee multiplier to all fee settings
    if "fee" in config:
        base_fee = config["fee"]
        config["fee"] = base_fee * fee_multiplier
    
    # Write temporary config
    temp_config_path = out_dir / f"temp_config_fee_{fee_multiplier}x.json"
    with open(temp_config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    
    return temp_config_path


def _create_temp_config_with_max_open_trades(
    base_config_path: str | Path,
    max_open_trades: int,
    out_dir: Path,
) -> Path:
    """Create a temporary config file with max_open_trades override.
    
    Args:
        base_config_path: Path to the base freqtrade config file
        max_open_trades: Maximum number of concurrent trades
        out_dir: Directory to write the temporary config
    
    Returns:
        Path to the temporary config file
    """
    import json
    from pathlib import Path
    
    base_config_path = Path(base_config_path)
    with open(base_config_path, encoding="utf-8") as f:
        config = json.load(f)
    
    # Override max_open_trades
    config["max_open_trades"] = max_open_trades
    
    # Write temporary config
    temp_config_path = out_dir / f"temp_config_max_trades_{max_open_trades}.json"
    with open(temp_config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    
    return temp_config_path


def _extract_last_close_price(
    pair: str,
    user_data_dir: str,
    timerange: str | None = None,
) -> float | None:
    """Extract the last close price for a pair from freqtrade data.
    
    Args:
        pair: Trading pair (e.g., "BTC/USDT")
        user_data_dir: Path to freqtrade user data directory
        timerange: Optional timerange to filter data
    
    Returns:
        Last close price or None if not available
    """
    from pathlib import Path
    
    data_dir = Path(user_data_dir) / "data"
    
    # Try to find the pair data file
    pair_filename = pair.replace("/", "_")
    pair_files = list(data_dir.rglob(f"{pair_filename}*.json"))
    
    if not pair_files:
        logger.warning("Helpers | No data file found for pair %s", pair)
        return None
    
    # Use the most recent file
    latest_file = max(pair_files, key=lambda p: p.stat().st_mtime)
    
    try:
        with open(latest_file, encoding="utf-8") as f:
            data = json.load(f)
        
        if not data:
            return None
        
        # Get the last candle's close price
        last_candle = data[-1]
        return float(last_candle.get("close", 0.0))
    except Exception as exc:
        logger.warning("Helpers | Failed to extract close price from %s: %s", latest_file, exc)
        return None


# Export strategy_path_args for use in other modules
def strategy_path_args(state: PipelineState) -> list[str]:
    """Get strategy path arguments for freqtrade commands."""
    from ...variants import strategy_path_args as _strategy_path_args
    return _strategy_path_args(state)
