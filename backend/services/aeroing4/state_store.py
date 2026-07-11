"""AeRoing4 state store for persistent run management."""

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .models import AeRoing4Run, AeRoing4RunStatus


class AeRoing4StateStore:
    """Persistent store for AeRoing4 run state.

    Runs are persisted to user_data/aeroing4/runs/{run_id}/state.json
    Uses atomic writes to prevent corruption.
    """

    def __init__(self, runs_root: Path):
        """Initialize state store with runs directory."""
        self.runs_root = runs_root
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._active_run_id: str | None = None

    def create_run(
        self,
        strategy_name: str,
        timeframe: str = "5m",
        smoke_timerange: str = "20240101-20240131",
        smoke_pairs: list[str] | None = None,
        enable_pair_discovery: bool = False,
        discovery_pairs: list[str] | None = None,
        discovery_timerange: str | None = None,
        confirmation_timerange: str | None = None,
        final_unseen_timerange: str | None = None,
        pair_selection_mode: str | None = None,
        target_pair_count: int = 4,
        manually_selected_pairs: list[str] | None = None,
        exchange: str = "binance",
        trading_mode: str = "spot",
        max_open_trades: int = 4,
        dry_run_wallet: float = 1000.0,
        config_file: str = "config.json",
        enable_research_loop: bool = False,
        enable_focused_hyperopt: bool = False,
    ) -> AeRoing4Run:
        """Create a new AeRoing4 run with generated run_id."""
        run_id = str(uuid.uuid4())
        if smoke_pairs is None:
            smoke_pairs = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]

        run = AeRoing4Run(
            run_id=run_id,
            strategy_name=strategy_name,
            timeframe=timeframe,
            smoke_timerange=smoke_timerange,
            smoke_pairs=smoke_pairs,
            enable_pair_discovery=enable_pair_discovery,
            discovery_pairs=discovery_pairs,
            discovery_timerange=discovery_timerange,
            confirmation_timerange=confirmation_timerange,
            final_unseen_timerange=final_unseen_timerange,
            pair_selection_mode=pair_selection_mode,
            target_pair_count=target_pair_count,
            manually_selected_pairs=manually_selected_pairs,
            exchange=exchange,
            trading_mode=trading_mode,
            max_open_trades=max_open_trades,
            dry_run_wallet=dry_run_wallet,
            config_file=config_file,
            enable_research_loop=enable_research_loop,
            enable_focused_hyperopt=enable_focused_hyperopt,
        )
        self.save_run(run)
        return run

    def load_run(self, run_id: str) -> AeRoing4Run | None:
        """Load a run by ID, return None if not found."""
        state_file = self._state_file(run_id)
        if not state_file.exists():
            return None

        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            return AeRoing4Run.model_validate(data)
        except Exception:
            return None

    def save_run(self, run: AeRoing4Run) -> None:
        """Atomically save run state to disk."""
        state_file = self._state_file(run.run_id)
        state_file.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            # Atomic write via temp file
            temp_file = state_file.with_suffix(".tmp")
            try:
                temp_file.write_text(
                    run.model_dump_json(indent=2), encoding="utf-8"
                )
                temp_file.replace(state_file)
            except Exception:
                temp_file.unlink(missing_ok=True)
                raise

    def update_run(self, run_id: str, **updates) -> AeRoing4Run | None:
        """Update run fields and persist."""
        run = self.load_run(run_id)
        if run is None:
            return None

        for key, value in updates.items():
            if hasattr(run, key):
                setattr(run, key, value)

        run.updated_at = datetime.now(UTC)
        self.save_run(run)
        return run

    def list_runs(self, status: AeRoing4RunStatus | None = None) -> list[AeRoing4Run]:
        """List all runs, optionally filtered by status."""
        runs = []
        for run_dir in self.runs_root.iterdir():
            if not run_dir.is_dir():
                continue
            run = self.load_run(run_dir.name)
            if run and (status is None or run.status == status):
                runs.append(run)

        return sorted(runs, key=lambda r: r.created_at, reverse=True)

    def delete_run(self, run_id: str) -> bool:
        """Delete a run directory."""
        run_dir = self._run_dir(run_id)
        if not run_dir.exists():
            return False

        import shutil
        shutil.rmtree(run_dir)
        return True

    def set_active_run(self, run_id: str | None) -> None:
        """Set the currently active run (for single-execution enforcement)."""
        with self._lock:
            self._active_run_id = run_id

    def get_active_run(self) -> str | None:
        """Get the currently active run ID."""
        with self._lock:
            return self._active_run_id

    def is_active_run(self, run_id: str) -> bool:
        """Check if a run is currently active."""
        with self._lock:
            return self._active_run_id == run_id

    def _state_file(self, run_id: str) -> Path:
        """Get the state file path for a run."""
        return self._run_dir(run_id) / "state.json"

    def _run_dir(self, run_id: str) -> Path:
        """Get the run directory for a run ID."""
        return self.runs_root / run_id
