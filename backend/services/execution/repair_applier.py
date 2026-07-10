"""Repair Proposal Applier — applies a validated AI repair proposal to a copy of StrategySpec."""

from __future__ import annotations

import logging
from typing import Any

from backend.models.strategy_spec import StrategySpec, validate_spec

logger = logging.getLogger(__name__)

ACTIONABLE_SCOPES = frozenset({
    "stoploss",
    "entry_logic",
    "exit_logic",
    "entry_parameter",
    "roi",
    "position_sizing",
})

_POSITION_SIZING_FIELDS = {
    "method",
    "atr_multiplier",
    "risk_per_trade_pct",
}


def apply_repair_proposal(
    spec: StrategySpec,
    proposal: dict,
) -> tuple[StrategySpec | None, list[str]]:
    """Apply a validated AI repair proposal to a deep copy of StrategySpec.

    Parameters
    ----------
    spec : StrategySpec
        The original spec (not mutated).
    proposal : dict
        Repair proposal dict with keys repair_scope, change, reasoning.

    Returns
    -------
    tuple[StrategySpec | None, list[str]]
        (new_spec, []) on success, (None, errors) on failure.
    """
    if not isinstance(proposal, dict):
        return None, ["proposal must be a dict"]

    scope = proposal.get("repair_scope")
    if not isinstance(scope, str):
        return None, ["repair_scope must be a string"]

    if scope not in ACTIONABLE_SCOPES:
        return None, [f"non-actionable scope: {scope}"]

    change = proposal.get("change")
    if not isinstance(change, dict) or not change:
        return None, ["change must be a non-empty dict"]

    err = _validate_change_fields(scope, change, spec)
    if err:
        return None, [err]

    copy = spec.model_copy(deep=True)

    apply_err = _apply_change(scope, change, copy)
    if apply_err:
        return None, [apply_err]

    copy.iteration_count = spec.iteration_count + 1
    copy.parent_spec_hash = spec.spec_hash()

    errors = validate_spec(copy)
    if errors:
        return None, errors

    return copy, []


def _validate_change_fields(scope: str, change: dict, spec: StrategySpec) -> str | None:
    if scope == "stoploss":
        if "stoploss" not in change:
            return "stoploss change must include 'stoploss' key"

    elif scope in ("entry_logic", "exit_logic"):
        if "index" not in change:
            return "change must include 'index'"
        if "field" not in change:
            return "change must include 'field'"
        if "new_value" not in change:
            return "change must include 'new_value'"
        idx = change["index"]
        conditions = spec.entry_conditions if scope == "entry_logic" else spec.exit_conditions
        if not isinstance(idx, int) or idx < 0 or idx >= len(conditions):
            return f"index {idx} out of bounds for {len(conditions)} conditions"

    elif scope == "entry_parameter":
        if "indicator" not in change:
            return "change must include 'indicator'"
        if "parameter" not in change:
            return "change must include 'parameter'"
        if "new_value" not in change:
            return "change must include 'new_value'"
        ind_name = change["indicator"]
        if not any(ind.name == ind_name for ind in spec.indicators):
            return f"indicator '{ind_name}' not found in spec"

    elif scope == "roi":
        if "action" not in change:
            return "change must include 'action'"
        if "index" not in change:
            return "change must include 'index'"
        idx = change["index"]
        action = change["action"]
        if action not in ("add", "remove", "modify"):
            return f"unknown roi action: {action}"
        if action == "add":
            if not isinstance(idx, int) or idx < 0 or idx > len(spec.roi):
                return f"index {idx} out of bounds for roi add"
            if "minutes" not in change:
                return "add action must include 'minutes'"
            if "ratio" not in change:
                return "add action must include 'ratio'"
        elif action == "remove":
            if not isinstance(idx, int) or idx < 0 or idx >= len(spec.roi):
                return f"index {idx} out of bounds for roi remove"
        elif action == "modify":
            if not isinstance(idx, int) or idx < 0 or idx >= len(spec.roi):
                return f"index {idx} out of bounds for roi modify"
            if "minutes" not in change:
                return "modify action must include 'minutes'"
            if "ratio" not in change:
                return "modify action must include 'ratio'"

    elif scope == "position_sizing":
        if "field" not in change:
            return "change must include 'field'"
        if "new_value" not in change:
            return "change must include 'new_value'"

    return None


def _apply_change(scope: str, change: dict, copy: StrategySpec) -> str | None:
    if scope == "stoploss":
        copy.stoploss = change["stoploss"]

    elif scope == "entry_logic":
        idx = change["index"]
        field = change["field"]
        setattr(copy.entry_conditions[idx], field, change["new_value"])

    elif scope == "exit_logic":
        idx = change["index"]
        field = change["field"]
        setattr(copy.exit_conditions[idx], field, change["new_value"])

    elif scope == "entry_parameter":
        ind_name = change["indicator"]
        param = change["parameter"]
        new_val = change["new_value"]
        for ind in copy.indicators:
            if ind.name == ind_name:
                ind.params[param] = new_val
                break

    elif scope == "roi":
        action = change["action"]
        idx = change["index"]
        if action == "add":
            copy.roi.insert(idx, (change["minutes"], change["ratio"]))
        elif action == "remove":
            copy.roi.pop(idx)
        elif action == "modify":
            copy.roi[idx] = (change["minutes"], change["ratio"])

    elif scope == "position_sizing":
        field = change["field"]
        new_val = change["new_value"]
        if field == "max_open_trades":
            copy.max_open_trades = new_val
        elif field in _POSITION_SIZING_FIELDS:
            setattr(copy.position_sizing, field, new_val)
        else:
            return f"unknown position_sizing field: {field}"

    return None
