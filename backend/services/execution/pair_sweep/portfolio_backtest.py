"""Portfolio backtest logic for running joint portfolio backtests on multiple pairs."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ....models.runs import RunMetadata
from ....models.base import RunType, RunStatus
from ....utils import utc_now
from ...storage.result_parser import ResultParser
from ..backtest_gate import _apply_gate_rules


def run_portfolio_backtest(
    *,
    strategy_path: str,
    strategy_name: str,
    config_file: str,
    timerange: str,
    timeframe: str,
    pairs: list[str],
    max_open_trades: int = 5,
    dry_run_wallet: float = 1000.0,
    user_data_dir: str,
    exchange: str = "binance",
    freqtrade_executable_path: str = "freqtrade",
) -> dict:
    """Run a single joint portfolio backtest on all provided pairs with capital constraints.

    Parameters
    ----------
    pairs : list[str]
        Top-N ranked pairs to test together (must not be empty).
    strategy_path : str
        Path to the strategy .py file on disk.
    strategy_name : str
        Strategy class name (for --strategy flag).
    config_file : str
        Path to Freqtrade config JSON.
    timerange : str
        Backtest timerange (e.g. ``"20240101-20240131"``).
    timeframe : str
        Candle timeframe (e.g. ``"5m"``).
    max_open_trades : int
        Capital constraint — max simultaneous open trades.
    dry_run_wallet : float
        Starting wallet balance.
    user_data_dir : str
        Resolved user_data directory path.
    exchange : str
        Exchange name (default "binance").
    freqtrade_executable_path : str
        Path to the freqtrade binary.

    Returns
    -------
    dict
        ``{
            "status": "passed" | "failed" | "backtest_failed",
            "failure_reasons": list[str],
            "run_id": str | None,
            "portfolio_summary": dict,
            "per_pair_metrics": list[dict],
            "config_used": dict,
        }``
    """
    if not pairs:
        raise ValueError("pairs must not be empty")
    if max_open_trades < 1:
        raise ValueError("max_open_trades must be >= 1")

    strategy_file = Path(strategy_path)
    if not strategy_file.exists():
        return {
            "status": "backtest_failed",
            "failure_reasons": [f"Strategy file not found: {strategy_path}"],
            "run_id": None,
            "portfolio_summary": {},
            "per_pair_metrics": [],
            "config_used": {
                "pairs_count": len(pairs),
                "max_open_trades": max_open_trades,
                "timerange": timerange,
                "timeframe": timeframe,
            },
        }

    strategy_source = strategy_file.read_text(encoding="utf-8")
    now = utc_now()
    run_id = f"portfolio_{now.strftime('%Y%m%d_%H%M%S')}_{strategy_name}"
    run_dir = Path(user_data_dir) / "portfolio_backtest" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "strategy_snapshot.py").write_text(strategy_source, encoding="utf-8")

    unique_pairs = list(dict.fromkeys(pairs))
    # Handle "py -m freqtrade" command by splitting it
    if freqtrade_executable_path == "py -m freqtrade":
        command = [
            "py", "-m", "freqtrade", "backtesting",
            "--user-data-dir", user_data_dir,
            "--config", config_file,
            "--strategy-path", str(run_dir),
            "--strategy", strategy_name,
            "--timerange", timerange,
            "--timeframe", timeframe,
            "--dry-run-wallet", str(dry_run_wallet),
            "--max-open-trades", str(max_open_trades),
            "--export", "trades",
            "--export-filename", str(run_dir / "raw_result.json"),
            "--pairs", *unique_pairs,
        ]
    else:
        command = [
            freqtrade_executable_path, "backtesting",
            "--user-data-dir", user_data_dir,
            "--config", config_file,
            "--strategy-path", str(run_dir),
            "--strategy", strategy_name,
            "--timerange", timerange,
            "--timeframe", timeframe,
            "--dry-run-wallet", str(dry_run_wallet),
            "--max-open-trades", str(max_open_trades),
            "--export", "trades",
            "--export-filename", str(run_dir / "raw_result.json"),
            "--pairs", *unique_pairs,
        ]

    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        return_code = process.returncode
        if stdout:
            (run_dir / "stdout.log").write_text(stdout.decode(errors="replace"), encoding="utf-8")
        if stderr:
            (run_dir / "stderr.log").write_text(stderr.decode(errors="replace"), encoding="utf-8")
    except Exception as exc:
        return {
            "status": "backtest_failed",
            "failure_reasons": [f"Subprocess execution failed: {exc}"],
            "run_id": None,
            "portfolio_summary": {},
            "per_pair_metrics": [],
            "config_used": {
                "pairs_count": len(pairs),
                "max_open_trades": max_open_trades,
                "timerange": timerange,
                "timeframe": timeframe,
            },
        }

    if return_code != 0:
        return {
            "status": "backtest_failed",
            "failure_reasons": [f"Freqtrade exited with code {return_code}"],
            "run_id": None,
            "portfolio_summary": {},
            "per_pair_metrics": [],
            "config_used": {
                "pairs_count": len(pairs),
                "max_open_trades": max_open_trades,
                "timerange": timerange,
                "timeframe": timeframe,
            },
        }

    raw_result_path = run_dir / "raw_result.json"
    if not raw_result_path.exists():
        return {
            "status": "backtest_failed",
            "failure_reasons": ["raw_result.json not produced by Freqtrade"],
            "run_id": None,
            "portfolio_summary": {},
            "per_pair_metrics": [],
            "config_used": {
                "pairs_count": len(pairs),
                "max_open_trades": max_open_trades,
                "timerange": timerange,
                "timeframe": timeframe,
            },
        }

    metadata = RunMetadata(
        run_id=run_id,
        strategy_name=strategy_name,
        strategy_version_id="portfolio",
        parent_version_id=None,
        baseline_run_id=None,
        run_type=RunType.BASELINE,
        run_status=RunStatus.COMPLETED,
        created_at=now,
        completed_at=utc_now(),
        freqtrade_exit_code=return_code,
        config_file=config_file,
        timerange=timerange,
        timeframe=timeframe,
        pairs=unique_pairs,
        max_open_trades=max_open_trades,
        dry_run_wallet=dry_run_wallet,
    )

    parser = ResultParser()
    try:
        summary, pair_results = parser.parse_run_artifacts(run_dir, metadata)
    except Exception as exc:
        return {
            "status": "backtest_failed",
            "failure_reasons": [f"Failed to parse backtest results: {exc}"],
            "run_id": run_id,
            "portfolio_summary": {},
            "per_pair_metrics": [],
            "config_used": {
                "pairs_count": len(pairs),
                "max_open_trades": max_open_trades,
                "timerange": timerange,
                "timeframe": timeframe,
            },
        }

    portfolio_summary = {
        "total_trades": summary.total_trades,
        "profit_factor": summary.profit_factor,
        "win_rate_pct": summary.win_rate_pct,
        "max_drawdown_pct": summary.max_drawdown_pct,
        "sharpe_ratio": summary.sharpe_ratio,
        "expectancy": summary.expectancy,
        "profit_total_pct": summary.net_profit_pct,
        "profit_total_abs": summary.net_profit_currency,
    }

    per_pair_metrics = [
        {
            "pair": pr.pair,
            "trades": pr.total_trades,
            "profit_factor": pr.net_profit_pct,
            "win_rate_pct": pr.win_rate_pct,
        }
        for pr in pair_results
    ]

    metrics_for_rules = {
        "total_trades": summary.total_trades,
        "profit_factor": summary.profit_factor,
        "win_rate_pct": summary.win_rate_pct,
        "max_drawdown_pct": summary.max_drawdown_pct,
        "sharpe_ratio": summary.sharpe_ratio,
        "expectancy": summary.expectancy,
    }
    failure_reasons = _apply_gate_rules(metrics_for_rules)
    status = "passed" if not failure_reasons else "failed"

    return {
        "status": status,
        "failure_reasons": failure_reasons,
        "run_id": run_id,
        "portfolio_summary": portfolio_summary,
        "per_pair_metrics": per_pair_metrics,
        "config_used": {
            "pairs_count": len(pairs),
            "max_open_trades": max_open_trades,
            "timerange": timerange,
            "timeframe": timeframe,
        },
    }
