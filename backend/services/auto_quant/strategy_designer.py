"""Strategy Designer helper for AI-proposed StrategySpec JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ...models.strategy_spec import StrategySpec, validate_spec
from .ollama_service import clean_json_response


_PROMPT_PATH = Path(__file__).parent / "prompts" / "strategy_designer.md"
_SIMPLE_PROMPT_PATH = Path(__file__).parent / "prompts" / "strategy_designer_simple.md"

# Indicator set templates
_INDICATOR_SET_TEMPLATES = {
    "rsi_only": [{"name": "rsi", "params": {"period": 14}}],
    "rsi_ema": [
        {"name": "rsi", "params": {"period": 14}},
        {"name": "ema_cross", "params": {"fast_period": 12, "slow_period": 26}}
    ],
    "rsi_ema_atr": [
        {"name": "rsi", "params": {"period": 14}},
        {"name": "ema_cross", "params": {"fast_period": 12, "slow_period": 26}},
        {"name": "atr", "params": {"period": 14}}
    ],
    "macd_bb": [
        {"name": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}},
        {"name": "bbands", "params": {"period": 20, "std_dev": 2}}
    ],
    "multi_indicator": [
        {"name": "rsi", "params": {"period": 14}},
        {"name": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}},
        {"name": "bbands", "params": {"period": 20, "std_dev": 2}},
        {"name": "atr", "params": {"period": 14}}
    ],
}

# Condition templates by family
_FAMILY_CONDITION_TEMPLATES = {
    "momentum": {
        "entry": [
            {"type": "indicator_cross", "indicator_a": "ema_cross", "operator": "crosses_above", "value_or_indicator_b": 0}
        ],
        "exit": [
            {"type": "indicator_threshold", "indicator_a": "rsi", "operator": ">", "value_or_indicator_b": 70}
        ]
    },
    "trend_following": {
        "entry": [
            {"type": "indicator_cross", "indicator_a": "ema_cross", "operator": "crosses_above", "value_or_indicator_b": 0}
        ],
        "exit": [
            {"type": "indicator_cross", "indicator_a": "ema_cross", "operator": "crosses_below", "value_or_indicator_b": 0}
        ]
    },
    "mean_reversion": {
        "entry": [
            {"type": "indicator_threshold", "indicator_a": "rsi", "operator": "<", "value_or_indicator_b": 30}
        ],
        "exit": [
            {"type": "indicator_threshold", "indicator_a": "rsi", "operator": ">", "value_or_indicator_b": 70}
        ]
    },
    "breakout": {
        "entry": [
            {"type": "indicator_threshold", "indicator_a": "bbands", "operator": "<", "value_or_indicator_b": 2}
        ],
        "exit": [
            {"type": "indicator_threshold", "indicator_a": "bbands", "operator": ">", "value_or_indicator_b": -2}
        ]
    },
    "adaptive": {
        "entry": [
            {"type": "indicator_threshold", "indicator_a": "atr", "operator": ">", "value_or_indicator_b": 0.02}
        ],
        "exit": [
            {"type": "indicator_threshold", "indicator_a": "atr", "operator": "<", "value_or_indicator_b": 0.01}
        ]
    },
    "ensemble": {
        "entry": [
            {"type": "indicator_cross", "indicator_a": "ema_cross", "operator": "crosses_above", "value_or_indicator_b": 0},
            {"type": "indicator_threshold", "indicator_a": "rsi", "operator": "<", "value_or_indicator_b": 70}
        ],
        "exit": [
            {"type": "indicator_threshold", "indicator_a": "rsi", "operator": ">", "value_or_indicator_b": 70}
        ]
    },
}

# Risk profile settings
_RISK_PROFILE_SETTINGS = {
    "conservative": {
        "stoploss": -0.05,
        "roi": [[0, 0.05], [30, 0.03], [60, 0.02]],
        "max_open_trades": 2,
    },
    "balanced": {
        "stoploss": -0.10,
        "roi": [[0, 0.12], [30, 0.08], [60, 0.05]],
        "max_open_trades": 3,
    },
    "aggressive": {
        "stoploss": -0.15,
        "roi": [[0, 0.20], [30, 0.15], [60, 0.10]],
        "max_open_trades": 5,
    },
}


async def generate_strategy_spec(
    client: Any,
    *,
    trading_style: str,
    timeframe: str,
    direction: str | None = None,
    risk_profile: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Generate and validate a StrategySpec using an existing Ollama client."""
    system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    user_prompt = _build_user_prompt(
        trading_style=trading_style,
        timeframe=timeframe,
        direction=direction,
        risk_profile=risk_profile,
        name=name,
        description=description,
    )

    raw_response = await client.generate(
        user_prompt,
        system_prompt=system_prompt,
        feature="strategy_designer",
        options={
            "num_predict": 1600,  # Increase output tokens for complete JSON
            "temperature": 0,      # Deterministic generation
        }
    )
    if not raw_response:
        return {"spec": None, "errors": ["EMPTY_OLLAMA_RESPONSE"], "raw_response": raw_response}

    cleaned = clean_json_response(raw_response)
    
    # Try to fix incomplete JSON by finding the last complete object
    if not cleaned.strip().endswith('}'):
        # Try to find the last complete JSON object by counting braces
        brace_count = 0
        last_complete_pos = -1
        for i, char in enumerate(cleaned):
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    last_complete_pos = i
        
        if last_complete_pos > 0:
            cleaned = cleaned[:last_complete_pos + 1]
    
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return {"spec": None, "errors": [f"INVALID_JSON: {e}"], "raw_response": raw_response}

    if not isinstance(payload, dict):
        return {"spec": None, "errors": ["INVALID_STRATEGY_SPEC_SCHEMA"], "raw_response": raw_response}

    # Post-process to fix common AI model errors
    payload = _fix_common_spec_errors(payload)

    try:
        spec = StrategySpec(**payload)
    except (ValidationError, TypeError, ValueError) as e:
        # Return detailed error for debugging
        error_msg = f"INVALID_STRATEGY_SPEC_SCHEMA: {str(e)}"
        if isinstance(e, ValidationError):
            error_msg = f"INVALID_STRATEGY_SPEC_SCHEMA: {e.errors()}"
        return {"spec": None, "errors": [error_msg], "raw_response": raw_response}

    errors = validate_spec(spec, strict_validation=True)
    if errors:
        return {"spec": None, "errors": errors, "raw_response": raw_response}

    return {"spec": spec, "errors": [], "raw_response": raw_response}


