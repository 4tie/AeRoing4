"""Snapshot service — timestamped file-system backups of strategy files.

Directory layout:
  data/backups/{strategy_name}/{YYYYMMDD_HHMMSS}/
    {strategy_name}.py        (copy of .py file if it existed)
    {strategy_name}.json      (copy of .json file if it existed)
    _meta.json                (trigger, created_at, file list)

Both strategy_name and timestamp are strictly validated to prevent
path-traversal attacks before any filesystem access.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_\-]+$")
_SAFE_TS   = re.compile(r"^\d{8}_\d{6}$")


class SnapshotService:
    """Creates, lists, and restores timestamped strategy backups."""

    def __init__(self, backups_root: Path) -> None:
        self.backups_root = backups_root

    # ── validation ─────────────────────────────────────────────────────────────

    def _validate_name(self, name: str) -> None:
        if not name or not _SAFE_NAME.match(name):
            raise ValueError(f"Invalid strategy name: {name!r}")

    def _validate_ts(self, ts: str) -> None:
        if not ts or not _SAFE_TS.match(ts):
            raise ValueError(f"Invalid snapshot timestamp: {ts!r}")

    def _strategy_dir(self, strategy_name: str) -> Path:
        self._validate_name(strategy_name)
        return self.backups_root / strategy_name

    # ── public API ─────────────────────────────────────────────────────────────

    def create_snapshot(
        self,
        strategy_name: str,
        strategies_dir: Path,
        trigger: str = "manual_save",
    ) -> dict:
        """Copy current .py + .json into a new timestamped backup folder.

        Returns a dict: {timestamp, files_backed_up, created}.
        If the strategy has no existing files nothing is written and
        ``created`` is False.
        """
        self._validate_name(strategy_name)

        # Gather which source files actually exist right now
        to_copy = [
            f for ext in (".py", ".json")
            if (f := strategies_dir / f"{strategy_name}{ext}").exists()
        ]
        if not to_copy:
            return {"timestamp": "", "files_backed_up": [], "created": False}

        ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        snap_dir = self._strategy_dir(strategy_name) / ts
        snap_dir.mkdir(parents=True, exist_ok=True)

        files_backed: list[str] = []
        for src in to_copy:
            shutil.copy2(src, snap_dir / src.name)
            files_backed.append(src.name)

        meta = {
            "strategy_name": strategy_name,
            "timestamp": ts,
            "trigger": trigger,
            "created_at": datetime.now(tz=UTC).isoformat(),
            "files": files_backed,
        }
        (snap_dir / "_meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        return {"timestamp": ts, "files_backed_up": files_backed, "created": True}

    def list_snapshots(self, strategy_name: str) -> list[dict]:
        """Return all snapshots for a strategy, newest first."""
        self._validate_name(strategy_name)
        strat_dir = self._strategy_dir(strategy_name)
        if not strat_dir.exists():
            return []

        results: list[dict] = []
        for entry in sorted(strat_dir.iterdir(), reverse=True):
            if not entry.is_dir() or not _SAFE_TS.match(entry.name):
                continue
            meta_path = entry / "_meta.json"
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            except Exception:
                meta = {}
            files = sorted(f.name for f in entry.iterdir() if not f.name.startswith("_"))
            results.append({
                "timestamp": entry.name,
                "created_at": meta.get("created_at", ""),
                "trigger": meta.get("trigger", "unknown"),
                "files": files,
            })
        return results

    def restore_snapshot(
        self,
        strategy_name: str,
        timestamp: str,
        strategies_dir: Path,
    ) -> dict:
        """Overwrite active strategy files with a snapshot's backed-up copies.

        Uses atomic rename so no partial writes reach the live files.
        """
        self._validate_name(strategy_name)
        self._validate_ts(timestamp)

        snap_dir = self._strategy_dir(strategy_name) / timestamp
        if not snap_dir.exists():
            raise FileNotFoundError(
                f"Snapshot '{timestamp}' not found for '{strategy_name}'."
            )

        restored: list[str] = []
        for src in snap_dir.iterdir():
            if src.name.startswith("_"):
                continue
            dest = strategies_dir / src.name
            tmp  = dest.with_suffix(dest.suffix + ".tmp")
            shutil.copy2(src, tmp)
            tmp.replace(dest)
            restored.append(src.name)

        if not restored:
            raise ValueError(
                f"Snapshot '{timestamp}' contains no strategy files — nothing restored."
            )

        return {
            "restored_files": sorted(restored),
            "timestamp": timestamp,
            "strategy_name": strategy_name,
        }
