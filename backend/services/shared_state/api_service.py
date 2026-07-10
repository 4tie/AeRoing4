"""Shared frontend state API helper services."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...utils import atomic_write_json, read_json


def state_file_path(root_dir: str | Path) -> Path:
    state_dir = Path(root_dir) / "data"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "frontend_shared_state.json"


def load_state(path: Path) -> dict[str, Any]:
    raw = read_json(path)
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    return {}


def update_state(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    state = load_state(path)
    state.update(payload)
    atomic_write_json(path, state)
    return state
