"""Pair screening endpoints for Auto-Quant."""

import asyncio
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from ....services.auto_quant import pipeline as _pl

from .schemas import ScreenPairsRequest


def register_pair_screening_endpoints(router: APIRouter) -> None:
    """Register pair screening endpoints on the given router."""
    
    @router.post(
        "/screen-pairs",
        summary="Run quick sequential backtests to rank a list of pairs",
    )
    async def screen_pairs(body: ScreenPairsRequest, request: Request) -> dict:
        services = request.app.state.services
        settings = services.settings_store.load()

        config_file = body.config_file or settings.default_config_file_path
        if not Path(config_file).exists():
            raise HTTPException(status_code=400, detail=f"Config file not found: {config_file}")

        strategies_dir = Path(settings.strategies_directory_path)
        strategy_path = strategies_dir / f"{body.strategy}.py"
        if not strategy_path.exists():
            raise HTTPException(status_code=404, detail=f"Strategy '{body.strategy}' not found.")

        freqtrade_path = settings.freqtrade_executable_path
        user_data_dir = settings.user_data_directory_path

        results: list[dict] = []
        errors: list[str] = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            for pair in body.pairs:
                pair_clean = pair.replace("/", "_")
                export_file = tmp_path / f"{pair_clean}.json"
                # Handle "py -m freqtrade" command by splitting it
                if freqtrade_path == "py -m freqtrade":
                    cmd = [
                        "py", "-m", "freqtrade", "backtesting",
                        "--config", config_file,
                        "--strategy", body.strategy,
                        "--timerange", body.date_range,
                        "--timeframe", body.timeframe,
                        "--user-data-dir", user_data_dir,
                        "--export", "trades",
                        "--export-filename", str(export_file),
                        "--no-color",
                        "--cache", "none",
                        "--pairs", pair,
                    ]
                else:
                    cmd = [
                        freqtrade_path, "backtesting",
                        "--config", config_file,
                        "--strategy", body.strategy,
                        "--timerange", body.date_range,
                        "--timeframe", body.timeframe,
                        "--user-data-dir", user_data_dir,
                        "--export", "trades",
                        "--export-filename", str(export_file),
                        "--no-color",
                        "--cache", "none",
                        "--pairs", pair,
                    ]
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    try:
                        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
                    except asyncio.TimeoutError:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        errors.append(f"{pair}: timed out after 5 minutes")
                        continue

                    if proc.returncode != 0:
                        stderr_text = stdout.decode("utf-8", errors="replace") if stdout else ""
                        tail = "\n".join(stderr_text.splitlines()[-5:])
                        errors.append(f"{pair}: backtest exited with rc={proc.returncode} — {tail[:200]}")
                        continue

                    data = _pl._find_backtest_result(tmp_path, pair_clean, user_data_dir)
                    if not data:
                        errors.append(f"{pair}: result JSON not found after backtest")
                        continue

                    summary = _pl._extract_backtest_summary(data, body.strategy)
                    trade_count = int(summary.get("total_trades", 0))

                    if trade_count == 0:
                        results.append({
                            "pair": pair,
                            "profit_pct": None,
                            "trade_count": 0,
                            "win_rate": None,
                            "max_dd": None,
                        })
                        continue

                    wins = summary.get("wins", 0)
                    losses = summary.get("losses", 0)
                    draws = summary.get("draws", 0)
                    total = wins + losses + draws
                    win_rate = round(wins / total * 100, 1) if total > 0 else None

                    results.append({
                        "pair": pair,
                        "profit_pct": round(float(summary.get("profit_total", 0.0)) * 100, 2),
                        "trade_count": trade_count,
                        "win_rate": win_rate,
                        "max_dd": round(float(summary.get("max_drawdown_account", 0.0)) * 100, 2),
                    })

                except Exception as exc:
                    errors.append(f"{pair}: {exc}")

        results.sort(key=lambda r: (r["profit_pct"] is None, -(r["profit_pct"] or 0.0)))

        return {
            "results": results,
            "screened": len(body.pairs),
            "errors": errors,
        }
