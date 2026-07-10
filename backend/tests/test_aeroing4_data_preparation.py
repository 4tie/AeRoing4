"""Tests for AeRoing4 data preparation step."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch

import pytest

from backend.services.aeroing4.models import AeRoing4StepStatus
from backend.services.aeroing4.steps.data_preparation import DataPreparationStep


@pytest.fixture
def mock_services():
    """Create mock services."""
    services = Mock()
    services.settings_store = Mock()
    services.backtest_runner = Mock()
    services.data_download_runner = Mock()
    return services


@pytest.fixture
def data_prep_step(mock_services):
    """Create data preparation step with mock services."""
    return DataPreparationStep(mock_services)


class TestDataPreparationStep:
    """Test DataPreparationStep functionality."""

    @pytest.mark.asyncio
    async def test_data_already_available(self, data_prep_step, mock_services):
        """Test data preparation when data is already available."""
        # Mock settings
        mock_settings = Mock()
        mock_settings.user_data_directory_path = "/tmp/user_data"
        mock_settings.default_config_file_path = "/tmp/config.json"
        mock_services.settings_store.load.return_value = mock_settings

        # Mock the internal _check_pair_data method
        with patch.object(
            data_prep_step, "_check_pair_data", return_value=True
        ):
            result = await data_prep_step.execute(
                pairs=["BTC/USDT", "ETH/USDT"],
                timeframe="5m",
                timerange="20240101-20240131",
            )

        assert result.step_name == "data_preparation"
        assert result.status == AeRoing4StepStatus.PASSED
        assert result.data["coverage_check_passed"] is True
        assert result.data["pairs_ready"]["BTC/USDT"] is True
        assert result.data["pairs_ready"]["ETH/USDT"] is True

    @pytest.mark.asyncio
    async def test_missing_data_downloads_successfully(self, data_prep_step, mock_services):
        """Test data preparation downloads missing data successfully."""
        # Mock settings
        mock_settings = Mock()
        mock_settings.user_data_directory_path = "/tmp/user_data"
        mock_settings.default_config_file_path = "/tmp/config.json"
        mock_services.settings_store.load.return_value = mock_settings

        # Mock data check to return False initially, then True after download
        with patch.object(
            data_prep_step, "_check_pair_data", side_effect=[False, True]
        ):
            # Mock successful download
            mock_services.data_download_runner.run_download.return_value = "download_123"

            result = await data_prep_step.execute(
                pairs=["BTC/USDT"],
                timeframe="5m",
                timerange="20240101-20240131",
            )

        assert result.status == AeRoing4StepStatus.PASSED
        assert result.data["coverage_check_passed"] is True
        assert "BTC/USDT" in result.data["missing_pairs_downloaded"]

    @pytest.mark.asyncio
    async def test_download_failure(self, data_prep_step, mock_services):
        """Test data preparation handles download failure."""
        # Mock settings
        mock_settings = Mock()
        mock_settings.user_data_directory_path = "/tmp/user_data"
        mock_settings.default_config_file_path = "/tmp/config.json"
        mock_services.settings_store.load.return_value = mock_settings

        # Mock data check to return False
        mock_services.backtest_runner._check_data_covers_timerange.return_value = False

        # Mock download failure
        from backend.core.errors import BackendError
        mock_services.data_download_runner.run_download.side_effect = BackendError(
            "Download failed", status_code=500
        )

        result = await data_prep_step.execute(
            pairs=["BTC/USDT"],
            timeframe="5m",
            timerange="20240101-20240131",
        )

        assert result.status == AeRoing4StepStatus.FAILED
        assert result.data["coverage_check_passed"] is False
        assert "download_errors" in result.data

    @pytest.mark.asyncio
    async def test_incomplete_coverage_after_download(self, data_prep_step, mock_services):
        """Test data preparation fails when coverage check fails after download."""
        # Mock settings
        mock_settings = Mock()
        mock_settings.user_data_directory_path = "/tmp/user_data"
        mock_settings.default_config_file_path = "/tmp/config.json"
        mock_services.settings_store.load.return_value = mock_settings

        # Mock data check to return False even after download
        mock_services.backtest_runner._check_data_covers_timerange.return_value = False

        # Mock successful download but data still not ready
        mock_services.data_download_runner.run_download.return_value = "download_123"

        result = await data_prep_step.execute(
            pairs=["BTC/USDT"],
            timeframe="5m",
            timerange="20240101-20240131",
        )

        assert result.status == AeRoing4StepStatus.FAILED
        assert result.data["coverage_check_passed"] is False
        assert "No smoke pair has usable data" in result.error

    @pytest.mark.asyncio
    async def test_exception_handling(self, data_prep_step, mock_services):
        """Test that exceptions are handled gracefully."""
        mock_services.settings_store.load.side_effect = Exception("Settings error")

        result = await data_prep_step.execute(
            pairs=["BTC/USDT"],
            timeframe="5m",
            timerange="20240101-20240131",
        )

        assert result.status == AeRoing4StepStatus.FAILED
        assert "Data preparation step failed" in result.error

    @pytest.mark.asyncio
    async def test_multiple_pairs_mixed_readiness(self, data_prep_step, mock_services):
        """Test data preparation with multiple pairs having mixed readiness."""
        # Mock settings
        mock_settings = Mock()
        mock_settings.user_data_directory_path = "/tmp/user_data"
        mock_settings.default_config_file_path = "/tmp/config.json"
        mock_services.settings_store.load.return_value = mock_settings

        # Mock data check: BTC ready, ETH not ready, then both ready
        with patch.object(
            data_prep_step, "_check_pair_data", side_effect=[True, False, True, True]
        ):
            # Mock successful download for ETH
            mock_services.data_download_runner.run_download.return_value = "download_123"

            result = await data_prep_step.execute(
                pairs=["BTC/USDT", "ETH/USDT"],
                timeframe="5m",
                timerange="20240101-20240131",
            )

        assert result.status == AeRoing4StepStatus.PASSED
        assert result.data["pairs_ready"]["BTC/USDT"] is True
        assert result.data["pairs_ready"]["ETH/USDT"] is True
        assert "ETH/USDT" in result.data["missing_pairs_downloaded"]
