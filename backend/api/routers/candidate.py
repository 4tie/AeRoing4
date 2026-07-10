"""Router: POST /api/candidate/evaluate

Evaluates a strategy candidate through the multi-gate pipeline.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from ...models.strategy_spec import StrategySpec, validate_spec
from ...services.candidate.models import (
    CandidateConfig,
    CandidateRunState,
    CandidateRunStatus,
    CandidateVerdict,
)
from ...services.candidate.orchestrator import evaluate_candidate
from ...services.candidate.run_manager import CandidateRunManager

router = APIRouter(prefix="/api/candidate", tags=["Candidate"])
candidate_run_manager = CandidateRunManager()


class CandidateEvaluateRequest(BaseModel):
    """Request body for candidate evaluation."""
    spec: StrategySpec
    config: CandidateConfig


class CandidateEvaluateResponse(BaseModel):
    """Response body for candidate evaluation."""
    verdict: CandidateVerdict


class CandidateRunStartResponse(BaseModel):
    """Response body for starting an async candidate run."""
    run_id: str
    status: CandidateRunStatus
    message: str


def _raise_invalid_spec(spec: StrategySpec) -> None:
    validation_errors = validate_spec(spec)
    if validation_errors:
        raise HTTPException(
            status_code=422,
            detail={
                "status": "error",
                "reason": "INVALID_SPEC",
                "errors": validation_errors,
                "message": "StrategySpec validation failed.",
            },
        )


async def _run_candidate_background(
    run_id: str,
    spec: StrategySpec,
    config: CandidateConfig,
    deps: dict | None = None,
) -> None:
    candidate_run_manager.mark_running(run_id)
    try:
        verdict = await evaluate_candidate(
            spec,
            config,
            deps=deps,
            progress_sink=lambda update: candidate_run_manager.update_gate(run_id, update),
        )
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        candidate_run_manager.mark_failed(run_id, detail)
        return
    candidate_run_manager.mark_completed(run_id, verdict)


def _spawn_candidate_task(coro):
    return asyncio.create_task(coro)


def _candidate_evaluation_deps(services) -> dict:
    data_download_runner = getattr(services, "data_download_runner", None)
    if data_download_runner is None:
        return {}
    return {"data_download_runner": data_download_runner}


def _run_state_event(event_type: str, state: CandidateRunState) -> dict:
    return {
        "type": event_type,
        "run_id": state.run_id,
        "data": state.model_dump(mode="json"),
    }


@router.post(
    "/runs",
    response_model=CandidateRunStartResponse,
    status_code=202,
    summary="Start an async candidate evaluation run",
)
async def start_candidate_run(
    body: CandidateEvaluateRequest,
    request: Request,
) -> CandidateRunStartResponse:
    """Start candidate evaluation in the background and return a run id."""
    services = getattr(request.app.state, "services", None)
    _raise_invalid_spec(body.spec)
    state = candidate_run_manager.create_run(body.spec, body.config)
    state = candidate_run_manager.mark_running(state.run_id) or state
    _spawn_candidate_task(
        _run_candidate_background(
            state.run_id,
            body.spec,
            body.config,
            _candidate_evaluation_deps(services),
        )
    )
    return CandidateRunStartResponse(
        run_id=state.run_id,
        status=state.status,
        message=(
            f"Candidate evaluation started for '{body.spec.name}'. "
            f"Poll /api/candidate/runs/{state.run_id} for progress."
        ),
    )


@router.get(
    "/runs/{run_id}",
    response_model=CandidateRunState,
    summary="Get current candidate evaluation run state",
)
async def get_candidate_run(run_id: str) -> CandidateRunState:
    """Return the current candidate run snapshot."""
    state = candidate_run_manager.get_run(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Candidate run '{run_id}' not found.")
    return state


@router.websocket("/ws/{run_id}")
async def candidate_websocket(websocket: WebSocket, run_id: str) -> None:
    """Stream live Candidate run progress."""
    await websocket.accept()

    state = candidate_run_manager.get_run(run_id)
    if state is None:
        await websocket.send_json({
            "type": "error",
            "run_id": run_id,
            "error": f"Candidate run '{run_id}' not found.",
        })
        await websocket.close()
        return

    await websocket.send_json(_run_state_event("snapshot", state))

    if state.status in {CandidateRunStatus.COMPLETED, CandidateRunStatus.FAILED}:
        await websocket.send_json(_run_state_event("final", state))
        await websocket.close()
        return

    queue = candidate_run_manager.subscribe(run_id)
    if queue is None:
        await websocket.send_json({
            "type": "error",
            "run_id": run_id,
            "error": f"Candidate run '{run_id}' not found.",
        })
        await websocket.close()
        return

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "keepalive", "run_id": run_id})
                continue

            await websocket.send_json(event)
            if event.get("type") == "final":
                await websocket.close()
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        candidate_run_manager.release(run_id, queue)


@router.post(
    "/evaluate",
    summary="Evaluate a strategy candidate",
    description=(
        "Runs a strategy candidate through the evaluation pipeline including "
        "render, data quality check, backtest gate, and optional repair loop. "
        "Returns a verdict with per-gate results."
    ),
)
async def evaluate_candidate_endpoint(
    body: CandidateEvaluateRequest,
    request: Request,
) -> CandidateEvaluateResponse:
    """Evaluate a strategy candidate through the multi-gate pipeline."""
    services = getattr(request.app.state, "services", None)
    # Validate StrategySpec
    _raise_invalid_spec(body.spec)

    # Call evaluate_candidate
    verdict = await evaluate_candidate(
        body.spec,
        body.config,
        deps=_candidate_evaluation_deps(services),
    )

    return CandidateEvaluateResponse(verdict=verdict)
