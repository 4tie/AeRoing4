"""Reusable optimizer job start function.

Extracted from backend/api/routers/optimizer.py to provide a single
source of truth for optimizer execution that both normal API routes
and the AI tool executor can use.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ...core.errors import BackendError
from ...core.optimizer_errors import OptimizerError
from ...models import (
    OptimizerParameterMode,
    OptimizerScoreMetric,
    ParameterSearchSpace,
    SearchStrategy,
    StartOptimizerRequest,
)
from ...services.optimizer import api_service as optimizer_api
from ...services.strategy.optimizer_auto_safe import apply_auto_safe_initial_spaces

if TYPE_CHECKING:
    from ...api.session_store import SessionStore


logger = logging.getLogger(__name__)

# Reuse optimizer API helpers
_TERMINAL_PHASES = optimizer_api.TERMINAL_PHASES
_monitor_optimizer = optimizer_api.monitor_optimizer


async def start_optimizer_job(
    services,
    store: SessionStore,
    strategy_name: str,
    timerange: str,
    timeframe: str = "1h",
    pairs: list[str] | None = None,
    search_spaces: list[dict[str, any]] | None = None,
    total_trials: int = 50,
    search_strategy: str = "random",
    parameter_mode: str = "auto_safe",
    score_metric: str = "composite",
    max_open_trades: int = 1,
    dry_run_wallet: float = 1000.0,
    fee_rate: float = 0.001,
    enable_vectorbt_screening: bool = True,
    vectorbt_candidate_count: int = 1000,
    vectorbt_keep_ratio: float = 0.10,
    vectorbt_timeout_seconds: int = 120,
    config_file: str | None = None,
) -> tuple[str, str, str]:
    """Start an optimizer job and return (api_session_id, optimizer_session_id, status).
    
    This function encapsulates the reusable optimizer start logic from
    the optimizer router so both the normal API and AI tool executor
    use the same workflow.
    
    Args:
        services: App services container
        store: SessionStore for job tracking
        strategy_name: Name of the strategy
        timerange: Date range
        timeframe: Candle timeframe
        pairs: List of trading pairs
        search_spaces: Parameter search spaces (list of dicts)
        total_trials: Total optimization trials
        search_strategy: Search strategy (random, grid, etc.)
        parameter_mode: Parameter mode (default, auto_safe)
        score_metric: Score metric (sharpe, profit, etc.)
        max_open_trades: Maximum open trades
        fee_rate: Trading fee rate
        enable_vectorbt_screening: Enable VectorBT screening
        vectorbt_candidate_count: VectorBT candidate count
        vectorbt_keep_ratio: VectorBT keep ratio
        vectorbt_timeout_seconds: VectorBT timeout
        config_file: Optional config file override
        dry_run_wallet: Dry run wallet amount
    
    Returns:
        (api_session_id, optimizer_session_id, initial_status)
    
    Raises:
        BackendError: If optimizer is busy or strategy not found
        ValueError: If validation fails
    """
    # Check if optimizer is running
    if services.strategy_optimizer.is_running():
        raise BackendError(
            "An optimizer session is already running. Cancel it first or wait for it to finish.",
            status_code=409,
        )

    # Get strategy
    try:
        services.registry.get_strategy(strategy_name)
    except BackendError as exc:
        raise BackendError(f"Strategy not found: {strategy_name}", status_code=404) from exc

    # Validate pairs (optional in API, but required for AI tool)
    resolved_pairs = pairs if pairs is not None else []
    if not resolved_pairs:
        raise ValueError("At least one trading pair is required.")

    # Check for accepted version
    pointer = services.version_manager.get_current_pointer(strategy_name)
    if pointer is None:
        raise BackendError(
            f"Strategy '{strategy_name}' has no accepted version. "
            "Accept a version before running the optimizer.",
            status_code=409,
        )

    # Create API session
    api_record = store.create("optimizer")

    try:
        settings = services.settings_store.load()
        resolved_config_file = config_file or settings.default_config_file_path

        # Parse search spaces (optional in API, but required for AI tool)
        resolved_search_spaces = search_spaces if search_spaces is not None else []
        parsed_spaces = []
        invalid_spaces: list[str] = []
        for idx, raw in enumerate(resolved_search_spaces, start=1):
            try:
                parsed_spaces.append(ParameterSearchSpace.model_validate(raw))
            except Exception as exc:
                invalid_spaces.append(f"search_spaces[{idx}]: {exc}")
        if invalid_spaces:
            raise ValueError("Invalid optimizer search spaces. " + " | ".join(invalid_spaces))
        
        # Apply auto-safe if needed
        parameter_mode_enum = OptimizerParameterMode(parameter_mode)
        if parameter_mode_enum == OptimizerParameterMode.AUTO_SAFE:
            parsed_spaces = apply_auto_safe_initial_spaces(parsed_spaces)

        # Build internal request
        internal_request = StartOptimizerRequest(
            strategy_name=strategy_name,
            timerange=timerange,
            timeframe=timeframe,
            pairs=pairs,
            config_file=resolved_config_file,
            total_trials=total_trials,
            search_strategy=SearchStrategy(search_strategy),
            parameter_mode=parameter_mode_enum,
            score_metric=OptimizerScoreMetric(score_metric),
            max_open_trades=max_open_trades,
            dry_run_wallet=dry_run_wallet,
            fee_rate=fee_rate,
            search_spaces=parsed_spaces,
            enable_vectorbt_screening=enable_vectorbt_screening,
            vectorbt_candidate_count=vectorbt_candidate_count,
            vectorbt_keep_ratio=vectorbt_keep_ratio,
            vectorbt_timeout_seconds=vectorbt_timeout_seconds,
        )

        # Start optimizer session
        optimizer_session = await services.strategy_optimizer.start_session(internal_request)

    except BackendError as exc:
        store.update(
            api_record.session_id,
            status="failed",
            completed_at=datetime.now(tz=UTC),
            error=exc.message,
        )
        logger.error("Backend error starting optimizer: %s", exc.message)
        raise
    except OptimizerError as exc:
        store.update(
            api_record.session_id,
            status="failed",
            completed_at=datetime.now(tz=UTC),
            error=exc.message,
        )
        logger.error("Optimizer error starting optimizer: %s", exc.message)
        raise
    except ValueError as exc:
        store.update(
            api_record.session_id,
            status="failed",
            completed_at=datetime.now(tz=UTC),
            error=str(exc),
        )
        logger.error("Validation error starting optimizer: %s", exc)
        raise

    # Update session to running
    store.update(
        api_record.session_id,
        status="running",
        started_at=datetime.now(tz=UTC),
        result={"optimizer_session_id": optimizer_session.session_id},
    )

    # Start monitoring task
    asyncio.create_task(
        _monitor_optimizer(
            services, store, api_record.session_id, optimizer_session.session_id
        )
    )

    return api_record.session_id, optimizer_session.session_id, "running"
