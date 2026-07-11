"""Tests for Portfolio Baseline configuration propagation.

Tests that custom configuration values propagate through:
Request -> Run -> State -> Portfolio Baseline -> Baseline Result config snapshot
"""

import pytest
from pathlib import Path
from backend.services.aeroing4.models import AeRoing4RunRequest, AeRoing4Run
from backend.services.aeroing4.state_store import AeRoing4StateStore
from backend.services.aeroing4.orchestrator import AeRoing4Orchestrator


def test_request_model_has_configuration_fields():
    """Test that AeRoing4RunRequest has configuration fields."""
    request = AeRoing4RunRequest(
        strategy_name="test_strategy",
        exchange="binance",
        trading_mode="spot",
        max_open_trades=4,
        dry_run_wallet=1000.0,
        config_file="config.json",
    )

    assert request.exchange == "binance"
    assert request.trading_mode == "spot"
    assert request.max_open_trades == 4
    assert request.dry_run_wallet == 1000.0
    assert request.config_file == "config.json"


def test_request_model_defaults():
    """Test that AeRoing4RunRequest has safe defaults."""
    request = AeRoing4RunRequest(strategy_name="test_strategy")

    assert request.exchange == "binance"
    assert request.trading_mode == "spot"
    assert request.max_open_trades == 4
    assert request.dry_run_wallet == 1000.0
    assert request.config_file == "config.json"


def test_run_model_has_configuration_fields():
    """Test that AeRoing4Run has configuration fields."""
    run = AeRoing4Run(
        run_id="test-run-id",
        strategy_name="test_strategy",
        exchange="binance",
        trading_mode="spot",
        max_open_trades=4,
        dry_run_wallet=1000.0,
        config_file="config.json",
    )

    assert run.exchange == "binance"
    assert run.trading_mode == "spot"
    assert run.max_open_trades == 4
    assert run.dry_run_wallet == 1000.0
    assert run.config_file == "config.json"


def test_run_model_defaults():
    """Test that AeRoing4Run has safe defaults."""
    run = AeRoing4Run(
        run_id="test-run-id",
        strategy_name="test_strategy",
    )

    assert run.exchange == "binance"
    assert run.trading_mode == "spot"
    assert run.max_open_trades == 4
    assert run.dry_run_wallet == 1000.0
    assert run.config_file == "config.json"


def test_state_store_creates_run_with_configuration():
    """Test that StateStore.create_run accepts and persists configuration."""
    runs_root = Path("/tmp/test_aeroing4_runs")
    runs_root.mkdir(parents=True, exist_ok=True)
    state_store = AeRoing4StateStore(runs_root)

    run = state_store.create_run(
        strategy_name="test_strategy",
        exchange="bybit",
        trading_mode="futures",
        max_open_trades=8,
        dry_run_wallet=5000.0,
        config_file="custom_config.json",
    )

    assert run.exchange == "bybit"
    assert run.trading_mode == "futures"
    assert run.max_open_trades == 8
    assert run.dry_run_wallet == 5000.0
    assert run.config_file == "custom_config.json"

    # Test persistence
    loaded_run = state_store.load_run(run.run_id)
    assert loaded_run is not None
    assert loaded_run.exchange == "bybit"
    assert loaded_run.trading_mode == "futures"
    assert loaded_run.max_open_trades == 8
    assert loaded_run.dry_run_wallet == 5000.0
    assert loaded_run.config_file == "custom_config.json"

    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)


def test_state_store_survives_reload():
    """Test that configuration survives state reload."""
    runs_root = Path("/tmp/test_aeroing4_runs_reload")
    runs_root.mkdir(parents=True, exist_ok=True)
    state_store = AeRoing4StateStore(runs_root)

    # Create run with custom configuration
    run = state_store.create_run(
        strategy_name="test_strategy",
        exchange="kraken",
        trading_mode="spot",
        max_open_trades=6,
        dry_run_wallet=2000.0,
        config_file="kraken_config.json",
    )

    # Reload from disk
    reloaded_run = state_store.load_run(run.run_id)
    assert reloaded_run is not None
    assert reloaded_run.exchange == "kraken"
    assert reloaded_run.trading_mode == "spot"
    assert reloaded_run.max_open_trades == 6
    assert reloaded_run.dry_run_wallet == 2000.0
    assert reloaded_run.config_file == "kraken_config.json"

    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)


