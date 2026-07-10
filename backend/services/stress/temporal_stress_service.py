"""Temporal stress testing service module for business logic extracted from routers."""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# ── Predefined crash periods ───────────────────────────────────────────────────

CRASH_PERIODS = [
    {
        "label": "COVID Crash",
        "start": "20200215",
        "end": "20200331",
        "description": "Global market crash triggered by COVID-19 pandemic",
    },
    {
        "label": "China Mining Ban",
        "start": "20210510",
        "end": "20210731",
        "description": "China bans crypto mining — massive hash-rate exodus + sell-off",
    },
    {
        "label": "Crypto Winter Onset",
        "start": "20220101",
        "end": "20220401",
        "description": "Post-ATH bear market descent following November 2021 peak",
    },
    {
        "label": "Luna / UST Collapse",
        "start": "20220505",
        "end": "20220620",
        "description": "Terra Luna ecosystem collapse wiping ~$60B in days",
    },
    {
        "label": "Summer Liquidity Crisis",
        "start": "20220615",
        "end": "20220831",
        "description": "Celsius, 3AC, Voyager insolvencies cascade through market",
    },
    {
        "label": "FTX Collapse",
        "start": "20221101",
        "end": "20221231",
        "description": "FTX exchange collapse and industry-wide contagion",
    },
]


def parse_date(s: str) -> date:
    """Parse date string in YYYYMMDD format.
    
    Args:
        s: Date string in YYYYMMDD format
        
    Returns:
        Date object
    """
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def fmt_date(d: date) -> str:
    """Format date to YYYYMMDD string.
    
    Args:
        d: Date object
        
    Returns:
        Date string in YYYYMMDD format
    """
    return d.strftime("%Y%m%d")


def split_timerange(timerange: str) -> tuple[date, date]:
    """Split timerange string into start and end dates.
    
    Args:
        timerange: Timerange string in YYYYMMDD-YYYYMMDD format
        
    Returns:
        Tuple of (start_date, end_date)
        
    Raises:
        ValueError: If timerange format is invalid
    """
    parts = timerange.split("-")
    if len(parts) != 2 or len(parts[0]) != 8 or len(parts[1]) != 8:
        raise ValueError(
            f"timerange must be YYYYMMDD-YYYYMMDD, got: '{timerange}'"
        )
    return parse_date(parts[0]), parse_date(parts[1])


def generate_time_split_segments(timerange: str, n_splits: int) -> list[dict]:
    """Generate time split segments for temporal stress testing.
    
    Args:
        timerange: Timerange string in YYYYMMDD-YYYYMMDD format
        n_splits: Number of segments to split into
        
    Returns:
        List of segment dictionaries with label, start, end, timerange, description
    """
    start, end = split_timerange(timerange)
    total_days = (end - start).days
    if total_days < n_splits * 2:
        raise ValueError(
            f"Timerange is only {total_days} days — too short for {n_splits} splits."
        )
    segment_days = total_days // n_splits
    segments: list[dict] = []
    for i in range(n_splits):
        seg_start = start + timedelta(days=i * segment_days)
        seg_end = end if i == n_splits - 1 else seg_start + timedelta(days=segment_days - 1)
        label = f"Segment {i + 1}"
        segments.append(
            {
                "label": label,
                "start": fmt_date(seg_start),
                "end": fmt_date(seg_end),
                "timerange": f"{fmt_date(seg_start)}-{fmt_date(seg_end)}",
                "description": "",
            }
        )
    return segments


def generate_monte_carlo_segments(
    timerange: str, n_windows: int, window_days: int
) -> list[dict]:
    """Generate Monte Carlo random window segments for temporal stress testing.
    
    Args:
        timerange: Timerange string in YYYYMMDD-YYYYMMDD format
        n_windows: Number of random windows to generate
        window_days: Length of each window in days
        
    Returns:
        List of segment dictionaries with label, start, end, timerange, description
    """
    start, end = split_timerange(timerange)
    total_days = (end - start).days
    if total_days < window_days + 1:
        raise ValueError(
            f"Timerange ({total_days} days) is shorter than window length ({window_days} days)."
        )
    max_offset = total_days - window_days
    rng = random.Random(42)
    seen: set[int] = set()
    segments: list[dict] = []
    for i in range(n_windows):
        for _ in range(100):
            offset = rng.randint(0, max_offset)
            if offset not in seen:
                seen.add(offset)
                break
        seg_start = start + timedelta(days=offset)
        seg_end = seg_start + timedelta(days=window_days - 1)
        segments.append(
            {
                "label": f"Random Window {i + 1}",
                "start": fmt_date(seg_start),
                "end": fmt_date(seg_end),
                "timerange": f"{fmt_date(seg_start)}-{fmt_date(seg_end)}",
                "description": f"{window_days}-day random sample",
            }
        )
    return segments


def generate_crash_gauntlet_segments() -> list[dict]:
    """Generate crash gauntlet segments using predefined crash periods.
    
    Returns:
        List of segment dictionaries for historical crash periods
    """
    return [
        {
            "label": cp["label"],
            "start": cp["start"],
            "end": cp["end"],
            "timerange": f"{cp['start']}-{cp['end']}",
            "description": cp["description"],
        }
        for cp in CRASH_PERIODS
    ]


def extract_segment_metrics(run_dir: Path, strategy_name: str) -> dict:
    """Extract key metrics from a backtest run directory.
    
    Args:
        run_dir: Path to the backtest run directory
        strategy_name: Name of the strategy
        
    Returns:
        Dictionary with net_profit_pct, total_trades, win_rate_pct, max_drawdown_pct
    """
    raw_path = run_dir / "raw_result.json"
    if not raw_path.exists():
        return {}
    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    block = (raw.get("strategy") or {}).get(strategy_name) or raw
    if not isinstance(block, dict):
        block = raw

    def _num(*keys: str) -> float | None:
        for k in keys:
            v = block.get(k)
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    pass
        return None

    def _int_val(*keys: str) -> int | None:
        for k in keys:
            v = block.get(k)
            if v is not None:
                try:
                    return int(v)
                except Exception:
                    pass
        return None

    profit_raw = _num("profit_total", "profit_total_long", "profit_factor")
    net_profit_pct: float | None = None
    if profit_raw is not None:
        net_profit_pct = round(profit_raw * 100, 4) if abs(profit_raw) <= 20 else round(profit_raw, 4)

    total_trades = _int_val("total_trades", "trade_count")
    trades_list = block.get("trades") or raw.get("trades") or []
    win_rate_pct: float | None = None
    if trades_list and total_trades and total_trades > 0:
        wins = sum(
            1 for t in trades_list
            if isinstance(t, dict) and float(t.get("profit_ratio", 0) or 0) > 0
        )
        win_rate_pct = round(wins / total_trades * 100, 2)

    max_dd = _num("max_drawdown", "max_drawdown_low", "drawdown_abs")

    return {
        "net_profit_pct": net_profit_pct,
        "total_trades": total_trades,
        "win_rate_pct": win_rate_pct,
        "max_drawdown_pct": max_dd,
    }


def consistency_score(results: list[dict]) -> float:
    """Calculate consistency score from segment results.
    
    Args:
        results: List of segment result dictionaries
        
    Returns:
        Consistency score (percentage of profitable segments)
    """
    finished = [r for r in results if r.get("status") in ("profitable", "loss")]
    if not finished:
        return 0.0
    profitable = sum(1 for r in finished if r["status"] == "profitable")
    return round(profitable / len(finished) * 100, 1)
