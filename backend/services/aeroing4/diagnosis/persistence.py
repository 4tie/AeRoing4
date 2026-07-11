"""Persistence for diagnosis results.

Provides atomic save/load/reload/list operations for DiagnosisResult.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .models import DiagnosisResult


class DiagnosisStore:
    """Store for diagnosis results with atomic persistence and history support."""

    def __init__(self, runs_root: str):
        """Initialize the diagnosis store.

        Args:
            runs_root: Path to the runs directory
        """
        self.runs_root = Path(runs_root)
        self.diagnoses_file = self.runs_root / "diagnoses.json"

    def save(self, result: DiagnosisResult) -> None:
        """Save a diagnosis result atomically.

        Args:
            result: DiagnosisResult to save
        """
        # Ensure directory exists
        self.diagnoses_file.parent.mkdir(parents=True, exist_ok=True)

        # Load existing diagnoses
        existing = self.load_all()

        # Add or update the diagnosis
        existing[result.diagnosis_id] = result.model_dump(mode="json")

        # Write atomically
        temp_file = self.diagnoses_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, default=str)

        # Atomic rename
        temp_file.replace(self.diagnoses_file)

    def load(self, diagnosis_id: str) -> Optional[DiagnosisResult]:
        """Load a specific diagnosis result by ID.

        Args:
            diagnosis_id: The diagnosis ID to load

        Returns:
            DiagnosisResult if found, None otherwise
        """
        all_diagnoses = self.load_all()
        data = all_diagnoses.get(diagnosis_id)
        if data is None:
            return None
        return DiagnosisResult.model_validate(data)

    def load_all(self) -> dict[str, dict]:
        """Load all diagnosis results.

        Returns:
            Dict mapping diagnosis_id to diagnosis data
        """
        if not self.diagnoses_file.exists():
            return {}

        with open(self.diagnoses_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_by_run(self, run_id: str) -> list[DiagnosisResult]:
        """List all diagnosis results for a specific run.

        Args:
            run_id: The run ID to filter by

        Returns:
            List of DiagnosisResult for the run
        """
        all_diagnoses = self.load_all()
        results = []
        for data in all_diagnoses.values():
            if data.get("run_id") == run_id:
                results.append(DiagnosisResult.model_validate(data))
        return results

    def list_by_champion(self, champion_id: str) -> list[DiagnosisResult]:
        """List all diagnosis results for a specific champion.

        Args:
            champion_id: The champion ID to filter by

        Returns:
            List of DiagnosisResult for the champion
        """
        all_diagnoses = self.load_all()
        results = []
        for data in all_diagnoses.values():
            if data.get("champion_id") == champion_id:
                results.append(DiagnosisResult.model_validate(data))
        return results

    def get_latest_for_run(self, run_id: str) -> Optional[DiagnosisResult]:
        """Get the most recent diagnosis for a run.

        Args:
            run_id: The run ID

        Returns:
            Latest DiagnosisResult for the run, or None if none exist
        """
        diagnoses = self.list_by_run(run_id)
        if not diagnoses:
            return None

        # Sort by created_at descending
        diagnoses.sort(key=lambda d: d.created_at, reverse=True)
        return diagnoses[0]

    def get_latest_for_champion(self, champion_id: str) -> Optional[DiagnosisResult]:
        """Get the most recent diagnosis for a champion.

        Args:
            champion_id: The champion ID

        Returns:
            Latest DiagnosisResult for the champion, or None if none exist
        """
        diagnoses = self.list_by_champion(champion_id)
        if not diagnoses:
            return None

        # Sort by created_at descending
        diagnoses.sort(key=lambda d: d.created_at, reverse=True)
        return diagnoses[0]

    def delete(self, diagnosis_id: str) -> bool:
        """Delete a specific diagnosis result.

        Args:
            diagnosis_id: The diagnosis ID to delete

        Returns:
            True if deleted, False if not found
        """
        all_diagnoses = self.load_all()
        if diagnosis_id not in all_diagnoses:
            return False

        del all_diagnoses[diagnosis_id]

        # Write atomically
        temp_file = self.diagnoses_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(all_diagnoses, f, indent=2, default=str)

        temp_file.replace(self.diagnoses_file)
        return True
