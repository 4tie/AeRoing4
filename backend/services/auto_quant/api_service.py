"""AutoQuant API-facing helpers.

This module keeps low-level persistence and pipeline facade operations out of
the FastAPI router while preserving the existing HTTP contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from . import pipeline as _pipeline
from .pipeline_modules.stage_runtime import (
    build_stage_cards,
    build_workflow_summary,
    derive_error_object,
)


def list_pipeline_runs() -> dict[str, list[dict[str, Any]]]:
    """Return the existing /api/auto-quant/runs response shape."""
    return {"runs": _pipeline.list_runs()}


def get_pipeline_status(run_id: str) -> dict[str, Any]:
    """Return a pipeline state snapshot or raise the existing 404 shape."""
    state = _pipeline.get_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
    snapshot = _pipeline._state_snapshot(state)
    snapshot["recent_events"] = _pipeline.get_event_history(run_id)
    snapshot["stage_cards"] = build_stage_cards(state)
    snapshot["workflow"] = build_workflow_summary(state)
    snapshot["error_object"] = derive_error_object(state)
    return snapshot


def request_pipeline_cancel(run_id: str) -> dict[str, str]:
    """Request cancellation while preserving the current response payload."""
    if not _pipeline.request_cancel(run_id):
        raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
    return {"run_id": run_id, "status": "cancellation_requested"}


def delete_pipeline_run(run_id: str, user_data_dir: str) -> dict[str, str]:
    """Delete a pipeline run from memory and disk."""
    if not _pipeline.delete_run(run_id, user_data_dir):
        raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
    return {"run_id": run_id, "status": "deleted"}


def load_options_data(user_data_dir: str | Path) -> dict[str, Any]:
    """Load persisted AutoQuant form options as a plain dict.

    The router owns Pydantic validation so this helper can stay independent of
    HTTP-layer models and avoid circular imports.
    """
    options_file = Path(user_data_dir).parent / "data" / "auto_quant_options.json"
    if not options_file.exists():
        return {}
    try:
        data = json.loads(options_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    if isinstance(data.get("pair_universe"), list):
        data["pair_universe"] = ",".join(str(pair) for pair in data["pair_universe"])
    return data


def save_options_data(user_data_dir: str | Path, data: dict[str, Any]) -> dict[str, str]:
    """Persist AutoQuant form options and return the existing success payload."""
    options_file = Path(user_data_dir).parent / "data" / "auto_quant_options.json"
    try:
        options_file.parent.mkdir(parents=True, exist_ok=True)
        options_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save options: {exc}")
    return {"status": "success", "message": "Options saved"}
