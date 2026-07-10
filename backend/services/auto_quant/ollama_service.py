"""Ollama AI service for AutoQuant pipeline enhancements.

This module provides a robust, non-blocking Ollama client with graceful fallbacks,
JSON response cleaning, and data pre-processing functions for AI-powered enhancements.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..ai.ollama_client import CircuitBreaker
from .assistant_prompt import AUTOQUANT_COPILOT_SYSTEM_PROMPT, build_autoquant_prompt_messages
from .ollama_client import create_ollama_client_from_settings, create_strategy_lab_client
from .ollama_data_processing import clean_json_response, summarize_failure_metrics
from .ollama_helpers import _fallback_explanation, _state_agent_context
from .ollama_sensitivity_fix import ask_ollama_for_sensitivity_fix, detect_strategy_type
from .ollama_validation import SAFE_RANGES, validate_ollama_suggestions
from .ollama_wfa_fix import ask_ollama_for_wfa_fix

logger = logging.getLogger(__name__)

# Global circuit breaker for ollama API calls
_ollama_circuit_breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=300)

# Re-export data processing functions for backward compatibility
from .ollama_data_processing import (
    summarize_hyperopt_trials,
    summarize_market_conditions,
    summarize_failure_metrics,
)

# Re-export validation constants and function for backward compatibility
__all__ = [
    "ask_ollama_for_sensitivity_fix",
    "ask_ollama_for_wfa_fix",
    "explain_autoquant_stage",
    "explain_autoquant_failure",
    "clean_json_response",
    "summarize_hyperopt_trials",
    "summarize_market_conditions",
    "summarize_failure_metrics",
    "validate_ollama_suggestions",
    "SAFE_RANGES",
    "detect_strategy_type",
    "create_ollama_client_from_settings",
    "create_strategy_lab_client",
]


async def explain_autoquant_stage(state: Any, stage_index: int | None = None, stage_name: str | None = None) -> dict[str, Any]:
    """Explain an AutoQuant stage using the shared AutoQuant copilot context."""
    target_stage = None
    for stage in getattr(state, "stages", []):
        if stage_index is not None and stage.index == stage_index:
            target_stage = stage
            break
        if stage_name and stage.name.casefold() == stage_name.casefold():
            target_stage = stage
            break
    if target_stage is None and getattr(state, "stages", None):
        current_stage = getattr(state, "current_stage", 1) or 1
        target_stage = state.stages[max(0, min(len(state.stages) - 1, current_stage - 1))]

    stage_payload = {
        "index": getattr(target_stage, "index", None),
        "name": getattr(target_stage, "name", None),
        "status": getattr(target_stage, "status", None),
        "message": getattr(target_stage, "message", None),
        "data": getattr(target_stage, "data", None),
    }
    user_message = (
        "Explain this AutoQuant stage using only backend context. "
        f"Stage: {json.dumps(stage_payload, default=str)}"
    )
    response = await _call_autoquant_copilot(state, user_message, feature="autoquant_explain_stage")
    if response:
        return {
            "source": "ollama",
            "title": f"{stage_payload.get('name') or 'Stage'} explanation",
            "explanation": response,
            "next_actions": [],
        }
    return _fallback_explanation("stage", state, stage_payload)


async def explain_autoquant_failure(state: Any, failure_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Explain an AutoQuant failure using the shared AutoQuant copilot context."""
    user_message = (
        "Explain this AutoQuant failure or paused review state. "
        "Include what failed, what backend evidence is available, why it matters, and safe next actions. "
        f"Failure context: {json.dumps(failure_context or {}, default=str)}"
    )
    response = await _call_autoquant_copilot(state, user_message, feature="autoquant_explain_failure")
    if response:
        return {
            "source": "ollama",
            "title": "AutoQuant failure explanation",
            "explanation": response,
            "next_actions": [],
        }
    return _fallback_explanation("failure", state, failure_context)


async def _call_autoquant_copilot(state: Any, user_message: str, *, feature: str) -> str | None:
    """Call the AutoQuant copilot with the given message."""
    client = create_strategy_lab_client(getattr(state, "user_data_dir", ""), strict_json=False)
    if client is None:
        return None
    try:
        if not _ollama_circuit_breaker.should_allow_call():
            return None
        if not await client.check_health():
            _ollama_circuit_breaker.record_failure()
            return None
        messages = build_autoquant_prompt_messages(
            user_message=user_message,
            agent_context=_state_agent_context(state),
            user_profile={
                "risk_profile": getattr(state, "risk_profile", None),
                "trading_style": getattr(state, "trading_style", None),
                "analysis_depth": getattr(state, "analysis_depth", None),
            },
        )
        system_prompt = messages[0]["content"] if messages else AUTOQUANT_COPILOT_SYSTEM_PROMPT
        prompt = "\n\n".join(f"{message['role']}: {message['content']}" for message in messages[1:])
        response = await client.generate(prompt, system_prompt=system_prompt, feature=feature)
        if response:
            _ollama_circuit_breaker.record_success()
            return response.strip()
        _ollama_circuit_breaker.record_failure()
        return None
    except Exception as exc:
        logger.warning("AutoQuant copilot explanation failed: %s", exc)
        _ollama_circuit_breaker.record_failure()
        return None
    finally:
        await client.close()
