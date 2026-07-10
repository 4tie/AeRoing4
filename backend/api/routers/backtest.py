"""Router: POST /api/backtest/run

Triggers a synchronous Freqtrade backtest wrapped inside a background task
so the HTTP response is returned immediately.  Callers poll
GET /api/session/status/{session_id} for the run_id once completed.

This router now delegates to the shared workflow_jobs.start_backtest_job function
to ensure both normal API routes and AI tool executor use the same workflow.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...core.errors import BackendError
from ...services.workflow_jobs import start_backtest_job
from ..dependencies import get_services, get_session_store
from ..models import AsyncJobResponse, BacktestApiRequest
from ..session_store import SessionStore

router = APIRouter(prefix="/api/backtest", tags=["Backtest"])


@router.post(
    "/run",
    response_model=AsyncJobResponse,
    status_code=202,
    summary="Run a strategy backtest",
    description=(
        "Queues a Freqtrade backtesting job for the specified strategy and parameters. "
        "Returns a session_id immediately; poll /api/session/status/{session_id} for the "
        "run_id once the backtest completes."
    ),
)
async def run_backtest(
    body: BacktestApiRequest,
    services=Depends(get_services),
    store: SessionStore = Depends(get_session_store),
) -> AsyncJobResponse:
    """Run backtest using shared workflow_jobs.start_backtest_job function."""
    try:
        session_id, status = await start_backtest_job(
            services=services,
            store=store,
            strategy_name=body.strategy_name,
            version_id=body.version_id,
            timerange=body.timerange,
            timeframe=body.timeframe,
            pairs=body.pairs,
            max_open_trades=body.max_open_trades,
            dry_run_wallet=body.dry_run_wallet,
            config_file=body.config_file,
        )
        
        return AsyncJobResponse(
            session_id=session_id,
            status=status,
            message=(
                f"Backtest queued for strategy '{body.strategy_name}'. "
                f"Poll /api/session/status/{session_id} for the run_id once completed."
            ),
        )
    except BackendError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
