"""AI suggestions endpoints for Auto-Quant."""

import asyncio

from fastapi import APIRouter, HTTPException

from ....services.auto_quant import pipeline as _pl
from ....services.auto_quant.ai_suggestions import (
    ai_assistance_summary,
    approve_suggestion,
    get_suggestion,
    normalize_ai_suggestions,
    optimization_stage_index,
    reject_suggestion,
    validate_proposed_changes,
)
from ....services.auto_quant.ollama_service import explain_autoquant_failure, explain_autoquant_stage

from .schemas import AISuggestionDecisionResponse, ExplainStageRequest, ExplainFailureRequest


def register_ai_suggestions_endpoints(router: APIRouter) -> None:
    """Register AI suggestions endpoints on the given router."""
    
    @router.get(
        "/{run_id}/ai-suggestions",
        summary="List AutoQuant AI suggestions for a run",
    )
    async def list_ai_suggestions(run_id: str) -> dict:
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        state.ai_suggestions = normalize_ai_suggestions(getattr(state, "ai_suggestions", []))
        return {
            "run_id": run_id,
            "pending_ai_suggestion_id": getattr(state, "pending_ai_suggestion_id", None),
            "suggestions": state.ai_suggestions,
            "manual_next_actions": ai_assistance_summary(state).get("manual_next_actions", []),
        }

    @router.post(
        "/{run_id}/ai-suggestions/{suggestion_id}/approve",
        response_model=AISuggestionDecisionResponse,
        summary="Approve an AutoQuant AI suggestion and retry",
    )
    async def approve_ai_suggestion(run_id: str, suggestion_id: str) -> AISuggestionDecisionResponse:
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        if get_suggestion(state, suggestion_id) is None:
            raise HTTPException(status_code=404, detail=f"AI suggestion '{suggestion_id}' not found.")
        try:
            validate_proposed_changes(get_suggestion(state, suggestion_id).get("proposed_changes"))
            suggestion = approve_suggestion(state, suggestion_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        _pl._save_state_to_disk(state)
        asyncio.create_task(_pl.run_pipeline(run_id))
        return AISuggestionDecisionResponse(
            run_id=run_id,
            status=state.status,
            suggestion=suggestion,
            message="AI suggestion approved. AutoQuant retry has been scheduled.",
        )

    @router.post(
        "/{run_id}/ai-suggestions/{suggestion_id}/reject",
        response_model=AISuggestionDecisionResponse,
        summary="Reject an AutoQuant AI suggestion",
    )
    async def reject_ai_suggestion(run_id: str, suggestion_id: str) -> AISuggestionDecisionResponse:
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        if get_suggestion(state, suggestion_id) is None:
            raise HTTPException(status_code=404, detail=f"AI suggestion '{suggestion_id}' not found.")
        try:
            suggestion = reject_suggestion(state, suggestion_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        _pl._save_state_to_disk(state)
        return AISuggestionDecisionResponse(
            run_id=run_id,
            status=state.status,
            suggestion=suggestion,
            message="AI suggestion rejected. Review the manual next actions before continuing.",
        )

    @router.post(
        "/{run_id}/ai/explain-stage",
        summary="Explain an AutoQuant stage",
    )
    async def explain_stage(run_id: str, body: ExplainStageRequest) -> dict:
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        return await explain_autoquant_stage(state, stage_index=body.stage_index, stage_name=body.stage_name)

    @router.post(
        "/{run_id}/ai/explain-failure",
        summary="Explain an AutoQuant failure",
    )
    async def explain_failure(run_id: str, body: ExplainFailureRequest) -> dict:
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        return await explain_autoquant_failure(state, body.failure_context or {})