def _build_user_prompt(
    *,
    trading_style: str,
    timeframe: str,
    direction: str | None,
    risk_profile: str | None,
    name: str | None,
    description: str | None,
) -> str:
    lines = [
        "Create one StrategySpec JSON object from these user inputs:",
        f"- trading_style: {trading_style}",
        f"- timeframe: {timeframe}",
    ]
    if direction:
        lines.append(f"- direction: {direction}")
    if risk_profile:
        lines.append(f"- risk_profile: {risk_profile}")
    if name:
        lines.append(f"- requested_name: {name}")
    if description:
        lines.append(f"- requested_description: {description}")
    lines.append("Return JSON only.")
    return "\n".join(lines)


def _fix_common_spec_errors(payload: dict) -> dict:
    """Fix common errors made by AI models in StrategySpec generation.

    This post-processing step corrects:
    - Empty indicators array (adds default RSI indicator)
    - Empty entry_conditions array (adds default RSI threshold condition)
    - Empty exit_conditions array (adds default RSI threshold condition)
    - Invalid position_sizing.method (changes "balanced" to "fixed")
    - Missing required fields (adds sensible defaults)
    """
    # Fix empty indicators
    if not payload.get("indicators") or len(payload.get("indicators", [])) == 0:
        payload["indicators"] = [{"name": "rsi", "params": {"period": 14}}]

    # Fix empty entry_conditions
    if not payload.get("entry_conditions") or len(payload.get("entry_conditions", [])) == 0:
        payload["entry_conditions"] = [
            {"type": "indicator_threshold", "indicator_a": "rsi", "operator": "<", "value_or_indicator_b": 30.0}
        ]

    # Fix empty exit_conditions
    if not payload.get("exit_conditions") or len(payload.get("exit_conditions", [])) == 0:
        trailing = payload.get("trailing", {})
        if not trailing.get("trailing_stop", False):
            payload["exit_conditions"] = [
                {"type": "indicator_threshold", "indicator_a": "rsi", "operator": ">", "value_or_indicator_b": 70.0}
            ]

    # Fix invalid position_sizing.method
    if "position_sizing" in payload:
        if isinstance(payload["position_sizing"], dict):
            method = payload["position_sizing"].get("method", "fixed")
            if method not in ["fixed", "atr_percent", "risk_per_trade"]:
                payload["position_sizing"]["method"] = "fixed"
    else:
        payload["position_sizing"] = {"method": "fixed"}

    # Fix invalid stoploss (must be negative)
    if "stoploss" in payload:
        if payload["stoploss"] >= 0:
            payload["stoploss"] = -0.10

    # Fix empty ROI
    if not payload.get("roi") or len(payload.get("roi", [])) == 0:
        payload["roi"] = [[0, 0.12]]

    # Fix missing trailing object
    if "trailing" not in payload:
        payload["trailing"] = {"trailing_stop": False}

    # Fix missing max_open_trades
    if "max_open_trades" not in payload:
        payload["max_open_trades"] = 3

    # Fix missing max_iterations
    if "max_iterations" not in payload:
        payload["max_iterations"] = 3

    # Fix missing iteration_count
    if "iteration_count" not in payload:
        payload["iteration_count"] = 0

    # Fix missing parent_spec_hash
    if "parent_spec_hash" not in payload:
        payload["parent_spec_hash"] = ""

    return payload


