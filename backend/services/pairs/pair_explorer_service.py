"""Pair Explorer API helper services.

The router keeps the FastAPI contract; this module owns persistence,
data-availability checks, result parsing, and session result normalization.
"""

from __future__ import annotations

import asyncio
import json
import zipfile
from pathlib import Path
from typing import Any

from ...models import DownloadDataRequest
from ...services.execution.data_download_runner import DataDownloadRunner

DOWNLOAD_LOCK = asyncio.Lock()
TERMINAL_GROUP_STATUSES = {"completed", "failed"}

# ── Shared in-memory session store ────────────────────────────────────────────
# The router and the AI pair-explorer job function share this dict so that
# the existing poll endpoint works regardless of which code path started the job.
SESSIONS: dict[str, dict[str, Any]] = {}


def register_session(session: dict[str, Any]) -> None:
    """Register a new pair-explorer session in the shared in-memory store."""
    SESSIONS[session["session_id"]] = session


def get_session(session_id: str) -> dict[str, Any] | None:
    """Return the in-memory session dict, or None if not found."""
    return SESSIONS.get(session_id)




def sessions_dir(user_data_dir: str) -> Path:
    directory = Path(user_data_dir) / "pair_explorer_sessions"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_session(session: dict[str, Any], user_data_dir: str) -> None:
    try:
        target = sessions_dir(user_data_dir) / f"{session['session_id']}.json"
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(session, indent=2), encoding="utf-8")
        tmp.replace(target)
    except Exception:
        pass


