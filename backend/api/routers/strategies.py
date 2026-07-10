"""Router: /api/strategies/*

  GET  /api/strategies          — list strategies (metadata)
  GET  /api/strategies/files    — list .py + .json pairings in strategies dir
  GET  /api/strategies/content  — return raw file content
  POST /api/strategies/save     — snapshot + overwrite file safely
  POST /api/strategies/validate — py_compile + freqtrade test-strategy
  GET  /api/strategies/history  — list timestamped snapshots for a strategy
  POST /api/strategies/rollback — restore a snapshot to the active files
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ...services.strategy.strategy_validation_service import extract_class_name, run_py_validate
from ..dependencies import get_services

router = APIRouter(prefix="/api/strategies", tags=["Strategies"])

# ── helpers ───────────────────────────────────────────────────────────────────

_ALLOWED_EXTS = {".py", ".json"}


def _strategies_dir(services) -> Path:
    settings = services.settings_store.load()
    return Path(settings.strategies_directory_path).resolve()


def _safe_path(strategies_dir: Path, filename: str) -> Path:
    """Resolve filename inside strategies_dir, blocking path traversal."""
    if "/" in filename or "\\" in filename or "\x00" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    p = (strategies_dir / filename).resolve()
    try:
        p.relative_to(strategies_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied.")
    if p.suffix not in _ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Only .py and .json files are allowed, got '{p.suffix}'.",
        )
    return p


# ── list strategies (existing) ────────────────────────────────────────────────


@router.get(
    "",
    summary="List all available strategies",
    description="Returns every strategy discovered in the strategies directory.",
)
async def list_strategies(services=Depends(get_services)) -> dict:
    records = services.registry.list_strategies()
    return {
        "strategies": [
            {
                "strategy_name": r.strategy_name,
                "class_name": r.class_name,
                "timeframe": r.timeframe,
                "parameter_count": r.parameter_count,
                "protection_count": r.protection_count,
                "managed_status": r.managed_status,
            }
            for r in records
        ],
    }


# ── file-system endpoints ─────────────────────────────────────────────────────


@router.get("/files", summary="List strategy files (.py + .json pairings)")
async def list_strategy_files(services=Depends(get_services)) -> dict:
    strategies_dir = _strategies_dir(services)
    if not strategies_dir.exists():
        return {"strategies": []}

    py_files   = {p.stem: p.name for p in strategies_dir.glob("*.py")}
    json_files = {p.stem: p.name for p in strategies_dir.glob("*.json")}
    all_stems  = sorted(set(py_files) | set(json_files))

    result = []
    for stem in all_stems:
        py_f   = py_files.get(stem)
        json_f = json_files.get(stem)
        if py_f:
            result.append(
                {"name": stem, "py_file": py_f, "json_file": json_f, "has_json": json_f is not None}
            )
    return {"strategies": result}


@router.get("/files/{strategy_name}", summary="Return both .py and .json content for a strategy")
async def get_strategy_files(strategy_name: str, services=Depends(get_services)) -> dict:
    strategies_dir = _strategies_dir(services)
    py_path   = strategies_dir / f"{strategy_name}.py"
    json_path = strategies_dir / f"{strategy_name}.json"
    if not py_path.exists():
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_name}' not found.")
    try:
        python_content = py_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not read '{py_path.name}': {exc}")
    json_content = ""
    if json_path.exists():
        try:
            json_content = json_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            json_content = ""
    return {
        "strategy_name": strategy_name,
        "python_path": py_path.name,
        "python_content": python_content,
        "json_path": json_path.name if json_path.exists() else None,
        "json_content": json_content,
        "json_exists": json_path.exists(),
    }


@router.get("/content", summary="Return raw file content")
async def get_file_content(
    filename: str = Query(..., description="Filename relative to strategies directory"),
    services=Depends(get_services),
) -> dict:
    strategies_dir = _strategies_dir(services)
    path = _safe_path(strategies_dir, filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found.")
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not read file '{filename}': {exc}")
    return {"filename": filename, "content": content}


class SaveRequest(BaseModel):
    filename: str = Field(..., description="Target filename (no path separators)")
    content:  str = Field(..., description="Full file content to write")


@router.post("/save", summary="Snapshot current file then overwrite it")
async def save_file(body: SaveRequest, services=Depends(get_services)) -> dict:
    strategies_dir = _strategies_dir(services)
    path           = _safe_path(strategies_dir, body.filename)

    # Create a backup of the CURRENT file(s) before we overwrite anything
    strategy_name = Path(body.filename).stem
    try:
        snap = services.snapshot_service.create_snapshot(
            strategy_name, strategies_dir, trigger="editor_save"
        )
    except Exception:
        snap = {"created": False, "timestamp": "", "files_backed_up": []}

    # Atomic write via temp file in same directory
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(body.content, encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Write failed: {exc}")

    return {
        "saved": True,
        "filename": body.filename,
        "snapshot": snap,
    }


class ValidateRequest(BaseModel):
    filename: str = Field(..., description="Strategy filename (e.g. MultiMa_v3.py)")
    content:  str = Field(..., description="Current editor content to validate")


@router.post("/validate", summary="Validate strategy syntax and Freqtrade structure")
async def validate_strategy(body: ValidateRequest, services=Depends(get_services)) -> dict:
    if not body.filename.endswith(".py"):
        import json as _json
        try:
            _json.loads(body.content)
            return {"valid": True, "errors": [], "warnings": [], "output": "✓ Valid JSON"}
        except Exception as exc:
            return {
                "valid": False,
                "errors": [str(exc)],
                "warnings": [],
                "output": f"JSON parse error: {exc}",
            }
    result = await asyncio.to_thread(run_py_validate, body, services)
    return result


# ── snapshot / version-history endpoints ─────────────────────────────────────


@router.get("/history", summary="List timestamped snapshots for a strategy")
async def get_history(
    strategy: str = Query(..., description="Strategy name (stem, no extension)"),
    services=Depends(get_services),
) -> dict:
    try:
        snaps = services.snapshot_service.list_snapshots(strategy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"strategy": strategy, "snapshots": snaps}


@router.get("/{strategy_name}/snapshots", summary="List snapshots for a strategy (path-param alias)")
async def get_snapshots_by_name(strategy_name: str, services=Depends(get_services)) -> dict:
    try:
        snaps = services.snapshot_service.list_snapshots(strategy_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"strategy": strategy_name, "snapshots": snaps}


class RollbackRequest(BaseModel):
    strategy_name: str = Field(..., description="Strategy stem name (e.g. MultiMa_v3)")
    timestamp:     str = Field(..., description="Snapshot timestamp (YYYYMMDD_HHMMSS)")


@router.post("/rollback", summary="Restore a snapshot to the active strategy files")
async def rollback_snapshot(body: RollbackRequest, services=Depends(get_services)) -> dict:
    strategies_dir = _strategies_dir(services)

    try:
        result = services.snapshot_service.restore_snapshot(
            body.strategy_name, body.timestamp, strategies_dir
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Restore failed: {exc}")

    # Return the freshly-restored file contents so the frontend can reload
    py_path   = strategies_dir / f"{body.strategy_name}.py"
    json_path = strategies_dir / f"{body.strategy_name}.json"

    return {
        "ok": True,
        "strategy_name": body.strategy_name,
        "timestamp": body.timestamp,
        "restored_files": result["restored_files"],
        "py_content":   py_path.read_text(encoding="utf-8")   if py_path.exists()   else None,
        "json_content": json_path.read_text(encoding="utf-8") if json_path.exists() else None,
    }

