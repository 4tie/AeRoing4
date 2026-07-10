"""Individual pair sweep logic for testing one strategy against each pair individually."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ....core.errors import BackendError
from ....models import RunRequest, RunStatus
from ....utils import utc_now
from ....settings_store import SettingsStore
from ..backtest_runner import BacktestRunner
from ...storage.run_repository import RunRepository
from ...strategy.strategy_registry import StrategyRegistry
from ...strategy.version_manager import VersionManager


async def run_individual_pair_sweep(
    backtest_runner: BacktestRunner,
    run_repository: RunRepository,
    registry: StrategyRegistry,
    version_manager: VersionManager,
    settings_store: SettingsStore,
    pairs: list[str],
    strategy_name: str,
    config_file: str,
    timerange: str,
    timeframe: str,
    fee_rate: float = 0.001,
    dry_run_wallet: float = 1000.0,
) -> list[dict]:
    """Test one strategy against each pair individually with max_open_trades=1.

    Runs a separate backtest for each pair with max_open_trades=1,
    collects per-pair metrics, scores, and returns results sorted descending.

    Returns a list of dicts, each with:
        pair, status, rejection_reason, score,
        total_trades, profit_factor, win_rate, max_drawdown, expectancy, profit_total
    """
    pool = list(dict.fromkeys(pairs))
    if not pool:
        return []

    strategy = registry.get_strategy(strategy_name)
    pointer = version_manager.get_current_pointer(strategy_name)
    if pointer is None:
        raise BackendError(
            f"Strategy '{strategy_name}' has no accepted version.",
            status_code=400,
        )
    version_id = pointer.accepted_version_id

    effective_config = config_file
    if not effective_config:
        settings = settings_store.load()
        effective_config = settings.default_config_file_path

    results: list[dict] = []

    for pair in pool:
        entry: dict = {
            "pair": pair,
            "status": "failed",
            "rejection_reason": None,
            "score": 0.0,
            "total_trades": None,
            "profit_factor": None,
            "win_rate": None,
            "max_drawdown": None,
            "expectancy": None,
            "profit_total": None,
        }

        run_request = RunRequest(
            strategy_name=strategy_name,
            version_id=version_id,
            config_file=effective_config,
            timerange=timerange,
            timeframe=timeframe,
            pairs=[pair],
            fee_rate=fee_rate,
            max_open_trades=1,
            dry_run_wallet=dry_run_wallet,
        )

        try:
            run_id = await backtest_runner.queue_strategy_backtest(
                strategy, version_id, run_request
            )
        except Exception as exc:
            entry["status"] = "backtest_failed"
            entry["rejection_reason"] = str(exc)
            results.append(entry)
            continue

        # Poll until terminal
        terminal_status: str | None = None
        poll_start = utc_now()
        while True:
            await asyncio.sleep(1.0)
            try:
                metadata = run_repository.load_metadata(run_id)
            except Exception:
                if (utc_now() - poll_start).total_seconds() > 30:
                    terminal_status = "failed"
                    entry["rejection_reason"] = "Could not load metadata within 30s"
                else:
                    continue
                break

            if metadata.run_status == RunStatus.COMPLETED:
                terminal_status = "completed"
                break
            if metadata.run_status in (RunStatus.FAILED, RunStatus.CANCELLED):
                terminal_status = str(metadata.run_status)
                break

            if (utc_now() - poll_start).total_seconds() > 60:
                terminal_status = "failed"
                entry["rejection_reason"] = "Backtest timed out after 60s"
                break

        if terminal_status != "completed":
            entry["status"] = "backtest_failed"
            entry["rejection_reason"] = (
                entry.get("rejection_reason") or f"Backtest {terminal_status}"
            )
            results.append(entry)
            continue

        # Extract metrics from completed backtest
        try:
            detail = run_repository.load_detail(run_id)
        except Exception:
            entry["status"] = "data_quality_failed"
            entry["rejection_reason"] = "Could not load backtest detail"
            results.append(entry)
            continue

        summary = detail.parsed_summary
        if summary is None:
            entry["status"] = "data_quality_failed"
            entry["rejection_reason"] = "No parsed summary — data may be missing"
            results.append(entry)
            continue

        total_trades = summary.total_trades or 0
        profit_factor = summary.profit_factor
        win_rate = summary.win_rate_pct
        max_drawdown = summary.max_drawdown_pct
        expectancy = summary.expectancy
        profit_total = summary.net_profit_pct

        entry["total_trades"] = total_trades
        entry["profit_factor"] = profit_factor
        entry["win_rate"] = win_rate
        entry["max_drawdown"] = max_drawdown
        entry["expectancy"] = expectancy
        entry["profit_total"] = profit_total

        if total_trades == 0:
            entry["status"] = "data_quality_failed"
            entry["rejection_reason"] = "No trades generated for this pair"
            results.append(entry)
            continue

        if profit_factor is None:
            entry["status"] = "data_quality_failed"
            entry["rejection_reason"] = "Profit factor is missing"
            results.append(entry)
            continue

        if profit_factor < 1.0:
            entry["status"] = "failed"
            entry["rejection_reason"] = f"Profit factor {profit_factor:.2f} below 1.0"
            results.append(entry)
            continue

        # Score: profit_factor * win_rate / max(0.01, max_drawdown)
        # win_rate and max_drawdown are already in percentage points (e.g. 50.0, 25.0)
        safe_dd = max(0.01, max_drawdown or 0.01)
        pf = profit_factor or 0.0
        wr = win_rate or 0.0
        score = pf * wr / safe_dd

        entry["status"] = "passed"
        entry["score"] = round(score, 6)
        results.append(entry)

    results.sort(key=lambda r: r["score"], reverse=True)
    return results
