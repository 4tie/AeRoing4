"""Router: POST /api/stress-lab/run

Launches a pair-sweep stress-testing session: N backtests are run with
different randomly-sampled subsets of pairs from the active pair-selector
pool to stress-test strategy robustness across changing pair combinations.

The PairSweepRunner already manages its own internal asyncio.Task so this
endpoint forwards the request, captures the sweep_session_id, and monitors
progress via a background coroutine that writes back to the API session store.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from ...core.errors import BackendError
from ...models import StartPairSweepRequest
from ..dependencies import get_services, get_session_store
from ..models import AsyncJobResponse, StressLabApiRequest
from ..session_store import SessionStore

router = APIRouter(prefix="/api/stress-lab", tags=["Stress Lab"])

_TERMINAL_PHASES = {"completed", "failed", "cancelled"}


@router.post(
    "/run",
    response_model=AsyncJobResponse,
    status_code=202,
    summary="Run a pair-sweep stress test",
    description=(
        "Starts a robustness stress test by running the strategy against "
        "iteration_count different randomly-sampled pair subsets. "
        "Returns a session_id immediately; poll /api/session/status/{session_id} "
        "for per-iteration results and aggregate metrics."
    ),
)
async def run_stress_lab(
    body: StressLabApiRequest,
    services=Depends(get_services),
    store: SessionStore = Depends(get_session_store),
) -> AsyncJobResponse:

    if services.pair_sweep_runner.is_running():
        raise HTTPException(
            status_code=409,
            detail="A stress-lab (pair sweep) session is already running.",
        )

    if services.backtest_runner.is_busy():
        raise HTTPException(
            status_code=409,
            detail="Backtest runner is busy. Wait for the current run to finish.",
        )

    try:
        services.registry.get_strategy(body.strategy_name)
    except BackendError as exc:
        raise HTTPException(status_code=404, detail=exc.message)

    pointer = services.version_manager.get_current_pointer(body.strategy_name)
    if pointer is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Strategy '{body.strategy_name}' has no accepted version. "
                "Accept a version before running the stress lab."
            ),
        )

    api_record = store.create("stress_lab")

    try:
        settings = services.settings_store.load()
        config_file = body.config_file or settings.default_config_file_path

        internal_request = StartPairSweepRequest(
            strategy_name=body.strategy_name,
            config_file=config_file,
            timerange=body.timerange,
            timeframe=body.timeframe,
            fee_rate=body.fee_rate,
            max_open_trades=body.max_open_trades,
            dry_run_wallet=body.dry_run_wallet,
            iteration_count=body.iteration_count,
            download_data_first=body.download_data_first,
        )

        sweep_session = await services.pair_sweep_runner.start_session(internal_request)

    except BackendError as exc:
        store.update(
            api_record.session_id,
            status="failed",
            completed_at=datetime.now(tz=UTC),
            error=exc.message,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:
        store.update(
            api_record.session_id,
            status="failed",
            completed_at=datetime.now(tz=UTC),
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc))

    store.update(
        api_record.session_id,
        status="running",
        started_at=datetime.now(tz=UTC),
        result={"sweep_session_id": sweep_session.session_id},
    )

    asyncio.create_task(
        _monitor_sweep(
            services, store, api_record.session_id, sweep_session.session_id
        )
    )

    return AsyncJobResponse(
        session_id=api_record.session_id,
        status="running",
        message=(
            f"Stress lab started — {body.iteration_count} iterations for '{body.strategy_name}'. "
            f"Internal sweep_session_id={sweep_session.session_id}. "
            f"Poll /api/session/status/{api_record.session_id} for progress."
        ),
    )


async def _monitor_sweep(
    services,
    store: SessionStore,
    api_session_id: str,
    sweep_session_id: str,
) -> None:
    """Poll the internal sweep store until the session reaches a terminal phase."""
    while True:
        await asyncio.sleep(4.0)
        try:
            session = services.sweep_store.load_session(sweep_session_id)
        except Exception:
            session = None

        if session is None:
            store.update(
                api_session_id,
                status="failed",
                completed_at=datetime.now(tz=UTC),
                error="Sweep session record could not be read from store.",
            )
            return

        if session.phase in _TERMINAL_PHASES:
            final_status = "completed" if session.phase == "completed" else "failed"

            completed = session.completed_iterations
            all_profits = [
                it.metrics.net_profit_pct
                for it in session.iterations
                if it.metrics and it.metrics.net_profit_pct is not None
            ]
            avg_profit: float | None = (
                round(sum(all_profits) / len(all_profits), 4) if all_profits else None
            )
            best_profit: float | None = max(all_profits) if all_profits else None

            store.update(
                api_session_id,
                status=final_status,
                completed_at=datetime.now(tz=UTC),
                result={
                    "sweep_session_id": sweep_session_id,
                    "phase": session.phase,
                    "total_iterations": session.total_iterations,
                    "completed_iterations": completed,
                    "failed_iterations": session.failed_iterations,
                    "avg_net_profit_pct": avg_profit,
                    "best_net_profit_pct": best_profit,
                    "stop_reason": session.stop_reason,
                },
            )
            return
