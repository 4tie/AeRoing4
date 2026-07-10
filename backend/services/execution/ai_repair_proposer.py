"""AI Repair Proposer — asks AI for a constrained, single-change repair proposal."""

from __future__ import annotations

import json
import logging
from typing import Any

from .repair_plan_gate import RepairPlan, RepairScope
from ..auto_quant.ollama_service import clean_json_response

logger = logging.getLogger(__name__)

_PERFORMANCE_CLAIMS = [
    "profitable",
    "guaranteed",
    "will pass",
    "will improve returns",
]

_SCOPE_PROMPT_INFO: dict[str, dict[str, str]] = {
    "stoploss": {
        "description": "Change the stoploss float value (must be between -0.50 and -0.01).",
        "example": '{\n  "repair_scope": "stoploss",\n  "change": {"stoploss": -0.12},\n  "reasoning": "Brief reason under 200 chars."\n}',
    },
    "entry_logic": {
        "description": "Change one field of one entry condition: index (int), field (str: operator|value_or_indicator_b), new_value.",
        "example": '{\n  "repair_scope": "entry_logic",\n  "change": {"index": 0, "field": "operator", "new_value": "crosses_above"},\n  "reasoning": "Brief reason under 200 chars."\n}',
    },
    "exit_logic": {
        "description": "Change one field of one exit condition: index (int), field (str), new_value.",
        "example": '{\n  "repair_scope": "exit_logic",\n  "change": {"index": 0, "field": "value_or_indicator_b", "new_value": 70},\n  "reasoning": "Brief reason under 200 chars."\n}',
    },
    "entry_parameter": {
        "description": "Change one indicator parameter: indicator (str), parameter (str), new_value (int|float).",
        "example": '{\n  "repair_scope": "entry_parameter",\n  "change": {"indicator": "rsi", "parameter": "period", "new_value": 10},\n  "reasoning": "Brief reason under 200 chars."\n}',
    },
    "roi": {
        "description": "Add, remove, or modify one ROI table entry: action (str), index (int), minutes (int), ratio (float).",
        "example": '{\n  "repair_scope": "roi",\n  "change": {"action": "modify", "index": 1, "minutes": 60, "ratio": 0.05},\n  "reasoning": "Brief reason under 200 chars."\n}',
    },
    "position_sizing": {
        "description": "Change one position sizing field: field (str), new_value (int|float).",
        "example": '{\n  "repair_scope": "position_sizing",\n  "change": {"field": "max_open_trades", "new_value": 5},\n  "reasoning": "Brief reason under 200 chars."\n}',
    },
}


def _build_system_prompt(scope: RepairScope) -> str:
    info = _SCOPE_PROMPT_INFO.get(scope)
    if not info:
        return "You are a repair proposal assistant. Respond with JSON only."

    return (
        "You are a trading strategy repair assistant. You propose exactly ONE repair change.\n\n"
        f"Allowed scope: {scope}\n"
        f"{info['description']}\n\n"
        "Respond ONLY with valid JSON in this exact format:\n"
        f"{info['example']}\n\n"
        "Rules:\n"
        f'- "repair_scope" must be exactly "{scope}".\n'
        '- "change" must represent exactly one repair operation (a single dict, not a list).\n'
        '- "reasoning" must be at most 200 characters.\n'
        "- Do NOT claim the change will be profitable, guaranteed, or improve returns.\n"
        "- Do NOT include Python code or backtest results.\n"
        "Respond with JSON only."
    )


def _build_user_prompt(
    scope: RepairScope,
    spec: Any,
    classification: Any,
) -> str:
    lines = ["Current strategy spec:"]
    lines.append(f"- stoploss: {getattr(spec, 'stoploss', 'N/A')}")
    lines.append(f"- roi: {getattr(spec, 'roi', [])}")
    lines.append(f"- max_open_trades: {getattr(spec, 'max_open_trades', 'N/A')}")
    lines.append(f"- entry_conditions count: {len(getattr(spec, 'entry_conditions', []))}")
    lines.append(f"- exit_conditions count: {len(getattr(spec, 'exit_conditions', []))}")
    lines.append(f"- iteration_count: {getattr(spec, 'iteration_count', 0)}")
    lines.append(f"- max_iterations: {getattr(spec, 'max_iterations', 3)}")

    indicators = getattr(spec, 'indicators', [])
    for ind in indicators:
        lines.append(f"- indicator {ind.name}: {dict(ind.params)}")

    if hasattr(spec, 'trailing') and spec.trailing:
        lines.append(f"- trailing_stop: {spec.trailing.trailing_stop}")

    if hasattr(spec, 'position_sizing') and spec.position_sizing:
        lines.append(f"- position_sizing method: {spec.position_sizing.method}")

    lines.append("")
    lines.append("Failure context:")
    lines.append(f"- primary_class: {classification.primary_class}")
    lines.append(f"- failed_metrics: {classification.failed_metrics}")
    lines.append(f"- next_route: {classification.next_route}")

    return "\n".join(lines)


