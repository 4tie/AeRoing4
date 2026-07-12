"""Read-only strategy library and AutoQuant flow visibility models.

This module exposes the strategy source-of-truth state as structured JSON for
the UI. It intentionally does not mutate strategy files or run research steps.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...core.errors import BackendError
from ...utils import ast_node_name, read_json
from .research.experiments import ExperimentDecision, ExperimentRecord, ExperimentStatus, ExperimentStore


PARAMETER_CLASS_NAMES = {
    "IntParameter",
    "DecimalParameter",
    "RealParameter",
    "CategoricalParameter",
    "BooleanParameter",
}

FLOW_STEP_NAMES = [
    "Source Strategy",
    "Candidate Copy",
    "Freqtrade Execution",
    "Metrics Parsing",
    "Decision",
    "Next Action",
]


class StrategyLibraryWarning(BaseModel):
    code: str
    message: str
    severity: str = "warning"


class StrategyLibraryParameter(BaseModel):
    name: str
    source: str
    parameter_type: str | None = None
    space: str | None = None
    default: Any = None
    current: Any = None
    min_value: Any = None
    max_value: Any = None
    choices: list[Any] | None = None
    optimizable: bool | None = None
    runtime_path: str | None = None
    runtime_executable: bool = False


class StrategyLibraryItem(BaseModel):
    strategy_name: str
    py_exists: bool
    json_exists: bool
    python_path: str | None = None
    json_path: str | None = None
    class_name: str | None = None
    json_strategy_name: str | None = None
    timeframe: str | None = None
    python_parameters: list[StrategyLibraryParameter] = Field(default_factory=list)
    json_runtime_params: list[StrategyLibraryParameter] = Field(default_factory=list)
    python_only_params: list[str] = Field(default_factory=list)
    json_only_params: list[str] = Field(default_factory=list)
    warnings: list[StrategyLibraryWarning] = Field(default_factory=list)


class StrategyLibraryScan(BaseModel):
    strategies_dir: str
    strategies: list[StrategyLibraryItem]


class AutoQuantFlowStep(BaseModel):
    name: str
    status: str
    paths: dict[str, str | None] = Field(default_factory=dict)
    message: str = ""
    technical_details: dict[str, Any] = Field(default_factory=dict)


class AutoQuantCandidateFlow(BaseModel):
    run_id: str
    experiment_id: str | None = None
    candidate_id: str | None = None
    strategy_name: str | None = None
    official_source_strategy_path: str | None = None
    official_source_json_path: str | None = None
    candidate_directory: str | None = None
    copied_candidate_py: str | None = None
    copied_candidate_json: str | None = None
    official_files_unchanged: bool | None = None
    freqtrade_command: str | None = None
    strategy_path_argument: str | None = None
    strategy_path_points_to_candidate_dir: bool = False
    strategy_path_points_to_run_dir: bool = False
    strategy_path_points_to_candidate_or_run_dir: bool = False
    output_zip_path: str | None = None
    output_zip_contains_py: bool | None = None
    output_zip_contains_json: bool | None = None
    parsed_metrics: dict[str, Any] = Field(default_factory=dict)
    decision: str
    reason_codes: list[str] = Field(default_factory=list)
    steps: list[AutoQuantFlowStep] = Field(default_factory=list)


class AutoQuantFlowResponse(BaseModel):
    run_id: str | None = None
    candidate: AutoQuantCandidateFlow | None = None
    message: str = ""


def scan_strategy_library(strategies_dir: Path) -> StrategyLibraryScan:
    """Scan top-level strategy .py/.json files under the official directory."""

    strategies_dir = Path(strategies_dir)
    if not strategies_dir.exists():
        return StrategyLibraryScan(strategies_dir=str(strategies_dir), strategies=[])

    py_files = {p.stem: p for p in strategies_dir.glob("*.py")}
    json_files = {p.stem: p for p in strategies_dir.glob("*.json")}
    stems = sorted(set(py_files) | set(json_files), key=str.lower)

    items = [
        _scan_strategy(stem, py_files.get(stem), json_files.get(stem))
        for stem in stems
    ]
    return StrategyLibraryScan(strategies_dir=str(strategies_dir), strategies=items)


def build_candidate_flow_for_run(
    *,
    run_id: str,
    runs_root: Path,
    run_repository: Any,
    strategies_dir: Path,
) -> AutoQuantFlowResponse:
    store = ExperimentStore(Path(runs_root), mark_interrupted_on_reload=False)
    try:
        experiments = store.list_for_run(run_id)
    except Exception as exc:  # noqa: BLE001 - read model should fail closed for this run
        # Fall back to artifact-based builder if experiment store is unavailable
        return _build_candidate_flow_from_artifacts(
            run_id=run_id,
            runs_root=Path(runs_root),
            run_repository=run_repository,
            strategies_dir=Path(strategies_dir),
        )

    candidate = _latest_candidate_experiment(experiments)
    if candidate is None:
        # Fall back to artifact-based builder if no experiments found
        return _build_candidate_flow_from_artifacts(
            run_id=run_id,
            runs_root=Path(runs_root),
            run_repository=run_repository,
            strategies_dir=Path(strategies_dir),
        )

    return AutoQuantFlowResponse(
        run_id=run_id,
        candidate=_build_candidate_flow(
            candidate,
            runs_root=Path(runs_root),
            run_repository=run_repository,
            strategies_dir=Path(strategies_dir),
        ),
    )


def build_latest_candidate_flow(
    *,
    runs_root: Path,
    run_repository: Any,
    strategies_dir: Path,
) -> AutoQuantFlowResponse:
    runs_root = Path(runs_root)
    if not runs_root.exists():
        return AutoQuantFlowResponse(message="No AeRoing4 runs directory exists yet.")

    run_dirs = sorted(
        [p for p in runs_root.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for run_dir in run_dirs:
        response = build_candidate_flow_for_run(
            run_id=run_dir.name,
            runs_root=runs_root,
            run_repository=run_repository,
            strategies_dir=strategies_dir,
        )
        if response.candidate is not None:
            return response

    latest = run_dirs[0].name if run_dirs else None
    return AutoQuantFlowResponse(
        run_id=latest,
        candidate=None,
        message="No candidate experiment artifacts found yet.",
    )


def _scan_strategy(
    stem: str,
    py_path: Path | None,
    json_path: Path | None,
) -> StrategyLibraryItem:
    warnings: list[StrategyLibraryWarning] = []
    class_name: str | None = None
    timeframe: str | None = None
    python_params: list[StrategyLibraryParameter] = []
    json_strategy_name: str | None = None
    json_runtime_params: list[StrategyLibraryParameter] = []
    json_payload: dict[str, Any] | None = None

    if py_path is not None:
        try:
            class_name, timeframe, python_params = _parse_strategy_python(py_path)
        except Exception as exc:  # noqa: BLE001 - surface bad row as a warning
            warnings.append(_warning("PYTHON_PARSE_ERROR", f"Could not parse {py_path.name}: {exc}", "error"))
    if json_path is not None:
        try:
            json_payload = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(json_payload, dict):
                json_strategy_name = _optional_str(json_payload.get("strategy_name"))
                json_runtime_params = _flatten_runtime_params(json_payload)
            else:
                warnings.append(_warning("JSON_PARSE_ERROR", f"{json_path.name} must contain a JSON object", "error"))
                json_payload = None
        except Exception as exc:  # noqa: BLE001
            warnings.append(_warning("JSON_PARSE_ERROR", f"Could not parse {json_path.name}: {exc}", "error"))

    if py_path is not None and json_path is None:
        warnings.append(_warning("MISSING_JSON", f"{stem}.json is missing"))

    if class_name and class_name != stem:
        warnings.append(
            _warning(
                "CLASS_FILE_MISMATCH",
                f"Strategy class {class_name!r} does not match file stem {stem!r}",
            )
        )

    if json_strategy_name and class_name and json_strategy_name != class_name:
        warnings.append(
            _warning(
                "JSON_STRATEGY_NAME_MISMATCH",
                f"JSON strategy_name {json_strategy_name!r} does not match class {class_name!r}",
            )
        )

    python_names = {p.name for p in python_params}
    json_hyperopt_names = {
        p.name for p in json_runtime_params
        if p.runtime_path and (p.runtime_path.startswith("params.buy.") or p.runtime_path.startswith("params.sell."))
    }
    python_only = sorted(python_names - json_hyperopt_names)
    json_only = sorted(json_hyperopt_names - python_names)

    if python_only:
        warnings.append(
            _warning(
                "PYTHON_ONLY_PARAMS",
                "Python tunable params missing from JSON runtime buy/sell: " + ", ".join(python_only),
            )
        )
    if json_only:
        warnings.append(
            _warning(
                "JSON_ONLY_PARAMS",
                "JSON runtime buy/sell params missing from Python declarations: " + ", ".join(json_only),
            )
        )

    if json_payload is not None and python_params:
        buy = ((json_payload.get("params") or {}).get("buy") or {}) if isinstance(json_payload.get("params"), dict) else {}
        sell = ((json_payload.get("params") or {}).get("sell") or {}) if isinstance(json_payload.get("params"), dict) else {}
        tunable_buy_sell = [p.name for p in python_params if p.space in {"buy", "sell"}]
        if not buy and not sell and tunable_buy_sell:
            warnings.append(
                _warning(
                    "EMPTY_JSON_BUY_SELL_WITH_PYTHON_PARAMS",
                    "JSON buy/sell runtime params are empty but Python declares tunable params: "
                    + ", ".join(sorted(tunable_buy_sell)),
                )
            )

    not_runtime = {
        p.name for p in python_params
        if not _is_runtime_executable_target(p.name, json_payload)
    }
    not_runtime.update(
        p.name for p in json_runtime_params
        if not p.runtime_executable
    )
    not_runtime_sorted = sorted(not_runtime)
    if not_runtime_sorted:
        warnings.append(
            _warning(
                "PARAMS_NOT_RUNTIME_EXECUTABLE",
                "Params are not executable by the current run-local sidecar mutation path: "
                + ", ".join(not_runtime_sorted),
            )
        )

    return StrategyLibraryItem(
        strategy_name=stem,
        py_exists=py_path is not None,
        json_exists=json_path is not None,
        python_path=str(py_path) if py_path else None,
        json_path=str(json_path) if json_path else None,
        class_name=class_name,
        json_strategy_name=json_strategy_name,
        timeframe=timeframe,
        python_parameters=python_params,
        json_runtime_params=json_runtime_params,
        python_only_params=python_only,
        json_only_params=json_only,
        warnings=warnings,
    )


def _parse_strategy_python(path: Path) -> tuple[str | None, str | None, list[StrategyLibraryParameter]]:
    source = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source, filename=str(path))
    class_def = _find_strategy_class(tree)
    if class_def is None:
        return None, None, []

    assignments = _collect_assignments(class_def)
    constants = {
        name: value
        for name, value_node in assignments.items()
        if (value := _safe_literal(value_node)) is not None
    }
    timeframe = _optional_str(_safe_literal(assignments.get("timeframe"), constants=constants))
    params = _collect_python_parameters(class_def, constants=constants)
    return class_def.name, timeframe, params


def _find_strategy_class(tree: ast.AST) -> ast.ClassDef | None:
    for node in getattr(tree, "body", []):
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


def _collect_assignments(class_def: ast.ClassDef) -> dict[str, ast.AST]:
    assignments: dict[str, ast.AST] = {}
    for node in class_def.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assignments[node.target.id] = node.value
    return assignments


def _collect_python_parameters(
    class_def: ast.ClassDef,
    *,
    constants: dict[str, Any],
) -> list[StrategyLibraryParameter]:
    params: list[StrategyLibraryParameter] = []
    for node in class_def.body:
        name: str | None = None
        value: ast.AST | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            value = node.value
        if not name or not isinstance(value, ast.Call):
            continue
        parameter_type = ast_node_name(value.func)
        if parameter_type not in PARAMETER_CLASS_NAMES:
            continue
        default = _keyword_literal(value, "default", constants=constants)
        space = _optional_str(_keyword_literal(value, "space", constants=constants))
        optimize = _keyword_literal(value, "optimize", fallback=True, constants=constants)
        min_value = None
        max_value = None
        choices = None
        if parameter_type in {"IntParameter", "DecimalParameter", "RealParameter"}:
            min_value = _call_arg_literal(value, 0, _keyword_literal(value, "low", constants=constants), constants=constants)
            max_value = _call_arg_literal(value, 1, _keyword_literal(value, "high", constants=constants), constants=constants)
        elif parameter_type == "CategoricalParameter":
            raw_choices = _call_arg_literal(value, 0, _keyword_literal(value, "choices", constants=constants), constants=constants)
            if isinstance(raw_choices, (list, tuple)):
                choices = list(raw_choices)
                if default is None and choices:
                    default = choices[0]
        elif parameter_type == "BooleanParameter" and default is None:
            default = False
        params.append(
            StrategyLibraryParameter(
                name=name,
                source="python",
                parameter_type=parameter_type,
                space=space,
                default=default,
                min_value=min_value,
                max_value=max_value,
                choices=choices,
                optimizable=bool(optimize) if isinstance(optimize, bool) else True,
                runtime_executable=False,
            )
        )
    return params


def _flatten_runtime_params(payload: dict[str, Any]) -> list[StrategyLibraryParameter]:
    runtime = payload.get("params")
    if not isinstance(runtime, dict):
        return []

    params: list[StrategyLibraryParameter] = []
    for group in ("buy", "sell"):
        values = runtime.get(group)
        if isinstance(values, dict):
            for name, current in sorted(values.items()):
                params.append(
                    StrategyLibraryParameter(
                        name=str(name),
                        source="json",
                        space=group,
                        current=current,
                        runtime_path=f"params.{group}.{name}",
                        runtime_executable=_is_runtime_executable_target(str(name), payload),
                    )
                )

    stoploss = runtime.get("stoploss")
    if isinstance(stoploss, dict) and "stoploss" in stoploss:
        params.append(
            StrategyLibraryParameter(
                name="stoploss",
                source="json",
                space="stoploss",
                current=stoploss.get("stoploss"),
                runtime_path="params.stoploss.stoploss",
                runtime_executable=True,
            )
        )

    roi = runtime.get("roi")
    if isinstance(roi, dict):
        params.append(
            StrategyLibraryParameter(
                name="roi",
                source="json",
                space="roi",
                current=roi,
                runtime_path="params.roi",
                runtime_executable=True,
            )
        )

    trailing = runtime.get("trailing")
    if isinstance(trailing, dict):
        for name, current in sorted(trailing.items()):
            params.append(
                StrategyLibraryParameter(
                    name=str(name),
                    source="json",
                    space="trailing",
                    current=current,
                    runtime_path=f"params.trailing.{name}",
                    runtime_executable=_is_runtime_executable_target(str(name), payload),
                )
            )
    return params


def _is_runtime_executable_target(target: str, payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    runtime = payload.get("params")
    if not isinstance(runtime, dict):
        return False
    if target.startswith("buy_"):
        return isinstance(runtime.get("buy"), dict) and target in runtime["buy"]
    if target.startswith("sell_"):
        return isinstance(runtime.get("sell"), dict) and target in runtime["sell"]
    if target == "stoploss":
        group = runtime.get("stoploss")
        return isinstance(group, dict) and "stoploss" in group
    if target in {"roi", "minimal_roi"}:
        return "roi" in runtime
    if target.startswith("trailing_"):
        group = runtime.get("trailing")
        return isinstance(group, dict) and target in group
    return False


def _latest_candidate_experiment(experiments: list[ExperimentRecord]) -> ExperimentRecord | None:
    candidates = [
        e for e in experiments
        if e.candidate_id or e.artifacts.get("candidate_dir") or e.underlying_execution_id
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda e: e.updated_at or e.created_at)[-1]


def _build_candidate_flow(
    experiment: ExperimentRecord,
    *,
    runs_root: Path,
    run_repository: Any,
    strategies_dir: Path,
) -> AutoQuantCandidateFlow:
    artifacts = dict(experiment.artifacts or {})
    strategy_name = (
        experiment.original_strategy_provenance.logical_name
        or _stem_from_path(experiment.original_strategy_provenance.path_reference)
    )

    official_strategy = artifacts.get("official_source_strategy_path") or experiment.original_strategy_provenance.path_reference
    official_json = artifacts.get("official_source_json_path") or (
        str(strategies_dir / f"{strategy_name}.json") if strategy_name else None
    )
    candidate_dir = artifacts.get("candidate_dir") or _candidate_dir_from_record(experiment, runs_root)
    copied_py = artifacts.get("candidate_strategy") or (
        str(Path(candidate_dir) / f"{strategy_name}.py") if candidate_dir and strategy_name else None
    )
    copied_json = artifacts.get("candidate_sidecar") or artifacts.get("candidate_json") or (
        str(Path(candidate_dir) / f"{strategy_name}.json") if candidate_dir and strategy_name else None
    )

    execution_id = artifacts.get("freqtrade_execution_id")
    if not execution_id and experiment.underlying_execution_id and not Path(str(experiment.underlying_execution_id)).exists():
        execution_id = experiment.underlying_execution_id
    execution_run_dir = _find_execution_run_dir(execution_id, run_repository)
    command = _read_text(execution_run_dir / "freqtrade_command.txt") if execution_run_dir else artifacts.get("freqtrade_command")
    strategy_path_arg = _extract_strategy_path_argument(command)

    output_zip = _first_existing_path(
        artifacts.get("output_zip_path"),
        str(execution_run_dir / "freqtrade_native_result.zip") if execution_run_dir else None,
    )
    zip_contains_py, zip_contains_json = _zip_contains_strategy_files(output_zip)

    parsed_metrics = _metric_values(experiment.metrics_after)
    if not parsed_metrics and execution_run_dir:
        parsed_metrics = _parsed_summary_values(read_json(execution_run_dir / "parsed_summary.json", default={}) or {})

    official_files_unchanged = _official_files_unchanged(
        experiment,
        official_strategy=official_strategy,
        official_json=official_json,
        artifacts=artifacts,
    )
    decision = _decision_label(experiment)
    reason_codes = _reason_codes(experiment)
    step_models = _flow_steps(
        experiment=experiment,
        strategy_name=strategy_name,
        official_strategy=official_strategy,
        official_json=official_json,
        candidate_dir=candidate_dir,
        copied_py=copied_py,
        copied_json=copied_json,
        official_files_unchanged=official_files_unchanged,
        command=command,
        strategy_path_arg=strategy_path_arg,
        execution_run_dir=str(execution_run_dir) if execution_run_dir else None,
        output_zip=output_zip,
        zip_contains_py=zip_contains_py,
        zip_contains_json=zip_contains_json,
        parsed_metrics=parsed_metrics,
        decision=decision,
        reason_codes=reason_codes,
    )

    points_to_candidate = _same_path(strategy_path_arg, candidate_dir)
    points_to_run = _same_path(strategy_path_arg, str(execution_run_dir) if execution_run_dir else None)
    return AutoQuantCandidateFlow(
        run_id=experiment.run_id,
        experiment_id=experiment.experiment_id,
        candidate_id=experiment.candidate_id,
        strategy_name=strategy_name,
        official_source_strategy_path=official_strategy,
        official_source_json_path=official_json,
        candidate_directory=candidate_dir,
        copied_candidate_py=copied_py,
        copied_candidate_json=copied_json,
        official_files_unchanged=official_files_unchanged,
        freqtrade_command=command,
        strategy_path_argument=strategy_path_arg,
        strategy_path_points_to_candidate_dir=points_to_candidate,
        strategy_path_points_to_run_dir=points_to_run,
        strategy_path_points_to_candidate_or_run_dir=points_to_candidate or points_to_run,
        output_zip_path=output_zip,
        output_zip_contains_py=zip_contains_py,
        output_zip_contains_json=zip_contains_json,
        parsed_metrics=parsed_metrics,
        decision=decision,
        reason_codes=reason_codes,
        steps=step_models,
    )


def _build_candidate_flow_from_artifacts(
    *,
    run_id: str,
    runs_root: Path,
    run_repository: Any,
    strategies_dir: Path,
) -> AutoQuantFlowResponse:
    """Build candidate flow from partial artifacts when ExperimentRecord is unavailable.
    
    This tolerant builder extracts whatever information is available from the run directory
    without requiring a complete ExperimentRecord. Missing fields are clearly marked.
    """
    run_dir = runs_root / run_id
    if not run_dir.exists():
        return AutoQuantFlowResponse(
            run_id=run_id,
            candidate=None,
            message=f"Run directory does not exist: {run_dir}",
        )
    
    # Scan for candidate artifacts
    experiments_dir = run_dir / "experiments"
    if not experiments_dir.exists():
        return AutoQuantFlowResponse(
            run_id=run_id,
            candidate=None,
            message=f"No experiments directory found in run: {experiments_dir}",
        )
    
    # Find the latest experiment directory
    experiment_dirs = sorted(
        [p for p in experiments_dir.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    
    if not experiment_dirs:
        return AutoQuantFlowResponse(
            run_id=run_id,
            candidate=None,
            message="No experiment directories found in run.",
        )
    
    latest_experiment_dir = experiment_dirs[0]
    candidate_dir = latest_experiment_dir / "candidate"
    
    # Find strategy name from candidate files
    candidate_py_files = list(candidate_dir.glob("*.py")) if candidate_dir.exists() else []
    candidate_json_files = list(candidate_dir.glob("*.json")) if candidate_dir.exists() else []
    
    if not candidate_py_files:
        return AutoQuantFlowResponse(
            run_id=run_id,
            candidate=None,
            message="No candidate .py file found in candidate directory.",
        )
    
    strategy_name = candidate_py_files[0].stem
    copied_py = str(candidate_py_files[0]) if candidate_py_files else None
    copied_json = str(candidate_json_files[0]) if candidate_json_files else None
    
    # Official strategy paths
    official_strategy = str(strategies_dir / f"{strategy_name}.py")
    official_json = str(strategies_dir / f"{strategy_name}.json")
    
    # Find output zip
    backtest_results_dir = latest_experiment_dir / "backtest_results"
    output_zips = list(backtest_results_dir.glob("backtest-result-*.zip")) if backtest_results_dir.exists() else []
    output_zip = str(output_zips[0]) if output_zips else None
    
    # Check zip contents
    zip_contains_py = False
    zip_contains_json = False
    if output_zip:
        zip_contains_py, zip_contains_json = _zip_contains_strategy_files(output_zip)
    
    # Try to find Freqtrade command
    command = None
    strategy_path_arg = None
    command_file = latest_experiment_dir / "freqtrade_command.txt"
    if command_file.exists():
        command = _read_text(command_file)
        strategy_path_arg = _extract_strategy_path_argument(command)
    
    # Build flow with available artifacts
    source_ok = _exists(official_strategy)
    candidate_ok = _exists(copied_py) and _exists(copied_json)
    command_ok = bool(command and "--strategy-path" in command)
    
    points_to_candidate = _same_path(strategy_path_arg, str(candidate_dir)) if candidate_dir else False
    
    # Build steps with available information
    step_models = [
        AutoQuantFlowStep(
            name="Source Strategy",
            status="done" if source_ok else "error",
            paths={"official_strategy": official_strategy, "official_json": official_json},
            message="Official strategy source loaded." if source_ok else "Official strategy source is missing.",
            technical_details={"strategy_name": strategy_name},
        ),
        AutoQuantFlowStep(
            name="Candidate Copy",
            status="done" if candidate_ok else "pending",
            paths={"candidate_dir": str(candidate_dir) if candidate_dir else None, "candidate_py": copied_py, "candidate_json": copied_json},
            message=(
                "Candidate copy created from artifacts."
                if candidate_ok
                else "Waiting for candidate artifact copy."
            ),
            technical_details={"official_files_unchanged": None},
        ),
        AutoQuantFlowStep(
            name="Freqtrade Execution",
            status="done" if command_ok else "pending",
            paths={"strategy_path": strategy_path_arg},
            message=(
                "Freqtrade command captured with run-local --strategy-path."
                if command_ok
                else "Freqtrade command has not been captured yet."
            ),
            technical_details={"command": command, "contains_strategy_path": bool(command_ok)},
        ),
        AutoQuantFlowStep(
            name="Metrics Parsing",
            status="done" if output_zip else "pending",
            paths={"output_zip": output_zip},
            message="Output zip available." if output_zip else "Output zip not available yet.",
            technical_details={
                "zip_contains_py": zip_contains_py,
                "zip_contains_json": zip_contains_json,
            },
        ),
        AutoQuantFlowStep(
            name="Decision",
            status="missing",
            paths={},
            message="Research decision not available (incomplete experiment record).",
            technical_details={"status": "missing", "reason": "ExperimentRecord incomplete"},
        ),
        AutoQuantFlowStep(
            name="Next Action",
            status="missing",
            paths={},
            message="Next action not available (research decision incomplete).",
            technical_details={"status": "missing", "reason": "ExperimentRecord incomplete"},
        ),
    ]
    
    return AutoQuantFlowResponse(
        run_id=run_id,
        candidate=AutoQuantCandidateFlow(
            run_id=run_id,
            experiment_id=latest_experiment_dir.name,
            candidate_id=None,
            strategy_name=strategy_name,
            official_source_strategy_path=official_strategy,
            official_source_json_path=official_json,
            candidate_directory=str(candidate_dir) if candidate_dir else None,
            copied_candidate_py=copied_py,
            copied_candidate_json=copied_json,
            official_files_unchanged=None,
            freqtrade_command=command,
            strategy_path_argument=strategy_path_arg,
            strategy_path_points_to_candidate_dir=points_to_candidate,
            strategy_path_points_to_run_dir=False,
            strategy_path_points_to_candidate_or_run_dir=points_to_candidate,
            output_zip_path=output_zip,
            output_zip_contains_py=zip_contains_py,
            output_zip_contains_json=zip_contains_json,
            parsed_metrics={},
            decision="UNAVAILABLE",
            reason_codes=["INCOMPLETE_EXPERIMENT_RECORD"],
            steps=step_models,
        ),
        message="Candidate flow built from partial artifacts (research decision incomplete).",
    )


def _flow_steps(
    *,
    experiment: ExperimentRecord,
    strategy_name: str | None,
    official_strategy: str | None,
    official_json: str | None,
    candidate_dir: str | None,
    copied_py: str | None,
    copied_json: str | None,
    official_files_unchanged: bool | None,
    command: str | None,
    strategy_path_arg: str | None,
    execution_run_dir: str | None,
    output_zip: str | None,
    zip_contains_py: bool | None,
    zip_contains_json: bool | None,
    parsed_metrics: dict[str, Any],
    decision: str,
    reason_codes: list[str],
) -> list[AutoQuantFlowStep]:
    source_ok = _exists(official_strategy)
    candidate_ok = _exists(copied_py) and _exists(copied_json)
    command_ok = bool(command and "--strategy-path" in command)
    metrics_ok = bool(parsed_metrics)
    rejected = decision == "REJECTED"

    next_action = {
        "KEEP": "Promote candidate champion, then diagnose the new champion.",
        "DROP": "Keep parent champion and move to the next hypothesis.",
        "INCONCLUSIVE": "Keep parent champion and collect better evidence.",
        "REJECTED": "Fix the system, protocol, or runtime issue before retrying.",
    }[decision]

    return [
        AutoQuantFlowStep(
            name="Source Strategy",
            status="done" if source_ok else "error",
            paths={"official_strategy": official_strategy, "official_json": official_json},
            message="Official strategy source loaded." if source_ok else "Official strategy source is missing.",
            technical_details={"strategy_name": strategy_name},
        ),
        AutoQuantFlowStep(
            name="Candidate Copy",
            status="done" if candidate_ok else "pending",
            paths={"candidate_dir": candidate_dir, "candidate_py": copied_py, "candidate_json": copied_json},
            message=(
                "Candidate copy created; official files unchanged."
                if candidate_ok and official_files_unchanged is True
                else "Candidate copy created; official file hash check is incomplete."
                if candidate_ok
                else "Waiting for candidate artifact copy."
            ),
            technical_details={"official_files_unchanged": official_files_unchanged},
        ),
        AutoQuantFlowStep(
            name="Freqtrade Execution",
            status="done" if command_ok and not rejected else "error" if rejected else "pending",
            paths={"execution_run_dir": execution_run_dir, "strategy_path": strategy_path_arg},
            message=(
                "Freqtrade command captured with run-local --strategy-path."
                if command_ok
                else "Freqtrade command has not been captured yet."
            ),
            technical_details={"command": command, "contains_strategy_path": bool(command_ok)},
        ),
        AutoQuantFlowStep(
            name="Metrics Parsing",
            status="done" if metrics_ok else "error" if rejected else "pending",
            paths={"output_zip": output_zip},
            message="Parsed metrics are available." if metrics_ok else "Parsed metrics are not available yet.",
            technical_details={
                "metrics": parsed_metrics,
                "zip_contains_py": zip_contains_py,
                "zip_contains_json": zip_contains_json,
                "metrics_availability_reason": experiment.metrics_availability_reason,
            },
        ),
        AutoQuantFlowStep(
            name="Decision",
            status="error" if rejected else "done",
            paths={},
            message=f"Decision: {decision}.",
            technical_details={"decision": decision, "reason_codes": reason_codes, "result": experiment.result},
        ),
        AutoQuantFlowStep(
            name="Next Action",
            status="error" if rejected else "done",
            paths={},
            message=next_action,
            technical_details={"experiment_status": experiment.status.value, "decision": decision},
        ),
    ]


def _safe_literal(node: ast.AST | None, *, fallback: Any = None, constants: dict[str, Any] | None = None) -> Any:
    if node is None:
        return fallback
    if isinstance(node, ast.Name) and constants and node.id in constants:
        return constants[node.id]
    try:
        return ast.literal_eval(node)
    except Exception:
        return fallback


def _keyword_literal(
    call: ast.Call,
    name: str,
    *,
    fallback: Any = None,
    constants: dict[str, Any] | None = None,
) -> Any:
    for keyword in call.keywords:
        if keyword.arg == name:
            return _safe_literal(keyword.value, fallback=fallback, constants=constants)
    return fallback


def _call_arg_literal(
    call: ast.Call,
    index: int,
    fallback: Any = None,
    *,
    constants: dict[str, Any] | None = None,
) -> Any:
    if len(call.args) <= index:
        return fallback
    return _safe_literal(call.args[index], fallback=fallback, constants=constants)


def _warning(code: str, message: str, severity: str = "warning") -> StrategyLibraryWarning:
    return StrategyLibraryWarning(code=code, message=message, severity=severity)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _sha256(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def _candidate_dir_from_record(experiment: ExperimentRecord, runs_root: Path) -> str | None:
    if experiment.candidate_id:
        return str(runs_root / experiment.run_id / "candidates" / experiment.candidate_id)
    underlying = experiment.underlying_execution_id
    if underlying and Path(str(underlying)).exists():
        return str(underlying)
    return None


def _find_execution_run_dir(execution_id: str | None, run_repository: Any) -> Path | None:
    if not execution_id:
        return None
    try:
        return Path(run_repository.find_run_dir(execution_id))
    except Exception:
        return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _extract_strategy_path_argument(command: str | None) -> str | None:
    if not command or "--strategy-path" not in command:
        return None
    # subprocess.list2cmdline quotes paths with spaces; this parser handles the
    # quoted and unquoted forms used by the runner.
    match = re.search(r"--strategy-path\s+(\"[^\"]+\"|'[^']+'|\S+)", command)
    if not match:
        return None
    return match.group(1).strip("\"'")


def _first_existing_path(*paths: str | None) -> str | None:
    for raw in paths:
        if raw and Path(raw).exists():
            return raw
    return None


def _zip_contains_strategy_files(zip_path: str | None) -> tuple[bool | None, bool | None]:
    if not zip_path:
        return None, None
    path = Path(zip_path)
    if not path.exists():
        return False, False
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except Exception:
        return False, False
    return any(name.endswith(".py") for name in names), any(name.endswith(".json") for name in names)


def _metric_values(snapshot: Any) -> dict[str, Any]:
    if snapshot is None:
        return {}
    result: dict[str, Any] = {}
    for name in (
        "total_trades",
        "net_profit_pct",
        "profit_factor",
        "expectancy",
        "max_drawdown_pct",
        "win_rate",
        "sharpe",
        "sortino",
        "calmar",
    ):
        metric = getattr(snapshot, name, None)
        if metric is not None and getattr(metric, "value", None) is not None:
            result[name] = metric.value
    return result


def _parsed_summary_values(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in (
        "total_trades",
        "net_profit_pct",
        "profit_factor",
        "expectancy",
        "max_drawdown_pct",
        "win_rate_pct",
        "sharpe_ratio",
        "sortino_ratio",
        "calmar_ratio",
    ):
        if name in payload and payload[name] is not None:
            result[name] = payload[name]
    return result


def _official_files_unchanged(
    experiment: ExperimentRecord,
    *,
    official_strategy: str | None,
    official_json: str | None,
    artifacts: dict[str, str],
) -> bool | None:
    strategy_hash_before = experiment.original_strategy_provenance.source_hash
    json_hash_before = artifacts.get("official_source_json_hash")
    strategy_ok = (
        _sha256(official_strategy) == strategy_hash_before
        if official_strategy and strategy_hash_before
        else None
    )
    json_ok = (
        _sha256(official_json) == json_hash_before
        if official_json and json_hash_before and Path(official_json).exists()
        else None
    )
    checks = [value for value in (strategy_ok, json_ok) if value is not None]
    if not checks:
        return None
    return all(checks)


def _decision_label(experiment: ExperimentRecord) -> str:
    result_text = (experiment.result or "").lower()
    if experiment.status in {ExperimentStatus.FAILED_SYSTEM, ExperimentStatus.INVALIDATED, ExperimentStatus.CANCELLED}:
        return "REJECTED"
    if result_text.startswith(("system_failure", "protocol_denied", "execution_system_failure")):
        return "REJECTED"
    if experiment.decision == ExperimentDecision.KEEP:
        return "KEEP"
    if experiment.decision == ExperimentDecision.DROP:
        return "DROP"
    return "INCONCLUSIVE"


def _reason_codes(experiment: ExperimentRecord) -> list[str]:
    codes: list[str] = []
    for raw in (experiment.result, experiment.metrics_availability_reason, experiment.status.value):
        if raw:
            codes.append(str(raw))
    if experiment.decision:
        codes.append(f"decision:{experiment.decision.value}")
    return list(dict.fromkeys(codes))


def _same_path(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    try:
        return Path(left).resolve() == Path(right).resolve()
    except Exception:
        return str(left) == str(right)


def _exists(path: str | None) -> bool:
    return bool(path and Path(path).exists())


def _stem_from_path(path: str | None) -> str | None:
    if not path:
        return None
    return Path(path).stem
