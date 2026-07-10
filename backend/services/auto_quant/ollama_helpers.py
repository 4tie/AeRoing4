"""Helper functions for Ollama AI service."""

from typing import Any


def _state_agent_context(state: Any) -> dict[str, Any]:
    """Extract agent context from pipeline state."""
    return {
        "active": {
            "auto_quant_run_id": getattr(state, "run_id", None),
            "strategy_name": getattr(state, "strategy", None),
        },
        "auto_quant": {
            "run_id": getattr(state, "run_id", None),
            "status": getattr(state, "status", None),
            "current_stage": getattr(state, "current_stage", None),
            "state": {
                "stages": [
                    {
                        "index": stage.index,
                        "name": stage.name,
                        "status": stage.status,
                        "message": stage.message,
                        "data": stage.data,
                    }
                    for stage in getattr(state, "stages", [])
                ],
                "run_config_snapshot": getattr(state, "run_config_snapshot", {}),
                "timeframe": getattr(state, "timeframe", None),
            },
            "metrics": {
                "validation_status": getattr(state, "validation_status", None),
                "readiness_label": getattr(state, "readiness_label", None),
                "score": getattr(state, "score", None),
                "score_explanation": getattr(state, "score_explanation", None),
            },
            "error": getattr(state, "error", None),
        },
        "strategy": {"strategy_name": getattr(state, "strategy", None)},
    }


def _fallback_explanation(kind: str, state: Any, target: Any = None) -> dict[str, Any]:
    """Generate fallback explanation when AI is unavailable."""
    stage = None
    if kind == "stage":
        stage = target if isinstance(target, dict) else {}
        title = f"{stage.get('name') or 'AutoQuant stage'} explanation"
        explanation = (
            f"{stage.get('name') or 'This stage'} is currently "
            f"{stage.get('status') or 'unknown'}. {stage.get('message') or 'No additional backend message is available.'}"
        )
    else:
        title = "AutoQuant failure explanation"
        explanation = (
            getattr(state, "error", None)
            or "AutoQuant has a failure or paused review state. Review the stage details and retry history before continuing."
        )
    return {
        "source": "deterministic",
        "title": title,
        "explanation": explanation,
        "next_actions": [
            "Review backend-provided stage metrics and logs.",
            "Approve a validated retry suggestion only if the proposed changes match your intent.",
            "Start a new run with manual settings if you reject the suggestion.",
        ],
    }
