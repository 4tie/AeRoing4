from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.models.strategy_spec import StrategySpec


def load_spec_registry(path: Path) -> dict:
    if not path.exists():
        return {"hashes": {}}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "hashes" in data:
            return data
        return {"hashes": {}}
    except (json.JSONDecodeError, OSError):
        return {"hashes": {}}


def save_spec_registry(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def is_duplicate_spec(spec: StrategySpec, registry: dict) -> bool:
    h = spec.spec_hash()
    return h in registry.get("hashes", {})


def record_spec(
    spec: StrategySpec,
    registry: dict,
    name: str | None = None,
) -> dict:
    h = spec.spec_hash()
    if "hashes" not in registry:
        registry["hashes"] = {}

    registry["hashes"][h] = {
        "hash": h,
        "name": name or spec.name,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    return registry
