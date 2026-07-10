"""Error scenario and edge case tests for AutoQuant pipeline.

Tests invalid configurations, missing files, and error handling.
"""

from __future__ import annotations

import pytest


class TestInvalidConfigurations:
    """Test error handling for invalid pipeline configurations."""

    def test_missing_strategy_field(self, app_with_service):
        """Verify missing 'strategy' field returns error."""
        client, tmp_path, settings = app_with_service

        payload = {
            # Missing 'strategy'
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 10,
        }

        response = client.post("/api/auto-quant/start", json=payload)

        # Should return 400 or 422 for missing required field
        assert response.status_code in (400, 422)

    def test_missing_timeframe_field(self, app_with_service):
        """Verify missing 'timeframe' uses policy defaults."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            # Missing 'timeframe'
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 10,
        }

        response = client.post("/api/auto-quant/start", json=payload)

        assert response.status_code == 202

    def test_missing_date_range_fields(self, app_with_service):
        """Verify missing date range fields use policy defaults."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            # Missing 'in_sample_range'
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 10,
        }

        response = client.post("/api/auto-quant/start", json=payload)

        assert response.status_code == 202

    def test_invalid_date_range_format(self, app_with_service):
        """Verify invalid date format returns error."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "invalid-date",  # Invalid format
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 10,
        }

        response = client.post("/api/auto-quant/start", json=payload)

        # Should return 400 for invalid format
        assert response.status_code in (400, 422)

    def test_invalid_hyperopt_epochs(self, app_with_service):
        """Verify invalid hyperopt epochs returns error."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": -5,  # Invalid: negative
        }

        response = client.post("/api/auto-quant/start", json=payload)

        # Should return 400 for invalid value
        assert response.status_code in (400, 422)

    def test_empty_pairs_list(self, app_with_service):
        """Verify empty pairs list returns error."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pair_universe": [],  # Empty
            "hyperopt_epochs": 10,
        }

        response = client.post("/api/auto-quant/start", json=payload)

        # Should return 400 for empty list
        assert response.status_code in (400, 422)


class TestMissingFiles:
    """Test error handling for missing required files."""

    def test_nonexistent_strategy_file(self, app_with_service):
        """Verify nonexistent strategy file returns 404."""
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
        assert response.status_code in (404, 400)


class TestInvalidRunIds:
    """Test error handling for invalid run IDs."""

    def test_status_unknown_run_id(self, app_with_service):
        """Verify GET /status with unknown run_id returns 404."""
        client, tmp_path, settings = app_with_service

        response = client.get("/api/auto-quant/status/unknown-run-id-12345")

        assert response.status_code == 404

    def test_cancel_unknown_run_id(self, app_with_service):
        """Verify POST /cancel with unknown run_id returns 404."""
        client, tmp_path, settings = app_with_service

        response = client.post("/api/auto-quant/cancel/unknown-run-id-12345")

        assert response.status_code == 404

    def test_report_unknown_run_id(self, app_with_service):
        """Verify GET /report with unknown run_id returns 404."""
        client, tmp_path, settings = app_with_service

        response = client.get("/api/auto-quant/report/unknown-run-id-12345")

        assert response.status_code == 404


class TestDownloadSecurity:
    """Test download endpoint security (path traversal prevention)."""

    def test_download_path_traversal_attempt(self, app_with_service):
        """Verify path traversal attacks are blocked."""
        client, tmp_path, settings = app_with_service

        # Try to traverse directories
        response = client.get("/api/auto-quant/download/run-id/../../../../etc/passwd")

        # Should either 404 or 403
        assert response.status_code in (404, 403, 400)

    def test_download_absolute_path_attempt(self, app_with_service):
        """Verify absolute path downloads are blocked."""
        client, tmp_path, settings = app_with_service

        response = client.get("/api/auto-quant/download/run-id//etc/passwd")

        # Should either 404 or 403
        assert response.status_code in (404, 403, 400)


class TestTypeErrors:
    """Test type validation in configuration."""

    def test_hyperopt_epochs_not_integer(self, app_with_service):
        """Verify non-integer hyperopt_epochs returns error."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": "not_an_int",  # String instead of int
        }

        response = client.post("/api/auto-quant/start", json=payload)

        # Should return 422 (validation error)
        assert response.status_code in (400, 422)

    def test_wfo_enabled_not_boolean(self, app_with_service):
        """Verify non-boolean wfo_enabled returns error."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 10,
            "wfo_enabled": "yes",  # String instead of boolean
        }

        response = client.post("/api/auto-quant/start", json=payload)

        # Should return 422 (validation error)
        assert response.status_code in (400, 422)

    def test_pairs_not_list(self, app_with_service):
        """Verify non-list pairs returns error."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pair_universe": "BTC/USDT",  # String instead of list
            "hyperopt_epochs": 10,
        }

        response = client.post("/api/auto-quant/start", json=payload)

        # Should return 422 (validation error)
        assert response.status_code in (400, 422)


class TestEdgeCases:
    """Test edge case scenarios."""

    def test_very_short_date_range(self, app_with_service):
        """Verify very short date range is handled (might fail in pipeline)."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20240101-20240102",  # Only 1 day
            "out_sample_range": "20240102-20240103",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 10,
        }

        response = client.post("/api/auto-quant/start", json=payload)

        # Should accept the config even if it might fail later
        assert response.status_code in (202, 400)

    def test_very_large_hyperopt_epochs(self, app_with_service):
        """Verify very large epoch count is accepted."""
        client, tmp_path, settings = app_with_service

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": ["BTC/USDT"],
            "hyperopt_epochs": 10000,  # Very large
        }

        response = client.post("/api/auto-quant/start", json=payload)

        # Should accept (might be slow but valid)
        assert response.status_code in (202, 400)

    def test_many_pairs(self, app_with_service):
        """Verify many pairs can be specified."""
        client, tmp_path, settings = app_with_service

        pairs = [f"COIN{i}/USDT" for i in range(100)]  # 100 pairs

        payload = {
            "strategy": "TestStrategy",
            "timeframe": "5m",
            "in_sample_range": "20230101-20240101",
            "out_sample_range": "20240101-20240601",
            "pairs": pairs,
            "hyperopt_epochs": 10,
        }

        response = client.post("/api/auto-quant/start", json=payload)

        # Should accept (might filter some pairs but valid)
        assert response.status_code in (202, 400)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
