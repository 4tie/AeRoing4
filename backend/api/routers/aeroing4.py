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
from ...services.aeroing4 import AeRoing4Run
from ...services.aeroing4.orchestrator import AeRoing4Orchestrator
from ...services.aeroing4.strategy_library import (
    build_candidate_flow_for_run,
    build_latest_candidate_flow,
    scan_strategy_library,
)
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

    # Milestone 7.5: Portfolio Baseline execution configuration
    exchange: str = "binance"
    trading_mode: str = "spot"
    max_open_trades: int = 4
    dry_run_wallet: float = 1000.0
    config_file: str = "config.json"

    # PROMPT 8: Controlled Research Loop (strict opt-in).
    enable_research_loop: bool = False

    # PROMPT 9: Focused Hyperopt + Sensitivity (strict opt-in, after KEEP champion).
    enable_focused_hyperopt: bool = False


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

    # Milestone 7.5: Portfolio Baseline execution configuration
    exchange: str
    trading_mode: str
    max_open_trades: int
    dry_run_wallet: float
    config_file: str

    # Diagnosis summary (latest diagnosis only)
    diagnosis: dict | None = None

    # PROMPT 8: Controlled Research Loop status (research_state.json).
    research_status: str | None = None
    current_iteration: int = 0
    pause_reason: str | None = None
    stop_reason: str | None = None
    last_decision_id: str | None = None
    current_champion_id: str | None = None
    current_hypothesis_id: str | None = None
    active_experiment_id: str | None = None
    budget_used: int = 0
    budget_remaining: int = 0

    # PROMPT 9: Focused Hyperopt + Sensitivity opt-in + Sensitivity progression gate.
    enable_focused_hyperopt: bool = False
    eligible_for_confirmation: bool | None = None
    last_sensitivity_status: str | None = None
    # PROMPT 10: Confirmation summary (source of truth is ConfirmationResult).
    confirmation_status: str | None = None
    latest_confirmation_result_id: str | None = None
    # PROMPT 11: Final Unseen summary (source of truth is FinalUnseenResult).
    final_unseen_status: str | None = None
    latest_final_unseen_result_id: str | None = None
    delivery_eligible: bool | None = None
    # PROMPT 12: Delivery summary (source of truth is DeliveryPackage manifest).
    delivery_status: str | None = None


class StartRunResponse(BaseModel):
    """Response model for starting a run."""
    run_id: str
    status: str
    message: str


def _run_to_response(run: AeRoing4Run, services) -> AeRoing4RunResponse:
    """Convert AeRoing4Run to API response."""
    # Get latest diagnosis summary if available
    diagnosis_summary = None
    diagnosis_step = run.steps.get("diagnosis")
    if diagnosis_step and diagnosis_step.status == "completed":
        diagnosis_data = diagnosis_step.data
        if diagnosis_data:
            diagnosis_summary = {
                "status": diagnosis_data.get("outcome"),
                "primary_code": diagnosis_data.get("primary_diagnosis", {}).get("diagnosis_code"),
                "severity": diagnosis_data.get("primary_diagnosis", {}).get("severity"),
                "confidence": diagnosis_data.get("primary_diagnosis", {}).get("confidence"),
                "evidence_quality": diagnosis_data.get("evidence_quality"),
            }

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
        enable_focused_hyperopt=getattr(run, "enable_focused_hyperopt", False),
        discovery_timerange=run.discovery_timerange,
        confirmation_timerange=run.confirmation_timerange,
        final_unseen_timerange=run.final_unseen_timerange,
        research_protocol_active=bool(
            run.confirmation_timerange and run.final_unseen_timerange
        ),
        exchange=run.exchange,
        trading_mode=run.trading_mode,
        max_open_trades=run.max_open_trades,
        dry_run_wallet=run.dry_run_wallet,
        config_file=run.config_file,
        diagnosis=diagnosis_summary,
    )

    # Populate Controlled Research Loop status from research_state.json when present.
    try:
        from ...services.aeroing4.research.research_state import ResearchStateStore

        rs_store = ResearchStateStore(services.aeroing4_orchestrator.state_store.runs_root)
        rs = rs_store.load(run.run_id)
        if rs is not None:
            resp.research_status = rs.research_status.value
            resp.current_iteration = rs.current_iteration
            resp.pause_reason = rs.pause_reason
            resp.stop_reason = rs.stop_reason
            resp.last_decision_id = rs.last_decision_id
            resp.current_champion_id = rs.current_champion_id
            resp.current_hypothesis_id = rs.current_hypothesis_id
            resp.active_experiment_id = rs.active_experiment_id
            resp.budget_used = rs.total_experiments_reserved
            resp.budget_remaining = max(0, rs.max_total_experiments - rs.total_experiments_reserved)
            resp.eligible_for_confirmation = rs.eligible_for_confirmation
            resp.last_sensitivity_status = rs.last_sensitivity_status
            resp.confirmation_status = rs.confirmation_status
            resp.latest_confirmation_result_id = rs.latest_confirmation_result_id
            resp.final_unseen_status = rs.final_unseen_status
            resp.latest_final_unseen_result_id = rs.latest_final_unseen_result_id
            resp.delivery_eligible = rs.delivery_eligible
            resp.delivery_status = rs.delivery_status
    except Exception:
        # Research loop not initialized for this run — leave defaults.
        pass

    return resp


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
            exchange=body.exchange,
            trading_mode=body.trading_mode,
            max_open_trades=body.max_open_trades,
            dry_run_wallet=body.dry_run_wallet,
            config_file=body.config_file,
            enable_research_loop=body.enable_research_loop,
            enable_focused_hyperopt=body.enable_focused_hyperopt,
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

    return _run_to_response(run, services)


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
    return [_run_to_response(run, services) for run in runs]


