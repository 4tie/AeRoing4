"""Router: /api/agent/* read-only observability endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from ...core.errors import BackendError
from ...services.agent_context import AgentContextService
from . import candidate

router = APIRouter(prefix="/api/agent", tags=["Agent Observability"])


class AgentUiStatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    active_tab: str | None = None
    active_panel: str | None = None
    strategy_name: str | None = None
    timeframe: str | None = None
    timerange: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    pairs: list[str] | None = None
    dry_run_wallet: float | None = None
    max_open_trades: int | None = None
    backtest_status: str | None = None
    auto_quant_run_id: str | None = None
    optimizer_session_id: str | None = None
    optimizer_trial_number: int | None = None
    backtest_run_id: str | None = None
    candidate_run_id: str | None = None
    stress_session_id: str | None = None
    temporal_stress_session_id: str | None = None
    readiness_profile: str | None = None
    api_session_id: str | None = None


def _service(request: Request) -> AgentContextService:
    services = request.app.state.services
    return AgentContextService(
        root_dir=services.root_dir,
        run_repository=services.run_repository,
        settings_store=services.settings_store,
        version_manager=services.version_manager,
        strategy_optimizer=getattr(services, "strategy_optimizer", None),
        backtest_runner=services.backtest_runner,
        optimizer_store=getattr(services, "optimizer_store", None),
        sweep_store=getattr(services, "sweep_store", None),
        run_detail_callable=services.run_detail,
        log_broadcaster=getattr(request.app.state, "log_broadcaster", None),
        session_store=getattr(request.app.state, "session_store", None),
        candidate_run_lookup=candidate.candidate_run_manager.get_run,
    )


def _raise_backend(exc: BackendError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post(
    "/ui-state",
    summary="Persist the frontend agent heartbeat",
    description="Stores the active tab, active panel, selected strategy, and active run IDs.",
)
async def update_agent_ui_state(body: AgentUiStatePayload, request: Request) -> dict[str, Any]:
    payload = body.model_dump(mode="json", exclude_unset=True)
    return _service(request).save_ui_state(payload)


@router.get(
    "/context",
    summary="Return the complete read-only agent context snapshot",
)
async def get_agent_context(
    request: Request,
    active_tab: str | None = Query(default=None),
    active_panel: str | None = Query(default=None),
    strategy_name: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    timerange: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    pairs: list[str] | None = Query(default=None),
    dry_run_wallet: float | None = Query(default=None),
    max_open_trades: int | None = Query(default=None),
    backtest_status: str | None = Query(default=None),
    auto_quant_run_id: str | None = Query(default=None),
    optimizer_session_id: str | None = Query(default=None),
    optimizer_trial_number: int | None = Query(default=None),
    backtest_run_id: str | None = Query(default=None),
    candidate_run_id: str | None = Query(default=None),
    stress_session_id: str | None = Query(default=None),
    temporal_stress_session_id: str | None = Query(default=None),
    readiness_profile: str | None = Query(default=None),
    api_session_id: str | None = Query(default=None),
) -> dict[str, Any]:
    overrides = {
        "active_tab": active_tab,
        "active_panel": active_panel,
        "strategy_name": strategy_name,
        "timeframe": timeframe,
        "timerange": timerange,
        "start_date": start_date,
        "end_date": end_date,
        "pairs": pairs or [],
        "dry_run_wallet": dry_run_wallet,
        "max_open_trades": max_open_trades,
        "backtest_status": backtest_status,
        "auto_quant_run_id": auto_quant_run_id,
        "optimizer_session_id": optimizer_session_id,
        "optimizer_trial_number": optimizer_trial_number,
        "backtest_run_id": backtest_run_id,
        "candidate_run_id": candidate_run_id,
        "stress_session_id": stress_session_id,
        "temporal_stress_session_id": temporal_stress_session_id,
        "readiness_profile": readiness_profile,
        "api_session_id": api_session_id,
    }
    return _service(request).build_context(overrides)


@router.get(
    "/runs/auto-quant/{run_id}",
    summary="Return an AutoQuant observability snapshot",
)
async def get_agent_auto_quant_run(run_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).auto_quant_run_context(run_id)
    except BackendError as exc:
        _raise_backend(exc)


@router.get(
    "/runs/optimizer/{session_id}",
    summary="Return an optimizer observability snapshot",
)
async def get_agent_optimizer_run(
    session_id: str,
    request: Request,
    optimizer_trial_number: int | None = Query(default=None),
) -> dict[str, Any]:
    try:
        return _service(request).optimizer_run_context(
            session_id,
            trial_number=optimizer_trial_number,
        )
    except BackendError as exc:
        _raise_backend(exc)


@router.get(
    "/runs/backtest/{run_id}",
    summary="Return a backtest observability snapshot",
)
async def get_agent_backtest_run(run_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).backtest_run_context(run_id)
    except BackendError as exc:
        _raise_backend(exc)


@router.get(
    "/files/strategy/{strategy_name}",
    summary="Return allowlisted strategy file content for the agent",
)
async def get_agent_strategy_files(strategy_name: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).strategy_file_context(strategy_name, include_content=True)
    except BackendError as exc:
        _raise_backend(exc)


@router.get(
    "/status",
    summary="Get agent status for the Overview tab",
)
async def get_agent_status(request: Request) -> dict[str, Any]:
    """Get agent status for the Overview tab with pipeline context."""
    # Get pipeline state from app state if available
    pipeline_state = None
    try:
        services = request.app.state.services
        if hasattr(services, 'run_repository'):
            # Get most recent run to determine pipeline stage
            runs = services.run_repository.list_runs(limit=1)
            if runs:
                latest_run = runs[0]
                pipeline_state = {
                    "current_stage": latest_run.get("current_stage", 0),
                    "status": latest_run.get("status", "idle"),
                    "strategy": latest_run.get("strategy", None)
                }
    except Exception:
        pass

    # Agent to pipeline stage mapping
    agent_stage_mapping = {
        0: "Scout",      # Sanity Backtest
        1: "Dev",        # Hyperopt Execution
        2: "Dev",        # Auto-Patching
        3: "Reach",      # Out-of-Sample Validation
        4: "Scout",      # Multi-Pair Stress Test
        5: "Orchestrator", # Risk Assessment
        6: "Scribe",     # Delivery
    }

    # Determine active agent based on pipeline stage
    active_agent = "Orchestrator"
    if pipeline_state and pipeline_state.get("current_stage") is not None:
        current_stage = pipeline_state["current_stage"]
        active_agent = agent_stage_mapping.get(current_stage, "Orchestrator")

    # Update agent statuses based on pipeline activity
    agents = [
        {
            "name": "Orchestrator",
            "status": "Active" if active_agent == "Orchestrator" else "Monitoring",
            "responses": 342,
            "tasks_completed": 156,
            "current_task": "Coordinating pipeline" if active_agent == "Orchestrator" else "Monitoring system"
        },
        {
            "name": "Scout",
            "status": "Scanning" if active_agent == "Scout" else "Idle",
            "responses": 289,
            "tasks_completed": 134,
            "current_task": "Market analysis" if active_agent == "Scout" else "Waiting for tasks"
        },
        {
            "name": "Dev",
            "status": "Processing" if active_agent == "Dev" else "Idle",
            "responses": 445,
            "tasks_completed": 201,
            "current_task": "Optimizing parameters" if active_agent == "Dev" else "Waiting for tasks"
        },
        {
            "name": "Scribe",
            "status": "Logging" if active_agent == "Scribe" else "Idle",
            "responses": 198,
            "tasks_completed": 89,
            "current_task": "Recording results" if active_agent == "Scribe" else "Waiting for tasks"
        },
        {
            "name": "Reach",
            "status": "Analyzing" if active_agent == "Reach" else "Idle",
            "responses": 156,
            "tasks_completed": 72,
            "current_task": "External analysis" if active_agent == "Reach" else "Waiting for tasks"
        }
    ]

    return {
        "agents": agents,
        "pipeline_state": pipeline_state,
        "active_agent": active_agent
    }
