"""Combined StrategySpec design, validation, and dedup flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..auto_quant.strategy_designer import generate_strategy_spec
from .strategy_spec_registry import (
    is_duplicate_spec,
    load_spec_registry,
    record_spec,
    save_spec_registry,
)


_AI_ERROR_CODES = {
    "EMPTY_OLLAMA_RESPONSE",
    "INVALID_JSON",
    "INVALID_STRATEGY_SPEC_SCHEMA",
}


async def design_validate_register_spec(
    client: Any,
    registry_path: str | Path,
    *,
    trading_style: str,
    timeframe: str,
    direction: str | None = None,
    risk_profile: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Generate, validate, deduplicate, and record a StrategySpec."""
    designer_result = await generate_strategy_spec(
        client,
        trading_style=trading_style,
        timeframe=timeframe,
        direction=direction,
        risk_profile=risk_profile,
        name=name,
        description=description,
    )
    spec = designer_result.get("spec")
    errors = list(designer_result.get("errors") or [])
    raw_response = designer_result.get("raw_response")

    if errors or spec is None:
        status = "ai_error" if any(error in _AI_ERROR_CODES for error in errors) else "validation_error"
        return _result(
            status=status,
            spec=None,
            errors=errors,
            spec_hash=None,
            registry_entry=None,
            raw_response=raw_response,
        )

    registry_file = Path(registry_path)
    registry = load_spec_registry(registry_file)
    spec_hash = spec.spec_hash()
    registry_entry = registry.get("hashes", {}).get(spec_hash)

    if is_duplicate_spec(spec, registry):
        return _result(
            status="duplicate",
            spec=spec,
            errors=[],
            spec_hash=spec_hash,
            registry_entry=registry_entry,
            raw_response=raw_response,
        )

    record_spec(spec, registry, name=name or spec.name)
    registry_entry = registry["hashes"][spec_hash]
    save_spec_registry(registry_file, registry)

    return _result(
        status="ready",
        spec=spec,
        errors=[],
        spec_hash=spec_hash,
        registry_entry=registry_entry,
        raw_response=raw_response,
    )


def _result(
    *,
    status: str,
    spec: Any,
    errors: list[str],
    spec_hash: str | None,
    registry_entry: dict | None,
    raw_response: str | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "spec": spec,
        "errors": errors,
        "spec_hash": spec_hash,
        "registry_entry": registry_entry,
        "raw_response": raw_response,
    }