@router.get(
    "/strategy-library",
    summary="Scan official strategy source-of-truth files",
    description=(
        "Returns structured strategy source-of-truth metadata from the official "
        "user_data/strategies directory. Parsing and validation stay on the backend."
    ),
)
async def get_strategy_library(services=Depends(get_services)) -> dict:
    """Return strategy file/class/json/parameter visibility for the UI."""
    scan = scan_strategy_library(services.paths.strategies_dir)
    return scan.model_dump(mode="json")


@router.get(
    "/candidate-flow/latest",
    summary="Get the latest AutoQuant candidate source-of-truth flow",
    description=(
        "Returns the newest candidate artifact/execution flow found under "
        "user_data/aeroing4/runs. This endpoint is read-only."
    ),
)
async def get_latest_candidate_flow(services=Depends(get_services)) -> dict:
    """Return latest candidate flow metadata, if any exists."""
    response = build_latest_candidate_flow(
        runs_root=services.aeroing4_orchestrator.state_store.runs_root,
        run_repository=services.run_repository,
        strategies_dir=services.paths.strategies_dir,
    )
    return response.model_dump(mode="json")


@router.get(
    "/runs/{run_id}/candidate-flow",
    summary="Get AutoQuant candidate source-of-truth flow for a run",
    description=(
        "Returns candidate source paths, copied artifacts, Freqtrade command, "
        "output artifacts, metrics, decision, and step-level UI details."
    ),
)
async def get_run_candidate_flow(
    run_id: str,
    services=Depends(get_services),
) -> dict:
    """Return candidate flow metadata for one AeRoing4 run."""
    response = build_candidate_flow_for_run(
        run_id=run_id,
        runs_root=services.aeroing4_orchestrator.state_store.runs_root,
        run_repository=services.run_repository,
        strategies_dir=services.paths.strategies_dir,
    )
    return response.model_dump(mode="json")


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

        return _run_to_response(run, services)

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to cancel run: {str(exc)}")


@router.get(
    "/runs/{run_id}/diagnoses",
    summary="Get diagnosis history for a run",
    description=(
        "Returns the full diagnosis history for an AeRoing4 run. "
        "This endpoint provides detailed diagnosis results including all findings, "
        "evidence quality, and rule evaluation metadata. Multiple diagnoses may exist "
        "for a single run if the champion changes during the research process."
    ),
)
async def get_diagnoses(
    run_id: str,
    services=Depends(get_services),
) -> list[dict]:
    """Get diagnosis history for a run."""
    from ...services.aeroing4.diagnosis.persistence import DiagnosisStore

    orchestrator = services.aeroing4_orchestrator
    run = orchestrator.get_run(run_id)

    if not run:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    # Load diagnosis history
    store = DiagnosisStore(str(orchestrator.state_store.runs_root))
    diagnoses = store.list_by_run(run_id)

    return [d.model_dump(mode="json") for d in diagnoses]
