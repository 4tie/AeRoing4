"""Reusable stress test job start functions.

Extracted from backend/api/routers to provide a single source of truth
for stress test execution that both normal API routes and the AI tool
executor can use.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ...core.errors import BackendError

if TYPE_CHECKING:
    from ...api.session_store import SessionStore


async def start_pair_stress_job(
    services,
    store: SessionStore,
    strategy_name: str,
    pairs: list[str],
    timeframe: str = "5m",
    timerange: str = "20230101-20240101",
    max_open_trades: int = 1,
    fee_rate: float = 0.001,
    config_file: str | None = None,
    dry_run_wallet: float = 1000.0,
) -> tuple[str, str]:
    """Start a pair stress lab job and return (session_id, status).
    
    This is a placeholder implementation. The actual Pair Stress Lab
    implementation should be extracted from the stress-lab router
    once that workflow is verified.
    
    Args:
        services: App services container
        store: SessionStore for job tracking
        strategy_name: Name of the strategy
        pairs: List of trading pairs
        timeframe: Candle timeframe
        timerange: Date range
        max_open_trades: Maximum open trades
        fee_rate: Trading fee rate
        config_file: Optional config file override
        dry_run_wallet: Dry run wallet amount
    
    Returns:
        (session_id, initial_status)
    
    Raises:
        BackendError: If stress lab is busy or strategy not found
    """
    # Placeholder - implement based on actual stress-lab router
    # For now, raise to indicate this needs implementation
    raise BackendError(
        "Pair Stress Lab job extraction not yet implemented. "
        "Extract from backend/api/routers/stress_lab.py",
        status_code=501,
    )


async def start_temporal_stress_job(
    services,
    store: SessionStore,
    strategy_name: str,
    pairs: list[str],
    timeframe: str = "5m",
    timerange: str = "20230101-20240101",
    tests: list[str] | None = None,
    max_open_trades: int = 1,
    fee_rate: float = 0.001,
    config_file: str | None = None,
    dry_run_wallet: float = 1000.0,
) -> tuple[str, str]:
    """Start a temporal stress test job and return (session_id, status).
    
    This is a placeholder implementation. The actual Temporal Stress Lab
    implementation should be extracted from the temporal-stress-lab router
    once that workflow is verified.
    
    Args:
        services: App services container
        store: SessionStore for job tracking
        strategy_name: Name of the strategy
        pairs: List of trading pairs
        timeframe: Candle timeframe
        timerange: Date range
        tests: List of tests to run (time_split, monte_carlo, crash_gauntlet)
        max_open_trades: Maximum open trades
        fee_rate: Trading fee rate
        config_file: Optional config file override
        dry_run_wallet: Dry run wallet amount
    
    Returns:
        (session_id, initial_status)
    
    Raises:
        BackendError: If stress lab is busy or strategy not found
    """
    # Placeholder - implement based on actual temporal-stress-lab router
    # For now, raise to indicate this needs implementation
    raise BackendError(
        "Temporal Stress Lab job extraction not yet implemented. "
        "Extract from backend/api/routers/temporal_stress_lab.py",
        status_code=501,
    )