def test_orchestrator_create_run_accepts_configuration():
    """Test that AeRoing4Orchestrator.create_run accepts configuration."""
    from unittest.mock import Mock
    runs_root = Path("/tmp/test_aeroing4_orchestrator")
    runs_root.mkdir(parents=True, exist_ok=True)
    state_store = AeRoing4StateStore(runs_root)

    # Mock services
    services = Mock()
    services.aeroing4_state_store = state_store

    orchestrator = AeRoing4Orchestrator(services, runs_root)

    run = orchestrator.create_run(
        strategy_name="test_strategy",
        exchange="okx",
        trading_mode="futures",
        max_open_trades=10,
        dry_run_wallet=10000.0,
        config_file="okx_config.json",
    )

    assert run.exchange == "okx"
    assert run.trading_mode == "futures"
    assert run.max_open_trades == 10
    assert run.dry_run_wallet == 10000.0
    assert run.config_file == "okx_config.json"

    # Cleanup
    import shutil
    shutil.rmtree(runs_root, ignore_errors=True)


def test_configuration_changes_identity():
    """Test that changing configuration changes baseline identity."""
    from backend.services.aeroing4.portfolio_baseline.executor import PortfolioBaselineExecutor
    from unittest.mock import Mock

    # Mock services
    services = Mock()
    executor = PortfolioBaselineExecutor(services)

    # Compute input hash with one configuration
    hash1 = executor._compute_input_hash(
        strategy_name="test_strategy",
        version_id=None,
        selected_pairs=["BTC/USDT", "ETH/USDT"],
        develop_timerange="20240101-20240630",
        timeframe="5m",
        max_open_trades=4,
        dry_run_wallet=1000.0,
        exchange="binance",
        trading_mode="spot",
        selection_hash="abc123",
    )

    # Compute input hash with different configuration
    hash2 = executor._compute_input_hash(
        strategy_name="test_strategy",
        version_id=None,
        selected_pairs=["BTC/USDT", "ETH/USDT"],
        develop_timerange="20240101-20240630",
        timeframe="5m",
        max_open_trades=8,  # Changed
        dry_run_wallet=1000.0,
        exchange="binance",
        trading_mode="spot",
        selection_hash="abc123",
    )

    # Hashes should be different
    assert hash1 != hash2


def test_configuration_snapshot_includes_configuration():
    """Test that configuration snapshot includes execution configuration."""
    from backend.services.aeroing4.portfolio_baseline.executor import PortfolioBaselineExecutor
    from unittest.mock import Mock

    # Mock services
    services = Mock()
    executor = PortfolioBaselineExecutor(services)

    config_snapshot = executor._build_config_snapshot(
        config_file="custom_config.json",
        max_open_trades=8,
        dry_run_wallet=5000.0,
        exchange="bybit",
        trading_mode="futures",
    )

    assert config_snapshot["config_file"] == "custom_config.json"
    assert config_snapshot["max_open_trades"] == 8
    assert config_snapshot["dry_run_wallet"] == 5000.0
    assert config_snapshot["exchange"] == "bybit"
    assert config_snapshot["trading_mode"] == "futures"


def test_portfolio_baseline_result_has_configuration_fields():
    """Test that PortfolioBaselineResult has configuration fields."""
    from backend.services.aeroing4.portfolio_baseline.models import PortfolioBaselineResult, PortfolioBaselineOutcome

    result = PortfolioBaselineResult(
        status=PortfolioBaselineOutcome.PASS_BASELINE_CREATED,
        selected_pairs=["BTC/USDT", "ETH/USDT"],
        exchange="binance",
        trading_mode="spot",
        max_open_trades=4,
        wallet_configuration={"dry_run_wallet": 1000.0},
        stake_configuration={"stake_amount": "unlimited"},
    )

    assert result.exchange == "binance"
    assert result.trading_mode == "spot"
    assert result.max_open_trades == 4
    assert result.wallet_configuration == {"dry_run_wallet": 1000.0}
    assert result.stake_configuration == {"stake_amount": "unlimited"}
