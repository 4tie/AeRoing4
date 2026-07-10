"""services/strategy/version_manager.py contains backend logic for version manager.

This file is intentionally documented in plain English so readers can follow
what each section does even without deep Python experience.
"""

from __future__ import annotations
import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from ...core.errors import BackendError
from ...models import (
    AcceptanceStatus,
    CurrentAcceptedPointer,
    ParamsSchema,
    QualityGateCheck,
    StrategyRecord,
    VersionChangeType,
    VersionCreationSource,
    VersionMetadata,
)
from ...utils import ast_node_name, atomic_write_json, atomic_write_text, build_version_id, read_json, utc_now
from .strategy_source import PARAMETER_CLASS_NAMES, ParsedStrategySource, StrategySourceParser


def _params_to_sidecar_json(strategy_name: str, params: "ParamsSchema") -> dict:
    """Convert a ParamsSchema into the sidecar JSON format used by strategies_dir."""
    trailing: dict = {"trailing_stop": params.trailing_stop}
    if params.trailing_stop_positive is not None:
        trailing["trailing_stop_positive"] = params.trailing_stop_positive
    if params.trailing_stop_positive_offset is not None:
        trailing["trailing_stop_positive_offset"] = params.trailing_stop_positive_offset
    if params.trailing_only_offset_is_reached is not None:
        trailing["trailing_only_offset_is_reached"] = params.trailing_only_offset_is_reached
    return {
        "strategy_name": strategy_name,
        "params": {
            "buy": dict(params.buy_params),
            "sell": dict(params.sell_params),
            "roi": {str(k): float(v) for k, v in params.roi_table.items()},
            "stoploss": {"stoploss": float(params.stoploss)},
            "trailing": trailing,
        },
    }