def load_all_sessions(user_data_dir: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    try:
        for path in sorted(sessions_dir(user_data_dir).glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                session_id = data.get("session_id")
                if session_id:
                    result[session_id] = data
            except Exception:
                pass
    except Exception:
        pass
    return result


def data_file_exists(user_data_dir: str, exchange: str, pair: str, timeframe: str) -> bool:
    pair_file = pair.replace("/", "_")
    data_dir = Path(user_data_dir) / "data" / exchange.lower()
    for extension in ("feather", "json", "jsongz", "parquet"):
        if (data_dir / f"{pair_file}-{timeframe}.{extension}").exists():
            return True
    return False


async def ensure_data(
    runner: DataDownloadRunner,
    pair: str,
    timeframe: str,
    timerange: str,
    config_file: str,
    user_data_dir: str,
    exchange: str,
) -> str | None:
    """Download data for a pair if not already present; returns an error string on failure."""
    if data_file_exists(user_data_dir, exchange, pair, timeframe):
        return None

    async with DOWNLOAD_LOCK:
        if data_file_exists(user_data_dir, exchange, pair, timeframe):
            return None
        request = DownloadDataRequest(
            config_file=config_file,
            timerange=timerange,
            timeframes=[timeframe],
            pairs=[pair],
        )
        try:
            await asyncio.wait_for(
                asyncio.to_thread(runner.run_download, request),
                timeout=180,
            )
            return None
        except asyncio.TimeoutError:
            return "Download timed out after 3 minutes"
        except Exception as exc:
            return str(exc)


def snapshot_zips(backtest_results_dir: Path) -> set[Path]:
    if not backtest_results_dir.exists():
        return set()
    return set(backtest_results_dir.glob("*.zip"))


def find_new_zip(before: set[Path], backtest_results_dir: Path) -> Path | None:
    after = snapshot_zips(backtest_results_dir)
    new = after - before
    if not new:
        return None
    return max(new, key=lambda path: path.stat().st_mtime)


def parse_zip_result(zip_path: Path, strategy_name: str) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            candidates = [
                name
                for name in zf.namelist()
                if name.endswith(".json") and "_config" not in name and not name.startswith(".")
            ]
            if not candidates:
                return {}
            candidates.sort(key=len)
            with zf.open(candidates[0]) as handle:
                payload = json.load(handle)
    except Exception:
        return {}
    return extract_metrics(payload, strategy_name)


def strategy_block(payload: dict, strategy_name: str) -> dict[str, Any]:
    strategy_payload = payload.get("strategy", {})
    if not isinstance(strategy_payload, dict):
        return {}
    block = strategy_payload.get(strategy_name)
    if isinstance(block, dict):
        return block
    for value in strategy_payload.values():
        if isinstance(value, dict):
            return value
    return {}


def extract_trade_rows(payload: dict, block: dict[str, Any]) -> list[dict[str, Any]]:
    for raw in (payload.get("trades"), block.get("trades")):
        if isinstance(raw, list):
            return [trade for trade in raw if isinstance(trade, dict)]
    return []


def extract_metrics(payload: dict, strategy_name: str) -> dict[str, Any]:
    block = strategy_block(payload, strategy_name)
    if not block:
        return {}

    def _num(data: dict, *keys) -> float | None:
        for key in keys:
            value = data.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass
        return None

    def _int(data: dict, *keys) -> int | None:
        for key in keys:
            value = data.get(key)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
        return None

    trades = extract_trade_rows(payload, block)
    total_trades = _int(block, "total_trades") or len(trades)

    profit_pct = _num(block, "profit_total_pct")
    if profit_pct is None:
        profit_ratio = _num(block, "profit_total", "profit_total_long")
        profit_pct = round(profit_ratio * 100, 4) if profit_ratio is not None else None
    else:
        profit_pct = round(profit_pct, 4)

    wins = sum(int(row.get("wins", 0)) for row in block.get("results_per_pair", []))
    win_rate = round(wins / total_trades * 100, 2) if total_trades > 0 else None

    sharpe: float | None = None
    for comp in payload.get("strategy_comparison", []):
        if isinstance(comp, dict):
            value = _num(comp, "sharpe")
            if value is not None:
                sharpe = round(value, 4)
                break
    if sharpe is None:
        raw = _num(block, "sharpe", "sharpe_ratio")
        if raw is not None:
            sharpe = round(raw, 4)

    max_dd = _num(block, "max_drawdown", "max_drawdown_abs", "max_drawdown_account")
    if max_dd is not None and abs(max_dd) < 2:
        max_dd = round(max_dd * 100, 4)
    elif max_dd is not None:
        max_dd = round(max_dd, 4)

    trades_by_pair: dict[str, dict[str, Any]] = {}
    for trade in trades:
        pair = trade.get("pair", "UNKNOWN")
        if pair not in trades_by_pair:
            trades_by_pair[pair] = {
                "total_trades": 0,
                "net_profit": 0.0,
                "wins": 0,
                "trades": [],
            }
        trades_by_pair[pair]["total_trades"] += 1
        profit_abs = _num(trade, "profit_abs") or 0.0
        trades_by_pair[pair]["net_profit"] += profit_abs
        if profit_abs > 0:
            trades_by_pair[pair]["wins"] += 1
        trades_by_pair[pair]["trades"].append(trade)

    if not trades_by_pair:
        for pair_result in block.get("results_per_pair", []) or []:
            if not isinstance(pair_result, dict):
                continue
            pair = pair_result.get("key") or pair_result.get("pair")
            if not pair or pair == "TOTAL":
                continue
            pair_trades = _int(pair_result, "trades", "total_trades") or 0
            pair_profit = _num(pair_result, "profit_total_abs", "profit_abs", "net_profit") or 0.0
            pair_winrate = _num(pair_result, "winrate", "win_rate")
            if pair_winrate is not None and abs(pair_winrate) <= 1:
                pair_winrate *= 100
            trades_by_pair[str(pair)] = {
                "total_trades": pair_trades,
                "net_profit": pair_profit,
                "wins": _int(pair_result, "wins") or 0,
                "win_rate": round(pair_winrate, 2) if pair_winrate is not None else 0.0,
                "trades": [],
            }

    for pair_data in trades_by_pair.values():
        if pair_data.get("win_rate") is not None:
            continue
        if pair_data["total_trades"] > 0:
            pair_data["win_rate"] = round(
                pair_data["wins"] / pair_data["total_trades"] * 100,
                2,
            )
        else:
            pair_data["win_rate"] = 0.0

    return {
        "total_profit_pct": profit_pct,
        "win_rate": win_rate,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "total_trades": total_trades,
        "trades": trades,
        "trades_by_pair": trades_by_pair,
    }


def group_key(chunk: list[str]) -> str:
    return " + ".join(chunk)


def safe_config_filename(session_id: str, group_key: str) -> str:
    raw = f"pe_{session_id}_{group_key}"
    safe = "".join(
        ch if ch.isalnum() or ch in {"-", "_", "."} else "_"
        for ch in raw
    )
    while "__" in safe:
        safe = safe.replace("__", "_")
    return f"{safe.strip('._') or 'pair_explorer_config'}.json"


def session_results_list(session: dict[str, Any]) -> list[dict[str, Any]]:
    results = session.get("results", {})
    if isinstance(results, dict):
        return list(results.values())
    if isinstance(results, list):
        return results
    return []


def coerce_results_dict(session: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results = session.get("results", {})
    if isinstance(results, dict):
        return results
    if isinstance(results, list):
        coerced = {
            str(row.get("group") or row.get("pair") or index): row
            for index, row in enumerate(results)
            if isinstance(row, dict)
        }
        session["results"] = coerced
        return coerced
    session["results"] = {}
    return session["results"]


def record_group_result(
    session: dict[str, Any],
    user_data_dir: str,
    group_key: str,
    result: dict[str, Any],
    *,
    complete: bool = False,
) -> None:
    results = coerce_results_dict(session)
    previous = results.get(group_key, {})
    was_terminal = previous.get("status") in TERMINAL_GROUP_STATUSES
    results[group_key] = result
    if complete and not was_terminal:
        session["completed"] = min(session.get("total", 0), session.get("completed", 0) + 1)
    save_session(session, user_data_dir)


def fail_unfinished_group(
    session: dict[str, Any],
    user_data_dir: str,
    chunk: list[str],
    error: str,
) -> None:
    key = group_key(chunk)
    current = coerce_results_dict(session).get(key)
    if current and current.get("status") in TERMINAL_GROUP_STATUSES:
        return
    record_group_result(
        session,
        user_data_dir,
        key,
        {
            "group": key,
            "pairs": chunk,
            "status": "failed",
            "error": error,
        },
        complete=True,
    )


def reconcile_terminal_session(session: dict[str, Any], user_data_dir: str) -> None:
    """Make stale persisted terminal sessions renderable if a task ended mid-row."""
    if session.get("status") not in {"completed", "failed"}:
        return
    changed = False
    results = coerce_results_dict(session)
    for key, row in list(results.items()):
        if not isinstance(row, dict) or row.get("status") in TERMINAL_GROUP_STATUSES:
            continue
        pairs = row.get("pairs") or key.split(" + ")
        results[key] = {
            **row,
            "group": row.get("group") or key,
            "pairs": pairs,
            "status": "failed",
            "error": row.get("error") or "Pair group ended without a terminal result.",
        }
        changed = True
    terminal_count = sum(
        1
        for row in results.values()
        if isinstance(row, dict) and row.get("status") in TERMINAL_GROUP_STATUSES
    )
    if terminal_count != session.get("completed"):
        session["completed"] = terminal_count
        changed = True
    if changed:
        save_session(session, user_data_dir)