def _validate_proposal(proposal: dict, plan: RepairPlan) -> tuple[bool, str]:
    scope = proposal.get("repair_scope")
    if scope != plan.scope:
        return False, f"scope mismatch: got '{scope}', expected '{plan.scope}'"

    change = proposal.get("change")
    if not isinstance(change, dict):
        return False, f"change must be a dict, got {type(change).__name__}"
    if len(change) == 0:
        return False, "change dict must not be empty"

    reasoning = proposal.get("reasoning", "")
    if not isinstance(reasoning, str):
        return False, "reasoning must be a string"
    if len(reasoning) > 200:
        return False, f"reasoning too long: {len(reasoning)} chars (max 200)"

    text_lower = reasoning.lower()
    for claim in _PERFORMANCE_CLAIMS:
        if claim in text_lower:
            return False, f"performance claim detected: '{claim}'"

    if "python" in text_lower and ("import" in reasoning or "def " in reasoning):
        return False, "Python code detected in reasoning"

    valid, msg = _validate_scope_ranges(scope, change)
    if not valid:
        return False, msg

    return True, ""


def _validate_scope_ranges(scope: str, change: dict) -> tuple[bool, str]:
    if scope == "stoploss":
        val = change.get("stoploss")
        if val is None or not isinstance(val, (int, float)):
            return False, "stoploss change must include a numeric 'stoploss' key"
        if not (-0.50 <= val <= -0.01):
            return False, f"stoploss {val} out of range [-0.50, -0.01]"

    elif scope == "entry_parameter":
        param = change.get("parameter", "")
        val = change.get("new_value")
        if val is None:
            return False, "entry_parameter change must include 'new_value'"
        if param == "period":
            if not isinstance(val, int) or val < 2 or val > 200:
                return False, f"period {val} out of range [2, 200]"
        else:
            if isinstance(val, (int, float)):
                if val < 0 or val > 100:
                    return False, f"threshold value {val} out of range [0, 100]"

    elif scope == "roi":
        minutes = change.get("minutes")
        ratio = change.get("ratio")
        if minutes is not None and (not isinstance(minutes, int) or minutes < 0):
            return False, f"roi minutes {minutes} must be int >= 0"
        if ratio is not None and (not isinstance(ratio, (int, float)) or ratio < 0):
            return False, f"roi ratio {ratio} must be >= 0"

    elif scope == "position_sizing":
        field = change.get("field", "")
        val = change.get("new_value")
        if val is None:
            return False, "position_sizing change must include 'new_value'"
        if field == "max_open_trades":
            if not isinstance(val, int) or val < 1 or val > 50:
                return False, f"max_open_trades {val} out of range [1, 50]"

    return True, ""


async def ask_ai_for_repair_proposal(
    client: Any,
    repair_plan: RepairPlan,
    spec: Any,
    classification: Any,
) -> dict[str, Any] | None:
    """Ask AI to propose exactly one repair change constrained by RepairPlan scope.

    Parameters
    ----------
    client : OllamaClient
        Injected OllamaClient instance (already configured).
    repair_plan : RepairPlan
        Output of build_repair_plan() — defines scope and permissions.
    spec : StrategySpec
        Current strategy spec — provides serialized context for the prompt.
    classification : FailureClassification
        Failure context from analyze_gate_failure().

    Returns
    -------
    dict | None
        Proposal dict with keys repair_scope, change, reasoning.
        None if AI is unavailable, response is unparseable, or validation fails.
    """
    if not repair_plan.can_repair:
        logger.info("repair_plan.can_repair is False — skipping AI call.")
        return None

    scope = repair_plan.scope
    system_prompt = _build_system_prompt(scope)
    user_prompt = _build_user_prompt(scope, spec, classification)

    raw = await client.generate(
        user_prompt,
        system_prompt=system_prompt,
        feature="repair_proposal",
    )

    if not raw:
        logger.warning("AI returned empty response for repair proposal.")
        return None

    cleaned = clean_json_response(raw)

    try:
        proposal = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse AI proposal JSON: {e}")
        return None

    if not isinstance(proposal, dict):
        logger.warning("AI proposal is not a dict.")
        return None

    valid, msg = _validate_proposal(proposal, repair_plan)
    if not valid:
        logger.warning(f"AI proposal validation failed: {msg}")
        return None

    return proposal
