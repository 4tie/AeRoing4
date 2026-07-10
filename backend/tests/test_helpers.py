"""backend/tests/test_helpers.py — Shared test helpers for Auto-Quant tests.

This file contains common test utilities used across all test files to avoid
duplication and provide a consistent testing environment.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import backend.services.auto_quant.pipeline as pl
from backend.services.auto_quant.pipeline import (
    PipelineState,
    STAGE_NAMES,
    StageState,
    _cancel_flags,
    _queues,
    _states,
)

from backend.services.auto_quant.pipeline_modules.helpers import _extract_per_pair_results


def _run(coro):
    """Execute an async coroutine synchronously in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_state(tmp_dir: str, **overrides) -> PipelineState:
    """Create and register a minimal PipelineState."""
    run_id = str(uuid.uuid4())
    stages = [StageState(index=i + 1, name=STAGE_NAMES[i]) for i in range(len(STAGE_NAMES))]
    
    # Create strategies directory and strategy file
    strategies_dir = Path(tmp_dir) / "strategies"
    strategies_dir.mkdir(parents=True, exist_ok=True)
    strategy_name = overrides.get("strategy", "AuditStrategy")
    strategy_file = strategies_dir / f"{strategy_name}.py"
    strategy_file.write_text("# fake strategy", encoding="utf-8")
    
    state = PipelineState(
        run_id=run_id,
        strategy=strategy_name,
        timeframe="1h",
        in_sample_range="20230101-20230601",
        out_sample_range="20230601-20231201",
        exchange="binance",
        config_file="/fake/config.json",
        freqtrade_path="freqtrade",
        user_data_dir=tmp_dir,
        stages=stages,
        created_at="2024-01-01T00:00:00+00:00",
    )
    for k, v in overrides.items():
        setattr(state, k, v)
    _states[run_id] = state
    _queues[run_id] = []
    _cancel_flags[run_id] = False
    return state


def _backtest_result(
    strategy: str,
    *,
    profit: float = 0.05,
    max_dd: float = 0.10,
    trades: int = 40,
    wins: int = 22,
    losses: int = 18,
    profit_factor: float = 1.4,
    sharpe: float = 1.2,
) -> dict:
    """Return a minimal Freqtrade-style backtest result dict."""
    return {
        "strategy": {
            strategy: {
                "profit_total": profit,
                "profit_total_abs": profit * 1000,
                "profit_mean": profit / max(trades, 1),
                "max_drawdown_account": max_dd,
                "total_trades": trades,
                "wins": wins,
                "losses": losses,
                "draws": 0,
                "win_rate": wins / max(trades, 1),
                "profit_factor": profit_factor,
                "sharpe_ratio": sharpe,
                "calmar_ratio": 1.1,
                "sortino_ratio": 1.2,
                "stake_currency": "USDT",
                "results_per_pair": [
                    {
                        "key": pair,
                        "profit_total": 0.03,
                        "profit_total_abs": 30.0,
                        "profit_mean": 0.002,
                        "trades": 2,
                        "wins": 1,
                        "losses": 1,
                        "profit_factor": 1.2,
                    }
                    for pair in pl.DEFAULT_STRESS_PAIRS
                ],
                "trades": [
                    {"close_date": f"2023-07-{(i % 28) + 1:02d}", "profit_ratio": 0.01 - (i % 5) * 0.005}
                    for i in range(trades)
                ],
            }
        }
    }


def _hyperopt_best(stoploss: float = -0.08) -> dict:
    return {
        "loss": -0.42,
        "params_dict": {
            "stoploss": stoploss,
            "trailing_stop": True,
            "trailing_stop_positive": 0.02,
            "trailing_stop_positive_offset": 0.03,
            "trailing_only_offset_is_reached": False,
            "minimal_roi": {"0": 0.10, "30": 0.05, "60": 0.02},
            "entry_logic": "macd_cross",
        },
        "params_details": {},
    }


def _write_strategy(strategies_dir: Path, name: str) -> Path:
    """Write a minimal strategy file that Stage 3 can patch."""
    src = strategies_dir / f"{name}.py"
    src.write_text(
        f"""
from freqtrade.strategy import IStrategy
from pandas import DataFrame


class {name}(IStrategy):
    INTERFACE_VERSION = 3
    minimal_roi = {{"0": 0.10, "60": 0.02}}
    stoploss = -0.10
    trailing_stop = False
    timeframe = "5m"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe
""",
        encoding="utf-8",
    )
    return src
