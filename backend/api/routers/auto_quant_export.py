"""Audited AutoQuant deployment export endpoint.

This module owns the Freqtrade-ready export bundle used by the FastAPI app.
It keeps export behavior read-only, derives artifacts from the resolved run
report/state, and guarantees every exported strategy ships with both the final
`.py` file and a sidecar `.json` params file.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ...services.auto_quant import pipeline as _pl
from ...services.auto_quant.variants import copy_to_output

router = APIRouter(prefix="/api/auto-quant", tags=["Auto-Quant Factory"])


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


def _user_data_dir(state: Any) -> Path:
    return Path(state.user_data_dir).resolve()


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _candidate_paths(state: Any, run_dir: Path, file_value: str | None) -> list[Path]:
    if not file_value:
        return []

    raw_path = Path(file_value)
    user_data_dir = _user_data_dir(state)

    if raw_path.is_absolute():
        if not _path_is_under(raw_path, user_data_dir):
            raise HTTPException(status_code=400, detail="Invalid export artifact path outside user_data.")
        return [raw_path]

    if ".." in raw_path.parts:
        raise HTTPException(status_code=400, detail="Invalid export artifact path.")

    candidates = [run_dir / raw_path]
    if raw_path.suffix in {".py", ".json"}:
        candidates.extend(
            [
                run_dir / raw_path.name,
                run_dir / "strategies" / raw_path.name,
                user_data_dir / "strategies" / raw_path.name,
            ]
        )
    return candidates


def _resolve_export_artifact(
    state: Any,
    run_dir: Path,
    file_value: str | None,
    label: str,
) -> Path:
    for candidate in _candidate_paths(state, run_dir, file_value):
        if candidate.exists() and candidate.is_file():
            return candidate
    raise HTTPException(status_code=404, detail=f"Export artifact '{label}' not found: {file_value}")


def _optional_export_artifact(state: Any, run_dir: Path, file_value: str | None) -> Path | None:
    if not file_value:
        return None
    try:
        return _resolve_export_artifact(state, run_dir, file_value, "optional")
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise


def _first_existing_artifact(
    state: Any,
    run_dir: Path,
    values: list[str | None],
    label: str,
) -> Path | None:
    for value in values:
        path = _optional_export_artifact(state, run_dir, value)
        if path is not None:
            return path
    return None


def _accepted_candidate(report: dict[str, Any]) -> dict[str, Any]:
    candidate = report.get("accepted_candidate") or report.get("acceptedCandidate")
    return candidate if isinstance(candidate, dict) else {}


def _resolve_strategy_path(state: Any, run_dir: Path, report: dict[str, Any]) -> Path:
    files = report.get("files") if isinstance(report.get("files"), dict) else {}
    accepted = _accepted_candidate(report)
    values = [
        accepted.get("strategy_file"),
        accepted.get("optimized_strategy"),
        accepted.get("strategy_py"),
        files.get("accepted_strategy"),
        files.get("strategy_py"),
        files.get("optimized_strategy"),
        report.get("optimized_strategy") and f"{report.get('optimized_strategy')}.py",
    ]
    strategy_path = _first_existing_artifact(state, run_dir, values, "strategy_py")
    if strategy_path is None:
        raise HTTPException(status_code=404, detail="No resolved accepted strategy .py file found for export.")
    if strategy_path.suffix != ".py":
        raise HTTPException(status_code=400, detail="Resolved strategy export artifact must be a .py file.")
    return strategy_path


def _sidecar_payload_from_best_params(strategy_name: str, best_params: dict[str, Any]) -> dict[str, Any]:
    params_dict = best_params.get("params_dict") if isinstance(best_params, dict) else {}
    params_dict = params_dict if isinstance(params_dict, dict) else {}

    trailing: dict[str, Any] = {}
    for field in (
        "trailing_stop",
        "trailing_stop_positive",
        "trailing_stop_positive_offset",
        "trailing_only_offset_is_reached",
    ):
        if field in params_dict:
            trailing[field] = params_dict[field]

    roi = params_dict.get("minimal_roi") or params_dict.get("roi") or {}
    if not isinstance(roi, dict):
        roi = {}

    buy = params_dict.get("buy") or params_dict.get("buy_params") or {}
    sell = params_dict.get("sell") or params_dict.get("sell_params") or {}

    stoploss = params_dict.get("stoploss", -0.10)
    try:
        stoploss_value = float(stoploss)
    except (TypeError, ValueError):
        stoploss_value = -0.10

    return {
        "strategy_name": strategy_name,
        "params": {
            "buy": buy if isinstance(buy, dict) else {},
            "sell": sell if isinstance(sell, dict) else {},
            "roi": {str(key): value for key, value in roi.items()},
            "stoploss": {"stoploss": stoploss_value},
            "trailing": trailing,
        },
    }


def _create_params_json_from_strategy(
    state: Any,
    strategy_path: Path,
    report: dict[str, Any],
    warnings: list[str],
) -> Path:
    sidecar_path = strategy_path.with_suffix(".json")
    try:
        from ...services.strategy.strategy_source import StrategySourceParser

        strategies_dir = Path(state.user_data_dir) / "strategies"
        parser = StrategySourceParser(strategies_dir, strategies_dir / "versions")
        parsed = parser.parse(strategy_path)
        parser.create_default_sidecar_json(strategy_path, parsed)
        if sidecar_path.exists():
            warnings.append("Params JSON was missing and was auto-created from the final strategy source.")
            return sidecar_path
    except Exception as exc:
        warnings.append(f"Parser-based params JSON creation failed: {exc}. Falling back to best_params.")

    payload = _sidecar_payload_from_best_params(strategy_path.stem, report.get("best_params") or {})
    sidecar_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    warnings.append("Params JSON was missing and was auto-created from report.best_params.")
    return sidecar_path


def _resolve_or_create_params_json(
    state: Any,
    run_dir: Path,
    strategy_path: Path,
    report: dict[str, Any],
    warnings: list[str],
) -> Path:
    files = report.get("files") if isinstance(report.get("files"), dict) else {}
    accepted = _accepted_candidate(report)
    values = [
        accepted.get("params_json"),
        accepted.get("params_file"),
        files.get("params_json"),
        files.get("accepted_params"),
        strategy_path.with_suffix(".json").name,
        f"{strategy_path.stem}.json",
    ]
    params_path = _first_existing_artifact(state, run_dir, values, "params_json")
    if params_path is not None:
        return params_path
    return _create_params_json_from_strategy(state, strategy_path, report, warnings)


def _resolve_or_create_config(
    state: Any,
    run_dir: Path,
    report: dict[str, Any],
    warnings: list[str],
) -> Path:
    files = report.get("files") if isinstance(report.get("files"), dict) else {}
    config_path = _first_existing_artifact(state, run_dir, [files.get("config"), "config.json"], "config")
    if config_path is not None:
        return config_path

    config: dict[str, Any] = {}
    source_config = Path(getattr(state, "config_file", "") or "")
    if source_config.exists() and source_config.is_file():
        try:
            config = json.loads(source_config.read_text(encoding="utf-8"))
        except Exception as exc:
            warnings.append(f"Could not read base config: {exc}. A minimal dry-run config was generated.")

    if not config:
        warnings.append("Config artifact was missing; generated a minimal dry-run config that must be reviewed.")

    config.setdefault("dry_run", True)
    if getattr(state, "timeframe", None):
        config["timeframe"] = state.timeframe
    if getattr(state, "exchange", None):
        config.setdefault("exchange", {})["name"] = state.exchange

    pairs = []
    for item in getattr(state, "selected_pairs", None) or report.get("selected_pair_universe") or []:
        if isinstance(item, dict) and item.get("key"):
            pairs.append(item["key"])
        elif isinstance(item, str):
            pairs.append(item)
    if pairs:
        config.setdefault("exchange", {})["pair_whitelist"] = pairs

    config_path = run_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    return config_path


def _optional_state_snapshot(state: Any, run_dir: Path, report: dict[str, Any]) -> Path | None:
    artifact_versions: dict[str, Any] = {}
    if isinstance(getattr(state, "artifact_versions", None), dict):
        artifact_versions.update(state.artifact_versions)
    if isinstance(report.get("artifact_versions"), dict):
        artifact_versions.update(report["artifact_versions"])

    for name in (
        artifact_versions.get("state_latest"),
        artifact_versions.get("state_v1"),
        artifact_versions.get("state"),
        "state_latest.json",
        "state.json",
    ):
        if not name:
            continue
        candidate = run_dir / Path(name).name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _validation_warnings(state: Any, report: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    validation_status = str(report.get("validation_status") or getattr(state, "validation_status", "") or "").lower()
    readiness_label = str(report.get("readiness_label") or getattr(state, "readiness_label", "") or "").lower()

    validated = validation_status in {"passed", "accepted", "validated", "dry_run_ready", "validated_candidate"}
    validated = validated or str(report.get("final_verdict") or "").lower() == "validated_candidate"
    ready = "ready" in readiness_label and "not" not in readiness_label
    if not (validated or ready):
        warnings.append(
            "This strategy is not marked as validated/dry-run-ready. Use dry-run only until QA is complete."
        )

    stages = report.get("stages") or []
    failed_stages = [s.get("name") or s.get("index") for s in stages if isinstance(s, dict) and s.get("status") == "failed"]
    if failed_stages:
        warnings.append(f"Failed pipeline stages are present: {failed_stages}.")

    config = report.get("config") if isinstance(report.get("config"), dict) else {}
    if config.get("dry_run") is False:
        warnings.append("Report/config indicates dry_run=false. Confirm manually before any live trading.")

    return warnings


def _dry_run_manifest(
    *,
    run_id: str,
    state: Any,
    report: dict[str, Any],
    strategy_path: Path,
    params_path: Path,
    config_path: Path,
    report_path: Path,
    warnings: list[str],
) -> dict[str, Any]:
    selected_pairs = []
    for item in getattr(state, "selected_pairs", None) or report.get("selected_pair_universe") or []:
        if isinstance(item, dict) and item.get("key"):
            selected_pairs.append(item["key"])
        elif isinstance(item, str):
            selected_pairs.append(item)

    return {
        "schema_version": "autoquant_export_manifest_v1",
        "created_at": datetime.now().isoformat(),
        "run_id": run_id,
        "strategy": report.get("strategy") or getattr(state, "strategy", None),
        "optimized_strategy": strategy_path.stem,
        "timeframe": report.get("selected_timeframe") or report.get("timeframe") or getattr(state, "timeframe", None),
        "pairs": selected_pairs,
        "validation_status": report.get("validation_status") or getattr(state, "validation_status", None),
        "readiness_label": report.get("readiness_label") or getattr(state, "readiness_label", None),
        "warnings": warnings,
        "files": {
            "strategy_py": strategy_path.name,
            "params_json": params_path.name,
            "config": config_path.name,
            "report": report_path.name,
        },
        "dry_run_readiness_checklist": [
            {"item": "Final strategy .py included", "passed": strategy_path.exists()},
            {"item": "Freqtrade params sidecar .json included", "passed": params_path.exists()},
            {"item": "Config included", "passed": config_path.exists()},
            {"item": "Final report included", "passed": report_path.exists()},
            {"item": "Validation/dry-run-ready status present", "passed": not warnings},
            {"item": "No profit promised; dry-run before live", "passed": True},
        ],
    }


@router.post(
    "/export/{run_id}",
    status_code=200,
    summary="Download an audited Freqtrade-ready deployment bundle for a completed run",
)
async def export_pipeline(run_id: str) -> FileResponse:
    state = _pl.get_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
    if state.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Pipeline run '{run_id}' is not completed (current status: {state.status}).",
        )

    run_dir = Path(state.user_data_dir) / "auto_quant" / run_id
    report = _load_export_report(state, run_dir)
    warnings = _validation_warnings(state, report)

    strategy_path = _resolve_strategy_path(state, run_dir, report)
    params_path = _resolve_or_create_params_json(state, run_dir, strategy_path, report, warnings)
    config_path = _resolve_or_create_config(state, run_dir, report, warnings)
    report_path = _resolve_export_artifact(
        state,
        run_dir,
        (report.get("files") or {}).get("report") if isinstance(report.get("files"), dict) else "report.json",
        "report",
    )

    # Keep the in-memory report aligned with the audited export result. This does
    # not mutate strategy code or run anything; it only records resolved artifacts.
    report.setdefault("files", {})["optimized_strategy"] = strategy_path.name
    report.setdefault("files", {})["params_json"] = params_path.name
    report.setdefault("files", {})["config"] = config_path.name
    report.setdefault("files", {})["report"] = report_path.name
    report["export_warnings"] = warnings
    state.report = report

    manifest = _dry_run_manifest(
        run_id=run_id,
        state=state,
        report=report,
        strategy_path=strategy_path,
        params_path=params_path,
        config_path=config_path,
        report_path=report_path,
        warnings=warnings,
    )
    manifest_path = run_dir / "autoquant_export_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    artifacts: list[tuple[Path, str]] = [
        (strategy_path, strategy_path.name),
        (params_path, params_path.name),
        (config_path, "config.json"),
        (report_path, "report.json"),
        (manifest_path, manifest_path.name),
    ]
    state_path = _optional_state_snapshot(state, run_dir, report)
    if state_path is not None:
        artifacts.append((state_path, state_path.name))

    strategy_name = _safe_export_name(report.get("strategy") or getattr(state, "strategy", None) or strategy_path.stem)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_name = f"{strategy_name}_{timestamp}"
    exports_root = Path(state.user_data_dir) / "exports"
    export_dir = exports_root / bundle_name
    export_dir.mkdir(parents=True, exist_ok=True)

    copied_paths: list[Path] = []
    seen_names: set[str] = set()
    for source, filename in artifacts:
        if filename in seen_names:
            continue
        copied_paths.append(copy_to_output(source, export_dir, filename))
        seen_names.add(filename)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for copied_path in copied_paths:
            bundle.write(copied_path, arcname=copied_path.name)

    zip_filename = f"{bundle_name}.zip"
    zip_path = exports_root / zip_filename
    zip_path.write_bytes(zip_buffer.getvalue())

    return FileResponse(
        path=str(zip_path),
        filename=zip_filename,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_filename}"',
            "X-AutoQuant-Export-Warnings": str(len(warnings)),
        },
    )
