"""Export and download helpers for Auto-Quant."""

import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ....services.auto_quant.variants import copy_to_output


def _safe_export_name(value: str | None) -> str:
    cleaned = "".join(
        ch if ch.isalnum() or ch in ("_", "-") else "_"
        for ch in (value or "strategy").strip()
    ).strip("_-")
    return cleaned or "strategy"


def _load_export_report(state: Any, run_dir: Path) -> dict[str, Any]:
    report = state.report
    if isinstance(report, dict):
        return report

    for report_path in (run_dir / "report_latest.json", run_dir / "report.json"):
        if report_path.exists():
            return json.loads(report_path.read_text(encoding="utf-8"))

    raise HTTPException(status_code=404, detail="Report not found for export.")


def _resolve_export_artifact(
    state: Any,
    run_dir: Path,
    file_value: str | None,
    label: str,
) -> Path:
    if not file_value:
        raise HTTPException(status_code=404, detail=f"Export artifact '{label}' is not listed in the report.")

    raw_path = Path(file_value)
    user_data_dir = Path(state.user_data_dir)
    candidates: list[Path] = []

    if raw_path.is_absolute():
        try:
            raw_path.resolve().relative_to(user_data_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid export artifact path for '{label}'.")
        candidates.append(raw_path)
    else:
        if ".." in raw_path.parts:
            raise HTTPException(status_code=400, detail=f"Invalid export artifact path for '{label}'.")
        candidates.append(run_dir / raw_path)
        if raw_path.suffix == ".py":
            candidates.append(run_dir / "strategies" / raw_path.name)
            candidates.append(user_data_dir / "strategies" / raw_path.name)

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    raise HTTPException(status_code=404, detail=f"Export artifact '{label}' not found: {file_value}")


def _optional_export_artifact(state: Any, run_dir: Path, file_value: str | None, label: str) -> Path | None:
    if not file_value:
        return None
    try:
        return _resolve_export_artifact(state, run_dir, file_value, label)
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise


def _optional_state_snapshot(state: Any, run_dir: Path, report: dict[str, Any]) -> Path | None:
    artifact_versions = {}
    if isinstance(getattr(state, "artifact_versions", None), dict):
        artifact_versions.update(state.artifact_versions)
    if isinstance(report.get("artifact_versions"), dict):
        artifact_versions.update(report["artifact_versions"])

    names = [
        artifact_versions.get("state_latest"),
        artifact_versions.get("state_v1"),
        artifact_versions.get("state"),
        "state_latest.json",
        "state.json",
    ]
    for name in names:
        if not name:
            continue
        candidate = run_dir / Path(name).name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def create_export_bundle(state: Any, run_id: str) -> tuple[Path, str]:
    """Create a Freqtrade-ready deployment bundle for a completed run.
    
    Returns:
        Tuple of (zip_path, zip_filename)
    """
    run_dir = Path(state.user_data_dir) / "auto_quant" / run_id
    report = _load_export_report(state, run_dir)
    files = report.get("files")
    if not isinstance(files, dict):
        raise HTTPException(status_code=404, detail="Report does not list export files.")

    optimized_path = _resolve_export_artifact(state, run_dir, files.get("optimized_strategy"), "optimized_strategy")
    config_path = _resolve_export_artifact(state, run_dir, files.get("config"), "config")
    report_path = _resolve_export_artifact(state, run_dir, files.get("report"), "report")

    artifacts: list[tuple[Path, str]] = [
        (optimized_path, optimized_path.name),
        (config_path, "config.json"),
        (report_path, "report.json"),
    ]
    seen_names = {name for _, name in artifacts}

    params_path = None
    if files.get("params_json"):
        params_path = _resolve_export_artifact(state, run_dir, files.get("params_json"), "params_json")
    else:
        inferred_params = optimized_path.with_suffix(".json")
        if inferred_params.exists() and inferred_params.is_file():
            params_path = inferred_params
        else:
            params_path = _optional_export_artifact(
                state,
                run_dir,
                f"{optimized_path.stem}.json",
                "params_json",
            )
    if params_path and params_path.name not in seen_names:
        artifacts.append((params_path, params_path.name))
        seen_names.add(params_path.name)

    state_path = _optional_state_snapshot(state, run_dir, report)
    if state_path and state_path.name not in seen_names:
        artifacts.append((state_path, state_path.name))

    strategy_name = _safe_export_name(report.get("strategy") or state.strategy or optimized_path.stem)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_name = f"{strategy_name}_{timestamp}"
    exports_root = Path(state.user_data_dir) / "exports"
    export_dir = exports_root / bundle_name
    export_dir.mkdir(parents=True, exist_ok=True)

    copied_paths = [copy_to_output(path, export_dir, filename) for path, filename in artifacts]

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for copied_path in copied_paths:
            bundle.write(copied_path, arcname=copied_path.name)

    zip_filename = f"{bundle_name}.zip"
    zip_path = exports_root / zip_filename
    zip_path.write_bytes(zip_buffer.getvalue())

    return zip_path, zip_filename
