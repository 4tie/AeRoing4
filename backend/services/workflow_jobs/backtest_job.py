"""Reusable backtest job start function.

Extracted from backend/api/routers/backtest.py to provide a single
source of truth for backtest execution that both normal API routes
and the AI tool executor can use.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ...core.errors import BackendError
from ...models import RunRequest, RunStatus
from ...services.backtest.backtest_service import extract_freqtrade_error, preflight_strategy

if TYPE_CHECKING:
    from ...api.session_store import SessionStore


async def start_backtest_job(
    services,
    store: SessionStore,
    strategy_name: str,
    version_id: str | None = None,
    timerange: str = "",
    timeframe: str | None = None,
    pairs: list[str] | None = None,
    max_open_trades: int = 1,
    dry_run_wallet: float = 1000.0,
    config_file: str | None = None,
) -> tuple[str, str]:
    """Start a backtest job and return (session_id, status).
    
    This function encapsulates the reusable backtest start logic from
    the backtest router so both the normal API and AI tool executor
    use the same workflow.
    
    Args:
        services: App services container
        store: SessionStore for job tracking
        strategy_name: Name of the strategy
        version_id: Optional version ID (uses current if None)
        timeframe: Candle timeframe
        timerange: Date range
        pairs: List of trading pairs
        max_open_trades: Maximum open trades
        fee_rate: Trading fee rate
        config_file: Optional config file override
        dry_run_wallet: Dry run wallet amount
    
    Returns:
        (session_id, initial_status)
    
    Raises:
        BackendError: If backtest runner is busy or strategy not found
        ValueError: If preflight validation fails
    """
    # Check if backtest runner is busy
    if services.backtest_runner.is_busy():
        raise BackendError(
            "Backtest runner is busy. Wait for the current run to finish.",
            status_code=409,
        )

    # Get strategy
    try:
        strategy = services.registry.get_strategy(strategy_name)
    except BackendError as exc:
        raise BackendError(f"Strategy not found: {strategy_name}", status_code=404) from exc

    # Resolve version
    pointer = services.version_manager.get_current_pointer(strategy_name)
    if pointer is None and version_id is None:
        try:
            await asyncio.to_thread(
                services.version_manager.ensure_registered, strategy
            )
            pointer = services.version_manager.get_current_pointer(strategy_name)
        except Exception as exc:
            raise BackendError(
                f"Could not auto-register strategy '{strategy_name}': {exc}",
                status_code=409,
            ) from exc

    resolved_version_id: str = version_id or (pointer.accepted_version_id if pointer else "")

    # Pre-flight validation
    settings = services.settings_store.load()
    preflight_errors = await asyncio.to_thread(
        preflight_strategy,
        settings.strategies_directory_path,
        strategy_name,
    )
    if preflight_errors:
        raise ValueError(
            f"Strategy pre-flight validation failed: {preflight_errors}"
        )

    # Handle optional pairs - if None, will use strategy default
    resolved_pairs = pairs if pairs is not None else []

    # Create session
    record = store.create("backtest")
    
    # Start background task
    asyncio.create_task(
        _run_backtest_task(
            services,
            store,
            record.session_id,
            strategy,
            resolved_version_id,
            strategy_name,
            timeframe,
            timerange,
            resolved_pairs,
            max_open_trades,
            config_file or settings.default_config_file_path,
            dry_run_wallet,
        )
    )
    
    return record.session_id, "queued"


async def _run_backtest_task(
    services,
    store: SessionStore,
    session_id: str,
    strategy,
    version_id: str,
    strategy_name: str,
    timeframe: str | None,
    timerange: str,
    pairs: list[str],
    max_open_trades: int,
    config_file: str,
    dry_run_wallet: float,
) -> None:
    """Background task that executes the backtest and updates the session store."""
    store.update(session_id, status="running", started_at=datetime.now(tz=UTC))
    
    try:
        run_request = RunRequest(
            strategy_name=strategy_name,
            version_id=version_id,
            config_file=config_file,
            timerange=timerange,
            timeframe=timeframe,
            pairs=pairs,
            max_open_trades=max_open_trades,
            dry_run_wallet=dry_run_wallet,
        )

        def _phase_callback(phase: str, result_data: dict | None = None) -> None:
            if result_data:
                existing = store.get(session_id)
                merged = {**(existing.result or {}), **result_data}
                store.update(session_id, status=phase, result=merged)
            else:
                store.update(session_id, status=phase)

        run_id: str = await asyncio.to_thread(
            services.backtest_runner.run_backtest, strategy, version_id, run_request, _phase_callback
        )

        metadata = services.run_repository.load_metadata(run_id)
        run_result = {
            "run_id": run_id,
            "strategy_name": strategy_name,
            "version_id": version_id,
            "timerange": timerange,
            **(store.get(session_id).result or {}),
        }

        if metadata.run_status == RunStatus.FAILED:
            exit_code = metadata.freqtrade_exit_code
            code_hint = f" (exit code {exit_code})" if exit_code is not None else ""
            run_dir = services.run_repository.find_run_dir(run_id)
            ft_error = extract_freqtrade_error(run_dir)
            if ft_error:
                error_msg = f"Backtest failed{code_hint}: {ft_error}"
            else:
                error_msg = (
                    f"Backtest failed{code_hint}. "
                    "Check the run logs for details — common causes are missing "
                    "candle data for the requested timerange, a strategy error, "
                    "or an invalid configuration."
                )
            store.update(
                session_id,
                status="failed",
                completed_at=datetime.now(tz=UTC),
                error=error_msg,
                result=run_result,
            )
        elif metadata.run_status == RunStatus.CANCELLED:
            store.update(
                session_id,
                status="failed",
                completed_at=datetime.now(tz=UTC),
                error="Backtest was cancelled.",
                result=run_result,
            )
        else:
            store.update(
                session_id,
                status="completed",
                completed_at=datetime.now(tz=UTC),
                result=run_result,
            )
    except BackendError as exc:
        store.update(
            session_id,
            status="failed",
            completed_at=datetime.now(tz=UTC),
            error=exc.message,
        )
    except Exception as exc:
        store.update(
            session_id,
            status="failed",
            completed_at=datetime.now(tz=UTC),
            error=str(exc),
        )
