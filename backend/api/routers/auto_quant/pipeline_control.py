"""Pipeline status and control endpoints for Auto-Quant."""

from fastapi import APIRouter, HTTPException

from ....services.auto_quant import pipeline as _pl
from ....services.auto_quant.api_service import (
    get_pipeline_status,
    request_pipeline_cancel,
    delete_pipeline_run,
)
from ....services.auto_quant.ai_suggestions import optimization_stage_index

from .schemas import ResumePipelineRequest


def register_pipeline_control_endpoints(router: APIRouter) -> None:
    """Register pipeline status and control endpoints on the given router."""
    
    @router.get(
        "/status/{run_id}",
        summary="Get current pipeline state",
    )
    async def get_status(run_id: str) -> dict:
        return get_pipeline_status(run_id)

    @router.post(
        "/cancel/{run_id}",
        summary="Request pipeline cancellation",
    )
    async def cancel_pipeline(run_id: str) -> dict:
        return request_pipeline_cancel(run_id)

    @router.post(
        "/resume/{run_id}",
        summary="Resume pipeline after user approval",
    )
    async def resume_pipeline(run_id: str, body: ResumePipelineRequest) -> dict:
        """Resume a paused pipeline with user-approved pairs."""
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        if state.status != "awaiting_user_approval":
            raise HTTPException(
                status_code=409,
                detail=f"Pipeline is not awaiting user approval (current status: {state.status})"
            )

        # Update state with approved pairs. Strip freqtrade's aggregate "TOTAL"
        # summary row here too (defense in depth) so it can never be forwarded
        # to freqtrade as a trading pair, even if the UI still shows a stale
        # pre-selection list from before the extraction fix.
        approved_pairs = [
            p for p in body.approved_pairs if p.strip().upper() != "TOTAL"
        ]
        state.user_approved_pairs = approved_pairs
        # Also populate selected_pairs directly to ensure pipeline can proceed
        state.selected_pairs = [{"key": pair} for pair in approved_pairs]
        # Advance current_stage to avoid getting stuck in resume logic
        if state.current_stage == 1:
            state.current_stage = 2
        elif state.current_stage == 2:
            # Stage 2 (Portfolio Baseline) approval - advance to optimization
            state.current_stage = optimization_stage_index()
            # Mark Stage 2 as passed since user approved the baseline
            if len(state.stages) > 1:
                state.stages[1].status = "passed"
        elif state.current_stage == optimization_stage_index():
            # Stage 3 (Standard Hyperopt) approval - advance to robustness
            state.current_stage = 4
            # Mark Stage 3 as passed since user approved the pairs
            stage_idx = optimization_stage_index()
            if 0 < stage_idx <= len(state.stages):
                state.stages[stage_idx - 1].status = "passed"
        state.status = "running"
        _pl._save_state_to_disk(state)

        # Resume the pipeline (this will trigger the next stage). Guarded
        # against double-launching if a resume request is duplicated or
        # races with an already-running orchestrator task for this run_id.
        task = _pl.launch_pipeline_task(run_id)
        if task is None:
            raise HTTPException(
                status_code=409,
                detail=f"Pipeline run '{run_id}' is already resuming/running.",
            )

        return {
            "run_id": run_id,
            "status": "running",
            "approved_pairs": body.approved_pairs,
            "message": f"Pipeline resumed with {len(body.approved_pairs)} approved pairs"
        }

    @router.delete(
        "/runs/{run_id}",
        summary="Delete a pipeline run",
    )
    async def delete_run(run_id: str, user_data_dir: str = None) -> dict:
        """Delete a pipeline run from memory and disk."""
        if not user_data_dir:
            # Default to user_data from config if not provided
            from ....config import settings
            user_data_dir = settings.USER_DATA_DIR
        return delete_pipeline_run(run_id, user_data_dir)
