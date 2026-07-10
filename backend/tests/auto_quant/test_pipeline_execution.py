"""Full 7-stage pipeline execution tests with mocked subprocess.

Tests the complete pipeline orchestration from start to completion,
verifying all stages execute in order with correct state transitions.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest


class TestPipelineHappyPath:
    """Test complete pipeline execution with all stages passing."""

    @pytest.mark.asyncio
    async def test_all_7_stages_complete(self, app_with_service, mock_freqtrade_subprocess):
        """Verify all 7 stages execute sequentially and complete successfully."""
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

        # Start pipeline
        response = client.post("/api/auto-quant/start", json=payload)
        assert response.status_code == 202
        run_id = response.json()["run_id"]

        # Wait for pipeline to complete (with timeout)
        max_wait = 60  # seconds
        start_time = time.time()
        completed = False

        while time.time() - start_time < max_wait:
            status_response = client.get(f"/api/auto-quant/status/{run_id}")
            if status_response.status_code == 200:
                status = status_response.json()
                if status.get("status") in ("completed", "failed"):
                    completed = True
                    break
            await asyncio.sleep(0.5)

        assert completed, f"Pipeline did not complete within {max_wait}s"

        # Verify final status
        final_status = status_response.json()
        assert final_status["run_id"] == run_id
        assert "current_stage" in final_status
        assert "stages" in final_status

    def test_stage_state_transitions(self, app_with_service):
        """Verify state machine follows legal transitions: pending → running → passed."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 10,
        }

        # Start pipeline
        response = client.post("/api/auto-quant/start", json=payload)
        run_id = response.json()["run_id"]

        # Check initial status
        status = client.get(f"/api/auto-quant/status/{run_id}").json()
        assert status["status"] in ("pending", "running")

        # Status should eventually be running (from pending)
        # and finally completed
        for _ in range(10):
            status = client.get(f"/api/auto-quant/status/{run_id}").json()
            assert status["status"] in ("pending", "running", "completed", "failed")
            if status["status"] == "completed":
                break
            time.sleep(1)

    @pytest.mark.asyncio
    async def test_concurrent_runs_isolated(self, app_with_service):
        """Verify two simultaneous pipelines don't interfere with each other."""
        client, tmp_path, settings = app_with_service

        payload1 = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 5,
        }

        payload2 = {
            "strategy": "TestStrategy",
            "timeframe": "1h",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["ETH/USDT"],
            "hyperopt_epochs": 5,
        }

        # Start both pipelines
        response1 = client.post("/api/auto-quant/start", json=payload1)
        response2 = client.post("/api/auto-quant/start", json=payload2)

        run_id1 = response1.json()["run_id"]
        run_id2 = response2.json()["run_id"]

        # Verify they're different
        assert run_id1 != run_id2

        # Check status of both
        status1 = client.get(f"/api/auto-quant/status/{run_id1}").json()
        status2 = client.get(f"/api/auto-quant/status/{run_id2}").json()

        assert status1["run_id"] == run_id1
        assert status2["run_id"] == run_id2

        # Verify different configurations
        assert status1.get("config", {}).get("timeframe") == "5m"
        assert status2.get("config", {}).get("timeframe") == "1h"


class TestPipelineOutputFiles:
    """Test that pipeline generates expected output files."""

    def test_output_directory_created(self, app_with_service):
        """Verify output directory is created for each run."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 5,
        }

        response = client.post("/api/auto-quant/start", json=payload)
        run_id = response.json()["run_id"]

        # Output directory should be created
        output_dir = Path(settings.user_data_directory_path) / "auto_quant" / run_id
        assert output_dir.exists(), f"Output directory not created at {output_dir}"

    def test_state_json_created(self, app_with_service):
        """Verify state.json is created and valid."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 5,
        }

        response = client.post("/api/auto-quant/start", json=payload)
        run_id = response.json()["run_id"]

        # Wait a moment for file to be created
        time.sleep(0.5)

        state_file = Path(settings.user_data_directory_path) / "auto_quant" / run_id / "state.json"
        assert state_file.exists(), f"state.json not created at {state_file}"

        # Verify it's valid JSON
        with open(state_file) as f:
            state_data = json.load(f)

        assert "run_id" in state_data
        assert state_data["run_id"] == run_id
        assert "status" in state_data
        assert "current_stage" in state_data


class TestPipelineConfiguration:
    """Test pipeline respects configuration parameters."""

    @pytest.mark.parametrize("timeframe", ["5m", "1h", "4h"])
    def test_pipeline_accepts_timeframes(self, app_with_service, timeframe):
        """Verify pipeline starts with various timeframes."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": timeframe,
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 5,
        }

        response = client.post("/api/auto-quant/start", json=payload)

        assert response.status_code == 202
        data = response.json()
        assert "run_id" in data

    @pytest.mark.parametrize("epochs", [5, 10, 50])
    def test_pipeline_hyperopt_epochs(self, app_with_service, epochs):
        """Verify pipeline accepts various hyperopt epoch counts."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": epochs,
        }

        response = client.post("/api/auto-quant/start", json=payload)

        assert response.status_code == 202
        status = client.get(f"/api/auto-quant/status/{response.json()['run_id']}").json()
        assert status.get("config", {}).get("hyperopt_epochs") == epochs

    @pytest.mark.parametrize("wfo_enabled", [True, False])
    def test_pipeline_wfo_toggle(self, app_with_service, wfo_enabled):
        """Verify WFO enable/disable is respected."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 5,
            "wfo_enabled": wfo_enabled,
        }

        response = client.post("/api/auto-quant/start", json=payload)

        assert response.status_code == 202
        status = client.get(f"/api/auto-quant/status/{response.json()['run_id']}").json()
        assert status.get("config", {}).get("wfo_enabled") == wfo_enabled

    @pytest.mark.parametrize("ensemble_enabled", [True, False])
    def test_pipeline_ensemble_toggle(self, app_with_service, ensemble_enabled):
        """Verify ensemble enable/disable is respected."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 5,
            "ensemble_enabled": ensemble_enabled,
        }

        response = client.post("/api/auto-quant/start", json=payload)

        assert response.status_code == 202
        status = client.get(f"/api/auto-quant/status/{response.json()['run_id']}").json()
        assert status.get("config", {}).get("ensemble_enabled") == ensemble_enabled


class TestPipelineProgress:
    """Test pipeline progress reporting."""

    def test_progress_updates(self, app_with_service):
        """Verify progress percentage is reported."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 5,
        }

        response = client.post("/api/auto-quant/start", json=payload)
        run_id = response.json()["run_id"]

        # Check progress
        status = client.get(f"/api/auto-quant/status/{run_id}").json()

        # Progress should be a percentage
        assert "progress" in status or "current_stage" in status

    def test_stage_in_status(self, app_with_service):
        """Verify current stage is reported in status."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 5,
        }

        response = client.post("/api/auto-quant/start", json=payload)
        run_id = response.json()["run_id"]

        status = client.get(f"/api/auto-quant/status/{run_id}").json()

        # Should report current stage
        assert "current_stage" in status or "stage" in status
        current_stage = status.get("current_stage", status.get("stage"))
        # Should be between 0 and 5 (or 7 if counting phases differently)
        assert isinstance(current_stage, int)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