def build_spec_from_decision(decision: dict, user_inputs: dict) -> StrategySpec:
    """Build complete StrategySpec from high-level AI decision and templates.

    Args:
        decision: Dict with keys: family, timeframe, indicator_set, risk_profile, direction
        user_inputs: Dict with user-provided inputs: trading_style, name, description

    Returns:
        StrategySpec object built from templates
    """
    family = decision.get("family", "momentum")
    timeframe = decision.get("timeframe", "5m")
    indicator_set = decision.get("indicator_set", "rsi_ema_atr")
    risk_profile = decision.get("risk_profile", "balanced")
    direction = decision.get("direction", "long")

    # Map user trading_style to valid StrategySpec trading_style
    user_trading_style = user_inputs.get("trading_style", "")
    trading_style_map = {
        "scalping": "momentum",
        "intraday": "momentum",
        "swing": "mean_reversion",
        "position": "trend_following",
    }
    # If user style maps to a valid style, use it; otherwise use AI's family choice
    trading_style = trading_style_map.get(user_trading_style, family)

    # Get indicators from template
    indicators = _INDICATOR_SET_TEMPLATES.get(indicator_set, _INDICATOR_SET_TEMPLATES["rsi_ema_atr"])

    # Get conditions from family template
    conditions = _FAMILY_CONDITION_TEMPLATES.get(family, _FAMILY_CONDITION_TEMPLATES["momentum"])
    entry_conditions = conditions["entry"]
    exit_conditions = conditions["exit"]

    # Get risk profile settings
    risk_settings = _RISK_PROFILE_SETTINGS.get(risk_profile, _RISK_PROFILE_SETTINGS["balanced"])
    stoploss = risk_settings["stoploss"]
    roi = risk_settings["roi"]
    max_open_trades = risk_settings["max_open_trades"]

    # Build spec
    spec_dict = {
        "name": user_inputs.get("name") or f"{family}_{indicator_set}_{timeframe}",
        "description": user_inputs.get("description") or f"{family} strategy using {indicator_set} indicators",
        "timeframe": timeframe,
        "trading_style": trading_style,
        "direction": direction,
        "indicators": indicators,
        "entry_conditions": entry_conditions,
        "exit_conditions": exit_conditions,
        "stoploss": stoploss,
        "trailing": {"trailing_stop": False},
        "position_sizing": {"method": "fixed"},
        "max_open_trades": max_open_trades,
        "roi": roi,
        "max_iterations": 3,
        "iteration_count": 0,
        "parent_spec_hash": "",
    }

    return StrategySpec(**spec_dict)


async def generate_strategy_spec_simple(
    client: Any,
    *,
    trading_style: str,
    timeframe: str,
    direction: str | None = None,
    risk_profile: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Generate StrategySpec using simplified decision-based approach.

    This function asks Hermes for high-level decisions only, then builds
    the complete StrategySpec from templates. This reduces the JSON size
    the AI needs to generate, making it more reliable for smaller models.

    Args:
        client: Ollama client instance
        trading_style: Trading style preference
        timeframe: Timeframe preference
        direction: Direction preference
        risk_profile: Risk profile preference
        name: Optional strategy name
        description: Optional strategy description

    Returns:
        Dict with keys: spec, errors, raw_response
    """
    system_prompt = _SIMPLE_PROMPT_PATH.read_text(encoding="utf-8")

    # Build user prompt with preferences
    lines = [
        "Choose strategy parameters based on these user preferences:",
        f"- trading_style: {trading_style}",
        f"- timeframe: {timeframe}",
    ]
    if direction:
        lines.append(f"- direction: {direction}")
    if risk_profile:
        lines.append(f"- risk_profile: {risk_profile}")
    lines.append("Return JSON only.")
    user_prompt = "\n".join(lines)

    # Call Hermes for high-level decision
    raw_response = await client.generate(
        user_prompt,
        system_prompt=system_prompt,
        feature="strategy_designer_simple",
        options={
            "num_predict": 200,   # Small JSON, don't need many tokens
            "temperature": 0,      # Deterministic
        }
    )

    if not raw_response:
        return {"spec": None, "errors": ["EMPTY_OLLAMA_RESPONSE"], "raw_response": raw_response}

    # Parse the decision JSON
    cleaned = clean_json_response(raw_response)
    try:
        decision = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return {"spec": None, "errors": [f"INVALID_DECISION_JSON: {e}"], "raw_response": raw_response}

    if not isinstance(decision, dict):
        return {"spec": None, "errors": ["INVALID_DECISION_SCHEMA"], "raw_response": raw_response}

    # Build complete spec from decision
    try:
        user_inputs = {
            "trading_style": trading_style,
            "timeframe": timeframe,
            "direction": direction,
            "risk_profile": risk_profile,
            "name": name,
            "description": description,
        }
        spec = build_spec_from_decision(decision, user_inputs)
    except (ValidationError, TypeError, ValueError) as e:
        error_msg = f"SPEC_BUILD_ERROR: {str(e)}"
        if isinstance(e, ValidationError):
            error_msg = f"SPEC_BUILD_ERROR: {e.errors()}"
        return {"spec": None, "errors": [error_msg], "raw_response": raw_response}

    # Validate the built spec
    errors = validate_spec(spec, strict_validation=True)
    if errors:
        return {"spec": None, "errors": errors, "raw_response": raw_response}

    return {"spec": spec, "errors": [], "raw_response": raw_response}
