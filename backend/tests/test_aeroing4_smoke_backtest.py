"""Tests for AeRoing4 smoke backtest step."""

from unittest.mock import Mock, AsyncMock, patch

import pytest

from backend.core.errors import BackendError
from backend.models import RunStatus
from backend.services.aeroing4.models import (
    AeRoing4StepStatus,
    SmokeBacktestOutcome,
)
from backend.services.aeroing4.steps.smoke_backtest import SmokeBacktestStep


@pytest.fixture
def mock_services():
    """Create mock services."""
    services = Mock()
    services.registry = Mock()
    services.backtest_runner = Mock()
    services.run_repository = Mock()
    services.version_manager = Mock()
    services.settings_store = Mock()
    return services


@pytest.fixture
def smoke_backtest_step(mock_services):
    """Create smoke backtest step with mock services."""
    return SmokeBacktestStep(mock_services)


class TestSmokeBacktestStep:
    """Test SmokeBacktestStep functionality."""

    @pytest.mark.asyncio
    async def test_successful_run_with_trades(self, smoke_backtest_step, mock_services):
        """Test smoke backtest with trades → PASS_ACTIVITY."""
        # Mock strategy
        mock_strategy = Mock()
        mock_strategy.file_path = "/path/to/strategy.py"
        mock_services.registry.get_strategy.return_value = mock_strategy

        # Mock version manager
        mock_pointer = Mock()
        mock_pointer.accepted_version_id = "v1"
        mock_services.version_manager.get_current_pointer.return_value = mock_pointer

        # Mock settings
        mock_settings = Mock()
        mock_settings.default_config_file_path = "/tmp/config.json"
        mock_services.settings_store.load.return_value = mock_settings

        # Mock backtest execution
        mock_services.backtest_runner.run_backtest.return_value = "run_123"

        # Mock run metadata
        mock_metadata = Mock()
        mock_metadata.run_status = RunStatus.COMPLETED
        mock_services.run_repository.load_metadata.return_value = mock_metadata

        # Mock run detail with trades
        mock_detail = Mock()
        mock_detail.parsed_summary.total_trades = 10
        mock_detail.parsed_summary.net_profit_pct = 5.0
        mock_detail.parsed_summary.profit_factor = 1.5
        mock_detail.parsed_summary.max_drawdown_pct = 0.2
        mock_detail.pair_results = [
            Mock(pair="BTC/USDT", total_trades=5),
            Mock(pair="ETH/USDT", total_trades=5),
        ]
        mock_services.run_repository.load_detail.return_value = mock_detail

        result = await smoke_backtest_step.execute(
            strategy_name="test_strategy",
            version_id="v1",
            pairs=["BTC/USDT", "ETH/USDT"],
            timeframe="5m",
            timerange="20240101-20240131",
        )

        assert result.step_name == "smoke_backtest"
        assert result.status == AeRoing4StepStatus.PASSED
        assert result.data["outcome"] == SmokeBacktestOutcome.PASS_ACTIVITY.value
        assert result.data["backtest_run_id"] == "run_123"
        assert result.data["total_trades"] == 10
        assert result.data["execution_error"] is None

    @pytest.mark.asyncio
    async def test_successful_run_with_zero_trades(self, smoke_backtest_step, mock_services):
        """Test smoke backtest with zero trades → NO_SIGNAL_ACTIVITY."""
        # Mock strategy
        mock_strategy = Mock()
        mock_strategy.file_path = "/path/to/strategy.py"
        mock_services.registry.get_strategy.return_value = mock_strategy

        # Mock version manager
        mock_pointer = Mock()
        mock_pointer.accepted_version_id = "v1"
        mock_services.version_manager.get_current_pointer.return_value = mock_pointer

        # Mock settings
        mock_settings = Mock()
        mock_settings.default_config_file_path = "/tmp/config.json"
        mock_services.settings_store.load.return_value = mock_settings

        # Mock backtest execution
        mock_services.backtest_runner.run_backtest.return_value = "run_123"

        # Mock run metadata
        mock_metadata = Mock()
        mock_metadata.run_status = RunStatus.COMPLETED
        mock_services.run_repository.load_metadata.return_value = mock_metadata

        # Mock run detail with zero trades
        mock_detail = Mock()
        mock_detail.parsed_summary.total_trades = None
        mock_detail.parsed_summary.net_profit_pct = 0.0
        mock_detail.parsed_summary.profit_factor = None
        mock_detail.parsed_summary.max_drawdown_pct = None
        mock_detail.pair_results = []
        mock_detail.trades = []
        mock_services.run_repository.load_detail.return_value = mock_detail

        result = await smoke_backtest_step.execute(
            strategy_name="test_strategy",
            version_id="v1",
            pairs=["BTC/USDT"],
            timeframe="5m",
            timerange="20240101-20240131",
        )

        assert result.status == AeRoing4StepStatus.PASSED
        assert result.data["outcome"] == SmokeBacktestOutcome.NO_SIGNAL_ACTIVITY.value
        assert result.data["total_trades"] == 0

    @pytest.mark.asyncio
    async def test_freqtrade_execution_error(self, smoke_backtest_step, mock_services):
        """Test smoke backtest with Freqtrade execution error → EXECUTION_FAILURE."""
        # Mock strategy
        mock_strategy = Mock()
        mock_strategy.file_path = "/path/to/strategy.py"
        mock_services.registry.get_strategy.return_value = mock_strategy

        # Mock version manager
        mock_pointer = Mock()
        mock_pointer.accepted_version_id = "v1"
        mock_services.version_manager.get_current_pointer.return_value = mock_pointer

        # Mock settings
        mock_settings = Mock()
        mock_settings.default_config_file_path = "/tmp/config.json"
        mock_services.settings_store.load.return_value = mock_settings

        # Mock backtest execution failure
        mock_services.backtest_runner.run_backtest.side_effect = BackendError(
            "Backtest failed", status_code=500
        )

        result = await smoke_backtest_step.execute(
            strategy_name="test_strategy",
            version_id="v1",
            pairs=["BTC/USDT"],
            timeframe="5m",
            timerange="20240101-20240131",
        )

        assert result.status == AeRoing4StepStatus.FAILED
        assert result.data["outcome"] == SmokeBacktestOutcome.EXECUTION_FAILURE.value
        assert result.data["execution_error"] == "Backtest failed"

    @pytest.mark.asyncio
    async def test_run_status_failed(self, smoke_backtest_step, mock_services, tmp_path):
        """Test smoke backtest when run status is FAILED."""
        # Mock strategy
        mock_strategy = Mock()
        mock_strategy.file_path = "/path/to/strategy.py"
        mock_services.registry.get_strategy.return_value = mock_strategy

        # Mock version manager
        mock_pointer = Mock()
        mock_pointer.accepted_version_id = "v1"
        mock_services.version_manager.get_current_pointer.return_value = mock_pointer

        # Mock settings
        mock_settings = Mock()
        mock_settings.default_config_file_path = "/tmp/config.json"
        mock_services.settings_store.load.return_value = mock_settings

        # Mock backtest execution
        mock_services.backtest_runner.run_backtest.return_value = "run_123"

        # Mock run metadata with FAILED status
        mock_metadata = Mock()
        mock_metadata.run_status = RunStatus.FAILED
        mock_services.run_repository.load_metadata.return_value = mock_metadata
        run_dir = tmp_path / "run_123"
        run_dir.mkdir()
        (run_dir / "logs.txt").write_text(
            "stderr: 2026-07-12 07:40:00,000 - freqtrade - ERROR - Could not load markets, therefore cannot start.\n",
            encoding="utf-8",
        )
        mock_services.run_repository.find_run_dir.return_value = run_dir
        mock_detail = Mock()
        mock_detail.parsed_summary = None
        mock_detail.pair_results = []
        mock_services.run_repository.load_detail.return_value = mock_detail

        result = await smoke_backtest_step.execute(
            strategy_name="test_strategy",
            version_id="v1",
            pairs=["BTC/USDT"],
            timeframe="5m",
            timerange="20240101-20240131",
        )

        assert result.status == AeRoing4StepStatus.FAILED
        assert result.data["outcome"] == SmokeBacktestOutcome.EXECUTION_FAILURE.value
        assert result.data["execution_error"] == "Could not load markets, therefore cannot start."
        assert result.error == "Could not load markets, therefore cannot start."

    @pytest.mark.asyncio
    async def test_no_accepted_version(self, smoke_backtest_step, mock_services):
        """Test smoke backtest fails when strategy has no accepted version."""
        # Mock strategy
        mock_strategy = Mock()
        mock_strategy.file_path = "/path/to/strategy.py"
        mock_services.registry.get_strategy.return_value = mock_strategy

        # Mock version manager with no accepted version
        mock_services.version_manager.get_current_pointer.return_value = None

        result = await smoke_backtest_step.execute(
            strategy_name="test_strategy",
            version_id=None,  # Don't provide version_id to trigger version manager check
            pairs=["BTC/USDT"],
            timeframe="5m",
            timerange="20240101-20240131",
        )

        assert result.status == AeRoing4StepStatus.FAILED
        assert "Strategy has no accepted version" in result.error

    @pytest.mark.asyncio
    async def test_exception_handling(self, smoke_backtest_step, mock_services):
        """Test that exceptions are handled gracefully."""
        mock_services.registry.get_strategy.side_effect = Exception("Registry error")

        result = await smoke_backtest_step.execute(
            strategy_name="test_strategy",
            version_id="v1",
            pairs=["BTC/USDT"],
            timeframe="5m",
            timerange="20240101-20240131",
        )

        assert result.status == AeRoing4StepStatus.FAILED
        assert "Smoke backtest step failed" in result.error
