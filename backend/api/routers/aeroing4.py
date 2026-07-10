"""Router: /api/aeroing4/*

Minimal API endpoints for AeRoing4 workflow execution.

POST /api/aeroing4/runs              - Start a new AeRoing4 run
GET  /api/aeroing4/runs/{run_id}     - Get run status and results
GET  /api/aeroing4/runs              - List all runs
POST /api/aeroing4/runs/{run_id}/cancel - Cancel an active run
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core.errors import BackendError
from ...services.aeroing4 import AeRoing4Orchestrator, AeRoing4Run
from ..dependencies import get_services

router = APIRouter(prefix="/api/aeroing4", tags=["AeRoing4"])


class AeRoing4RunRequest(BaseModel):
    """Request model for starting an AeRoing4 run."""
    strategy_name: str
    timeframe: str = "5m"
    smoke_timerange: str = "20240101-20240131"
    smoke_pairs: list[str] | None = None

    # Milestone 2A: Pair Discovery
    enable_pair_discovery: bool = False
    discovery_pairs: list[str] | None = None
    discovery_timerange: str | None = None

    # Milestone 3: Research Protocol / Data Zone Guard.
    # Providing both fields activates the protocol for this run; the
    # existing discovery_timerange (or its default) becomes the DEVELOP
    # zone. Omitting both preserves current behavior exactly.
    confirmation_timerange: str | None = None
    final_unseen_timerange: str | None = None


class AeRoing4RunResponse(BaseModel):
    """Response model for AeRoing4 run."""
    run_id: str
    strategy_name: str
    timeframe: str
    smoke_pairs: list[str]
    smoke_timerange: str
    status: str
    current_step: str
    steps: dict[str, dict]
    error: str | None
    created_at: str
    updated_at: str
    completed_at: str | None

    # Milestone 2A: Pair Discovery fields
    enable_pair_discovery: bool
    discovery_pairs: list[str] | None
    discovery_timerange: str | None

    # Milestone 3: Research Protocol / Data Zone Guard visibility.
    confirmation_timerange: str | None
    final_unseen_timerange: str | None
    research_protocol_active: bool


class StartRunResponse(BaseModel):
    """Response model for starting a run."""
    run_id: str
    status: str
    message: str


def _run_to_response(run: AeRoing4Run) -> AeRoing4RunResponse:
    """Convert AeRoing4Run to API response."""
    return AeRoing4RunResponse(
        run_id=run.run_id,
        strategy_name=run.strategy_name,
        timeframe=run.timeframe,
        smoke_pairs=run.smoke_pairs,
        smoke_timerange=run.smoke_timerange,
        status=run.status.value,
        current_step=run.current_step,
        steps={k: v.model_dump() for k, v in run.steps.items()},
        error=run.error,
        created_at=run.created_at.isoformat(),
        updated_at=run.updated_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        enable_pair_discovery=run.enable_pair_discovery,
        discovery_pairs=run.discovery_pairs,
        discovery_timerange=run.discovery_timerange,
        confirmation_timerange=run.confirmation_timerange,
        final_unseen_timerange=run.final_unseen_timerange,
        research_protocol_active=bool(
            run.confirmation_timerange and run.final_unseen_timerange
        ),
    )


@router.post(
    "/runs",
    response_model=StartRunResponse,
    status_code=202,
    summary="Start a new AeRoing4 run",
    description=(
        "Creates and starts a new AeRoing4 workflow execution. "
        "The workflow performs strict validation, data preparation, and smoke backtesting. "
        "When enable_pair_discovery=true and smoke backtest returns PASS_ACTIVITY, "
        "pair discovery runs against the discovery universe. "
        "Returns immediately with run_id for status polling."
    ),
)
async def start_run(
    body: AeRoing4RunRequest,
    services=Depends(get_services),
) -> StartRunResponse:
    """Start a new AeRoing4 run."""
    try:
        orchestrator = services.aeroing4_orchestrator

        # Create run
        run = orchestrator.create_run(
            strategy_name=body.strategy_name,
            timeframe=body.timeframe,
            smoke_timerange=body.smoke_timerange,
            smoke_pairs=body.smoke_pairs,
            enable_pair_discovery=body.enable_pair_discovery,
            discovery_pairs=body.discovery_pairs,
            discovery_timerange=body.discovery_timerange,
            confirmation_timerange=body.confirmation_timerange,
            final_unseen_timerange=body.final_unseen_timerange,
        )

        # Start execution
        await orchestrator.start_run(run.run_id)

        discovery_note = (
            " Pair Discovery enabled — will run if smoke backtest passes."
            if body.enable_pair_discovery
            else ""
        )

        return StartRunResponse(
            run_id=run.run_id,
            status=run.status.value,
            message=(
                f"AeRoing4 run started for strategy '{body.strategy_name}'.{discovery_note} "
                f"Poll /api/aeroing4/runs/{run.run_id} for status."
            ),
        )

    except BackendError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start run: {str(exc)}")


@router.get(
    "/runs/{run_id}",
    response_model=AeRoing4RunResponse,
    summary="Get AeRoing4 run status",
    description=(
        "Returns the current status and results of an AeRoing4 run. "
        "When pair_discovery step is present, the steps dict includes full "
        "discovery results with ranked_pairs and all per-pair evaluation evidence."
    ),
)
async def get_run(
    run_id: str,
    services=Depends(get_services),
) -> AeRoing4RunResponse:
    """Get AeRoing4 run status."""
    orchestrator = services.aeroing4_orchestrator
    run = orchestrator.get_run(run_id)

    if not run:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    return _run_to_response(run)


@router.get(
    "/runs",
    response_model=list[AeRoing4RunResponse],
    summary="List all AeRoing4 runs",
    description="Returns all AeRoing4 runs, newest first.",
)
async def list_runs(
    services=Depends(get_services),
) -> list[AeRoing4RunResponse]:
    """List all AeRoing4 runs."""
    orchestrator = services.aeroing4_orchestrator
    runs = orchestrator.list_runs()
    return [_run_to_response(run) for run in runs]


@router.post(
    "/runs/{run_id}/cancel",
    response_model=AeRoing4RunResponse,
    summary="Cancel an AeRoing4 run",
    description="Cancels an active AeRoing4 run.",
)
async def cancel_run(
    run_id: str,
    services=Depends(get_services),
) -> AeRoing4RunResponse:
    """Cancel an AeRoing4 run."""
    try:
        orchestrator = services.aeroing4_orchestrator
        await orchestrator.cancel_run(run_id)

        run = orchestrator.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        return _run_to_response(run)

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to cancel run: {str(exc)}")
