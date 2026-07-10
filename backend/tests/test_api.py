"""backend/tests/test_api.py — API endpoint tests.

Tests for the Auto-Quant API endpoints, including:
- GET /api/auto-quant/runs
- GET /api/auto-quant/status/{run_id}
- GET /api/auto-quant/download/{run_id}/{filename}
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import backend.services.auto_quant.pipeline as pl

from .test_helpers import _make_state

MOD = "backend.services.auto_quant.pipeline"


class TestApiEndpoints:
    """Verify /runs and /download return correct HTTP status codes and valid JSON."""

    def test_start_request_defaults_to_profit_lockin_loss(self):
        """API clients should see ProfitLockinHyperOptLoss unless they override it."""
        from backend.api.routers.auto_quant import StartAutoQuantRequest

        body = StartAutoQuantRequest(
            strategy="AuditStrategy",
            in_sample_range="20230101-20230601",
            out_sample_range="20230601-20231201",
        )

        assert body.hyperopt_loss == "ProfitLockinHyperOptLoss"

    # ── GET /api/auto-quant/runs ───────────────────────────────────────────────

    def test_runs_returns_200(self, app_client):
        """GET /runs must return HTTP 200."""
        client, _, _ = app_client
        resp = client.get("/api/auto-quant/runs")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_runs_returns_json_with_runs_key(self, app_client):
        """GET /runs must return a JSON body with a top-level 'runs' list."""
        client, _, _ = app_client
        resp = client.get("/api/auto-quant/runs")
        body = resp.json()
        assert "runs" in body, f"'runs' key missing from response: {body}"
        assert isinstance(body["runs"], list)

    def test_runs_includes_created_run(self, app_client, tmp_path):
        """A run created via create_run() must appear in GET /runs."""
        client, tmp_path, settings = app_client
        user_data = tmp_path / "user_data"
        user_data.mkdir(parents=True, exist_ok=True)

        with patch(f"{MOD}._save_state_to_disk"):
            run_id = pl.create_run(
                strategy="Listed",
                timeframe="5m",
                in_sample_range="20230101-20231201",
                out_sample_range="20240101-20240601",
                exchange="binance",
                config_file=str(tmp_path / "config.json"),
                freqtrade_path="freqtrade",
                user_data_dir=str(user_data),
            )

        resp = client.get("/api/auto-quant/runs")
        assert resp.status_code == 200
        ids = [r["run_id"] for r in resp.json()["runs"]]
        assert run_id in ids, f"run_id {run_id} not in /runs response: {ids}"

    def test_runs_does_not_return_500(self, app_client):
        """GET /runs must never return a 500 Internal Server Error."""
        client, _, _ = app_client
        for _ in range(3):
            resp = client.get("/api/auto-quant/runs")
            assert resp.status_code != 500, f"Got 500 on /runs: {resp.text}"

    def test_runs_endpoint_never_500_with_empty_registry(self, app_client):
        """/runs must not 500 even when no runs have been created."""
        client, _, _ = app_client
        pl._states.clear()
        resp = client.get("/api/auto-quant/runs")
        assert resp.status_code == 200
        assert resp.json()["runs"] == [] or isinstance(resp.json()["runs"], list)

    # ── GET /api/auto-quant/status/{run_id} ───────────────────────────────────

    def test_status_endpoint_returns_correct_run_data(self, app_client, tmp_path):
        """GET /status/{run_id} must return the correct state snapshot."""
        client, tmp_path, settings = app_client
        user_data = tmp_path / "user_data"
        user_data.mkdir(parents=True, exist_ok=True)

        with patch(f"{MOD}._save_state_to_disk"):
            run_id = pl.create_run(
                strategy="StatusTest",
                timeframe="1h",
                in_sample_range="20230101-20231201",
                out_sample_range="20240101-20240601",
                exchange="binance",
                config_file=str(tmp_path / "config.json"),
                freqtrade_path="freqtrade",
                user_data_dir=str(user_data),
            )

        resp = client.get(f"/api/auto-quant/status/{run_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == run_id
        assert body["strategy"] == "StatusTest"
        assert len(body["stages"]) == 6

    def test_status_404_for_unknown_run(self, app_client):
        """GET /status for an unknown run_id must return 404."""
        client, _, _ = app_client
        resp = client.get("/api/auto-quant/status/totally-fake-run-id")
        assert resp.status_code == 404

    # ── GET /api/auto-quant/download/{run_id}/{filename} ─────────────────────

    def test_download_py_file_returns_200(self, app_client, tmp_path):
        """Downloading a .py output file must return HTTP 200."""
        client, tmp_path, settings = app_client
        user_data = tmp_path / "user_data"
        user_data.mkdir(parents=True, exist_ok=True)

        with patch(f"{MOD}._save_state_to_disk"):
            run_id = pl.create_run(
                strategy="DownloadTest",
                timeframe="5m",
                in_sample_range="20230101-20231201",
                out_sample_range="20240101-20240601",
                exchange="binance",
                config_file=str(tmp_path / "config.json"),
                freqtrade_path="freqtrade",
                user_data_dir=str(user_data),
            )

        out_dir = user_data / "auto_quant" / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        py_file = out_dir / "DownloadTest_Optimized.py"
        py_file.write_text("class DownloadTest_Optimized: pass\n", encoding="utf-8")

        resp = client.get(f"/api/auto-quant/download/{run_id}/DownloadTest_Optimized.py")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_download_json_file_returns_200(self, app_client, tmp_path):
        """Downloading a .json output file must return HTTP 200."""
        client, tmp_path, settings = app_client
        user_data = tmp_path / "user_data"
        user_data.mkdir(parents=True, exist_ok=True)

        with patch(f"{MOD}._save_state_to_disk"):
            run_id = pl.create_run(
                strategy="DownloadTest",
                timeframe="5m",
                in_sample_range="20230101-20231201",
                out_sample_range="20240101-20240601",
                exchange="binance",
                config_file=str(tmp_path / "config.json"),
                freqtrade_path="freqtrade",
                user_data_dir=str(user_data),
            )

        out_dir = user_data / "auto_quant" / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "config.json").write_text('{"exchange": {"name": "binance"}}', encoding="utf-8")

        resp = client.get(f"/api/auto-quant/download/{run_id}/config.json")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_download_unknown_run_returns_404(self, app_client):
        """Downloading a file for a non-existent run_id must return 404."""
        client, _, _ = app_client
        resp = client.get("/api/auto-quant/download/does-not-exist/config.json")
        assert resp.status_code == 404

    def test_download_missing_file_returns_404(self, app_client, tmp_path):
        """Downloading a file that does not exist on disk must return 404."""
        client, tmp_path, settings = app_client
        user_data = tmp_path / "user_data"
        user_data.mkdir(parents=True, exist_ok=True)

        with patch(f"{MOD}._save_state_to_disk"):
            run_id = pl.create_run(
                strategy="NoFile",
                timeframe="5m",
                in_sample_range="20230101-20231201",
                out_sample_range="20240101-20240601",
                exchange="binance",
                config_file=str(tmp_path / "config.json"),
                freqtrade_path="freqtrade",
                user_data_dir=str(user_data),
            )

        resp = client.get(f"/api/auto-quant/download/{run_id}/NonExistentFile.py")
        assert resp.status_code == 404

    def test_download_rejects_path_traversal(self, app_client, tmp_path):
        """Path traversal filenames must be rejected with 400."""
        client, tmp_path, settings = app_client
        user_data = tmp_path / "user_data"
        user_data.mkdir(parents=True, exist_ok=True)

        with patch(f"{MOD}._save_state_to_disk"):
            run_id = pl.create_run(
                strategy="TraversalTest",
                timeframe="5m",
                in_sample_range="20230101-20231201",
                out_sample_range="20240101-20240601",
                exchange="binance",
                config_file=str(tmp_path / "config.json"),
                freqtrade_path="freqtrade",
                user_data_dir=str(user_data),
            )

        resp = client.get(f"/api/auto-quant/download/{run_id}/../../etc/passwd.json")
        assert resp.status_code in (400, 404, 422), (
            f"Path traversal should be rejected, got {resp.status_code}"
        )

    def test_download_rejects_non_py_non_json_suffix(self, app_client, tmp_path):
        """Files with disallowed suffixes must be rejected with 400."""
        client, tmp_path, settings = app_client
        user_data = tmp_path / "user_data"
        user_data.mkdir(parents=True, exist_ok=True)

        with patch(f"{MOD}._save_state_to_disk"):
            run_id = pl.create_run(
                strategy="SuffixTest",
                timeframe="5m",
                in_sample_range="20230101-20231201",
                out_sample_range="20240101-20240601",
                exchange="binance",
                config_file=str(tmp_path / "config.json"),
                freqtrade_path="freqtrade",
                user_data_dir=str(user_data),
            )

        for bad_name in ("secret.pkl", "archive.zip", "data.csv", "notes.txt"):
            resp = client.get(f"/api/auto-quant/download/{run_id}/{bad_name}")
            assert resp.status_code == 400, (
                f"Expected 400 for {bad_name!r}, got {resp.status_code}"
            )
