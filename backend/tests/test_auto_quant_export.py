"""Tests for the AutoQuant Freqtrade deployment export endpoint."""

from __future__ import annotations

import asyncio
import json
import re
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.api.routers.auto_quant_export import export_pipeline
from .test_helpers import _make_state


def _run(coro):
    return asyncio.run(coro)


def _completed_export_state(
    root,
    strategy: str = "ExportStrategy",
    *,
    include_params: bool = True,
    include_config: bool = True,
    validation_status: str = "validated",
    readiness_label: str = "Dry-run ready",
):
    user_data = root / "user_data"
    user_data.mkdir(parents=True, exist_ok=True)

    state = _make_state(
        str(user_data),
        strategy=strategy,
        status="completed",
        validation_status=validation_status,
        readiness_label=readiness_label,
    )
    run_dir = user_data / "auto_quant" / state.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    strategy_name = f"{strategy}_Optimized"
    strategy_file = run_dir / f"{strategy_name}.py"
    config_file = run_dir / "config.json"
    report_file = run_dir / "report.json"
    params_file = run_dir / f"{strategy_name}.json"
    state_file = run_dir / "state_latest.json"

    strategy_file.write_text(
        f"""
class {strategy_name}(IStrategy):
    INTERFACE_VERSION = 3
    minimal_roi = {{"0": 0.10, "60": 0.02}}
    stoploss = -0.08
    trailing_stop = True
""".lstrip(),
        encoding="utf-8",
    )
    if include_config:
        config_file.write_text(json.dumps({"exchange": {"name": "binance"}, "dry_run": True}), encoding="utf-8")
    if include_params:
        params_file.write_text(json.dumps({"strategy_name": strategy_name, "params": {"buy": {}}}), encoding="utf-8")

    files = {
        "optimized_strategy": strategy_file.name,
        "report": report_file.name,
    }
    if include_config:
        files["config"] = config_file.name
    if include_params:
        files["params_json"] = params_file.name

    report = {
        "run_id": state.run_id,
        "strategy": strategy,
        "optimized_strategy": strategy_name,
        "validation_status": validation_status,
        "readiness_label": readiness_label,
        "best_params": {
            "params_dict": {
                "minimal_roi": {"0": 0.10, "60": 0.02},
                "stoploss": -0.08,
                "trailing_stop": True,
            }
        },
        "files": files,
    }
    report_file.write_text(json.dumps(report), encoding="utf-8")
    state_file.write_text(json.dumps({"run_id": state.run_id, "status": "completed"}), encoding="utf-8")

    state.report = report
    state.artifact_versions = {"state_latest": state_file.name}
    return state


def _zip_names(response) -> set[str]:
    with zipfile.ZipFile(Path(response.path)) as bundle:
        return set(bundle.namelist())


def _zip_json(response, filename: str) -> dict:
    with zipfile.ZipFile(Path(response.path)) as bundle:
        with bundle.open(filename) as handle:
            return json.loads(handle.read().decode("utf-8"))


def test_export_rejects_non_completed(tmp_path):
    state = _make_state(str(tmp_path / "user_data"), status="pending", report={"files": {}})

    with pytest.raises(HTTPException) as exc_info:
        _run(export_pipeline(state.run_id))

    assert exc_info.value.status_code == 409


def test_export_unknown_run():
    with pytest.raises(HTTPException) as exc_info:
        _run(export_pipeline("fake-id"))

    assert exc_info.value.status_code == 404


def test_export_zip_contains_expected_files(tmp_path):
    state = _completed_export_state(tmp_path)
    response = _run(export_pipeline(state.run_id))

    assert response.media_type == "application/zip"
    names = _zip_names(response)

    assert "ExportStrategy_Optimized.py" in names
    assert "ExportStrategy_Optimized.json" in names
    assert "config.json" in names
    assert "report.json" in names
    assert "autoquant_export_manifest.json" in names


def test_export_zip_filename_format(tmp_path):
    state = _completed_export_state(tmp_path, strategy="FormatStrategy")

    response = _run(export_pipeline(state.run_id))

    content_disposition = response.headers.get("content-disposition", "")
    assert re.search(
        r'filename="?FormatStrategy_\d{8}_\d{6}\.zip"?',
        content_disposition,
    )


def test_export_auto_creates_missing_params_json(tmp_path):
    state = _completed_export_state(tmp_path, strategy="MissingParams", include_params=False)

    response = _run(export_pipeline(state.run_id))
    names = _zip_names(response)
    sidecar_name = "MissingParams_Optimized.json"
    sidecar = _zip_json(response, sidecar_name)
    manifest = _zip_json(response, "autoquant_export_manifest.json")

    assert sidecar_name in names
    assert sidecar["strategy_name"] == "MissingParams_Optimized"
    assert sidecar["params"]["stoploss"]["stoploss"] == -0.08
    assert any("auto-created" in warning for warning in manifest["warnings"])


def test_export_auto_creates_config_when_missing(tmp_path):
    state = _completed_export_state(tmp_path, strategy="MissingConfig", include_config=False)
    state.selected_pairs = [{"key": "BTC/USDT"}]

    response = _run(export_pipeline(state.run_id))
    config = _zip_json(response, "config.json")
    manifest = _zip_json(response, "autoquant_export_manifest.json")

    assert config["dry_run"] is True
    assert config["exchange"]["name"] == "binance"
    assert config["exchange"]["pair_whitelist"] == ["BTC/USDT"]
    assert any("Config artifact was missing" in warning for warning in manifest["warnings"])


def test_export_manifest_warns_when_not_validated(tmp_path):
    state = _completed_export_state(
        tmp_path,
        strategy="RiskyStrategy",
        validation_status="failed",
        readiness_label="Not Ready",
    )

    response = _run(export_pipeline(state.run_id))
    manifest = _zip_json(response, "autoquant_export_manifest.json")

    assert response.headers["x-autoquant-export-warnings"] != "0"
    assert any("not marked as validated" in warning for warning in manifest["warnings"])
    assert manifest["dry_run_readiness_checklist"][-1] == {
        "item": "No profit promised; dry-run before live",
        "passed": True,
    }
