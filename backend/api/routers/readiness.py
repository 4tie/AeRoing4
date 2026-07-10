"""Candidate readiness API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

from ...services.readiness_service import ReadinessService
from . import candidate


router = APIRouter(prefix="/api/readiness", tags=["Readiness"])


@router.get("/report")
async def get_readiness_report(
    request: Request,
    strategy_name: Annotated[str | None, Query(description="Strategy name to annotate the report with.")] = None,
    optimizer_session_id: Annotated[str | None, Query(description="Optimizer session ID.")] = None,
    trial_number: Annotated[int | None, Query(description="Optimizer trial number.")] = None,
    backtest_run_id: Annotated[str | None, Query(description="Backtest run ID.")] = None,
    candidate_run_id: Annotated[str | None, Query(description="Candidate run ID.")] = None,
    stress_session_id: Annotated[str | None, Query(description="Stress-lab session ID.")] = None,
    temporal_stress_session_id: Annotated[str | None, Query(description="Temporal stress session ID.")] = None,
    profile: Annotated[str | None, Query(description="Optional readiness profile override.")] = None,
) -> dict:
    services = request.app.state.services
    readiness = ReadinessService(
        root_dir=services.root_dir,
        run_repository=getattr(services, "run_repository", None),
        optimizer_store=getattr(services, "optimizer_store", None),
        sweep_store=getattr(services, "sweep_store", None),
        session_store=getattr(request.app.state, "session_store", None),
        candidate_run_lookup=candidate.candidate_run_manager.get_run,
    )
    return readiness.build_report(
        strategy_name=strategy_name,
        optimizer_session_id=optimizer_session_id,
        trial_number=trial_number,
        backtest_run_id=backtest_run_id,
        candidate_run_id=candidate_run_id,
        stress_session_id=stress_session_id,
        temporal_stress_session_id=temporal_stress_session_id,
        profile=profile,
    )
