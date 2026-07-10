"""Pair explorer job extraction.

Provides a reusable start function for pair explorer jobs that mimics
the existing Pair Explorer API route's behavior but can be called by
the AI copilot or other internal systems.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from ...api.routers.pair_explorer import _explore_task
from ...services.pairs import pair_explorer_service as pair_explorer_api

logger = logging.getLogger(__name__)


async def start_pair_explorer_job(
    services,
    strategy_name: str,
    pairs: list[str],
    timeframe: str,
    timerange: str,
    dry_run_wallet: float = 1000.0,
    max_open_trades: int = 1,
) -> tuple[str, str]:
    """Start a new Pair Explorer job and return its ID and initial status.

    Args:
        services: App services container
        strategy_name: Strategy to backtest
        pairs: List of pairs to explore
        timeframe: Candle timeframe (e.g., '1h')
        timerange: Backtest time range (e.g., '20230101-20240101')
        dry_run_wallet: Starting wallet balance
        max_open_trades: How many pairs to run together in one backtest group

    Returns:
        tuple[str, str]: (session_id, initial_status)
    """
    settings = services.settings_store.load()

    pairs = [p.strip().upper() for p in pairs if p.strip()]
    if not pairs:
        raise ValueError("At least one pair must be selected.")

    # Get exchange name for data checks
    try:
        import json
        from pathlib import Path
        config_data = json.loads(Path(settings.default_config_file_path).read_text(encoding="utf-8"))
        exchange = config_data.get("exchange", {}).get("name", "binance")
    except Exception:
        exchange = "binance"

    # Chunk pairs into groups
    n = max_open_trades
    chunks = [pairs[i:i + n] for i in range(0, len(pairs), n)]

    session_id = str(uuid.uuid4())
    session_data = {
        "session_id": session_id,
        "status": "running",
        "total": len(chunks),
        "completed": 0,
        "results": {},
        "strategy_name": strategy_name,
        "timeframe": timeframe,
        "timerange": timerange,
        "dry_run_wallet": dry_run_wallet,
        "max_open_trades": max_open_trades,
        "pairs": pairs,
        "created_at": datetime.now(tz=UTC).isoformat(),
        "completed_at": None,
    }
    
    # Save to disk and register in shared memory so the API/observer can see it
    pair_explorer_api.save_session(session_data, settings.user_data_directory_path)
    pair_explorer_api.register_session(session_data)

    logger.info(f"[Pair Explorer Job] Starting background task for session {session_id} with {len(chunks)} chunks")
    
    # Schedule background execution
    asyncio.create_task(
        _explore_task(
            session_id, chunks,
            strategy_name, timeframe, timerange,
            settings.freqtrade_executable_path,
            settings.default_config_file_path,
            settings.strategies_directory_path,
            settings.user_data_directory_path,
            exchange,
            services.data_download_runner,
            dry_run_wallet=dry_run_wallet,
            max_open_trades=max_open_trades,
        )
    )

    return session_id, "running"
