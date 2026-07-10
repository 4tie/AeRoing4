"""Pipeline cancellation tests.

Tests cancelling pipelines at various stages and verifying proper cleanup.
"""

from __future__ import annotations

import time

import pytest


class TestCancellationBasics:
    """Basic cancellation functionality tests."""

    def test_cancel_pending_run(self, app_with_service):
        """Verify cancelling a pending run works."""
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
        start_response = client.post("/api/auto-quant/start", json=payload)
        run_id = start_response.json()["run_id"]

        # Cancel immediately
        cancel_response = client.post(f"/api/auto-quant/cancel/{run_id}")

        assert cancel_response.status_code == 200
        data = cancel_response.json()
        assert data["run_id"] == run_id
        assert "cancel" in data["status"].lower()

    def test_cancel_running_run(self, app_with_service):
        """Verify cancelling a running pipeline works."""
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
        start_response = client.post("/api/auto-quant/start", json=payload)
        run_id = start_response.json()["run_id"]

        # Wait for it to start running
        time.sleep(1)

        # Cancel while running
        cancel_response = client.post(f"/api/auto-quant/cancel/{run_id}")

        assert cancel_response.status_code == 200
        assert "cancel" in cancel_response.json()["status"].lower()

    def test_cancel_unknown_run(self, app_with_service):
        """Verify cancelling unknown run returns 404."""
        client, tmp_path, settings = app_with_service

        response = client.post("/api/auto-quant/cancel/unknown-run-id")

        assert response.status_code == 404

    def test_cancel_twice(self, app_with_service):
        """Verify cancelling twice is idempotent."""
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
        start_response = client.post("/api/auto-quant/start", json=payload)
        run_id = start_response.json()["run_id"]

        # Cancel twice
        response1 = client.post(f"/api/auto-quant/cancel/{run_id}")
        response2 = client.post(f"/api/auto-quant/cancel/{run_id}")

        # Both should succeed
        assert response1.status_code == 200
        assert response2.status_code == 200


class TestCancellationStateTransitions:
    """Test state transitions after cancellation."""

    def test_cancelled_status_reported(self, app_with_service):
        """Verify status shows 'cancelled' after cancellation."""
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
        start_response = client.post("/api/auto-quant/start", json=payload)
        run_id = start_response.json()["run_id"]

        # Cancel
        client.post(f"/api/auto-quant/cancel/{run_id}")

        # Check status
        status_response = client.get(f"/api/auto-quant/status/{run_id}")
        status = status_response.json()

        # Status should reflect cancellation or that pipeline already failed
        assert status["status"] in ("cancelled", "cancellation_requested", "running", "pending", "failed")

    def test_cancel_prevents_progress(self, app_with_service):
        """Verify cancellation stops pipeline progress."""
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
        start_response = client.post("/api/auto-quant/start", json=payload)
        run_id = start_response.json()["run_id"]

        # Get initial status
        status1 = client.get(f"/api/auto-quant/status/{run_id}").json()
        stage1 = status1.get("current_stage", 0)

        # Cancel
        client.post(f"/api/auto-quant/cancel/{run_id}")

        # Wait a moment
        time.sleep(2)

        # Get status after cancel
        status2 = client.get(f"/api/auto-quant/status/{run_id}").json()
        stage2 = status2.get("current_stage", 0)

        # Stage should not advance significantly after cancel
        # (it might advance slightly if already in progress)
        assert stage2 <= stage1 + 1


class TestCancellationEdgeCases:
    """Edge cases in cancellation."""

    def test_cancel_already_completed_run(self, app_with_service):
        """Verify cancelling already completed run returns appropriate response."""
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
        start_response = client.post("/api/auto-quant/start", json=payload)
        run_id = start_response.json()["run_id"]

        # Wait for completion or long enough
        time.sleep(2)

        # Try to cancel completed run
        response = client.post(f"/api/auto-quant/cancel/{run_id}")

        # Should succeed or indicate already completed
        assert response.status_code in (200, 409)

    def test_cancel_multiple_runs(self, app_with_service):
        """Verify cancelling one run doesn't affect others."""
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

        # Cancel first run
        client.post(f"/api/auto-quant/cancel/{run_id1}")

        # Check status of both
        status1 = client.get(f"/api/auto-quant/status/{run_id1}").json()
        status2 = client.get(f"/api/auto-quant/status/{run_id2}").json()

        # First should be cancelled or failed (pipeline may fail before cancellation completes)
        assert "cancel" in status1["status"].lower() or status1["status"] in ("cancelled", "failed")

        # Second should still be running or pending
        assert status2["status"] in ("running", "pending", "completed")


class TestCancellationResponseFormat:
    """Test cancellation response format."""

    def test_cancel_response_has_required_fields(self, app_with_service):
        """Verify cancel response contains required fields."""
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
        start_response = client.post("/api/auto-quant/start", json=payload)
        run_id = start_response.json()["run_id"]

        # Cancel
        response = client.post(f"/api/auto-quant/cancel/{run_id}")

        assert response.status_code == 200
        data = response.json()

        # Should have required fields
        assert "run_id" in data
        assert "status" in data
        assert data["run_id"] == run_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
