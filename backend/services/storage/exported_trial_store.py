"""services/storage/exported_trial_store.py — persistence for exported optimizer trials.

Wraps data/exported_optimizer_runs.json with load / append / list helpers.
Thread-safety is not required: the temporal stress lab router calls this only from
a single background task coroutine at a time, and the export endpoints are
fire-and-forget writes.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ExportedTrialStore:
    """Flat-file persistence for exported optimizer trial configurations."""

    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path

    # ── internal helpers ──────────────────────────────────────────────────────

    def _load_raw(self) -> list[dict[str, Any]]:
        if not self.store_path.exists():
            return []
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_raw(self, records: list[dict[str, Any]]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.store_path)

    # ── public API ────────────────────────────────────────────────────────────

    def list_all(self) -> list[dict[str, Any]]:
        """Return all exported trial records, newest first."""
        records = self._load_raw()
        records.sort(key=lambda r: r.get("exported_at", ""), reverse=True)
        return records

    def find_by_id(self, trial_id: str) -> dict[str, Any] | None:
        """Return the record with the given id, or None."""
        for rec in self._load_raw():
            if rec.get("id") == trial_id:
                return rec
        return None

    def append(
        self,
        *,
        strategy_name: str,
        trial_number: int,
        score: float | None,
        parameters: dict[str, Any],
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        """Create and persist a new ExportedTrial record. Returns the new record."""
        score_val = float(score) if score is not None else 0.0
        score_str = f"{score_val:.2f}"
        record: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "label": f"[Opt] {strategy_name} - Trial #{trial_number} (Score: {score_str})",
            "strategy_name": strategy_name,
            "trial_number": trial_number,
            "score": score_val,
            "parameters": parameters,
            "metrics": metrics,
            "exported_at": datetime.now(tz=UTC).isoformat(),
        }
        records = self._load_raw()
        records.append(record)
        self._save_raw(records)
        return record
