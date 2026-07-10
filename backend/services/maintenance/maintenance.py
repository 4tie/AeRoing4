"""services/maintenance/maintenance.py contains backend logic for maintenance.

This file is intentionally documented in plain English so readers can follow
what each section does even without deep Python experience.
"""

from __future__ import annotations
import shutil
from pathlib import Path


class MaintenanceService:
    """MaintenanceService contains class-level backend logic."""
    def __init__(
        self,
        *,
        root_dir: Path,
        user_data_dir: Path,
        app_log_file: Path,
        data_downloads_root: Path,
    ) -> None:
        """__init__ implements function-level backend logic."""
        self.root_dir = root_dir
        self.user_data_dir = user_data_dir
        self.app_log_file = app_log_file
        self.data_downloads_root = data_downloads_root

    def plan_cleanup_targets(self) -> dict[str, list[str]]:
        """plan_cleanup_targets implements function-level backend logic."""
        file_targets = [
            self.app_log_file,
            self.user_data_dir / "process.log",
            self.user_data_dir / "services.log",
        ]
        directory_targets = [
            self.user_data_dir / "logs",
            self.data_downloads_root,
        ]
        pycache_targets = list((self.root_dir / "backend").rglob("__pycache__"))
        return {
            "files": [str(path) for path in file_targets],
            "directories": [str(path) for path in directory_targets],
            "pycache_directories": [str(path) for path in pycache_targets],
        }

    def cleanup(self) -> dict[str, list[str]]:
        """cleanup implements function-level backend logic."""
        deleted_files: list[str] = []
        deleted_directories: list[str] = []
        failed_targets: list[str] = []

        for file_path in [
            self.app_log_file,
            self.user_data_dir / "process.log",
            self.user_data_dir / "services.log",
        ]:
            if not file_path.exists():
                continue
            try:
                file_path.unlink()
                deleted_files.append(str(file_path.resolve()))
            except OSError:
                failed_targets.append(str(file_path.resolve()))

        for directory in [self.user_data_dir / "logs", self.data_downloads_root]:
            if not directory.exists() or not directory.is_dir():
                continue
            for child in directory.iterdir():
                if self._remove_path(child):
                    deleted_directories.append(str(child.resolve()))
                else:
                    failed_targets.append(str(child.resolve()))

        for pycache_dir in (self.root_dir / "backend").rglob("__pycache__"):
            if self._remove_path(pycache_dir):
                deleted_directories.append(str(pycache_dir.resolve()))
            else:
                failed_targets.append(str(pycache_dir.resolve()))

        return {
            "deleted_files": deleted_files,
            "deleted_directories": deleted_directories,
            "failed_targets": failed_targets,
        }

    def _remove_path(self, path: Path) -> bool:
        """_remove_path implements function-level backend logic."""
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            return True
        except OSError:
            return False
