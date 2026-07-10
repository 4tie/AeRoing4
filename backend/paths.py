"""paths.py contains backend logic for paths.

This file is intentionally documented in plain English so readers can follow
what each section does even without deep Python experience.
"""

from __future__ import annotations
from pathlib import Path

from .models import LocalPaths, SettingsModel
from .utils import ensure_directory


def build_local_paths(root_dir: Path, settings: SettingsModel) -> LocalPaths:
    """build_local_paths implements function-level backend logic."""
    strategies_dir = Path(settings.strategies_directory_path)
    user_data_dir = Path(settings.user_data_directory_path)
    versions_root = user_data_dir / "strategies" / "versions"
    backtest_results_root = user_data_dir / "backtest_results"
    data_downloads_root = user_data_dir / "data_downloads"
    pair_selector_data_dir = user_data_dir / "pair_selector"
    optimizer_root = user_data_dir / "optimizer_sessions"
    sweep_root = user_data_dir / "backtest_results" / "_sweeps"
    backups_root = root_dir / "data" / "backups"
    ensure_directory(versions_root)
    ensure_directory(backtest_results_root)
    ensure_directory(data_downloads_root)
    ensure_directory(pair_selector_data_dir)
    ensure_directory(optimizer_root)
    ensure_directory(sweep_root)
    ensure_directory(backups_root)
    return LocalPaths(
        root_dir=root_dir,
        settings_file=root_dir / "data" / "strategy_lab_settings.json",
        app_log_file=root_dir / "data" / "app.log",
        data_downloads_root=data_downloads_root,
        strategies_dir=strategies_dir,
        versions_root=versions_root,
        backtest_results_root=backtest_results_root,
        default_config_file=Path(settings.default_config_file_path),
        pair_selector_data_dir=pair_selector_data_dir,
        optimizer_root=optimizer_root,
        sweep_root=sweep_root,
        backups_root=backups_root,
    )
