"""Workflow tool executor - explicit dispatch for validated tool calls.

This executor:
- Receives validated WorkflowToolCall
- Resolves tool spec from registry
- Enforces server-side policy
- Executes only allowlisted handlers
- Uses existing application workflows
- Normalizes results
- Produces context patches
- Records tool execution
- Returns structured failures instead of hiding them
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from ...core.errors import BackendError
from .copilot_session_store import CopilotSessionStore
from .strategy_resolver import (
    AmbiguousStrategyError,
    StrategyNotFoundError,
    resolve_strategy,
)
from .workflow_tool_models import (
    EditStrategySectionArgs,
    GetPairUniverseArgs,
    InspectAppStructureArgs,
    JobReference,
    ListStrategiesArgs,
    ReadStrategyFileArgs,
    RunBacktestArgs,
    RunOptimizerArgs,
    RunPairExplorerArgs,
    ToolRunStatus,
    ToolSafety,
    ValidateStrategySyntaxArgs,
    ViewBestParamsArgs,
    ViewTrialParamsArgs,
    WorkflowToolCall,
    WorkflowToolResult,
)
from .workflow_tool_registry import (
    calculate_arguments_hash,
    get_handler_name,
    get_tool_safety,
    is_long_running,
    validate_tool_arguments,
)

if TYPE_CHECKING:
    from ...api.session_store import SessionStore


# Progress callback type
ProgressCallback = Callable[[str, dict[str, Any]], None]


class WorkflowToolExecutor:
    """Explicit executor for workflow tools with server-side policy enforcement."""

    MAX_TOOL_RESULT_SIZE = 100_000  # Characters

    def __init__(
        self,
        services,
        session_store: SessionStore,
        copilot_store: CopilotSessionStore,
        root_dir: Path | None = None,
    ):
        self.services = services
        self.session_store = session_store
        self.copilot_store = copilot_store
        self.root_dir = root_dir or Path.cwd()

    async def execute(
        self,
        *,
        tool_call: WorkflowToolCall,
        copilot_session_id: str,
        confirmed: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> WorkflowToolResult:
        """Execute a validated tool call.
        
        Args:
            tool_call: Validated tool call with name, arguments, safety
            copilot_session_id: Copilot session ID for context
            confirmed: Whether user has confirmed this action
            progress_callback: Optional callback for progress updates
        
        Returns:
            WorkflowToolResult with status, result_summary, context_patch, error
        """
        tool_run_id = tool_call.tool_call_id
        tool_name = tool_call.tool_name
        
        # Resolve tool spec
        spec = get_tool_spec(tool_name)
        if spec is None:
            return WorkflowToolResult(
                tool_run_id=tool_run_id,
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_name,
                status=ToolRunStatus.FAILED,
                error=f"Unknown tool: {tool_name}",
            )

        # Enforce safety policy
        safety = get_tool_safety(tool_name)
        if safety == ToolSafety.FORBIDDEN:
            return WorkflowToolResult(
                tool_run_id=tool_run_id,
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_name,
                status=ToolRunStatus.FAILED,
                error=f"Tool '{tool_name}' is forbidden from AI execution",
            )

        if safety == ToolSafety.CONFIRMATION_REQUIRED and not confirmed:
            return WorkflowToolResult(
                tool_run_id=tool_run_id,
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_name,
                status=ToolRunStatus.AWAITING_CONFIRMATION,
                error="Confirmation required for this action",
            )

        # Execute using explicit dispatch
        started_at = datetime.now(tz=UTC).isoformat()
        
        try:
            handler_name = get_handler_name(tool_name)
            result = await self._dispatch_handler(
                handler_name,
                tool_call.arguments,
                copilot_session_id,
                progress_callback,
            )
            status = self._status_from_handler_result(result, tool_name)
            completed_at = (
                datetime.now(tz=UTC).isoformat()
                if status in {
                    ToolRunStatus.COMPLETED,
                    ToolRunStatus.FAILED,
                    ToolRunStatus.CANCELLED,
                    ToolRunStatus.TIMED_OUT,
                }
                else None
            )
            summary = result.get("summary")
            error = result.get("error")
            if error is None and isinstance(summary, dict):
                raw_error = summary.get("error")
                error = str(raw_error) if raw_error else None
            
            return WorkflowToolResult(
                tool_run_id=tool_run_id,
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_name,
                status=status,
                result_summary=summary,
                context_patch=result.get("context_patch"),
                error=error if status == ToolRunStatus.FAILED else None,
                started_at=started_at,
                completed_at=completed_at,
            )
        except Exception as exc:
            completed_at = datetime.now(tz=UTC).isoformat()
            error_msg = f"Tool execution failed: {exc}"
            
            return WorkflowToolResult(
                tool_run_id=tool_run_id,
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_name,
                status=ToolRunStatus.FAILED,
                error=error_msg,
                started_at=started_at,
                completed_at=completed_at,
            )

    def _status_from_handler_result(self, result: dict[str, Any], tool_name: str) -> ToolRunStatus:
        """Map backend handler status to a tool-run status without hiding failures."""
        raw_status = result.get("status")
        summary = result.get("summary")
        if raw_status is None and isinstance(summary, dict):
            raw_status = summary.get("status") or summary.get("phase")

        return self._normalize_status(raw_status, tool_name)

    def _normalize_status(self, raw_status: Any, tool_name: str) -> ToolRunStatus:
        if isinstance(raw_status, ToolRunStatus):
            return raw_status
        if raw_status is None:
            return ToolRunStatus.COMPLETED

        normalized = str(raw_status).strip().lower()
        if normalized in {"completed", "complete", "done", "success", "succeeded", "stopped"}:
            return ToolRunStatus.COMPLETED
        if normalized in {"failed", "failure", "error", "errored"}:
            return ToolRunStatus.FAILED
        if normalized in {"cancelled", "canceled"}:
            return ToolRunStatus.CANCELLED
        if normalized in {"observation_timeout", "observation_paused", "monitoring_paused"}:
            return ToolRunStatus.OBSERVATION_PAUSED
        if normalized in {"timed_out", "timeout", "execution_timeout", "execution_timed_out"}:
            return ToolRunStatus.TIMED_OUT
        if normalized in {"queued", "pending", "starting", "started", "running", "in_progress"}:
            return ToolRunStatus.RUNNING
        return ToolRunStatus.RUNNING if is_long_running(tool_name) else ToolRunStatus.COMPLETED

    async def _dispatch_handler(
        self,
        handler_name: str,
        arguments: dict[str, Any],
        copilot_session_id: str,
        progress_callback: ProgressCallback | None,
    ) -> dict[str, Any]:
        """Explicit dispatch to handler functions."""
        
        # READ-ONLY handlers
        if handler_name == "inspect_app_structure":
            return await self._handle_inspect_app_structure(arguments)
        if handler_name == "list_strategies":
            return await self._handle_list_strategies(arguments)
        if handler_name == "read_strategy_file":
            return await self._handle_read_strategy_file(arguments)
        if handler_name == "validate_strategy_syntax":
            return await self._handle_validate_strategy_syntax(arguments)
        if handler_name == "view_best_params":
            return await self._handle_view_best_params(arguments)
        if handler_name == "view_trial_params":
            return await self._handle_view_trial_params(arguments)
        if handler_name == "get_pair_universe":
            return await self._handle_get_pair_universe(arguments)
        
        # CONFIRMATION-REQUIRED handlers
        if handler_name == "run_backtest":
            return await self._handle_run_backtest(arguments, copilot_session_id, progress_callback)
        if handler_name == "run_optimizer":
            return await self._handle_run_optimizer(arguments, copilot_session_id, progress_callback)
        if handler_name == "run_pair_explorer":
            return await self._handle_run_pair_explorer(arguments, copilot_session_id, progress_callback)
        if handler_name == "edit_strategy_section":
            return await self._handle_edit_strategy_section(arguments, copilot_session_id)
        
        # Unknown handler
        raise ValueError(f"Unknown handler: {handler_name}")

    # ── READ-ONLY handlers ───────────────────────────────────────────────────────

    async def _handle_inspect_app_structure(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle inspect_app_structure tool."""
        settings = self.services.settings_store.load()
        
        return {
            "summary": {
                "strategies_directory": settings.strategies_directory_path,
                "user_data_directory": settings.user_data_directory_path,
                "freqtrade_executable": settings.freqtrade_executable_path,
                "default_config": settings.default_config_file_path,
                "available_endpoints": [
                    "/api/pair-explorer/run",
                    "/api/backtest/run",
                    "/api/optimizer/run",
                    "/api/stress-lab/run",
                    "/api/temporal-stress-lab/run",
                ],
                "ollama_configured": bool(settings.ollama_model),
                "ollama_model": settings.ollama_model or "Not configured",
            }
        }

    async def _handle_list_strategies(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle list_strategies tool."""
        settings = self.services.settings_store.load()
        strategies_dir = Path(settings.strategies_directory_path)

        py_files = {p.stem: p for p in strategies_dir.glob("*.py")}
        json_files = {p.stem: p.name for p in strategies_dir.glob("*.json")}
        all_stems = sorted(set(py_files) | set(json_files))

        strategies = []
        for stem in all_stems:
            py_path = py_files.get(stem)
            json_f = json_files.get(stem)
            if py_path:
                # Extract class name from file
                from .strategy_resolver import _extract_class_name
                class_name = _extract_class_name(py_path)
                strategies.append({
                    "name": stem,
                    "class_name": class_name,
                    "py_file": py_path.name,
                    "json_file": json_f,
                    "has_json": json_f is not None,
                })

        return {
            "summary": {
                "strategies": strategies,
                "count": len(strategies),
            }
        }

    async def _handle_read_strategy_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle read_strategy_file tool — uses strategy resolver for flexible name matching."""
        args = ReadStrategyFileArgs(**arguments)
        settings = self.services.settings_store.load()
        strategies_dir = Path(settings.strategies_directory_path)

        try:
            resolution = resolve_strategy(args.strategy_name, strategies_dir)
        except StrategyNotFoundError as exc:
            raise BackendError(str(exc), status_code=404) from exc
        except AmbiguousStrategyError as exc:
            raise BackendError(str(exc), status_code=409) from exc

        python_content = resolution.py_path.read_text(encoding="utf-8", errors="replace")
        json_content = None
        if resolution.has_json and resolution.json_path is not None:
            json_content = resolution.json_path.read_text(encoding="utf-8", errors="replace")

        # Truncate if too large
        if len(python_content) > self.MAX_TOOL_RESULT_SIZE:
            python_content = python_content[:self.MAX_TOOL_RESULT_SIZE] + "\n...[truncated]"

        return {
            "summary": {
                "strategy_name": resolution.stem,
                "class_name": resolution.class_name,
                "python_content": python_content,
                "json_content": json_content,
            }
        }

    async def _handle_validate_strategy_syntax(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle validate_strategy_syntax tool — uses strategy resolver for flexible name matching."""
        args = ValidateStrategySyntaxArgs(**arguments)

        # Import validation helpers
        import py_compile
        import tempfile

        settings = self.services.settings_store.load()
        strategies_dir = Path(settings.strategies_directory_path)

        try:
            resolution = resolve_strategy(args.strategy_name, strategies_dir)
        except StrategyNotFoundError as exc:
            raise BackendError(str(exc), status_code=404) from exc
        except AmbiguousStrategyError as exc:
            raise BackendError(str(exc), status_code=409) from exc

        content = resolution.py_path.read_text(encoding="utf-8", errors="replace")
        errors = []

        # py_compile check
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", encoding="utf-8", delete=False) as tf:
                tf.write(content)
                tmp_path = Path(tf.name)
            try:
                py_compile.compile(str(tmp_path), doraise=True)
            except py_compile.PyCompileError as exc:
                errors.append(str(exc).replace(str(tmp_path), f"{resolution.stem}.py"))
            finally:
                tmp_path.unlink(missing_ok=True)
        except Exception as exc:
            errors.append(str(exc))

        return {
            "summary": {
                "strategy_name": resolution.stem,
                "class_name": resolution.class_name,
                "valid": len(errors) == 0,
                "errors": errors,
            }
        }

    async def _handle_view_best_params(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle view_best_params tool."""
        args = ViewBestParamsArgs(**arguments)
        
        # Load optimizer session
        session = self.services.optimizer_store.load_session(args.optimizer_session_id)
        if session is None:
            raise BackendError(f"Optimizer session not found: {args.optimizer_session_id}", status_code=404)
        
        # Use real OptimizerSession fields: best_trial_number, best_metrics, trials
        if session.best_trial_number is None:
            return {
                "summary": {
                    "optimizer_session_id": args.optimizer_session_id,
                    "best_trial_number": None,
                    "message": "No best trial found yet",
                }
            }
        
        # Get the best trial from trials list
        best_trial = None
        for trial in session.trials:
            if trial.trial_number == session.best_trial_number:
                best_trial = trial
                break
        
        if best_trial is None:
            return {
                "summary": {
                    "optimizer_session_id": args.optimizer_session_id,
                    "best_trial_number": session.best_trial_number,
                    "message": f"Best trial #{session.best_trial_number} not found in trials list",
                }
            }
        
        return {
            "summary": {
                "optimizer_session_id": args.optimizer_session_id,
                "best_trial_number": session.best_trial_number,
                "parameters": best_trial.parameters or {},
                "metrics": best_trial.metrics.model_dump() if best_trial.metrics else {},
            }
        }

    async def _handle_view_trial_params(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle view_trial_params tool."""
        args = ViewTrialParamsArgs(**arguments)
        
        # Load optimizer session
        session = self.services.optimizer_store.load_session(args.optimizer_session_id)
        if session is None:
            raise BackendError(f"Optimizer session not found: {args.optimizer_session_id}", status_code=404)
        
        trial = None
        for t in session.trials:
            if t.trial_number == args.trial_number:
                trial = t
                break
        
        if trial is None:
            raise BackendError(f"Trial {args.trial_number} not found in session", status_code=404)
        
        return {
            "summary": {
                "optimizer_session_id": args.optimizer_session_id,
                "trial_number": trial.trial_number,
                "parameters": trial.parameters or {},
                "metrics": trial.metrics.model_dump() if trial.metrics else {},
            }
        }

    async def _handle_get_pair_universe(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle get_pair_universe tool — reads real PairSelectorService state."""
        args = GetPairUniverseArgs(**arguments)

        pair_selector = getattr(self.services, "pair_selector", None)
        if pair_selector is None:
            raise BackendError(
                "PairSelectorService is not available on services.",
                status_code=503,
            )

        state = pair_selector.get_state()
        # Union of available + extended pairs
        all_pairs: list[str] = list(state.available_pairs)
        extended = getattr(state, "extended_pairs", []) or []
        seen: set[str] = set(all_pairs)
        for p in extended:
            if p not in seen:
                all_pairs.append(p)
                seen.add(p)

        # Apply quote_currency filter
        if args.quote_currency:
            suffix = f"/{args.quote_currency.upper()}"
            all_pairs = [p for p in all_pairs if p.upper().endswith(suffix)]

        # Apply exclude filter
        if args.exclude_pairs:
            excluded = {p.upper() for p in args.exclude_pairs}
            all_pairs = [p for p in all_pairs if p.upper() not in excluded]

        # Cap at max_candidates
        if args.max_candidates is not None:
            all_pairs = all_pairs[: args.max_candidates]

        return {
            "summary": {
                "pairs": all_pairs,
                "total": len(all_pairs),
                "filtered_by": {
                    "quote_currency": args.quote_currency,
                    "excluded": args.exclude_pairs or [],
                    "max_candidates": args.max_candidates,
                },
                "note": (
                    "These are available pairs from PairSelectorService. "
                    "Profitability is NOT implied — use run_pair_explorer to measure performance."
                ),
            }
        }

    # ── CONFIRMATION-REQUIRED handlers ─────────────────────────────────────────────

    async def _handle_run_backtest(
        self,
        arguments: dict[str, Any],
        copilot_session_id: str,
        progress_callback: ProgressCallback | None,
    ) -> dict[str, Any]:
        """Handle run_backtest tool using reusable job function and observe to completion."""
        from ..workflow_jobs import start_backtest_job
        from .job_observer import observe_job
        
        args = RunBacktestArgs(**arguments)
        
        if progress_callback:
            progress_callback("tool_started", {"tool_name": "run_backtest"})
        
        # Call reusable job start function
        api_session_id, initial_status = await start_backtest_job(
            services=self.services,
            store=self.session_store,
            strategy_name=args.strategy_name,
            version_id=args.version_id,
            timerange=args.timerange,
            timeframe=args.timeframe,
            pairs=args.pairs,
            max_open_trades=args.max_open_trades,
            dry_run_wallet=args.dry_run_wallet,
            config_file=args.config_file,
        )
        
        # Add job reference to copilot session (preserve api_session_id separately)
        job_ref = JobReference(
            job_type="backtest",
            api_session_id=api_session_id,
            status=initial_status,
        )
        
        copilot_session = self.copilot_store.load_session(copilot_session_id)
        self.copilot_store.add_active_job(copilot_session, job_ref.model_dump())
        self.copilot_store.save_session(copilot_session)
        
        # Observe job to terminal status
        final_status = initial_status
        final_result = {}
        run_id = None
        timed_out = False

        async for event in observe_job(
            session_store=self.session_store,
            api_session_id=api_session_id,
            job_type="backtest",
        ):
            if progress_callback:
                progress_callback("tool_progress", event)

            if event["type"] == "observation_timeout":
                # Backend never reached a terminal status within the window.
                # The job is still running from the backend's perspective, so it
                # must NOT be reported as COMPLETED.
                timed_out = True
                final_status = ToolRunStatus.OBSERVATION_PAUSED.value
                if run_id is None and event.get("result"):
                    final_result = event.get("result", {})
                    if "run_id" in final_result:
                        run_id = final_result["run_id"]
                continue

            if event["type"] == "job_progress":
                backend_status = event["status"]
                final_result = event.get("result", {})

                # Map backend status to ToolRunStatus (never silently COMPLETED)
                if backend_status == "completed":
                    final_status = ToolRunStatus.COMPLETED.value
                elif backend_status == "failed":
                    final_status = ToolRunStatus.FAILED.value
                elif backend_status == "cancelled":
                    final_status = ToolRunStatus.CANCELLED.value
                else:
                    # queued, running, or any non-terminal status
                    final_status = ToolRunStatus.RUNNING.value

                # Extract run_id from result when available
                if "run_id" in final_result:
                    run_id = final_result["run_id"]

            if event["type"] == "error":
                return {
                    "summary": {
                        "api_session_id": api_session_id,
                        "strategy_name": args.strategy_name,
                        "status": ToolRunStatus.FAILED.value,
                        "error": event.get("error"),
                    },
                    "context_patch": {},
                }

        # Build context patch with real run_id if available
        context_patch = {}
        if run_id:
            context_patch["backtest_run_id"] = run_id

        return {
            "summary": {
                "api_session_id": api_session_id,
                "run_id": run_id,
                "strategy_name": args.strategy_name,
                "pairs": args.pairs,
                "timeframe": args.timeframe,
                "timerange": args.timerange,
                "status": final_status,
                "timed_out": timed_out,
                "result": final_result,
            },
            "context_patch": context_patch,
        }

    async def _handle_run_optimizer(
        self,
        arguments: dict[str, Any],
        copilot_session_id: str,
        progress_callback: ProgressCallback | None,
    ) -> dict[str, Any]:
        """Handle run_optimizer tool using reusable job function and observe to completion."""
        from ..workflow_jobs import start_optimizer_job
        from .job_observer import observe_optimizer_job
        
        args = RunOptimizerArgs(**arguments)
        
        if progress_callback:
            progress_callback("tool_started", {"tool_name": "run_optimizer"})
        
        # Call reusable job start function
        api_session_id, optimizer_session_id, initial_status = await start_optimizer_job(
            services=self.services,
            store=self.session_store,
            strategy_name=args.strategy_name,
            timerange=args.timerange,
            timeframe=args.timeframe,
            pairs=args.pairs,
            search_spaces=args.search_spaces,
            total_trials=args.total_trials,
            search_strategy=args.search_strategy,
            parameter_mode=args.parameter_mode,
            score_metric=args.score_metric,
            max_open_trades=args.max_open_trades,
            dry_run_wallet=args.dry_run_wallet,
            fee_rate=args.fee_rate,
            enable_vectorbt_screening=args.enable_vectorbt_screening,
            vectorbt_candidate_count=args.vectorbt_candidate_count,
            vectorbt_keep_ratio=args.vectorbt_keep_ratio,
            vectorbt_timeout_seconds=args.vectorbt_timeout_seconds,
            config_file=args.config_file,
        )
        
        # Add job reference to copilot session
        job_ref = JobReference(
            job_type="optimizer",
            api_session_id=api_session_id,
            workflow_session_id=optimizer_session_id,
            status=initial_status,
        )
        
        copilot_session = self.copilot_store.load_session(copilot_session_id)
        self.copilot_store.add_active_job(copilot_session, job_ref.model_dump())
        self.copilot_store.save_session(copilot_session)
        
        # Observe optimizer to terminal status
        final_phase = initial_status
        final_metrics = {}
        timed_out = False

        async for event in observe_optimizer_job(
            services=self.services,
            api_session_id=api_session_id,
            optimizer_session_id=optimizer_session_id,
        ):
            if progress_callback:
                progress_callback("tool_progress", event)

            if event["type"] == "observation_timeout":
                # Optimizer never reached a terminal phase within the window.
                # It is still running from the backend's perspective, so it
                # must NOT be reported as COMPLETED.
                timed_out = True
                final_phase = ToolRunStatus.OBSERVATION_PAUSED.value
                continue

            if event["type"] == "optimizer_progress":
                backend_phase = event["phase"]
                final_metrics = {
                    "total_trials": event["total_trials"],
                    "completed_trials": event["completed_trials"],
                    "failed_trials": event["failed_trials"],
                    "best_trial_number": event["best_trial_number"],
                    "best_metrics": event["best_metrics"],
                    "stop_reason": event["stop_reason"],
                }

                # Map optimizer phase to ToolRunStatus (never silently COMPLETED)
                if backend_phase in ("completed", "stopped"):
                    final_phase = ToolRunStatus.COMPLETED.value
                elif backend_phase == "failed":
                    final_phase = ToolRunStatus.FAILED.value
                elif backend_phase == "cancelled":
                    final_phase = ToolRunStatus.CANCELLED.value
                else:
                    # queued, running, or any non-terminal phase
                    final_phase = ToolRunStatus.RUNNING.value

            if event["type"] == "error":
                return {
                    "summary": {
                        "api_session_id": api_session_id,
                        "optimizer_session_id": optimizer_session_id,
                        "strategy_name": args.strategy_name,
                        "status": ToolRunStatus.FAILED.value,
                        "error": event.get("error"),
                    },
                    "context_patch": {},
                }

        return {
            "summary": {
                "api_session_id": api_session_id,
                "optimizer_session_id": optimizer_session_id,
                "strategy_name": args.strategy_name,
                "pairs": args.pairs,
                "total_trials": args.total_trials,
                "status": final_phase,
                "timed_out": timed_out,
                "metrics": final_metrics,
            },
            "context_patch": {
                "optimizer_session_id": optimizer_session_id,
            },
        }

    async def _handle_run_pair_explorer(
        self,
        arguments: dict[str, Any],
        copilot_session_id: str,
        progress_callback: ProgressCallback | None,
    ) -> dict[str, Any]:
        """Handle run_pair_explorer tool using reusable job function and observe to completion."""
        from ..workflow_jobs import start_pair_explorer_job
        from .job_observer import observe_pair_explorer_job

        args = RunPairExplorerArgs(**arguments)

        if progress_callback:
            progress_callback("tool_started", {"tool_name": "run_pair_explorer"})

        # Call reusable job start function
        pe_session_id, initial_status = await start_pair_explorer_job(
            services=self.services,
            strategy_name=args.strategy_name,
            pairs=args.pairs,
            timeframe=args.timeframe,
            timerange=args.timerange,
            dry_run_wallet=args.dry_run_wallet,
            max_open_trades=args.max_open_trades,
        )

        # Add job reference to copilot session
        job_ref = JobReference(
            job_type="pair_explorer",
            api_session_id=pe_session_id,
            status=initial_status,
        )

        copilot_session = self.copilot_store.load_session(copilot_session_id)
        self.copilot_store.add_active_job(copilot_session, job_ref.model_dump())
        self.copilot_store.save_session(copilot_session)

        # Observe job to terminal status
        final_status = initial_status
        final_results = []
        timed_out = False

        async for event in observe_pair_explorer_job(
            services=self.services,
            pe_session_id=pe_session_id,
        ):
            if progress_callback:
                progress_callback("job_active", {"job_ref": job_ref.model_dump(), "event": event})

            if event["type"] == "observation_timeout":
                timed_out = True
                break

            if event["type"] == "pair_explorer_progress":
                final_status = event.get("status", final_status)
                final_results = event.get("results", [])

                # Update copilot session
                copilot_session = self.copilot_store.load_session(copilot_session_id)
                self.copilot_store.update_job_status(copilot_session, "pair_explorer", final_status)
                self.copilot_store.save_session(copilot_session)

            if event["type"] == "error":
                final_status = "failed"
                break

        # Final terminal update
        if progress_callback:
            if timed_out:
                progress_callback("tool_timed_out", {"tool_name": "run_pair_explorer"})
            elif final_status == "failed":
                progress_callback("tool_failed", {"tool_name": "run_pair_explorer"})
            else:
                progress_callback("tool_result", {"tool_name": "run_pair_explorer"})

        # Compile final structured result
        if timed_out:
            return {
                "status": "timed_out",
                "message": (
                    f"Pair Explorer (session {pe_session_id}) is still running "
                    "in the background after 5 minutes."
                ),
            }

        return {
            "summary": {
                "pair_explorer_session_id": pe_session_id,
                "status": final_status,
                "total_pairs_tested": sum(len(g.get("pairs", [])) for g in final_results),
                "results": final_results,
            }
        }

    async def _handle_edit_strategy_section(
        self,
        arguments: dict[str, Any],
        copilot_session_id: str,
    ) -> dict[str, Any]:
        """Handle edit_strategy_section tool with preview + confirmation flow."""
        # This should implement the full edit flow:
        # 1. Resolve allowlisted strategy path
        # 2. Generate diff preview
        # 3. Store current SHA256
        # 4. Return preview for UI confirmation
        # 5. On confirmation: snapshot, atomic write, validate, rollback on failure
        
        # For now, placeholder
        raise BackendError(
            "Strategy edit tool execution not yet implemented. "
            "Implement with preview + confirmation flow.",
            status_code=501,
        )


def get_tool_spec(name: str):
    """Import get_tool_spec from registry."""
    from .workflow_tool_registry import get_tool_spec as _get_tool_spec
    return _get_tool_spec(name)