class VersionManager:
    """VersionManager contains class-level backend logic."""
    def __init__(self, versions_root: Path, strategy_parser: StrategySourceParser) -> None:
        """__init__ implements function-level backend logic."""
        self.versions_root = versions_root
        self.strategy_parser = strategy_parser
        self.strategies_dir = strategy_parser.strategies_dir
        self.runner_module = "backend.quality_gate_runner"
        self.stub_root = Path(__file__).resolve().parent.parent.parent / "stubs"

    def strategy_root(self, strategy_name: str) -> Path:
        """strategy_root implements function-level backend logic."""
        if not strategy_name:
            raise BackendError("Strategy name is required.", status_code=400)
        return self.versions_root / strategy_name

    def version_dir(self, strategy_name: str, version_id: str) -> Path:
        """version_dir implements function-level backend logic."""
        return self.strategy_root(strategy_name) / version_id

    def current_pointer_path(self, strategy_name: str) -> Path:
        """current_pointer_path implements function-level backend logic."""
        if not strategy_name:
            raise BackendError("Strategy name is required.", status_code=400)
        return self.strategy_root(strategy_name) / "current_accepted.json"

    def get_current_pointer(self, strategy_name: str) -> CurrentAcceptedPointer | None:
        """get_current_pointer implements function-level backend logic."""
        pointer = self.current_pointer_path(strategy_name)
        if not pointer.exists():
            return None
        return CurrentAcceptedPointer.model_validate(read_json(pointer))

    def list_versions(self, strategy_name: str) -> list[VersionMetadata]:
        """list_versions implements function-level backend logic."""
        strategy_root = self.strategy_root(strategy_name)
        if not strategy_root.exists():
            return []
        versions: list[VersionMetadata] = []
        for metadata_path in strategy_root.glob("v*/metadata.json"):
            versions.append(VersionMetadata.model_validate(read_json(metadata_path)))
        versions.sort(key=lambda item: item.created_at)
        return versions

    def find_version(self, version_id: str) -> tuple[str, VersionMetadata, Path]:
        """find_version implements function-level backend logic."""
        matches: list[tuple[str, VersionMetadata, Path]] = []
        for strategy_root in self.versions_root.iterdir():
            if not strategy_root.is_dir():
                continue
            metadata_path = strategy_root / version_id / "metadata.json"
            if metadata_path.exists():
                metadata = VersionMetadata.model_validate(read_json(metadata_path))
                matches.append((strategy_root.name, metadata, metadata_path.parent))
        if not matches:
            raise BackendError(f"Version '{version_id}' was not found.", status_code=404)
        if len(matches) > 1:
            raise BackendError(
                f"Version id '{version_id}' is ambiguous across multiple strategies.",
                status_code=409,
            )
        return matches[0]

    def resolve_version(self, strategy_name: str, version_id: str | None) -> VersionMetadata:
        """resolve_version implements function-level backend logic."""
        if not strategy_name:
            raise BackendError("Strategy name is required.", status_code=400)
        if version_id is None:
            pointer = self.get_current_pointer(strategy_name)
            if pointer is None:
                raise BackendError(
                    f"Strategy '{strategy_name}' is unmanaged and has no accepted version.",
                    status_code=409,
                )
            version_id = pointer.accepted_version_id
        metadata_path = self.version_dir(strategy_name, version_id) / "metadata.json"
        if not metadata_path.exists():
            raise BackendError(
                f"Version '{version_id}' does not exist for strategy '{strategy_name}'.",
                status_code=404,
            )
        return VersionMetadata.model_validate(read_json(metadata_path))

    def load_params(self, strategy_name: str, version_id: str) -> ParamsSchema:
        """load_params implements function-level backend logic."""
        params_path = self.version_dir(strategy_name, version_id) / "params.json"
        return ParamsSchema.model_validate(read_json(params_path))

    def load_strategy_source(self, strategy_name: str, version_id: str) -> str:
        """load_strategy_source implements function-level backend logic."""
        return (self.version_dir(strategy_name, version_id) / "strategy.py").read_text(
            encoding="utf-8"
        )

    def materialize_strategy_source(
        self,
        strategy_name: str,
        version_id: str,
        source: str | None = None,
        params: ParamsSchema | None = None,
    ) -> str:
        """materialize_strategy_source implements function-level backend logic."""
        if source is None:
            source = self.load_strategy_source(strategy_name, version_id)
        if params is None:
            params = self.load_params(strategy_name, version_id)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return source

        class_def = self._find_strategy_class(tree)
        if class_def is None:
            return source

        special_assignments = {
            "buy_params": params.buy_params,
            "sell_params": params.sell_params,
            "minimal_roi": params.roi_table,
            "stoploss": params.stoploss,
            "trailing_stop": params.trailing_stop,
            "trailing_stop_positive": params.trailing_stop_positive,
            "trailing_stop_positive_offset": params.trailing_stop_positive_offset,
            "trailing_only_offset_is_reached": params.trailing_only_offset_is_reached,
        }
        parameter_defaults = {
            **params.buy_params,
            **params.sell_params,
            **params.protection_params,
            **params.custom_params,
        }

        for node in class_def.body:
            target_name = self._assignment_name(node)
            if target_name is None:
                continue
            if target_name in special_assignments:
                value_node = getattr(node, "value", None)
                if value_node is not None:
                    node.value = self._literal_node(special_assignments[target_name])
                continue
            if target_name not in parameter_defaults:
                continue

            call = getattr(node, "value", None)
            if not isinstance(call, ast.Call):
                continue
            func_name = ast_node_name(call.func)
            if func_name not in PARAMETER_CLASS_NAMES:
                continue

            default_updated = False
            for keyword in call.keywords:
                if keyword.arg == "default":
                    keyword.value = self._literal_node(parameter_defaults[target_name])
                    default_updated = True
                    break
            if not default_updated:
                call.keywords.append(
                    ast.keyword(
                        arg="default",
                        value=self._literal_node(parameter_defaults[target_name]),
                    )
                )

        ast.fix_missing_locations(tree)
        try:
            return ast.unparse(tree)
        except Exception:
            return source

    def ensure_registered(self, record: StrategyRecord) -> VersionMetadata:
        """ensure_registered implements function-level backend logic."""
        pointer = self.get_current_pointer(record.strategy_name)
        if pointer is not None:
            return self.resolve_version(record.strategy_name, pointer.accepted_version_id)
        parsed = self.strategy_parser.parse(Path(record.file_path))
        params = self.strategy_parser.extract_params(parsed, "v001")
        checks = self.run_quality_gate(parsed.source_text, params)
        self._ensure_gate_passed(checks)

        strategy_root = self.strategy_root(record.strategy_name)
        version_dir = self.version_dir(record.strategy_name, "v001")
        version_dir.mkdir(parents=True, exist_ok=False)
        atomic_write_text(version_dir / "strategy.py", parsed.source_text)
        atomic_write_json(version_dir / "params.json", params.model_dump(mode="json"))
        metadata = VersionMetadata(
            version_id="v001",
            strategy_name=record.strategy_name,
            parent_version_id=None,
            created_at=utc_now(),
            change_type=VersionChangeType.INITIAL,
            creation_source=VersionCreationSource.BOOTSTRAP,
            proposal_id=None,
            source_run_id=None,
            acceptance_status=AcceptanceStatus.ACCEPTED,
            accepted_at=utc_now(),
            rejected_at=None,
            result_summary_run_id=None,
            quality_gate_results=checks,
        )
        atomic_write_json(version_dir / "metadata.json", metadata.model_dump(mode="json"))
        pointer = CurrentAcceptedPointer(
            strategy_name=record.strategy_name,
            accepted_version_id="v001",
            accepted_at=metadata.accepted_at or metadata.created_at,
            accepted_run_id=None,
        )
        atomic_write_json(self.current_pointer_path(record.strategy_name), pointer.model_dump(mode="json"))
        return metadata

    def create_candidate_version(
        self,
        strategy_name: str,
        parent_version_id: str,
        change_type: VersionChangeType,
        creation_source: VersionCreationSource,
        proposal_id: str | None,
        source_run_id: str | None,
        strategy_source: str,
        params: ParamsSchema,
    ) -> VersionMetadata:
        """create_candidate_version implements function-level backend logic."""
        next_version = build_version_id(self._next_version_counter(strategy_name))
        candidate_params = params.model_copy(update={"version_id": next_version, "extracted_at": utc_now()})
        checks = self.run_quality_gate(strategy_source, candidate_params)
        self._ensure_gate_passed(checks)

        version_dir = self.version_dir(strategy_name, next_version)
        version_dir.mkdir(parents=True, exist_ok=False)
        atomic_write_text(version_dir / "strategy.py", strategy_source)
        atomic_write_json(version_dir / "params.json", candidate_params.model_dump(mode="json"))
        metadata = VersionMetadata(
            version_id=next_version,
            strategy_name=strategy_name,
            parent_version_id=parent_version_id,
            created_at=utc_now(),
            change_type=change_type,
            creation_source=creation_source,
            proposal_id=proposal_id,
            source_run_id=source_run_id,
            acceptance_status=AcceptanceStatus.CANDIDATE,
            accepted_at=None,
            rejected_at=None,
            result_summary_run_id=None,
            quality_gate_results=checks,
        )
        atomic_write_json(version_dir / "metadata.json", metadata.model_dump(mode="json"))
        return metadata

    def create_version_from_optimizer_trial(
        self,
        run_repository,
        run_id: str,
        session_id: str,
        trial_number: int,
        parameters: dict,
        metrics: dict,
    ) -> str:
        """Create a candidate version from optimizer trial parameters.

        Mirrors the logic used during trial execution: loads the accepted version's
        source and params, merges the trial parameters into the full ParamsSchema
        (preserving stoploss, ROI, trailing, sell params, etc.), injects the merged
        params into the source, then creates a proper candidate version.
        """
        # Get the original run to extract strategy info
        run_detail = run_repository.load_detail(run_id)
        if not run_detail:
            raise BackendError(f"Run '{run_id}' not found.", status_code=404)

        strategy_name = run_detail.metadata.strategy_name

        # Get current accepted version as parent
        current = self.get_current_pointer(strategy_name)
        if current is None:
            raise BackendError(
                f"Strategy '{strategy_name}' has no accepted version.", status_code=400
            )
        parent_version_id = current.accepted_version_id

        # Load the accepted version's source and params — never read the live file
        parent_source = self.load_strategy_source(strategy_name, parent_version_id)
        parent_params = self.load_params(strategy_name, parent_version_id)

        # Merge trial parameters into the full parent ParamsSchema, preserving all
        # fields that the optimizer did not touch (stoploss, ROI, trailing, sell, etc.)
        merged_params = self._merge_trial_parameters(parent_params, parameters)

        # Inject the merged params into the source so the .py file is consistent
        modified_source = self._inject_params_into_source(parent_source, merged_params)

        # Create the candidate version
        metadata = self.create_candidate_version(
            strategy_name=strategy_name,
            parent_version_id=parent_version_id,
            change_type=VersionChangeType.PARAMETER,
            creation_source=VersionCreationSource.OPTIMIZER_TRIAL,
            proposal_id=f"{session_id}_trial_{trial_number}",
            source_run_id=run_id,
            strategy_source=modified_source,
            params=merged_params,
        )

        return metadata.version_id

    def merge_trial_parameters(
        self, parent_params: ParamsSchema, trial_parameters: dict
    ) -> ParamsSchema:
        """Public wrapper for merging optimizer trial fields into parent params."""
        return self._merge_trial_parameters(parent_params, trial_parameters)

    def inject_params_into_source(self, source: str, params: ParamsSchema) -> str:
        """Public wrapper for rendering merged params back into strategy source."""
        return self._inject_params_into_source(source, params)

    def overwrite_accepted_params(
        self,
        strategy_name: str,
        version_id: str,
        params: ParamsSchema,
        output_strategy_name: str | None = None,
    ) -> dict[str, str]:
        """Overwrite accepted params and sync the live strategy .py/.json files."""
        target_name = (output_strategy_name or "").strip() or strategy_name
        if not target_name.isidentifier():
            raise BackendError(
                f"'{target_name}' is not a valid Python identifier for a strategy name.",
                status_code=400,
            )

        version_dir = self.version_dir(strategy_name, version_id)
        params = params.model_copy(update={"version_id": version_id, "extracted_at": utc_now()})
        source = self.load_strategy_source(strategy_name, version_id)
        materialized_source = self.materialize_strategy_source(
            strategy_name,
            version_id,
            source=source,
            params=params,
        )

        version_params_path = version_dir / "params.json"
        version_source_path = version_dir / "strategy.py"
        live_source_path = self.strategies_dir / f"{target_name}.py"
        live_sidecar_path = self.strategies_dir / f"{target_name}.json"

        atomic_write_json(version_params_path, params.model_dump(mode="json"))
        atomic_write_text(version_source_path, materialized_source)
        atomic_write_text(live_source_path, materialized_source)
        atomic_write_text(
            live_sidecar_path,
            json.dumps(_params_to_sidecar_json(target_name, params), indent=2),
        )

        return {
            "version_params_path": str(version_params_path),
            "version_source_path": str(version_source_path),
            "live_source_path": str(live_source_path),
            "live_sidecar_path": str(live_sidecar_path),
        }

    def preview_optimizer_trial_application(
        self,
        run_repository,
        optimizer_store,
        session_id: str,
        trial_number: int,
    ) -> dict:
        """Build a JSON preview showing how one optimizer trial changes params."""
        trial = self._resolve_completed_optimizer_trial(optimizer_store, session_id, trial_number)
        run_detail = run_repository.load_detail(trial.run_id)
        if run_detail is None:
            raise BackendError(f"Run '{trial.run_id}' not found.", status_code=404)

        strategy_name = run_detail.metadata.strategy_name
        current = self.get_current_pointer(strategy_name)
        if current is None:
            raise BackendError(f"Strategy '{strategy_name}' has no accepted version.", status_code=400)

        parent_version_id = current.accepted_version_id
        original_params = self.load_params(strategy_name, parent_version_id)
        merged_params = self.merge_trial_parameters(original_params, trial.parameters)
        return {
            "session_id": session_id,
            "trial_number": trial_number,
            "run_id": trial.run_id,
            "original_json": original_params.model_dump(mode="json"),
            "modified_json": merged_params.model_dump(mode="json"),
        }

    def apply_optimizer_trial_to_new_version(
        self,
        run_repository,
        optimizer_store,
        session_id: str,
        trial_number: int,
    ) -> dict:
        """Create a candidate version from a completed optimizer trial."""
        trial = self._resolve_completed_optimizer_trial(optimizer_store, session_id, trial_number)
        version_id = self.create_version_from_optimizer_trial(
            run_repository=run_repository,
            run_id=trial.run_id,
            session_id=session_id,
            trial_number=trial_number,
            parameters=trial.parameters,
            metrics=trial.metrics,
        )
        return {
            "version_id": version_id,
            "session_id": session_id,
            "trial_number": trial_number,
            "run_id": trial.run_id,
            "applied_at": utc_now().isoformat(),
        }

    def _merge_trial_parameters(
        self, parent_params: ParamsSchema, trial_parameters: dict
    ) -> ParamsSchema:
        """Merge raw optimizer trial parameters into a full ParamsSchema.

        Handles the same key namespaces as StrategyOptimizerService._build_trial_params:
        ``buy__``, ``sell__``, ``protection__``, ``custom__``, ``stoploss__value``,
        ``roi__<time>``, ``trailing__stop/positive/offset``.  Unknown keys fall back
        to ``custom_params``.
        """
        trial_buy = dict(parent_params.buy_params)
        trial_sell = dict(parent_params.sell_params)
        trial_protection = dict(parent_params.protection_params)
        trial_custom = dict(parent_params.custom_params)
        roi_updates: dict[str, float] = {}

        new_stoploss: float = parent_params.stoploss
        new_trailing_stop: bool = parent_params.trailing_stop
        new_trailing_positive: float | None = parent_params.trailing_stop_positive
        new_trailing_offset: float | None = parent_params.trailing_stop_positive_offset

        for key, value in trial_parameters.items():
            if key.startswith("buy__"):
                trial_buy[key[5:]] = value
            elif key.startswith("sell__"):
                trial_sell[key[6:]] = value
            elif key.startswith("protection__"):
                trial_protection[key[12:]] = value
            elif key.startswith("custom__"):
                trial_custom[key[8:]] = value
            elif key == "stoploss__value":
                new_stoploss = float(value)
            elif key.startswith("roi__"):
                roi_updates[key[5:]] = float(value)
            elif key == "trailing__stop":
                new_trailing_stop = bool(value)
            elif key == "trailing__positive":
                new_trailing_positive = float(value)
            elif key == "trailing__offset":
                new_trailing_offset = float(value)
            elif key in parent_params.buy_params:
                trial_buy[key] = value
            elif key in parent_params.sell_params:
                trial_sell[key] = value
            elif key in parent_params.protection_params:
                trial_protection[key] = value
            elif key in parent_params.custom_params:
                trial_custom[key] = value
            else:
                trial_custom[key] = value

        trial_roi = {**parent_params.roi_table, **roi_updates}

        # If trailing was explicitly disabled, clear the dependent fields
        if "trailing__stop" in trial_parameters and not new_trailing_stop:
            new_trailing_positive = None
            new_trailing_offset = None

        return parent_params.model_copy(
            update={
                "buy_params": trial_buy,
                "sell_params": trial_sell,
                "protection_params": trial_protection,
                "custom_params": trial_custom,
                "stoploss": new_stoploss,
                "roi_table": trial_roi,
                "trailing_stop": new_trailing_stop,
                "trailing_stop_positive": new_trailing_positive,
                "trailing_stop_positive_offset": new_trailing_offset,
            }
        )

    def _inject_params_into_source(self, source: str, params: ParamsSchema) -> str:
        """Inject merged parameters into strategy source code via AST rewriting."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return source

        # Find the strategy class
        class_def = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_def = node
                break
        if class_def is None:
            return source

        special_assignments: dict[str, object] = {
            "buy_params": params.buy_params,
            "sell_params": params.sell_params,
            "minimal_roi": params.roi_table,
            "stoploss": params.stoploss,
            "trailing_stop": params.trailing_stop,
        }
        if params.trailing_stop_positive is not None:
            special_assignments["trailing_stop_positive"] = params.trailing_stop_positive
        if params.trailing_stop_positive_offset is not None:
            special_assignments["trailing_stop_positive_offset"] = (
                params.trailing_stop_positive_offset
            )
        if params.trailing_only_offset_is_reached is not None:
            special_assignments["trailing_only_offset_is_reached"] = (
                params.trailing_only_offset_is_reached
            )

        for node in ast.walk(class_def):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                name = target.id
                if name not in special_assignments:
                    continue
                value = special_assignments[name]
                try:
                    node.value = ast.parse(repr(value), mode="eval").body
                except Exception:
                    pass

        try:
            return ast.unparse(tree)
        except Exception:
            return source

    def _resolve_completed_optimizer_trial(self, optimizer_store, session_id: str, trial_number: int):
        """Load and validate one completed optimizer trial from persisted session storage."""
        session = optimizer_store.load_session(session_id)
        if session is None:
            raise BackendError(f"Optimizer session '{session_id}' not found.", status_code=404)

        trial = next((item for item in session.trials if item.trial_number == trial_number), None)
        if trial is None:
            raise BackendError(
                f"Trial #{trial_number} not found in session '{session_id}'.",
                status_code=404,
            )
        if trial.status != "completed":
            raise BackendError(f"Trial #{trial_number} has not completed yet.", status_code=400)
        if not trial.run_id:
            raise BackendError(
                f"Trial #{trial_number} has no associated backtest run.",
                status_code=400,
            )
        return trial

    def _resolve_version_by_id(
        self, version_id: str, strategy_name: str | None
    ) -> tuple[str, VersionMetadata, Path]:
        """Resolve a version by ID, using strategy_name to avoid ambiguity when provided."""
        if strategy_name:
            metadata = self.resolve_version(strategy_name, version_id)
            version_dir = self.version_dir(strategy_name, version_id)
            return strategy_name, metadata, version_dir
        return self.find_version(version_id)

    def accept_version(
        self,
        version_id: str,
        confirmation_token: str,
        output_strategy_name: str | None = None,
        strategy_name: str | None = None,
    ) -> VersionMetadata:
        """accept_version implements function-level backend logic."""
        if confirmation_token != version_id:
            raise BackendError("Invalid confirmation token.", status_code=400)
        strategy_name, metadata, version_dir = self._resolve_version_by_id(version_id, strategy_name)
        if metadata.acceptance_status == AcceptanceStatus.REJECTED:
            raise BackendError("Rejected versions cannot be accepted.", status_code=409)
        if metadata.acceptance_status not in {AcceptanceStatus.CANDIDATE, AcceptanceStatus.SUPERSEDED}:
            raise BackendError("Only candidate or superseded versions can be accepted.", status_code=409)

        # Validate and normalise the requested output name
        target_name = (output_strategy_name or "").strip() or strategy_name
        if not target_name.isidentifier():
            raise BackendError(
                f"'{target_name}' is not a valid Python identifier for a strategy name.",
                status_code=400,
            )

        previous = self.get_current_pointer(strategy_name)
        if previous and previous.accepted_version_id != version_id:
            previous_metadata = self.resolve_version(strategy_name, previous.accepted_version_id)
            if previous_metadata.acceptance_status == AcceptanceStatus.ACCEPTED:
                self._write_metadata(
                    strategy_name,
                    previous.accepted_version_id,
                    previous_metadata.model_copy(
                        update={
                            "acceptance_status": AcceptanceStatus.SUPERSEDED,
                            "accepted_at": previous_metadata.accepted_at,
                        }
                    ),
                )

        accepted_at = utc_now()
        updated = metadata.model_copy(
            update={"acceptance_status": AcceptanceStatus.ACCEPTED, "accepted_at": accepted_at}
        )
        self._write_metadata(strategy_name, version_id, updated)
        pointer = CurrentAcceptedPointer(
            strategy_name=strategy_name,
            accepted_version_id=version_id,
            accepted_at=accepted_at,
            accepted_run_id=updated.result_summary_run_id,
        )
        atomic_write_json(self.current_pointer_path(strategy_name), pointer.model_dump(mode="json"))

        # Write the accepted version's source back to the live strategies directory
        # so Freqtrade can pick it up immediately.
        source = self.load_strategy_source(strategy_name, version_id)
        atomic_write_text(self.strategies_dir / f"{target_name}.py", source)

        # Also write a matching sidecar JSON so strategies_dir always has both files.
        try:
            params = self.load_params(strategy_name, version_id)
            sidecar = _params_to_sidecar_json(target_name, params)
            atomic_write_text(
                self.strategies_dir / f"{target_name}.json",
                json.dumps(sidecar, indent=2),
            )
        except Exception:
            pass

        return updated

    def reject_version(
        self, version_id: str, reason: str | None = None, strategy_name: str | None = None
    ) -> VersionMetadata:
        """reject_version implements function-level backend logic."""
        strategy_name, metadata, _ = self._resolve_version_by_id(version_id, strategy_name)
        if metadata.acceptance_status != AcceptanceStatus.CANDIDATE:
            raise BackendError("Only candidate versions can be rejected.", status_code=409)
        updated = metadata.model_copy(
            update={"acceptance_status": AcceptanceStatus.REJECTED, "rejected_at": utc_now()}
        )
        self._write_metadata(strategy_name, version_id, updated)
        return updated

    def rollback_version(
        self, version_id: str, confirmation_token: str, strategy_name: str | None = None
    ) -> VersionMetadata:
        """rollback_version implements function-level backend logic."""
        if confirmation_token != version_id:
            raise BackendError("Invalid confirmation token.", status_code=400)
        strategy_name, metadata, _ = self._resolve_version_by_id(version_id, strategy_name)
        if metadata.acceptance_status not in {AcceptanceStatus.ACCEPTED, AcceptanceStatus.SUPERSEDED}:
            raise BackendError(
                "Only previously accepted or superseded versions can be rolled back to.",
                status_code=409,
            )
        current = self.get_current_pointer(strategy_name)
        if current and current.accepted_version_id != version_id:
            current_metadata = self.resolve_version(strategy_name, current.accepted_version_id)
            self._write_metadata(
                strategy_name,
                current.accepted_version_id,
                current_metadata.model_copy(
                    update={"acceptance_status": AcceptanceStatus.SUPERSEDED}
                ),
            )

        rolled_back_at = utc_now()
        updated = metadata.model_copy(
            update={"acceptance_status": AcceptanceStatus.ACCEPTED, "accepted_at": rolled_back_at}
        )
        self._write_metadata(strategy_name, version_id, updated)
        pointer = CurrentAcceptedPointer(
            strategy_name=strategy_name,
            accepted_version_id=version_id,
            accepted_at=rolled_back_at,
            accepted_run_id=updated.result_summary_run_id,
        )
        atomic_write_json(self.current_pointer_path(strategy_name), pointer.model_dump(mode="json"))
        return updated

    def update_result_summary(self, strategy_name: str, version_id: str, run_id: str) -> VersionMetadata:
        """update_result_summary implements function-level backend logic."""
        metadata = self.resolve_version(strategy_name, version_id)
        updated = metadata.model_copy(update={"result_summary_run_id": run_id})
        self._write_metadata(strategy_name, version_id, updated)
        return updated

    def run_quality_gate(self, strategy_source: str, params: ParamsSchema) -> list[QualityGateCheck]:
        """run_quality_gate implements function-level backend logic."""
        with TemporaryDirectory() as temp_dir_raw:
            temp_dir = Path(temp_dir_raw)
            strategy_path = temp_dir / "candidate_strategy.py"
            params_path = temp_dir / "params.json"
            strategy_path.write_text(strategy_source, encoding="utf-8")
            params_path.write_text(json.dumps(params.model_dump(mode="json")), encoding="utf-8")
            command = [
                sys.executable,
                "-m",
                self.runner_module,
                str(strategy_path),
                str(params_path),
                str(self.stub_root),
            ]
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                raise BackendError(
                    f"Quality gate runner failed: {completed.stderr or completed.stdout}",
                    status_code=500,
                )
            raw_checks = json.loads(completed.stdout or "[]")
        return [QualityGateCheck.model_validate(item) for item in raw_checks]

    def _ensure_gate_passed(self, checks: list[QualityGateCheck]) -> None:
        """_ensure_gate_passed implements function-level backend logic."""
        failures = [check for check in checks if check.status == "fail"]
        if failures:
            messages = "; ".join(
                f"{failure.check_name}: {failure.error_detail or 'failed'}" for failure in failures
            )
            raise BackendError(f"Quality gate failed. {messages}", status_code=400)

    def _next_version_counter(self, strategy_name: str) -> int:
        """_next_version_counter implements function-level backend logic."""
        strategy_root = self.strategy_root(strategy_name)
        if not strategy_root.exists():
            return 1
        existing = [path.name for path in strategy_root.iterdir() if path.is_dir()]
        highest = 0
        for name in existing:
            if name.startswith("v") and name[1:].isdigit():
                highest = max(highest, int(name[1:]))
        return highest + 1

    def _write_metadata(self, strategy_name: str, version_id: str, metadata: VersionMetadata) -> None:
        """_write_metadata implements function-level backend logic."""
        atomic_write_json(
            self.version_dir(strategy_name, version_id) / "metadata.json",
            metadata.model_dump(mode="json"),
        )

    def _find_strategy_class(self, tree: ast.AST) -> ast.ClassDef | None:
        """_find_strategy_class implements function-level backend logic."""
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = {ast_node_name(base) for base in node.bases}
            method_names = {
                child.name for child in node.body if isinstance(child, ast.FunctionDef)
            }
            if "IStrategy" in base_names or {
                "populate_indicators",
                "populate_entry_trend",
                "populate_exit_trend",
            }.issubset(method_names):
                return node
        return None

    def _assignment_name(self, node: ast.AST) -> str | None:
        """_assignment_name implements function-level backend logic."""
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            return node.targets[0].id
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            return node.target.id
        return None

    def _literal_node(self, value):
        """_literal_node implements function-level backend logic."""
        return ast.parse(repr(value), mode="eval").body
