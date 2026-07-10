"""Data loading and extraction helpers for assessment stages."""

from __future__ import annotations

import json
from pathlib import Path

from ..logging import logger
from ...profit_lockin import extract_strategy_trades


def _load_stage4_result(out_dir: Path) -> dict:
    stage4_path = out_dir / "stage4_result.json"
    if not stage4_path.exists():
        # Try glob for timestamped variant
        candidates = sorted(out_dir.glob("stage4_result*.json"),
                            key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            return {}
        stage4_path = candidates[0]

    try:
        return json.loads(stage4_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Stage Assessment | failed to read stage4 result %s: %s", stage4_path, exc)
        return {}


def _extract_oos_trades(out_dir: Path, strategy_name: str) -> list[dict]:
    """Load exported Stage 4 OOS trades for a strategy."""
    return extract_strategy_trades(_load_stage4_result(out_dir), strategy_name)


def _extract_oos_profit_ratios(out_dir: Path, strategy_name: str) -> list[float]:
    """Load per-trade profit ratios from the Stage 4 OOS backtest result on disk.

    Freqtrade's backtest JSON stores a ``trades`` list under
    ``strategy -> <name>``.  Each trade has a ``profit_ratio`` field.  We sort
    by ``close_date`` so the series is chronologically ordered before passing
    to the Monte Carlo engine.
    """
    trades = _extract_oos_trades(out_dir, strategy_name)
    if not trades:
        return []

    # Sort chronologically by close_date and extract profit_ratio
    try:
        trades_sorted = sorted(trades, key=lambda t: t.get("close_date", ""))
    except Exception as exc:
        logger.warning("Stage Assessment | failed to sort trades by close_date: %s", exc)
        trades_sorted = trades

    ratios = []
    for t in trades_sorted:
        pr = t.get("profit_ratio", t.get("profit_abs"))
        if pr is not None:
            ratios.append(float(pr))
    return ratios


def _first_float(data: dict, *keys: str) -> float | None:
    for key in keys:
        if key not in data:
            continue
        try:
            return float(data[key])
        except (TypeError, ValueError):
            continue
    return None
