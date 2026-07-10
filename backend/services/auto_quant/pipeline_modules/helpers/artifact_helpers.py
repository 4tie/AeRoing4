"""Backtest result finding and extraction helpers."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from ..logging import logger


def _find_backtest_result(out_dir: Path, prefix: str, user_data_dir: str | None = None) -> dict:
    """Find and parse the freqtrade backtest result JSON for this stage.

    Freqtrade does not always honour the ``--export-filename`` absolute path —
    it may write to its default ``backtest_results/`` directory instead.  We
    try three locations in order:
      1. The direct ``{out_dir}/{prefix}.json`` path we passed to freqtrade.
      2. Any ``{prefix}*.json`` glob in ``out_dir`` (timestamped variants).
      3. The latest zip in ``user_data/backtest_results/`` via
         ``backtest_results/.last_result.json`` (freqtrade's own pointer file).
    """
    # 1. Direct export-filename path
    direct = out_dir / f"{prefix}.json"
    if direct.exists():
        try:
            logger.debug("Helpers | loading direct backtest result: %s", direct)
            return json.loads(direct.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Helpers | failed to read direct result %s: %s", direct, exc)

    # 2. Glob fallback inside out_dir
    candidates = sorted(
        out_dir.glob(f"{prefix}*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        try:
            logger.debug("Helpers | loading fallback backtest result: %s", candidates[0])
            return json.loads(candidates[0].read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Helpers | failed to read candidate result %s: %s", candidates[0], exc)

    # 3. Read from freqtrade's default backtest_results directory
    if user_data_dir:
        data = _read_latest_freqtrade_backtest(Path(user_data_dir), out_dir, prefix)
        if data:
            return data

    return {}


def _read_latest_freqtrade_backtest(
    user_data_dir: Path, out_dir: Path, prefix: str
) -> dict:
    """Extract the latest backtest result zip from freqtrade's default output dir.

    freqtrade writes ``backtest_results/.last_result.json`` pointing at the
    newest zip.  We open that zip, pull out the main JSON member, cache it to
    ``out_dir/{prefix}.json`` for subsequent calls, and return the parsed dict.
    """
    results_dir = user_data_dir / "backtest_results"
    last_ptr = results_dir / ".last_result.json"
    if not last_ptr.exists():
        return {}
    try:
        ptr_data = json.loads(last_ptr.read_text(encoding="utf-8"))
    except Exception:
        return {}

    latest_name = ptr_data.get("latest_backtest")
    if not latest_name:
        return {}

    latest_zip = results_dir / latest_name
    if not latest_zip.exists():
        logger.warning("Helpers | latest backtest zip missing: %s", latest_zip)
        return {}

    try:
        logger.debug("Helpers | loading latest backtest zip: %s", latest_zip)
        with zipfile.ZipFile(latest_zip) as archive:
            json_members = [
                name for name in archive.namelist()
                if name.endswith(".json") and not name.endswith("_config.json")
            ]
            if not json_members:
                return {}
            # Prefer the member whose name doesn't include "_result" (the trades file)
            preferred = next(
                (n for n in json_members if "_result" not in n), json_members[0]
            )
            with archive.open(preferred) as fh:
                data = json.loads(fh.read())
        # Cache to out_dir so the direct path works on any retry
        try:
            (out_dir / f"{prefix}.json").write_text(
                json.dumps(data), encoding="utf-8"
            )
        except Exception:
            pass
        return data
    except Exception:
        return {}


def _extract_backtest_summary(data: dict, strategy_name: str) -> dict:
    """Extract top-level summary metrics for a strategy from a backtest result."""
    strategy_data = data.get("strategy", {})
    if strategy_name in strategy_data:
        return strategy_data[strategy_name]
    # Fallback: return first strategy if name not found
    if strategy_data:
        return next(iter(strategy_data.values()))
    return {}


def _extract_trade_count(data: dict, strategy_name: str) -> int:
    summary = _extract_backtest_summary(data, strategy_name)
    return int(summary.get("total_trades", 0))


def _extract_per_pair_results(data: dict, strategy_name: str) -> list[dict]:
    """Extract per-pair profit data from backtest result.

    Supports both old format (strategy[strategy_name].per_pair) and new format
    (results_per_pair at top level) for backward compatibility.
    """
    def extract_win_rate(pair_data: dict) -> float:
        """Extract win rate from pair data, handling both 'winrate' and 'win_rate' field names."""
        return pair_data.get("winrate", pair_data.get("win_rate", 0.0))

    def _is_summary_row(pair_data: dict) -> bool:
        """Return True for freqtrade aggregate summary rows (e.g. 'TOTAL') that
        are not real trading pairs and must never be included in pair lists."""
        key = pair_data.get("key", "")
        return key.strip().upper() == "TOTAL"

    # Try new format first (results_per_pair at top level)
    per_pair = data.get("results_per_pair", [])
    if per_pair:
        result = []
        for pair_data in per_pair:
            if _is_summary_row(pair_data):
                continue  # skip the freqtrade aggregate TOTAL row
            result.append({
                "key": pair_data.get("key", ""),
                "profit_total": pair_data.get("profit_total", 0.0),
                "profit_total_abs": pair_data.get("profit_total_abs", 0.0),
                "profit_factor": pair_data.get("profit_factor", 0.0),
                "trades": pair_data.get("trades", 0),
                "win_rate": extract_win_rate(pair_data),
                "max_drawdown": pair_data.get("max_drawdown", 0.0),
            })
        return result

    # Fallback to old format (strategy[strategy_name].results_per_pair or .per_pair)
    strategy_data = data.get("strategy", {})
    if strategy_name in strategy_data:
        # Try results_per_pair first (newer old format)
        per_pair = strategy_data[strategy_name].get("results_per_pair", [])
        if not per_pair:
            # Fallback to per_pair (older format)
            per_pair = strategy_data[strategy_name].get("per_pair", [])
        result = []
        for pair_data in per_pair:
            if _is_summary_row(pair_data):
                continue  # skip the freqtrade aggregate TOTAL row
            result.append({
                "key": pair_data.get("key", ""),
                "profit_total": pair_data.get("profit_total", 0.0),
                "profit_total_abs": pair_data.get("profit_total_abs", 0.0),
                "profit_factor": pair_data.get("profit_factor", 0.0),
                "trades": pair_data.get("trades", 0),
                "win_rate": extract_win_rate(pair_data),
                "max_drawdown": pair_data.get("max_drawdown", 0.0),
            })
        return result
    return []


def _extract_trade_distribution(data: dict, strategy_name: str) -> dict:
    """Extract trade distribution data for visualization."""
    from ...profit_lockin import extract_strategy_trades
    
    trades = extract_strategy_trades(data, strategy_name)
    if not trades:
        return {"by_pair": {}, "by_hour": {}, "by_day": {}}
    
    by_pair = {}
    by_hour = {}
    by_day = {}
    
    for trade in trades:
        pair = trade.get("pair", "unknown")
        profit = trade.get("profit_abs", 0.0)
        
        # By pair
        if pair not in by_pair:
            by_pair[pair] = {"count": 0, "total_profit": 0.0, "wins": 0, "losses": 0}
        by_pair[pair]["count"] += 1
        by_pair[pair]["total_profit"] += profit
        if profit > 0:
            by_pair[pair]["wins"] += 1
        else:
            by_pair[pair]["losses"] += 1
        
        # By hour (if timestamp available)
        if "open_date" in trade:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(trade["open_date"])
                hour = dt.hour
                if hour not in by_hour:
                    by_hour[hour] = {"count": 0, "total_profit": 0.0}
                by_hour[hour]["count"] += 1
                by_hour[hour]["total_profit"] += profit
            except Exception:
                pass
        
        # By day (if timestamp available)
        if "open_date" in trade:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(trade["open_date"])
                day = dt.strftime("%A")
                if day not in by_day:
                    by_day[day] = {"count": 0, "total_profit": 0.0}
                by_day[day]["count"] += 1
                by_day[day]["total_profit"] += profit
            except Exception:
                pass
    
    return {
        "by_pair": by_pair,
        "by_hour": by_hour,
        "by_day": by_day,
    }
