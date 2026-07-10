"""Results list API helper services."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ...models import ParsedSummary


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def duration_ms(created_at, completed_at) -> float | None:
    if not completed_at or not created_at:
        return None
    try:
        if isinstance(completed_at, str):
            completed = datetime.fromisoformat(completed_at)
        else:
            completed = completed_at
        if isinstance(created_at, str):
            created = datetime.fromisoformat(created_at)
        else:
            created = created_at
        return (completed - created).total_seconds() * 1000
    except Exception:
        return None


def created_at_text(created_at) -> str:
    if hasattr(created_at, "isoformat"):
        return created_at.isoformat()
    return str(created_at)


def result_item_payload(metadata, run_dir: Path) -> dict[str, Any]:
    summary_raw = read_json(run_dir / "parsed_summary.json")
    summary = ParsedSummary.model_validate(summary_raw) if summary_raw else None

    return {
        "run_id": metadata.run_id,
        "strategy_name": metadata.strategy_name,
        "timerange": metadata.timerange,
        "timeframe": metadata.timeframe,
        "created_at": created_at_text(metadata.created_at),
        "duration_ms": duration_ms(metadata.created_at, metadata.completed_at),
        "parsed_summary": summary,
    }
