"""services/execution/run_progress.py contains backend logic for run progress.

This file is intentionally documented in plain English so readers can follow
what each section does even without deep Python experience.
"""

from __future__ import annotations
import json
import re
from datetime import timedelta
from math import floor
from pathlib import Path

from pydantic import ValidationError

from ...models import (
    RunEtaState,
    RunMetadata,
    RunPhase,
    RunProgress,
    RunProgressUpdateSource,
    RunStatus,
)
from ...utils import append_text, atomic_write_json, utc_now
from ..storage.run_repository import RunRepository


class RunProgressService:
    """RunProgressService contains class-level backend logic."""
    RECOVERY_ORPHAN_NOTE = "[RECOVERY] Run marked as failed on startup due to missing active process.\n"
    RECOVERY_CORRUPT_NOTE = (
        "[RECOVERY] progress.json missing or invalid; synthesized failed-safe progress state.\n"
    )

    PHASE_BOUNDS: dict[RunPhase, tuple[int, int]] = {
        RunPhase.QUEUED: (0, 0),
        RunPhase.INITIALIZING: (1, 9),
        RunPhase.DATA_LOADING: (10, 29),
        RunPhase.INDICATOR_CALCULATION: (30, 49),
        RunPhase.BACKTESTING: (50, 89),
        RunPhase.FINALIZING: (90, 99),
        RunPhase.COMPLETED: (100, 100),
        RunPhase.FAILED: (0, 99),
        RunPhase.CANCELLED: (0, 99),
    }

    PHASE_LABELS: dict[RunPhase, str] = {
        RunPhase.QUEUED: "Queued",
        RunPhase.INITIALIZING: "Starting Freqtrade",
        RunPhase.DATA_LOADING: "Loading OHLCV data",
        RunPhase.INDICATOR_CALCULATION: "Calculating indicators",
        RunPhase.BACKTESTING: "Running backtest simulation",
        RunPhase.FINALIZING: "Parsing and saving results",
        RunPhase.COMPLETED: "Completed",
        RunPhase.FAILED: "Failed",
        RunPhase.CANCELLED: "Cancelled",
    }

    PHASE_WINDOWS_SECONDS: dict[RunPhase, int] = {
        RunPhase.INITIALIZING: 12,
        RunPhase.DATA_LOADING: 18,
        RunPhase.INDICATOR_CALCULATION: 12,
        RunPhase.BACKTESTING: 60,
        RunPhase.FINALIZING: 12,
    }

    PHASE_MARKERS: tuple[tuple[re.Pattern[str], RunPhase], ...] = (
        (re.compile(r"using config:|using resolved strategy|starting freqtrade in backtesting mode", re.I), RunPhase.INITIALIZING),
        (re.compile(r"loading data from", re.I), RunPhase.DATA_LOADING),
        (re.compile(r"dataload complete\. calculating indicators", re.I), RunPhase.INDICATOR_CALCULATION),
        (re.compile(r"backtesting with data from", re.I), RunPhase.BACKTESTING),
        (re.compile(r"result for strategy|summary metrics|backtested .*max open trades", re.I), RunPhase.FINALIZING),
    )

    ALLOWED_TRANSITIONS: dict[RunPhase, set[RunPhase]] = {
        RunPhase.QUEUED: {RunPhase.QUEUED, RunPhase.INITIALIZING, RunPhase.FAILED, RunPhase.CANCELLED},
        RunPhase.INITIALIZING: {
            RunPhase.INITIALIZING,
            RunPhase.DATA_LOADING,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
        },
        RunPhase.DATA_LOADING: {
            RunPhase.DATA_LOADING,
            RunPhase.INDICATOR_CALCULATION,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
        },
        RunPhase.INDICATOR_CALCULATION: {
            RunPhase.INDICATOR_CALCULATION,
            RunPhase.BACKTESTING,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
        },
        RunPhase.BACKTESTING: {
            RunPhase.BACKTESTING,
            RunPhase.FINALIZING,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
        },
        RunPhase.FINALIZING: {
            RunPhase.FINALIZING,
            RunPhase.COMPLETED,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
        },
        RunPhase.COMPLETED: {RunPhase.COMPLETED},
        RunPhase.FAILED: {RunPhase.FAILED},
        RunPhase.CANCELLED: {RunPhase.CANCELLED},
    }

    def __init__(self, run_repository: RunRepository) -> None:
        """__init__ implements function-level backend logic."""
        self.run_repository = run_repository

    def initialize_progress(self, run_dir: Path, started_at) -> RunProgress:
        """initialize_progress implements function-level backend logic."""
        progress = self._build_progress(
            phase=RunPhase.QUEUED,
            progress_pct=0,
            started_at=started_at,
            phase_started_at=started_at,
            updated_at=started_at,
            last_update_source=RunProgressUpdateSource.LOG_MARKER,
        )
        self._write_progress(run_dir, progress)
        return progress

    def load_progress(self, run_dir: Path, metadata: RunMetadata, *, refresh: bool = True) -> RunProgress:
        """load_progress implements function-level backend logic."""
        progress, raw_text, invalid = self._read_progress(run_dir)
        if progress is None:
            progress = self._recover_progress(run_dir, metadata, raw_text=raw_text, invalid=invalid)
            metadata = self.run_repository.load_metadata(metadata.run_id)
        if metadata.run_status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
            progress = self._sync_terminal(run_dir, metadata, progress)
            return progress
        if refresh:
            progress = self._refresh_nonterminal(run_dir, metadata, progress)
        return progress

    def update_phase(
        self,
        run_dir: Path,
        metadata: RunMetadata,
        target_phase: RunPhase,
        *,
        source: RunProgressUpdateSource,
    ) -> RunProgress:
        """update_phase implements function-level backend logic."""
        progress = self.load_progress(run_dir, metadata, refresh=False)
        if progress.terminal:
            return progress
        now = utc_now()
        if target_phase in {RunPhase.COMPLETED, RunPhase.FAILED, RunPhase.CANCELLED}:
            terminal = self._build_terminal_progress(progress, metadata, target_phase, now)
            terminal = self._apply_eta(terminal, now)
            return self._write_progress(run_dir, terminal)
        if target_phase == progress.phase:
            next_progress = self._interpolate(progress, now)
            next_progress = next_progress.model_copy(
                update={
                    "updated_at": now,
                    "elapsed_seconds": self._elapsed_seconds(next_progress.started_at, now),
                    "last_update_source": source,
                }
            )
            next_progress = self._apply_eta(next_progress, now)
            return self._write_progress(run_dir, next_progress)
        if target_phase not in self.ALLOWED_TRANSITIONS[progress.phase]:
            append_text(
                run_dir / "logs.txt",
                (
                    f"[PROGRESS] Ignored invalid phase jump from {progress.phase} "
                    f"to {target_phase.value}; continuing interpolation.\n"
                ),
            )
            next_progress = self._apply_eta(self._interpolate(progress, now), now)
            return self._write_progress(run_dir, next_progress)

        lower, upper = self.PHASE_BOUNDS[target_phase]
        next_progress = self._build_progress(
            phase=target_phase,
            progress_pct=self._clamp(max(progress.progress_pct, lower), lower, upper),
            started_at=progress.started_at,
            phase_started_at=now,
            updated_at=now,
            last_update_source=source,
        )
        next_progress = self._apply_eta(next_progress, now)
        return self._write_progress(run_dir, next_progress)

    def record_log_line(self, run_dir: Path, metadata: RunMetadata, line: str) -> RunProgress | None:
        """record_log_line implements function-level backend logic."""
        clean_line = line.strip()
        if not clean_line:
            return None
        for pattern, phase in self.PHASE_MARKERS:
            if pattern.search(clean_line):
                return self.update_phase(
                    run_dir,
                    metadata,
                    phase,
                    source=RunProgressUpdateSource.LOG_MARKER,
                )
        return None

    def mark_terminal(self, run_dir: Path, metadata: RunMetadata, phase: RunPhase) -> RunProgress:
        """mark_terminal implements function-level backend logic."""
        return self.update_phase(
            run_dir,
            metadata,
            phase,
            source=RunProgressUpdateSource.TERMINAL_UPDATE,
        )

    def recover_orphaned_runs(self) -> None:
        """recover_orphaned_runs implements function-level backend logic."""
        now = utc_now()
        for metadata in self.run_repository.list_runs():
            if metadata.run_status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
                continue
            
            # Only mark as orphaned if it's been idle for more than 5 minutes
            # This prevents immediately marking new runs as failed
            idle_time = now - metadata.created_at
            if idle_time < timedelta(minutes=5):
                continue
                
            run_dir = self.run_repository.find_run_dir(metadata.run_id)
            append_text(run_dir / "logs.txt", self.RECOVERY_ORPHAN_NOTE)
            updated = metadata.model_copy(
                update={
                    "run_status": RunStatus.FAILED,
                    "completed_at": now,
                }
            )
            self.run_repository.save_metadata(metadata.run_id, updated)
            progress, raw_text, _ = self._read_progress(run_dir)
            recovered_pct = self._recover_percent(raw_text)
            if progress is None:
                progress = self._terminal_from_metadata(updated, recovered_pct)
            else:
                progress = self._build_terminal_progress(
                    progress,
                    updated,
                    RunPhase.FAILED,
                    now,
                )
            self._write_progress(run_dir, progress)

    def _refresh_nonterminal(
        self,
        run_dir: Path,
        metadata: RunMetadata,
        progress: RunProgress,
    ) -> RunProgress:
        """_refresh_nonterminal implements function-level backend logic."""
        now = utc_now()
        if metadata.run_status == RunStatus.RUNNING and progress.phase == RunPhase.QUEUED:
            progress = self.update_phase(
                run_dir,
                metadata,
                RunPhase.INITIALIZING,
                source=RunProgressUpdateSource.LOG_MARKER,
            )
            progress = self.load_progress(run_dir, metadata, refresh=False)
        next_progress = self._interpolate(progress, now)
        next_progress = next_progress.model_copy(
            update={
                "updated_at": now,
                "elapsed_seconds": self._elapsed_seconds(next_progress.started_at, now),
                "last_update_source": RunProgressUpdateSource.INTERPOLATION,
            }
        )
        next_progress = self._apply_eta(next_progress, now)
        return self._write_progress(run_dir, next_progress)

    def _read_progress(self, run_dir: Path) -> tuple[RunProgress | None, str | None, bool]:
        """_read_progress implements function-level backend logic."""
        progress_path = self._progress_path(run_dir)
        if not progress_path.exists():
            return None, None, False
        raw_text = progress_path.read_text(encoding="utf-8")
        try:
            return RunProgress.model_validate(json.loads(raw_text)), raw_text, False
        except (json.JSONDecodeError, ValidationError, ValueError):
            return None, raw_text, True

    def _recover_progress(
        self,
        run_dir: Path,
        metadata: RunMetadata,
        *,
        raw_text: str | None,
        invalid: bool,
    ) -> RunProgress:
        """_recover_progress implements function-level backend logic."""
        recovered_pct = self._recover_percent(raw_text)
        if metadata.run_status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
            progress = self._terminal_from_metadata(metadata, recovered_pct)
            self._write_progress(run_dir, progress)
            return progress

        append_text(run_dir / "logs.txt", self.RECOVERY_CORRUPT_NOTE)
        updated = metadata.model_copy(
            update={
                "run_status": RunStatus.FAILED,
                "completed_at": utc_now(),
            }
        )
        self.run_repository.save_metadata(metadata.run_id, updated)
        progress = self._terminal_from_metadata(updated, recovered_pct, failed_safe=True)
        self._write_progress(run_dir, progress)
        return progress

    def _sync_terminal(self, run_dir: Path, metadata: RunMetadata, progress: RunProgress) -> RunProgress:
        """_sync_terminal implements function-level backend logic."""
        terminal_phase = self._phase_from_status(metadata.run_status)
        if progress.terminal and progress.phase == terminal_phase:
            if terminal_phase == RunPhase.COMPLETED and progress.progress_pct != 100:
                progress = progress.model_copy(update={"progress_pct": 100})
                return self._write_progress(run_dir, progress)
            return progress
        now = utc_now()
        progress = self._build_terminal_progress(progress, metadata, terminal_phase, now)
        progress = self._apply_eta(progress, now)
        return self._write_progress(run_dir, progress)

    def _build_terminal_progress(
        self,
        progress: RunProgress,
        metadata: RunMetadata,
        phase: RunPhase,
        now,
    ) -> RunProgress:
        """_build_terminal_progress implements function-level backend logic."""
        if phase == RunPhase.COMPLETED:
            progress_pct = 100
        else:
            progress_pct = max(progress.progress_pct, 0)
        return self._build_progress(
            phase=phase,
            progress_pct=progress_pct,
            started_at=progress.started_at,
            phase_started_at=now,
            updated_at=now,
            last_update_source=RunProgressUpdateSource.TERMINAL_UPDATE,
        )

    def _terminal_from_metadata(
        self,
        metadata: RunMetadata,
        recovered_pct: int,
        *,
        failed_safe: bool = False,
    ) -> RunProgress:
        """_terminal_from_metadata implements function-level backend logic."""
        phase = self._phase_from_status(metadata.run_status)
        started_at = metadata.created_at
        phase_started_at = metadata.completed_at or metadata.created_at
        progress_pct = 100 if phase == RunPhase.COMPLETED else max(recovered_pct, 0)
        source = RunProgressUpdateSource.TERMINAL_UPDATE
        if failed_safe:
            phase = RunPhase.FAILED
        progress = self._build_progress(
            phase=phase,
            progress_pct=progress_pct,
            started_at=started_at,
            phase_started_at=phase_started_at,
            updated_at=metadata.completed_at or utc_now(),
            last_update_source=source,
        )
        return self._apply_eta(progress, progress.updated_at)

    def _build_progress(
        self,
        *,
        phase: RunPhase,
        progress_pct: int,
        started_at,
        phase_started_at,
        updated_at,
        last_update_source: RunProgressUpdateSource,
    ) -> RunProgress:
        """_build_progress implements function-level backend logic."""
        lower, upper = self.PHASE_BOUNDS[phase]
        if phase == RunPhase.COMPLETED:
            progress_pct = 100
        elif phase in {RunPhase.FAILED, RunPhase.CANCELLED}:
            progress_pct = max(progress_pct, 0)
        else:
            progress_pct = self._clamp(progress_pct, lower, upper)
        return RunProgress(
            phase=phase,
            progress_pct=progress_pct,
            started_at=started_at,
            phase_started_at=phase_started_at,
            updated_at=updated_at,
            elapsed_seconds=self._elapsed_seconds(started_at, updated_at),
            eta_seconds=None,
            eta_state=RunEtaState.ESTIMATING,
            current_step_label=self.PHASE_LABELS[phase],
            last_update_source=last_update_source,
            terminal=phase in {RunPhase.COMPLETED, RunPhase.FAILED, RunPhase.CANCELLED},
        )

    def _interpolate(self, progress: RunProgress, now) -> RunProgress:
        """_interpolate implements function-level backend logic."""
        if progress.terminal or progress.phase in {RunPhase.QUEUED, RunPhase.COMPLETED}:
            return progress
        if progress.phase in {RunPhase.FAILED, RunPhase.CANCELLED}:
            return progress
        lower, upper = self.PHASE_BOUNDS[progress.phase]
        window_seconds = self.PHASE_WINDOWS_SECONDS.get(progress.phase)
        if window_seconds is None:
            return progress
        phase_elapsed = max(0, self._elapsed_seconds(progress.phase_started_at, now))
        width = upper - lower
        interpolated = lower + floor(width * min(phase_elapsed / window_seconds, 1.0))
        next_pct = max(progress.progress_pct, interpolated)
        next_pct = self._clamp(next_pct, lower, upper)
        return progress.model_copy(
            update={
                "progress_pct": next_pct,
                "updated_at": now,
                "elapsed_seconds": self._elapsed_seconds(progress.started_at, now),
            }
        )

    def _apply_eta(self, progress: RunProgress, now) -> RunProgress:
        """_apply_eta implements function-level backend logic."""
        elapsed_seconds = self._elapsed_seconds(progress.started_at, now)
        if progress.terminal:
            return progress.model_copy(
                update={
                    "eta_seconds": None,
                    "eta_state": RunEtaState.NOT_APPLICABLE,
                    "elapsed_seconds": elapsed_seconds,
                }
            )
        if progress.phase in {
            RunPhase.QUEUED,
            RunPhase.INITIALIZING,
            RunPhase.DATA_LOADING,
        } or elapsed_seconds < 10 or progress.progress_pct < 5:
            return progress.model_copy(
                update={
                    "eta_seconds": None,
                    "eta_state": RunEtaState.ESTIMATING,
                    "elapsed_seconds": elapsed_seconds,
                }
            )
        eta_seconds = round(elapsed_seconds * (100 - progress.progress_pct) / progress.progress_pct)
        return progress.model_copy(
            update={
                "eta_seconds": max(eta_seconds, 0),
                "eta_state": RunEtaState.AVAILABLE,
                "elapsed_seconds": elapsed_seconds,
            }
        )

    def _phase_from_status(self, status: RunStatus) -> RunPhase:
        """_phase_from_status implements function-level backend logic."""
        return {
            RunStatus.COMPLETED: RunPhase.COMPLETED,
            RunStatus.FAILED: RunPhase.FAILED,
            RunStatus.CANCELLED: RunPhase.CANCELLED,
            RunStatus.RUNNING: RunPhase.INITIALIZING,
            RunStatus.QUEUED: RunPhase.QUEUED,
        }[status]

    def _progress_path(self, run_dir: Path) -> Path:
        """_progress_path implements function-level backend logic."""
        return run_dir / "progress.json"

    def _write_progress(self, run_dir: Path, progress: RunProgress) -> RunProgress:
        """_write_progress implements function-level backend logic."""
        atomic_write_json(self._progress_path(run_dir), progress.model_dump(mode="json"))
        return progress

    def _recover_percent(self, raw_text: str | None) -> int:
        """_recover_percent implements function-level backend logic."""
        if not raw_text:
            return 0
        match = re.search(r'"progress_pct"\s*:\s*(\d+)', raw_text)
        if not match:
            return 0
        return self._clamp(int(match.group(1)), 0, 100)

    def _elapsed_seconds(self, started_at, current_at) -> int:
        """_elapsed_seconds implements function-level backend logic."""
        return max(0, round((current_at - started_at).total_seconds()))

    def _clamp(self, value: int, minimum: int, maximum: int) -> int:
        """_clamp implements function-level backend logic."""
        return max(minimum, min(value, maximum))
