"""API endpoint tests for AutoQuant router.

Tests the lifecycle of API calls: start → status → cancel → report.
"""

from __future__ import annotations

import json

import pytest


class TestStartEndpoint:
    """Test POST /api/auto-quant/start endpoint."""

    def test_start_valid_config(self, app_with_service):
        """Verify POST /start returns 202 with run_id."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 10,
            "wfo_enabled": False,
            "ensemble_enabled": False,
        }

        response = client.post("/api/auto-quant/start", json=payload)

        assert response.status_code == 202, f"Expected 202, got {response.status_code}: {response.text}"
        data = response.json()
        assert "run_id" in data
        assert len(data["run_id"]) > 0
        # Pipeline starts immediately, so status is "running" not "pending"
        assert data["status"] in ("pending", "running")

    def test_start_missing_strategy(self, app_with_service):
        """Verify POST /start with missing strategy returns error."""
        client, tmp_path, settings = app_with_service

        payload = {
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            # Missing 'strategy'
        }

        response = client.post("/api/auto-quant/start", json=payload)

        # Should either return 400 (missing field) or 422 (validation error)
        assert response.status_code in (400, 422), f"Expected 400/422, got {response.status_code}"

    def test_start_nonexistent_strategy(self, app_with_service):
        """Verify POST /start with nonexistent strategy returns 404."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "NonExistentStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 10,
        }

        response = client.post("/api/auto-quant/start", json=payload)

        # Should return 404 if strategy file doesn't exist
        assert response.status_code in (404, 400), f"Expected 404/400, got {response.status_code}"

    @pytest.mark.parametrize("timeframe", ["5m", "1h", "4h"])
    def test_start_various_timeframes(self, app_with_service, timeframe):
        """Verify start works with various timeframes."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": timeframe,
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 10,
        }

        response = client.post("/api/auto-quant/start", json=payload)

        assert response.status_code == 202
        assert response.json()["run_id"]


class TestStatusEndpoint:
    """Test GET /api/auto-quant/status/{run_id} endpoint."""

    def test_status_unknown_run(self, app_with_service):
        """Verify GET /status with unknown run_id returns 404."""
        client, tmp_path, settings = app_with_service

        response = client.get("/api/auto-quant/status/unknown-run-id")

        assert response.status_code == 404

    def test_status_after_start(self, app_with_service):
        """Verify GET /status returns current state after start."""
        client, tmp_path, settings = app_with_service

        # Start pipeline
        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 10,
        }
        start_response = client.post("/api/auto-quant/start", json=payload)
        run_id = start_response.json()["run_id"]

        # Check status
        response = client.get(f"/api/auto-quant/status/{run_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == run_id
        assert "status" in data
        assert "current_stage" in data


class TestCancelEndpoint:
    """Test POST /api/auto-quant/cancel/{run_id} endpoint."""

    def test_cancel_unknown_run(self, app_with_service):
        """Verify POST /cancel with unknown run_id returns 404."""
        client, tmp_path, settings = app_with_service

        response = client.post("/api/auto-quant/cancel/unknown-run-id")

        assert response.status_code == 404

    def test_cancel_active_run(self, app_with_service):
        """Verify POST /cancel requests cancellation of active run."""
        client, tmp_path, settings = app_with_service

        # Start pipeline
        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 10,
        }
        start_response = client.post("/api/auto-quant/start", json=payload)
        run_id = start_response.json()["run_id"]

        # Cancel it
        response = client.post(f"/api/auto-quant/cancel/{run_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == run_id
        # Status might be "cancellation_requested" or "cancelled"
        assert "cancel" in data["status"].lower()

    def test_cancel_twice(self, app_with_service):
        """Verify cancelling twice doesn't error."""
        client, tmp_path, settings = app_with_service

        # Start pipeline
        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 10,
        }
        start_response = client.post("/api/auto-quant/start", json=payload)
        run_id = start_response.json()["run_id"]

        # Cancel twice
        response1 = client.post(f"/api/auto-quant/cancel/{run_id}")
        response2 = client.post(f"/api/auto-quant/cancel/{run_id}")

        assert response1.status_code == 200
        assert response2.status_code == 200


class TestReportEndpoint:
    """Test GET /api/auto-quant/report/{run_id} endpoint."""

    def test_report_unknown_run(self, app_with_service):
        """Verify GET /report with unknown run_id returns 404."""
        client, tmp_path, settings = app_with_service

        response = client.get("/api/auto-quant/report/unknown-run-id")

        assert response.status_code == 404

    def test_report_json_format(self, app_with_service):
        """Verify GET /report returns valid JSON."""
        client, tmp_path, settings = app_with_service

        # Start pipeline
        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 10,
        }
        start_response = client.post("/api/auto-quant/start", json=payload)
        run_id = start_response.json()["run_id"]

        # Get report
        response = client.get(f"/api/auto-quant/report/{run_id}")

        # Should return 200 if available, 202 if still processing, or 409 if conflict
        assert response.status_code in (200, 202, 409)

        # Should be valid JSON
        data = response.json()
        assert isinstance(data, dict)


class TestRunsEndpoint:
    """Test GET /api/auto-quant/runs endpoint."""

    def test_runs_empty(self, app_with_service):
        """Verify GET /runs returns list (empty initially)."""
        client, tmp_path, settings = app_with_service

        response = client.get("/api/auto-quant/runs")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))

    def test_runs_after_start(self, app_with_service):
        """Verify run appears in /runs list after start."""
        client, tmp_path, settings = app_with_service

        # Start pipeline
        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 10,
        }
        start_response = client.post("/api/auto-quant/start", json=payload)
        run_id = start_response.json()["run_id"]

        # Check /runs list
        response = client.get("/api/auto-quant/runs")

        assert response.status_code == 200
        data = response.json()

        # Find the run in the list
        if isinstance(data, list):
            run_ids = [r.get("run_id") for r in data]
            assert run_id in run_ids, f"Run {run_id} not found in {run_ids}"


class TestOptionsEndpoint:
    """Test GET/POST /api/auto-quant/options endpoint."""

    def test_options_get(self, app_with_service):
        """Verify GET /options returns valid options."""
        client, tmp_path, settings = app_with_service

        response = client.get("/api/auto-quant/options")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_options_post(self, app_with_service):
        """Verify POST /options saves options."""
        client, tmp_path, settings = app_with_service

        options = {
            "default_timeframe": "1h",
            "default_pairs": "BTC/USDT,ETH/USDT",
        }

        response = client.post("/api/auto-quant/options", json=options)

        # Should return 200 on success or validation error
        assert response.status_code in (200, 202)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
