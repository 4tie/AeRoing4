"""Read-only observability context for the local agent layer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from backend.core.errors import BackendError
from backend.services.auto_quant import pipeline as auto_quant_pipeline
from backend.services.readiness_service import ReadinessService
from backend.utils import atomic_write_json, read_json

if TYPE_CHECKING:
    from backend.services.interfaces import IRunRepository, ISettingsStore


AGENT_CONTEXT_SCHEMA = "agent_context_v1"
UI_STATE_SCHEMA = "agent_ui_state_v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump_model(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return [_dump_model(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _dump_model(item) for key, item in value.items()}
    return value


def _tail_text(path: Path, limit: int = 100) -> list[str]:
    if not path.exists() or not path.is_file():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, limit):]
    except OSError:
        return []


def _file_record(path: Path, root: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
        rel = str(path.relative_to(root))
    except (OSError, ValueError):
        stat = None
        rel = path.name
    return {
        "name": path.name,
        "relative_path": rel,
        "suffix": path.suffix,
        "size_bytes": stat.st_size if stat else None,
        "modified_at": (
            datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
            if stat
            else None
        ),
        "content_available": False,
    }


def _file_inventory(root: Path, *, max_files: int = 150) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if len(files) >= max_files:
            break
        if "__pycache__" in path.parts:
            continue
        if path.is_file():
            files.append(path)
    return [_file_record(path, root) for path in files]


def _selected_report_metrics(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    keys = (
        "score",
        "validation_status",
        "readiness_label",
        "sanity_backtest",
        "oos_validation",
        "risk",
        "monte_carlo",
        "stress_test",
        "thresholds",
    )
    return {key: report.get(key) for key in keys if key in report}


def _bounded_dump(items: list[Any], *, limit: int) -> dict[str, Any]:
    total = len(items)
    sample = items[-max(1, limit):] if items else []
    return {
        "total": total,
        "sample_count": len(sample),
        "sample": _dump_model(sample),
        "truncated": total > len(sample),
    }


class AgentContextService:
    """Build agent-readable snapshots from backend-owned state and artifacts."""

    def __init__(
        self,
        root_dir: Path,
        run_repository: IRunRepository,
        settings_store: ISettingsStore,
        version_manager: Any | None = None,
        strategy_optimizer: Any | None = None,
        backtest_runner: Any | None = None,
        optimizer_store: Any | None = None,
        sweep_store: Any | None = None,
        run_detail_callable: Any | None = None,
        *,
        log_broadcaster: Any | None = None,
        session_store: Any | None = None,
        candidate_run_lookup: Any | None = None,
    ) -> None:
        self.root_dir: Path = root_dir
        self.run_repository: IRunRepository = run_repository
        self.settings_store: ISettingsStore = settings_store
        self.version_manager: Any = version_manager
        self.strategy_optimizer: Any = strategy_optimizer
        self.backtest_runner: Any = backtest_runner
        self.optimizer_store: Any = optimizer_store
        self.sweep_store: Any = sweep_store
        self.run_detail_callable: Any = run_detail_callable
        self.log_broadcaster: Any = log_broadcaster
        self.session_store: Any = session_store
        self.candidate_run_lookup: Any = candidate_run_lookup

    @property
    def ui_state_path(self) -> Path:
        state_dir = self.root_dir / "data"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / "agent_ui_state.json"

    def load_ui_state(self) -> dict[str, Any]:
        raw = read_json(self.ui_state_path)
        return raw if isinstance(raw, dict) else {}

    def save_ui_state(self, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.load_ui_state()
        cleaned = {key: value for key, value in patch.items() if key != "schema_version"}
        current.update(cleaned)
        current["schema_version"] = UI_STATE_SCHEMA
        current["updated_at"] = _now()
        atomic_write_json(self.ui_state_path, current)
        return current

    def build_context(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        warnings: list[str] = []
        ui_state = self.load_ui_state()
        active = self._resolve_active_context(overrides or {}, ui_state, warnings)

        auto_quant = None
        optimizer = None
        backtest = None
        readiness = None

        if active.get("auto_quant_run_id"):
            try:
                auto_quant = self.auto_quant_run_context(str(active["auto_quant_run_id"]))
            except BackendError as exc:
                warnings.append(exc.message)

        if active.get("optimizer_session_id"):
            try:
                optimizer = self.optimizer_run_context(
                    str(active["optimizer_session_id"]),
                    trial_number=active.get("optimizer_trial_number"),
                )
            except BackendError as exc:
                warnings.append(exc.message)

        if active.get("backtest_run_id"):
            try:
                backtest = self.backtest_run_context(str(active["backtest_run_id"]))
            except BackendError as exc:
                warnings.append(exc.message)

        strategy_name = active.get("strategy_name")
        if not strategy_name:
            strategy_name = self._strategy_from_contexts(auto_quant, optimizer, backtest)
            active["strategy_name"] = strategy_name
            if strategy_name:
                active.setdefault("sources", {})["strategy_name"] = "resolved_from_active_context"

        strategy = None
        if strategy_name:
            try:
                strategy = self.strategy_file_context(str(strategy_name), include_content=False)
                strategy["versions"] = self.strategy_version_context(str(strategy_name))
            except BackendError as exc:
                warnings.append(exc.message)

        if not ui_state:
            warnings.append("No frontend heartbeat has been received yet.")
        readiness_ids = (
            "optimizer_session_id",
            "backtest_run_id",
            "candidate_run_id",
            "stress_session_id",
            "temporal_stress_session_id",
        )
        if any(active.get(key) for key in readiness_ids):
            try:
                readiness = ReadinessService(
                    root_dir=self.root_dir,
                    run_repository=self.run_repository,
                    optimizer_store=self.optimizer_store,
                    sweep_store=self.sweep_store,
                    session_store=self.session_store,
                    candidate_run_lookup=self.candidate_run_lookup,
                ).build_report(
                    strategy_name=strategy_name,
                    optimizer_session_id=active.get("optimizer_session_id"),
                    trial_number=active.get("optimizer_trial_number"),
                    backtest_run_id=active.get("backtest_run_id"),
                    candidate_run_id=active.get("candidate_run_id"),
                    stress_session_id=active.get("stress_session_id"),
                    temporal_stress_session_id=active.get("temporal_stress_session_id"),
                    profile=active.get("readiness_profile"),
                )
            except Exception as exc:  # noqa: BLE001 - context should degrade, not block chat.
                warnings.append(f"Readiness report could not be built: {exc}")

        if not any(active.get(key) for key in ("auto_quant_run_id", *readiness_ids)):
            warnings.append("No active run or optimizer session is selected.")

        return {
            "schema_version": AGENT_CONTEXT_SCHEMA,
            "generated_at": _now(),
            "app": {
                "ui_state": ui_state,
                "active_tab": active.get("active_tab"),
                "active_panel": active.get("active_panel"),
            },
            "active": active,
            "auto_quant": auto_quant,
            "optimizer": optimizer,
            "backtest": backtest,
            "readiness": readiness,
            "strategy": strategy,
            "logs": {
                "source": "log_broadcaster.history" if self.log_broadcaster is not None else None,
                "recent": self._recent_global_logs(),
            },
            "warnings": warnings,
        }

    def _resolve_active_context(
        self,
        overrides: dict[str, Any],
        ui_state: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        fields = (
            "active_tab",
            "active_panel",
            "strategy_name",
            "timeframe",
            "timerange",
            "start_date",
            "end_date",
            "pairs",
            "dry_run_wallet",
            "max_open_trades",
            "backtest_status",
            "auto_quant_run_id",
            "optimizer_session_id",
            "optimizer_trial_number",
            "backtest_run_id",
            "candidate_run_id",
            "stress_session_id",
            "temporal_stress_session_id",
            "readiness_profile",
            "api_session_id",
        )
        active: dict[str, Any] = {"sources": {}}
        for field in fields:
            if overrides.get(field) not in (None, ""):
                active[field] = overrides[field]
                active["sources"][field] = "query"
            elif ui_state.get(field) not in (None, ""):
                active[field] = ui_state[field]
                active["sources"][field] = "ui_state"
            else:
                active[field] = None

        if active["optimizer_session_id"] is None:
            session_id = self._active_optimizer_session_id()
            if session_id:
                active["optimizer_session_id"] = session_id
                active["sources"]["optimizer_session_id"] = "active_service"

        if active["backtest_run_id"] is None:
            run_id = self._active_backtest_run_id()
            if run_id:
                active["backtest_run_id"] = run_id
                active["sources"]["backtest_run_id"] = "active_service"

        if active["auto_quant_run_id"] is None:
            run_id = self._single_running_auto_quant_id(warnings)
            if run_id:
                active["auto_quant_run_id"] = run_id
                active["sources"]["auto_quant_run_id"] = "active_service"

        if active["api_session_id"] and self.session_store is not None:
            record = self.session_store.get(str(active["api_session_id"]))
            active["api_session"] = _dump_model(record) if record else None
            if record is None:
                warnings.append(f"API session '{active['api_session_id']}' was not found.")

        return active

    def _active_optimizer_session_id(self) -> str | None:
        optimizer = self.strategy_optimizer
        if optimizer is None or not hasattr(optimizer, "get_active_session_id"):
            return None
        try:
            return optimizer.get_active_session_id()
        except Exception:
            return None

    def _active_backtest_run_id(self) -> str | None:
        runner = self.backtest_runner
        if runner is None or not hasattr(runner, "get_current_run_id"):
            return None
        try:
            return runner.get_current_run_id()
        except Exception:
            return None

    def _single_running_auto_quant_id(self, warnings: list[str]) -> str | None:
        active_statuses = {"pending", "running", "awaiting_user_approval"}
        run_ids = sorted(
            run_id
            for run_id, state in auto_quant_pipeline.get_states().items()
            if getattr(state, "status", None) in active_statuses
        )
        if len(run_ids) == 1:
            return run_ids[0]
        if len(run_ids) > 1:
            warnings.append("Multiple AutoQuant runs are active; provide auto_quant_run_id explicitly.")
        return None

    def _recent_global_logs(self, limit: int = 100) -> list[str]:
        if self.log_broadcaster is None:
            return []
        try:
            return list(self.log_broadcaster.history)[-max(1, limit):]
        except Exception:
            return []

    def _strategy_from_contexts(
        self,
        auto_quant: dict[str, Any] | None,
        optimizer: dict[str, Any] | None,
        backtest: dict[str, Any] | None,
    ) -> str | None:
        for context in (auto_quant, optimizer, backtest):
            if not context:
                continue
            strategy = context.get("strategy_name") or context.get("strategy", {}).get("name")
            if strategy:
                return str(strategy)
        return None

    def auto_quant_run_context(self, run_id: str) -> dict[str, Any]:
        state = auto_quant_pipeline.get_state(run_id)
        if state is None:
            raise BackendError(f"AutoQuant run '{run_id}' was not found.", status_code=404)

        snapshot = auto_quant_pipeline._state_snapshot(state)
        run_dir = Path(state.user_data_dir) / "auto_quant" / run_id
        report = state.report if isinstance(state.report, dict) else None
        metrics = {
            "source": "auto_quant_pipeline_state",
            "score": state.score,
            "validation_status": state.validation_status,
            "readiness_label": state.readiness_label,
            "score_explanation": state.score_explanation,
            "report": _selected_report_metrics(report),
            "report_source": "state.report" if report else None,
        }
        return {
            "kind": "auto_quant",
            "run_id": run_id,
            "strategy_name": state.strategy,
            "status": state.status,
            "current_stage": state.current_stage,
            "progress_percent": snapshot.get("progress_percent"),
            "state": snapshot,
            "metrics": metrics,
            "stage_reports": snapshot.get("stages", []),
            "events": {
                "source": "auto_quant_event_history",
                "recent": auto_quant_pipeline.get_event_history(run_id, limit=200),
            },
            "files": {
                "root": str(run_dir),
                "artifact_versions": state.artifact_versions,
                "inventory": _file_inventory(run_dir),
            },
        }

    def optimizer_run_context(
        self,
        session_id: str,
        *,
        trial_number: int | str | None = None,
    ) -> dict[str, Any]:
        store = self.optimizer_store
        if store is None:
            raise BackendError("Optimizer store is unavailable.", status_code=500)
        session = store.load_session(session_id)
        if session is None:
            raise BackendError(f"Optimizer session '{session_id}' was not found.", status_code=404)

        session_dir = store.session_dir(session_id)
        trials = list(session.trials or [])
        best_trial = None
        if session.best_trial_number is not None:
            best_trial = next(
                (trial for trial in trials if trial.trial_number == session.best_trial_number),
                None,
            )
        selected_trial = None
        selected_trial_number = None
        if trial_number not in (None, ""):
            try:
                selected_trial_number = int(trial_number)
            except (TypeError, ValueError):
                selected_trial_number = None
            if selected_trial_number is not None:
                selected_trial = next(
                    (trial for trial in trials if trial.trial_number == selected_trial_number),
                    None,
                )
        return {
            "kind": "optimizer",
            "session_id": session_id,
            "strategy_name": session.strategy_name,
            "phase": session.phase,
            "summary": {
                "total_trials": session.total_trials,
                "completed_trials": session.completed_trials,
                "failed_trials": session.failed_trials,
                "elapsed_seconds": session.elapsed_seconds,
                "eta_seconds": session.eta_seconds,
                "best_trial_number": session.best_trial_number,
                "stop_reason": session.stop_reason,
            },
            "config": _dump_model(session.config),
            "metrics": {
                "source": "optimizer_session.best_metrics",
                "best_metrics": _dump_model(session.best_metrics),
                "best_trial_metrics": _dump_model(best_trial.metrics) if best_trial else None,
            },
            "best_trial": _dump_model(best_trial),
            "selected_trial_number": selected_trial_number,
            "selected_trial": _dump_model(selected_trial),
            "recent_trials": [_dump_model(trial) for trial in trials[-50:]],
            "files": {
                "root": str(session_dir),
                "inventory": _file_inventory(session_dir),
            },
        }

    def backtest_run_context(self, run_id: str) -> dict[str, Any]:
        if self.run_detail_callable is None:
            raise BackendError("Run detail service is unavailable.", status_code=500)
        detail = self.run_detail_callable(run_id)
        run_dir = self.run_repository.find_run_dir(run_id)
        metadata = detail.metadata
        return {
            "kind": "backtest",
            "run_id": run_id,
            "strategy_name": getattr(metadata, "strategy_name", None),
            "status": getattr(metadata, "run_status", None),
            "metadata": _dump_model(metadata),
            "progress": _dump_model(getattr(detail, "progress", None)),
            "metrics": {
                "parsed_summary": {
                    "source": "parsed_summary.json",
                    "value": _dump_model(detail.parsed_summary),
                },
                "advanced_metrics": {
                    "source": "advanced_metrics.json",
                    "value": _dump_model(detail.advanced_metrics),
                },
                "pair_results": {
                    "source": "pair_results.json",
                    "value": _dump_model(detail.pair_results),
                },
                "trades": {
                    "source": "trades.json",
                    "value": _bounded_dump(list(getattr(detail, "trades", []) or []), limit=30),
                },
            },
            "logs": {
                "source": "logs.txt",
                "recent": _tail_text(run_dir / "logs.txt", limit=120),
            },
            "files": {
                "root": str(run_dir),
                "inventory": _file_inventory(run_dir),
            },
        }

    def strategy_version_context(self, strategy_name: str) -> dict[str, Any]:
        version_manager = self.version_manager
        if version_manager is None:
            return {"source": None, "current_accepted": None, "versions": []}
        result: dict[str, Any] = {
            "source": "version_manager",
            "current_accepted": None,
            "accepted_params": None,
            "candidate_versions": [],
            "versions": [],
        }
        try:
            pointer = version_manager.get_current_pointer(strategy_name)
            result["current_accepted"] = _dump_model(pointer)
            if pointer is not None:
                try:
                    params = version_manager.load_params(strategy_name, pointer.accepted_version_id)
                    result["accepted_params"] = _dump_model(params)
                except Exception:
                    result["accepted_params"] = None
        except Exception:
            result["current_accepted"] = None

        try:
            versions = version_manager.list_versions(strategy_name)
        except Exception:
            versions = []
        dumped_versions = [_dump_model(version) for version in versions]
        result["versions"] = dumped_versions[-20:]
        result["candidate_versions"] = [
            version for version in dumped_versions
            if str(version.get("acceptance_status", "")).lower() == "candidate"
        ][-10:]
        return result

    def strategy_file_context(self, strategy_name: str, *, include_content: bool = False) -> dict[str, Any]:
        base = Path(self.settings_store.load().strategies_directory_path).resolve()
        paths = self._safe_strategy_paths(base, strategy_name)
        inventory = []
        for key, path in paths.items():
            if path.exists():
                item = _file_record(path, base)
                item["kind"] = key
                item["content_available"] = include_content
                inventory.append(item)
        if not inventory:
            raise BackendError(f"Strategy '{strategy_name}' was not found.", status_code=404)

        result: dict[str, Any] = {
            "strategy_name": strategy_name,
            "root": str(base),
            "files": inventory,
        }
        if include_content:
            result["content"] = {
                key: path.read_text(encoding="utf-8", errors="replace")
                for key, path in paths.items()
                if path.exists()
            }
        return result

    def _safe_strategy_paths(self, base: Path, strategy_name: str) -> dict[str, Path]:
        if not strategy_name or "/" in strategy_name or "\\" in strategy_name or "\x00" in strategy_name:
            raise BackendError("Invalid strategy name.", status_code=400)
        if strategy_name.endswith(".py") or strategy_name.endswith(".json"):
            raise BackendError("Use the strategy name without a file extension.", status_code=400)
        paths = {
            "python": (base / f"{strategy_name}.py").resolve(),
            "json": (base / f"{strategy_name}.json").resolve(),
        }
        for path in paths.values():
            try:
                path.relative_to(base)
            except ValueError as exc:
                raise BackendError("Access denied.", status_code=403) from exc
        return paths
