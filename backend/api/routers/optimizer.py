"""Router: POST /api/optimizer/run

Starts a systematic parameter-search session.  The optimizer already manages
its own internal asyncio.Task, so this endpoint simply forwards the request,
gets an optimizer_session_id back immediately, and then monitors the session
in a lightweight background coroutine that updates the API session store.

This router now delegates to the shared workflow_jobs.start_optimizer_job function
to ensure both normal API routes and AI tool executor use the same workflow.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.errors import BackendError
from ...core.optimizer_errors import OptimizerError
from ...models import (
    OptimizerParameterMode,
    OptimizerScoreMetric,
    SearchStrategy,
    StartOptimizerRequest,
)
from ...services.strategy.optimizer_auto_safe import apply_auto_safe_initial_spaces
from ...services.optimizer import api_service as optimizer_api
from ...services.workflow_jobs import start_optimizer_job
from ..dependencies import get_services, get_session_store
from ..models import AsyncJobResponse, OptimizerApiRequest
from ..session_store import SessionStore

router = APIRouter(prefix="/api/optimizer", tags=["Optimizer"])
logger = logging.getLogger(__name__)


# ── Export / Apply request models ─────────────────────────────────────────────


class ApplyTrialRequest(BaseModel):
    strategy_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExportTrialItem(BaseModel):
    strategy_name: str
    trial_number: int
    score: float | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)


class ExportTrialsRequest(BaseModel):
    trials: list[ExportTrialItem]


_TERMINAL_PHASES = optimizer_api.TERMINAL_PHASES
_enum_value = optimizer_api.enum_value
_optimizer_error_status = optimizer_api.optimizer_error_status
_load_session_or_404 = optimizer_api.load_session_or_404
_space_by_name = optimizer_api.space_by_name
_flat_params_to_freqtrade_format = optimizer_api.flat_params_to_freqtrade_format
_get_trial_by_number = optimizer_api.get_trial_by_number
_monitor_optimizer = optimizer_api.monitor_optimizer


def _raise_backend_error(exc: BackendError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


def _raise_optimizer_error(exc: OptimizerError) -> None:
    raise HTTPException(status_code=_optimizer_error_status(exc), detail=exc.message)


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


@router.post(
    "/run",
    response_model=AsyncJobResponse,
    status_code=202,
    summary="Start a parameter optimizer session",
    description=(
        "Launches a systematic multi-trial parameter search for the given strategy. "
        "Returns a session_id immediately; poll /api/session/status/{session_id} for progress "
        "and the final best trial details."
    ),
)
async def run_optimizer(
    body: OptimizerApiRequest,
    services=Depends(get_services),
    store: SessionStore = Depends(get_session_store),
) -> AsyncJobResponse:
    """Run optimizer using shared workflow_jobs.start_optimizer_job function."""
    try:
        api_session_id, optimizer_session_id, status = await start_optimizer_job(
            services=services,
            store=store,
            strategy_name=body.strategy_name,
            timerange=body.timerange,
            timeframe=body.timeframe,
            pairs=body.pairs,
            search_spaces=body.search_spaces,
            total_trials=body.total_trials,
            search_strategy=body.search_strategy,
            parameter_mode=body.parameter_mode,
            score_metric=body.score_metric,
            max_open_trades=body.max_open_trades,
            dry_run_wallet=body.dry_run_wallet,
            fee_rate=body.fee_rate,
            enable_vectorbt_screening=body.enable_vectorbt_screening,
            vectorbt_candidate_count=body.vectorbt_candidate_count,
            vectorbt_keep_ratio=body.vectorbt_keep_ratio,
            vectorbt_timeout_seconds=body.vectorbt_timeout_seconds,
            config_file=body.config_file,
        )
        
        return AsyncJobResponse(
            session_id=api_session_id,
            status=status,
            message=(
                f"Optimizer started — {body.total_trials} trials for '{body.strategy_name}'. "
                f"Internal optimizer_session_id={optimizer_session_id}. "
                f"Poll /api/session/status/{api_session_id} for progress."
            ),
        )
    except BackendError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get(
    "/search-spaces/{strategy_name}",
    summary="Get default parameter search spaces for a strategy",
    description=(
        "Returns a list of ParameterSearchSpace objects inferred from the strategy's "
        "parameter definitions. Used by the frontend to populate the parameters table."
    ),
)
async def get_search_spaces(strategy_name: str, request: Request):
    services = request.app.state.services
    try:
        spaces = services.strategy_optimizer.build_search_spaces_from_strategy(strategy_name)
    except BackendError as exc:
        _raise_backend_error(exc)
    except OptimizerError as exc:
        _raise_optimizer_error(exc)
    return {"strategy_name": strategy_name, "search_spaces": [s.model_dump() for s in spaces]}


@router.get(
    "/sessions",
    summary="List optimizer sessions",
    description="Returns all optimizer sessions sorted by newest first. Filter by strategy_name if provided.",
)
async def list_optimizer_sessions(
    strategy_name: str | None = None,
    request: Request = None,
) -> list[dict]:
    services = request.app.state.services
    summaries = services.optimizer_store.list_sessions(strategy_name)
    return [s.model_dump(mode="json") for s in summaries]


@router.get(
    "/session/{optimizer_session_id}",
    summary="Get full optimizer session data including all trials",
    description=(
        "Returns the complete OptimizerSession record from disk, including the "
        "full trials[] array with per-trial metrics. Poll this at 300 ms during "
        "a run to drive live charts and the trial table."
    ),
)
async def get_optimizer_session(
    optimizer_session_id: str,
    request: Request,
):
    from fastapi.responses import JSONResponse
    services = request.app.state.services
    session = _load_session_or_404(services, optimizer_session_id)
    return JSONResponse(
        content=_json_safe(session.model_dump(mode="json")),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.post(
    "/apply-trial",
    summary="Apply a trial's parameters to the current accepted version",
    description=(
        "Writes the given parameter values into the accepted version and live strategy "
        ".py/.json files so subsequent backtests and the strategy editor pick them up. "
        "Does not create a new version or touch git."
    ),
)
async def apply_trial(body: ApplyTrialRequest, request: Request) -> dict:
    services = request.app.state.services
    if services.backtest_runner.is_busy():
        logger.warning("Attempted to apply trial while backtest running")
        raise HTTPException(
            status_code=409,
            detail="Cannot apply trial parameters while a backtest is running. Wait for it to complete first.",
        )
    try:
        services.registry.get_strategy(body.strategy_name)
    except BackendError as exc:
        logger.error("Strategy not found: %s", body.strategy_name)
        _raise_backend_error(exc)

    pointer = services.version_manager.get_current_pointer(body.strategy_name)
    if pointer is None:
        logger.warning("No accepted version found for strategy: %s", body.strategy_name)
        raise HTTPException(
            status_code=409,
            detail=f"Strategy '{body.strategy_name}' has no accepted version.",
        )

    try:
        version_id = pointer.accepted_version_id
        parent_params = services.version_manager.load_params(body.strategy_name, version_id)
        merged = services.strategy_optimizer.trial_executor.build_trial_params(
            parent_params, body.parameters
        )
        written_paths = services.version_manager.overwrite_accepted_params(
            body.strategy_name,
            version_id,
            merged,
        )
    except FileNotFoundError as exc:
        logger.error("Params file not found for strategy %s: %s", body.strategy_name, exc)
        raise HTTPException(
            status_code=404,
            detail=f"Parameters file not found for '{body.strategy_name}'.",
        )
    except BackendError as exc:
        logger.error("Backend error applying trial for %s: %s", body.strategy_name, exc.message)
        _raise_backend_error(exc)
    except OptimizerError as exc:
        logger.error("Optimizer error applying trial for %s: %s", body.strategy_name, exc.message)
        _raise_optimizer_error(exc)
    except Exception as exc:
        logger.error("Error applying trial for %s: %s", body.strategy_name, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to apply trial parameters: {exc}",
        )

    return {
        "ok": True,
        "message": f"Parameters applied to '{body.strategy_name}' accepted version and live strategy files.",
        "strategy_name": body.strategy_name,
        "accepted_version_id": version_id,
        "written_paths": written_paths,
    }


@router.post(
    "/export-trials",
    summary="Export one or more optimizer trials to the Stress Test Lab",
    description="Persists trial configurations to exported_optimizer_runs.json for use in temporal stress tests.",
)
async def export_trials(body: ExportTrialsRequest, request: Request) -> dict:
    services = request.app.state.services
    created = []
    for item in body.trials:
        record = services.exported_trial_store.append(
            strategy_name=item.strategy_name,
            trial_number=item.trial_number,
            score=item.score,
            parameters=item.parameters,
            metrics=item.metrics,
        )
        created.append(record)
    return {"ok": True, "exported": created, "count": len(created)}


@router.get(
    "/exported-trials",
    summary="List all exported optimizer trial configurations",
    description="Returns all records from exported_optimizer_runs.json, newest first.",
)
async def get_exported_trials(request: Request) -> dict:
    services = request.app.state.services
    records = services.exported_trial_store.list_all()
    return {"trials": records}


@router.post(
    "/cancel/{optimizer_session_id}",
    summary="Cancel a running optimizer session",
    description="Requests cancellation of the optimizer session and stops any active backtest.",
)
async def cancel_optimizer_session(optimizer_session_id: str, request: Request) -> dict:
    services = request.app.state.services
    try:
        session = await services.strategy_optimizer.cancel_session(optimizer_session_id)
        logger.info("Successfully cancelled optimizer session: %s", optimizer_session_id)
        return {
            "ok": True,
            "phase": _enum_value(session.phase),
            "optimizer_session_id": optimizer_session_id,
        }
    except BackendError as exc:
        logger.error("Backend error cancelling session %s: %s", optimizer_session_id, exc.message)
        _raise_backend_error(exc)
    except OptimizerError as exc:
        logger.error("Optimizer error cancelling session %s: %s", optimizer_session_id, exc.message)
        _raise_optimizer_error(exc)
    except Exception as exc:
        logger.error("Unexpected error cancelling session %s: %s", optimizer_session_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel optimizer session: {exc}",
        )


@router.get(
    "/session/{session_id}/best-trial/params",
    summary="Get best trial parameters in Freqtrade-compatible format",
)
async def get_best_trial_params(session_id: str, request: Request) -> dict:
    services = request.app.state.services
    session = _load_session_or_404(services, session_id)
    if session.best_trial_number is None:
        logger.warning("No best trial available for session: %s", session_id)
        raise HTTPException(status_code=404, detail="No best trial available yet.")
    trial = _get_trial_by_number(session, session.best_trial_number)
    return _flat_params_to_freqtrade_format(
        session.config.strategy_name,
        trial.parameters or {},
        _space_by_name(session),
    )


@router.get(
    "/session/{session_id}/trial/{trial_number}/params",
    summary="Get a specific trial's parameters in Freqtrade-compatible format",
)
async def get_trial_params(session_id: str, trial_number: int, request: Request) -> dict:
    services = request.app.state.services
    session = _load_session_or_404(services, session_id)
    trial = _get_trial_by_number(session, trial_number)
    return _flat_params_to_freqtrade_format(
        session.config.strategy_name,
        trial.parameters or {},
        _space_by_name(session),
    )


@router.get(
    "/session/{session_id}/best-trial/preview-application",
    summary="Preview applying the best trial parameters without writing files",
)
async def preview_best_trial_application(session_id: str, request: Request) -> dict:
    services = request.app.state.services
    session = _load_session_or_404(services, session_id)
    if session.best_trial_number is None:
        logger.warning("No best trial available for session: %s", session_id)
        raise HTTPException(status_code=404, detail="No best trial available yet.")
    try:
        return services.version_manager.preview_optimizer_trial_application(
            run_repository=services.run_repository,
            optimizer_store=services.optimizer_store,
            session_id=session_id,
            trial_number=session.best_trial_number,
        )
    except BackendError as exc:
        logger.error("Backend error previewing trial application: %s", exc.message)
        _raise_backend_error(exc)
    except OptimizerError as exc:
        logger.error("Optimizer error previewing trial application: %s", exc.message)
        _raise_optimizer_error(exc)
    except Exception as exc:
        logger.error("Unexpected error previewing trial application: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to preview trial application: {exc}",
        )


@router.get(
    "/session/{session_id}/trial/{trial_number}/preview-application",
    summary="Preview applying a trial's parameters without writing files",
)
async def preview_trial_application(
    session_id: str,
    trial_number: int,
    request: Request,
) -> dict:
    services = request.app.state.services
    try:
        return services.version_manager.preview_optimizer_trial_application(
            run_repository=services.run_repository,
            optimizer_store=services.optimizer_store,
            session_id=session_id,
            trial_number=trial_number,
        )
    except BackendError as exc:
        logger.error("Backend error previewing trial application: %s", exc.message)
        _raise_backend_error(exc)
    except OptimizerError as exc:
        logger.error("Optimizer error previewing trial application: %s", exc.message)
        _raise_optimizer_error(exc)
    except Exception as exc:
        logger.error("Unexpected error previewing trial application: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to preview trial application: {exc}",
        )


@router.post(
    "/session/{session_id}/best-trial/promote-candidate",
    summary="Promote best optimizer trial to a candidate version (safe — does not touch accepted version)",
)
async def promote_best_trial_to_candidate(session_id: str, request: Request) -> dict:
    services = request.app.state.services
    session = _load_session_or_404(services, session_id)
    phase = _enum_value(session.phase)
    if phase != "completed":
        logger.warning(
            "Attempted to promote from incomplete session %s (phase: %s)",
            session_id,
            phase,
        )
        raise HTTPException(
            status_code=409,
            detail=f"Session is not completed (current phase: '{phase}'). Wait for it to finish before promoting.",
        )
    if session.best_trial_number is None:
        logger.warning("No best trial found in session: %s", session_id)
        raise HTTPException(status_code=404, detail="No best trial found in this session.")
    trial = _get_trial_by_number(session, session.best_trial_number)
    trial_status = _enum_value(trial.status)
    if trial_status != "completed":
        logger.warning("Best trial not completed: #%s in session %s", trial.trial_number, session_id)
        raise HTTPException(
            status_code=400,
            detail=f"Best trial #{trial.trial_number} is not completed.",
        )
    if not trial.parameters:
        logger.warning("Best trial has no parameters: #%s in session %s", trial.trial_number, session_id)
        raise HTTPException(
            status_code=400,
            detail=f"Best trial #{trial.trial_number} has no parameters.",
        )
    if not trial.run_id:
        logger.warning("Best trial has no run_id: #%s in session %s", trial.trial_number, session_id)
        raise HTTPException(
            status_code=400,
            detail=f"Best trial #{trial.trial_number} has no associated backtest run and cannot be promoted.",
        )
    try:
        result = services.version_manager.apply_optimizer_trial_to_new_version(
            run_repository=services.run_repository,
            optimizer_store=services.optimizer_store,
            session_id=session_id,
            trial_number=trial.trial_number,
        )
    except BackendError as exc:
        logger.error("Backend error promoting trial: %s", exc.message)
        _raise_backend_error(exc)
    except OptimizerError as exc:
        logger.error("Optimizer error promoting trial: %s", exc.message)
        _raise_optimizer_error(exc)
    except Exception as exc:
        logger.error("Unexpected error promoting trial: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to promote trial to candidate: {exc}",
        )
    return {
        "ok": True,
        "strategy_name": session.config.strategy_name,
        "candidate_version_id": result["version_id"],
        "trial_number": trial.trial_number,
        "score": trial.metrics.score if trial.metrics else None,
        "metrics": trial.metrics.model_dump(mode="json") if trial.metrics else {},
    }


@router.post(
    "/session/{session_id}/trial/{trial_number}/promote-candidate",
    summary="Promote a specific optimizer trial to a candidate version (safe — does not touch accepted version)",
)
async def promote_trial_to_candidate(session_id: str, trial_number: int, request: Request) -> dict:
    services = request.app.state.services
    session = _load_session_or_404(services, session_id)
    trial = _get_trial_by_number(session, trial_number)
    trial_status = _enum_value(trial.status)
    if trial_status != "completed":
        logger.warning("Trial not completed: #%s in session %s", trial_number, session_id)
        raise HTTPException(status_code=400, detail=f"Trial #{trial_number} is not completed.")
    if not trial.parameters:
        logger.warning("Trial has no parameters: #%s in session %s", trial_number, session_id)
        raise HTTPException(status_code=400, detail=f"Trial #{trial_number} has no parameters.")
    if not trial.run_id:
        logger.warning("Trial has no run_id: #%s in session %s", trial_number, session_id)
        raise HTTPException(
            status_code=400,
            detail=f"Trial #{trial_number} has no associated backtest run and cannot be promoted.",
        )
    try:
        result = services.version_manager.apply_optimizer_trial_to_new_version(
            run_repository=services.run_repository,
            optimizer_store=services.optimizer_store,
            session_id=session_id,
            trial_number=trial_number,
        )
    except BackendError as exc:
        logger.error("Backend error promoting trial: %s", exc.message)
        _raise_backend_error(exc)
    except OptimizerError as exc:
        logger.error("Optimizer error promoting trial: %s", exc.message)
        _raise_optimizer_error(exc)
    except Exception as exc:
        logger.error("Unexpected error promoting trial: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to promote trial to candidate: {exc}",
        )
    return {
        "ok": True,
        "strategy_name": session.config.strategy_name,
        "candidate_version_id": result["version_id"],
        "trial_number": trial_number,
        "score": trial.metrics.score if trial.metrics else None,
        "metrics": trial.metrics.model_dump(mode="json") if trial.metrics else {},
    }
