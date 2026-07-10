"""Workflow copilot orchestration loop.

This module implements the core orchestration loop:
1. Build bounded context from app state
2. Call model with tools
3. Extract tool calls
4. Validate tool calls against registry
5. Check safety policy
6. Require confirmation for guarded actions
7. Execute tool via executor
8. Observe long-running job progress
9. Return tool result to model
10. Continue until final answer or max steps

Key invariants:
- No arbitrary function dispatch
- No eval/exec/globals
- Server-side policy enforcement
- Evidence-based results
- Duplicate detection
- Max step guard
- Confirmation pause/resume
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

from ...services.agent_context import AgentContextService
from .copilot_session_store import CopilotSessionStore
from .intent_router import route_intent, WorkflowPlan
from .ollama_client import OllamaClient
from .ollama_errors import friendly_ollama_error
from .strategy_resolver import resolve_strategy
from .workflow_tool_executor import WorkflowToolExecutor
from .workflow_tool_models import (
    PendingToolAction,
    ToolRunRecord,
    ToolRunStatus,
    ToolSafety,
    WorkflowToolCall,
)
from .workflow_tool_registry import (
    calculate_arguments_hash,
    get_model_tools,
    get_tool_safety,
    validate_tool_arguments,
)

if TYPE_CHECKING:
    from ...api.session_store import SessionStore


import re

logger = logging.getLogger(__name__)

MAX_ORCHESTRATION_STEPS = 10
DUPLICATE_DETECTION_WINDOW = 3  # Check last N tool calls for duplicates

# Cheap sanity patterns used by the guarded-tool auto-confirm pre-check.
_TIMERANGE_RE = re.compile(r"^\d{8}-\d{8}$")
_PAIR_RE = re.compile(r"^[A-Z0-9]{2,20}/[A-Z0-9]{2,10}$")
_GUARDED_TOOLS_NEEDING_PAIRS = {
    "run_pair_explorer",
    "run_pair_stress_lab",
    "run_temporal_stress_test",
}


class WorkflowCopilot:
    """Orchestrates the model-tool-result loop with safety and confirmation."""

    def __init__(
        self,
        services,
        session_store: SessionStore,
        copilot_store: CopilotSessionStore,
        executor: WorkflowToolExecutor,
        context_service: AgentContextService,
        ollama_client: OllamaClient,
        root_dir: Path | None = None,
    ):
        self.services = services
        self.session_store = session_store
        self.copilot_store = copilot_store
        self.executor = executor
        self.context_service = context_service
        self.ollama_client = ollama_client
        self.root_dir = root_dir or Path.cwd()

    # ── Guarded-tool auto-confirm pre-check ────────────────────────────────────

    def _precheck_guarded_tool(self, tool_name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        """Cheap, local sanity check for guarded tools before auto-confirming.

        Runs NO backtest/optimizer — just validates the request is well-formed:
        - strategy exists on disk (reuse the real resolver)
        - timerange looks like YYYYMMDD-YYYYMMDD and start <= end
        - if the tool needs pairs, the list is non-empty and each entry is a
          sane pair symbol (BASE/QUOTE)

        Returns (passed, reason). On failure the caller must still PAUSE and ask
        the user, never auto-run.
        """
        try:
            settings = self.services.settings_store.load()
            strategies_dir = Path(settings.strategies_directory_path)
        except Exception as exc:
            return False, f"could not load settings: {exc}"

        # 1) strategy exists
        strategy_name = arguments.get("strategy_name")
        if not strategy_name:
            return False, "missing strategy_name"
        try:
            resolve_strategy(strategy_name, strategies_dir)
        except Exception as exc:
            return False, f"strategy not found: {exc}"

        # 2) timerange sane (only when the tool declares one)
        timerange = arguments.get("timerange")
        if timerange:
            m = _TIMERANGE_RE.match(str(timerange))
            if not m:
                return False, f"timerange '{timerange}' is not YYYYMMDD-YYYYMMDD"
            start, end = str(timerange).split("-")
            if start > end:
                return False, f"timerange start {start} is after end {end}"

        # 3) pairs valid (only for tools that require them)
        if tool_name in _GUARDED_TOOLS_NEEDING_PAIRS:
            pairs = arguments.get("pairs") or []
            if not pairs:
                return False, f"{tool_name} requires a non-empty pairs list"
            for p in pairs:
                if not _PAIR_RE.match(str(p)):
                    return False, f"pair '{p}' is not a valid BASE/QUOTE symbol"

        return True, "pre-check passed"

    async def process_turn(
        self,
        session_id: str,
        user_message: str,
        model: str | None = None,
        mode: str = "analysis",
        stream: bool = False,
        context_overrides: dict[str, Any] | None = None,
        auto_confirm: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        """Process a single user turn through the orchestration loop.
        
        Yields events for streaming:
        - "message": partial message content
        - "tool_call": tool call requiring confirmation
        - "tool_started": tool execution started
        - "tool_progress": tool progress update
        - "tool_result": tool execution result
        - "tool_failed": tool execution failed
        - "final": final answer from model
        - "error": orchestration error
        """
        # Load or create session
        try:
            session = self.copilot_store.load_session(session_id)
        except Exception:
            session = self.copilot_store.create_session(
                model=model or "llama3",
                mode=mode,
            )
            session["session_id"] = session_id
        
        # Persist context overrides if provided
        if context_overrides:
            session["last_context_overrides"] = context_overrides
            self.copilot_store.save_session(session)

        # Persist auto-confirm preference for this turn (honored on resume too)
        session["auto_confirm"] = bool(auto_confirm)
        self.copilot_store.save_session(session)

        # Add user message
        self.copilot_store.add_message(session, "user", user_message)
        self.copilot_store.save_session(session)

        # Try deterministic intent routing first
        workflow_plan = route_intent(user_message)
        if workflow_plan and workflow_plan["steps"]:
            logger.info(f"Intent detected: {workflow_plan['intent']} with confidence {workflow_plan['confidence']}")
            async for event in self._execute_workflow_plan(
                session_id,
                workflow_plan,
                session,
                mode,
            ):
                yield event
            return

        # Resolve model
        resolved_model = model or session.get("model") or "llama3"

        # Build bounded context
        context = self._build_context(session, mode)

        # Build prompt messages
        messages = self._build_messages(session, context, mode)

        # Orchestration loop
        step = 0
        seen_hashes: set[str] = set()

        while step < MAX_ORCHESTRATION_STEPS:
            step += 1
            logger.info(f"Orchestration step {step}/{MAX_ORCHESTRATION_STEPS}")

            # Call model with tools
            yield {"type": "status", "message": f"Thinking (step {step})..."}
            
            try:
                tools = get_model_tools(mode)
                response = await self.ollama_client.chat(
                    messages=messages,
                    tools=tools,
                    model=resolved_model,
                )
            except Exception as exc:
                logger.error(f"Model call failed: {exc}")
                friendly_error = friendly_ollama_error(exc)
                yield {"type": "error", "message": f"⚠️ {friendly_error}"}
                return

            # Extract content and tool calls
            content = getattr(response, "content", "")
            tool_calls = self._extract_tool_calls(response)

            # Resolve the tool_call_id assigned to each tool call so we can later
            # attach the tool result to the exact assistant message that
            # requested it (Ollama/OpenAI tool-call protocol invariant).
            for idx, tc in enumerate(tool_calls):
                tc.setdefault("tool_call_id", f"call_{step}_{idx}")

            # Add assistant message (preserve tool_calls in the in-memory list)
            self.copilot_store.add_message(
                session,
                "assistant",
                content,
                tool_calls=tool_calls,
            )
            self.copilot_store.save_session(session)

            assistant_message = {
                "role": "assistant",
                "content": content,
            }
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            messages.append(assistant_message)

            # Yield content
            if content:
                yield {"type": "message", "content": content}

            # If no tool calls, we're done
            if not tool_calls:
                yield {"type": "final", "content": content}
                return

            # Process tool calls
            for tool_call_data in tool_calls:
                tool_name = tool_call_data.get("name")
                arguments = tool_call_data.get("arguments", {})

                # Validate tool
                is_valid, error_msg, validated = validate_tool_arguments(tool_name, arguments)
                if not is_valid:
                    logger.warning(f"Invalid tool call: {error_msg}")
                    yield {"type": "error", "message": error_msg}
                    continue

                # Check for duplicate
                tool_hash = calculate_arguments_hash(tool_name, arguments)
                if tool_hash in seen_hashes:
                    logger.warning(f"Duplicate tool call detected: {tool_name}")
                    yield {"type": "error", "message": f"Duplicate tool call: {tool_name}"}
                    continue
                seen_hashes.add(tool_hash)

                # Check safety
                safety = get_tool_safety(tool_name)
                if safety == ToolSafety.FORBIDDEN:
                    yield {"type": "error", "message": f"Tool '{tool_name}' is forbidden"}
                    continue

                # Create workflow tool call
                workflow_call_kwargs = {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "safety": safety,
                }
                if tool_call_data.get("tool_call_id"):
                    workflow_call_kwargs["tool_call_id"] = tool_call_data["tool_call_id"]
                workflow_call = WorkflowToolCall(
                    **workflow_call_kwargs,
                )

                # If confirmation required, decide auto-confirm vs. pause
                if safety == ToolSafety.CONFIRMATION_REQUIRED:
                    auto_confirm_now = bool(session.get("auto_confirm", False))
                    if auto_confirm_now:
                        passed, reason = self._precheck_guarded_tool(tool_name, arguments)
                        if passed:
                            yield {
                                "type": "auto_confirmed",
                                "tool_name": tool_name,
                                "reason": reason,
                            }
                            yield {"type": "tool_started", "tool_name": tool_name}
                            result = await self.executor.execute(
                                tool_call=workflow_call,
                                copilot_session_id=session_id,
                                confirmed=True,
                                progress_callback=None,
                            )
                            # Record + emit result (mirrors read-only path below)
                            tool_run = ToolRunRecord(
                                tool_call_id=workflow_call.tool_call_id,
                                tool_name=tool_name,
                                arguments=arguments,
                                safety=safety,
                                status=result.status,
                                started_at=result.started_at,
                                completed_at=result.completed_at,
                                result_summary=result.result_summary,
                                error=result.error,
                            )
                            self.copilot_store.add_tool_run(session, tool_run.model_dump())
                            self.copilot_store.save_session(session)
                            if result.status == ToolRunStatus.COMPLETED:
                                yield {
                                    "type": "tool_result",
                                    "tool_name": tool_name,
                                    "result": result.result_summary,
                                }
                            else:
                                yield {
                                    "type": "tool_failed",
                                    "tool_name": tool_name,
                                    "error": result.error,
                                }
                            # Add tool result to messages for next model turn.
                            tool_result_content = json.dumps(result.result_summary or {"error": result.error})
                            messages.append({
                                "role": "tool",
                                "content": tool_result_content,
                                "tool_call_id": workflow_call.tool_call_id,
                            })
                            self.copilot_store.add_message(
                                session, "tool", tool_result_content,
                                tool_call_id=workflow_call.tool_call_id,
                            )
                            self.copilot_store.save_session(session)
                            continue
                        # Pre-check failed: still pause and surface the reason.
                        yield {
                            "type": "auto_confirm_blocked",
                            "tool_name": tool_name,
                            "reason": reason,
                        }

                    pending_action = PendingToolAction(
                        session_id=session_id,
                        tool_call_id=workflow_call.tool_call_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        arguments_hash=tool_hash,
                        safety=safety,
                    )
                    self.copilot_store.add_pending_action(session, pending_action.model_dump())
                    self.copilot_store.save_session(session)

                    yield {
                        "type": "tool_confirmation_required",
                        "action_id": pending_action.action_id,
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "confirmation_endpoint": "/api/ai/actions/confirm",
                        "confirmation_action_type": "confirm_tool_action",
                        "confirmation_payload": {"action_id": pending_action.action_id},
                    }
                    return  # Pause for user confirmation

                # Execute read-only tools immediately
                yield {"type": "tool_started", "tool_name": tool_name}

                result = await self.executor.execute(
                    tool_call=workflow_call,
                    copilot_session_id=session_id,
                    confirmed=False,
                    progress_callback=None,  # Progress events handled separately
                )

                # Record tool run
                tool_run = ToolRunRecord(
                    tool_call_id=workflow_call.tool_call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    safety=safety,
                    status=result.status,
                    started_at=result.started_at,
                    completed_at=result.completed_at,
                    result_summary=result.result_summary,
                    error=result.error,
                )
                self.copilot_store.add_tool_run(session, tool_run.model_dump())
                self.copilot_store.save_session(session)

                # Yield result
                if result.status == ToolRunStatus.COMPLETED:
                    yield {
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "result": result.result_summary,
                    }
                else:
                    yield {
                        "type": "tool_failed",
                        "tool_name": tool_name,
                        "error": result.error,
                    }
                    # Continue with other tools even if one fails

                # Add tool result to messages for next model turn.
                # Must follow the assistant message that carried the tool call
                # and carry the matching tool_call_id (protocol invariant).
                tool_result_content = json.dumps(result.result_summary or {"error": result.error})
                messages.append({
                    "role": "tool",
                    "content": tool_result_content,
                    "tool_call_id": workflow_call.tool_call_id,
                })
                self.copilot_store.add_message(
                    session,
                    "tool",
                    tool_result_content,
                    tool_call_id=workflow_call.tool_call_id,
                )
                self.copilot_store.save_session(session)

        # Max steps reached
        yield {
            "type": "error",
            "message": f"Reached maximum orchestration steps ({MAX_ORCHESTRATION_STEPS})",
        }

    async def confirm_action(
        self,
        session_id: str,
        action_id: str,
    ) -> dict[str, Any]:
        """Confirm and execute a pending tool action.
        
        Returns the tool execution result.
        """
        result, _tool_run = await self._execute_pending_action(session_id, action_id)
        return result.model_dump()

    async def _execute_pending_action(
        self,
        session_id: str,
        action_id: str,
        progress_callback=None,
    ):
        session = self.copilot_store.load_session(session_id)
        pending = self.copilot_store.get_pending_action(session, action_id)

        if pending is None:
            raise ValueError(f"Pending action not found: {action_id}")

        self.copilot_store.remove_pending_action(session, action_id)
        self.copilot_store.save_session(session)

        workflow_call_kwargs = {
            "tool_name": pending["tool_name"],
            "arguments": pending["arguments"],
            "safety": pending["safety"],
        }
        if pending.get("tool_call_id"):
            workflow_call_kwargs["tool_call_id"] = pending["tool_call_id"]
        workflow_call = WorkflowToolCall(**workflow_call_kwargs)

        result = await self.executor.execute(
            tool_call=workflow_call,
            copilot_session_id=session_id,
            confirmed=True,
            progress_callback=progress_callback,
        )

        latest_session = self.copilot_store.load_session(session_id)
        self.copilot_store.remove_pending_action(latest_session, action_id)
        tool_run = ToolRunRecord(
            tool_call_id=workflow_call.tool_call_id,
            tool_name=pending["tool_name"],
            arguments=pending["arguments"],
            safety=pending["safety"],
            status=result.status,
            started_at=result.started_at,
            completed_at=result.completed_at,
            result_summary=result.result_summary,
            error=result.error,
        )
        dumped_tool_run = tool_run.model_dump()
        self.copilot_store.add_tool_run(latest_session, dumped_tool_run)
        self.copilot_store.save_session(latest_session)

        return result, dumped_tool_run

    async def resume_after_confirmation(
        self,
        session_id: str,
        action_id: str,
        stream: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        """Resume orchestration after tool confirmation.
        
        This method:
        1. Confirms and executes the pending action
        2. Adds the tool result to the conversation
        3. Continues the model-tool-result loop
        
        Yields events for streaming.
        """
        session = self.copilot_store.load_session(session_id)
        pending = self.copilot_store.get_pending_action(session, action_id)
        if pending is None:
            yield {"type": "error", "message": f"Pending action not found: {action_id}"}
            return

        tool_name = pending["tool_name"]
        progress_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        def progress_callback(kind: str, data: dict[str, Any]) -> None:
            event = self._progress_event_from_callback(tool_name, kind, data)
            if event is not None:
                progress_queue.put_nowait(event)

        yield {
            "type": "tool_started",
            "tool_name": tool_name,
            "action_id": action_id,
        }

        execution_task = asyncio.create_task(
            self._execute_pending_action(
                session_id,
                action_id,
                progress_callback=progress_callback,
            )
        )

        while not execution_task.done():
            try:
                yield await asyncio.wait_for(progress_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

        try:
            result, tool_run = await execution_task
        except Exception as exc:
            yield {"type": "tool_failed", "tool_name": tool_name, "error": str(exc)}
            return

        while not progress_queue.empty():
            yield progress_queue.get_nowait()

        yield self._terminal_event_for_result(result)

        session = self.copilot_store.load_session(session_id)
        
        # Build context and continue reasoning
        context = self._build_context(session, session.get("mode", "analysis"))
        messages = self._build_messages(session, context, session.get("mode", "analysis"))
        
        # Add tool result message for the model and persist to session
        tool_result_content = self._tool_result_content(result)
        tool_result_msg = {
            "role": "tool",
            "content": tool_result_content,
            "tool_call_id": tool_run.get("tool_call_id"),
        }
        messages.append(tool_result_msg)
        
        # Persist tool result to session for subsequent model calls
        self.copilot_store.add_message(
            session,
            "tool",
            tool_result_content,
            tool_call_id=tool_run.get("tool_call_id"),
        )
        self.copilot_store.save_session(session)
        
        # Continue orchestration loop
        step = 0
        seen_hashes: set[str] = set()
        
        while step < MAX_ORCHESTRATION_STEPS:
            step += 1
            logger.info(f"Resume orchestration step {step}/{MAX_ORCHESTRATION_STEPS}")
            
            yield {"type": "status", "message": f"Thinking (step {step})..."}
            
            try:
                model = session.get("model") or "llama3"
                tools = get_model_tools(session.get("mode", "analysis"))
                response = await self.ollama_client.chat(
                    messages=messages,
                    tools=tools,
                    model=model,
                )
            except Exception as exc:
                logger.error(f"Model call failed: {exc}")
                friendly_error = friendly_ollama_error(exc)
                yield {"type": "error", "message": f"⚠️ {friendly_error}"}
                return
            
            # Extract content and tool calls
            content = getattr(response, "content", "")
            tool_calls = self._extract_tool_calls(response)

            for idx, tc in enumerate(tool_calls):
                tc.setdefault("tool_call_id", f"resume_call_{step}_{idx}")
            
            # Add assistant message
            self.copilot_store.add_message(
                session,
                "assistant",
                content,
                tool_calls=tool_calls,
            )
            self.copilot_store.save_session(session)

            assistant_message = {
                "role": "assistant",
                "content": content,
            }
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            messages.append(assistant_message)
            
            # Yield content
            if content:
                yield {"type": "message", "content": content}
            
            # If no tool calls, we're done
            if not tool_calls:
                yield {"type": "final", "content": content}
                return
            
            # Process tool calls
            for tool_call_data in tool_calls:
                tool_name = tool_call_data.get("name")
                arguments = tool_call_data.get("arguments", {})
                
                # Validate tool
                is_valid, error_msg, validated = validate_tool_arguments(tool_name, arguments)
                if not is_valid:
                    logger.warning(f"Invalid tool call: {error_msg}")
                    yield {"type": "error", "message": error_msg}
                    continue
                
                # Check for duplicate
                tool_hash = calculate_arguments_hash(tool_name, arguments)
                if tool_hash in seen_hashes:
                    logger.warning(f"Duplicate tool call detected: {tool_name}")
                    yield {"type": "error", "message": f"Duplicate tool call: {tool_name}"}
                    continue
                seen_hashes.add(tool_hash)
                
                # Check safety
                safety = get_tool_safety(tool_name)
                if safety == ToolSafety.FORBIDDEN:
                    yield {"type": "error", "message": f"Tool '{tool_name}' is forbidden"}
                    continue
                
                # Create workflow tool call
                workflow_call_kwargs = {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "safety": safety,
                }
                if tool_call_data.get("tool_call_id"):
                    workflow_call_kwargs["tool_call_id"] = tool_call_data["tool_call_id"]
                workflow_call = WorkflowToolCall(
                    **workflow_call_kwargs,
                )
                
                # If confirmation required, decide auto-confirm vs. pause again
                if safety == ToolSafety.CONFIRMATION_REQUIRED:
                    auto_confirm_now = bool(session.get("auto_confirm", False))
                    if auto_confirm_now:
                        passed, reason = self._precheck_guarded_tool(tool_name, arguments)
                        if passed:
                            yield {
                                "type": "auto_confirmed",
                                "tool_name": tool_name,
                                "reason": reason,
                            }
                            yield {"type": "tool_started", "tool_name": tool_name}
                            result = await self.executor.execute(
                                tool_call=workflow_call,
                                copilot_session_id=session_id,
                                confirmed=True,
                                progress_callback=progress_callback,
                            )
                            tool_run = ToolRunRecord(
                                tool_call_id=workflow_call.tool_call_id,
                                tool_name=tool_name,
                                arguments=arguments,
                                safety=safety,
                                status=result.status,
                                started_at=result.started_at,
                                completed_at=result.completed_at,
                                result_summary=result.result_summary,
                                error=result.error,
                            )
                            self.copilot_store.add_tool_run(session, tool_run.model_dump())
                            self.copilot_store.save_session(session)
                            if result.status == ToolRunStatus.COMPLETED:
                                yield {"type": "tool_result", "tool_name": tool_name, "result": result.result_summary}
                            else:
                                yield {"type": "tool_failed", "tool_name": tool_name, "error": result.error}
                            tool_result_content = json.dumps(result.result_summary or {"error": result.error})
                            messages.append({
                                "role": "tool",
                                "content": tool_result_content,
                                "tool_call_id": workflow_call.tool_call_id,
                            })
                            self.copilot_store.add_message(
                                session, "tool", tool_result_content,
                                tool_call_id=workflow_call.tool_call_id,
                            )
                            self.copilot_store.save_session(session)
                            continue
                        yield {
                            "type": "auto_confirm_blocked",
                            "tool_name": tool_name,
                            "reason": reason,
                        }

                    pending_action = PendingToolAction(
                        session_id=session_id,
                        tool_call_id=workflow_call.tool_call_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        arguments_hash=tool_hash,
                        safety=safety,
                    )
                    self.copilot_store.add_pending_action(session, pending_action.model_dump())
                    self.copilot_store.save_session(session)
                    
                    yield {
                        "type": "tool_confirmation_required",
                        "action_id": pending_action.action_id,
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "confirmation_endpoint": "/api/ai/actions/confirm",
                        "confirmation_action_type": "confirm_tool_action",
                        "confirmation_payload": {"action_id": pending_action.action_id},
                    }
                    return  # Pause again for user confirmation
                
                # Execute read-only tools immediately
                yield {"type": "tool_started", "tool_name": tool_name}
                
                result = await self.executor.execute(
                    tool_call=workflow_call,
                    copilot_session_id=session_id,
                    confirmed=False,
                )
                
                # Record tool run
                tool_run = ToolRunRecord(
                    tool_call_id=workflow_call.tool_call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    safety=safety,
                    status=result.status,
                    started_at=result.started_at,
                    completed_at=result.completed_at,
                    result_summary=result.result_summary,
                    error=result.error,
                )
                self.copilot_store.add_tool_run(session, tool_run.model_dump())
                self.copilot_store.save_session(session)
                
                # Yield result
                if result.status == ToolRunStatus.COMPLETED:
                    yield {
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "result": result.result_summary,
                    }
                else:
                    yield {
                        "type": "tool_failed",
                        "tool_name": tool_name,
                        "error": result.error,
                    }
                
                # Add tool result to messages for next model turn.
                # Must follow the assistant message that carried the tool call
                # and carry the matching tool_call_id (protocol invariant).
                tool_result_content = json.dumps(result.result_summary or {"error": result.error})
                messages.append({
                    "role": "tool",
                    "content": tool_result_content,
                    "tool_call_id": workflow_call.tool_call_id,
                })
                self.copilot_store.add_message(
                    session,
                    "tool",
                    tool_result_content,
                    tool_call_id=workflow_call.tool_call_id,
                )
                self.copilot_store.save_session(session)
        
        # Max steps reached
        yield {
            "type": "error",
            "message": f"Reached maximum orchestration steps ({MAX_ORCHESTRATION_STEPS})",
        }

    def _progress_event_from_callback(
        self,
        tool_name: str,
        kind: str,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        if kind == "tool_started":
            return None
        if data.get("type") == "observation_timeout":
            return {
                "type": "observation_timeout",
                "tool_name": tool_name,
                "api_session_id": data.get("api_session_id"),
                "job_type": data.get("job_type"),
                "elapsed_seconds": data.get("elapsed_seconds"),
            }
        status = data.get("status") or data.get("phase")
        event_type = "job_active" if str(status).lower() in {"queued", "running", "pending"} else "tool_progress"
        return {
            "type": event_type,
            "tool_name": tool_name,
            "status": status,
            "progress": data,
        }

    def _terminal_event_for_result(self, result) -> dict[str, Any]:
        status = result.status
        if not isinstance(status, ToolRunStatus):
            status = ToolRunStatus(str(status))

        base = {
            "tool_name": result.tool_name,
            "tool_call_id": result.tool_call_id,
            "status": status.value,
            "result": result.result_summary,
        }
        if status == ToolRunStatus.COMPLETED:
            return {"type": "tool_result", **base}
        if status == ToolRunStatus.FAILED:
            return {"type": "tool_failed", **base, "error": result.error}
        if status == ToolRunStatus.CANCELLED:
            return {"type": "tool_cancelled", **base, "error": result.error}
        if status == ToolRunStatus.TIMED_OUT:
            return {"type": "tool_timed_out", **base, "error": result.error}
        if status == ToolRunStatus.OBSERVATION_PAUSED:
            return {"type": "observation_timeout", **base, "error": result.error}
        if status in {ToolRunStatus.RUNNING, ToolRunStatus.QUEUED}:
            return {"type": "job_active", **base, "error": result.error}
        return {"type": "tool_progress", **base, "error": result.error}

    def _tool_result_content(self, result) -> str:
        payload = result.result_summary or {}
        if result.error:
            payload = {**payload, "error": result.error}
        payload.setdefault("status", result.status.value if isinstance(result.status, ToolRunStatus) else str(result.status))
        return json.dumps(payload)

    async def _execute_workflow_plan(
        self,
        session_id: str,
        workflow_plan: WorkflowPlan,
        session: dict[str, Any],
        mode: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute a deterministic workflow plan from intent router.
        
        Executes workflow steps sequentially, yielding events for each step.
        The model is only used for final explanation, not orchestration.
        """
        intent = workflow_plan["intent"]
        steps = workflow_plan["steps"]
        extracted_slots = workflow_plan["extracted_slots"]
        
        yield {"type": "status", "message": f"Executing {intent} workflow..."}
        
        # Execute each step in the workflow
        for step in steps:
            tool_name = step.get("tool")
            action = step.get("action")
            args = step.get("args", {})
            requires_confirmation = step.get("requires_confirmation", False)
            
            # Handle meta-actions (e.g., ask for missing information)
            if action == "ask_missing":
                slot = args.get("slot")
                prompt = args.get("prompt", f"Please provide {slot}")
                yield {
                    "type": "message",
                    "content": prompt,
                }
                yield {
                    "type": "final",
                    "content": prompt,
                }
                return  # Wait for user response
            
            # Execute tool calls
            if tool_name:
                # Validate tool
                is_valid, error_msg, validated = validate_tool_arguments(tool_name, args)
                if not is_valid:
                    logger.warning(f"Invalid tool call in workflow: {error_msg}")
                    yield {"type": "error", "message": error_msg}
                    continue
                
                # Check safety
                safety = get_tool_safety(tool_name)
                if safety == ToolSafety.FORBIDDEN:
                    yield {"type": "error", "message": f"Tool '{tool_name}' is forbidden"}
                    continue
                
                # Create workflow tool call
                workflow_call = WorkflowToolCall(
                    tool_name=tool_name,
                    arguments=args,
                    safety=safety,
                )
                
                # If confirmation required, pause and yield action card
                if requires_confirmation:
                    pending_action = PendingToolAction(
                        session_id=session_id,
                        tool_call_id=workflow_call.tool_call_id,
                        tool_name=tool_name,
                        arguments=args,
                        arguments_hash=calculate_arguments_hash(tool_name, args),
                        safety=safety,
                    )
                    self.copilot_store.add_pending_action(session, pending_action.model_dump())
                    self.copilot_store.save_session(session)
                    
                    yield {
                        "type": "tool_confirmation_required",
                        "action_id": pending_action.action_id,
                        "tool_name": tool_name,
                        "arguments": args,
                        "confirmation_endpoint": "/api/ai/actions/confirm",
                        "confirmation_action_type": "confirm_tool_action",
                        "confirmation_payload": {"action_id": pending_action.action_id},
                    }
                    return  # Pause for user confirmation
                
                # Execute read-only tools immediately
                yield {"type": "tool_started", "tool_name": tool_name}
                
                result = await self.executor.execute(
                    tool_call=workflow_call,
                    copilot_session_id=session_id,
                    confirmed=False,
                )
                
                # Record tool run
                tool_run = ToolRunRecord(
                    tool_call_id=workflow_call.tool_call_id,
                    tool_name=tool_name,
                    arguments=args,
                    safety=safety,
                    status=result.status,
                    started_at=result.started_at,
                    completed_at=result.completed_at,
                    result_summary=result.result_summary,
                    error=result.error,
                )
                self.copilot_store.add_tool_run(session, tool_run.model_dump())
                self.copilot_store.save_session(session)
                
                # Yield result
                if result.status == ToolRunStatus.COMPLETED:
                    yield {
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "result": result.result_summary,
                    }
                else:
                    yield {
                        "type": "tool_failed",
                        "tool_name": tool_name,
                        "error": result.error,
                    }
                    continue  # Stop workflow on tool failure
        
        # Workflow completed successfully - use model for final explanation
        yield {"type": "status", "message": "Workflow completed. Generating explanation..."}
        
        # Build context for model explanation
        context = self._build_context(session, mode)
        messages = self._build_messages(session, context, mode)
        
        # Add system prompt for explanation
        explanation_prompt = (
            f"The {intent} workflow has been executed successfully. "
            f"Review the tool results above and provide a clear, concise explanation "
            f"of what was done and the key findings. Base your answer only on the "
            f"actual tool results - do not hallucinate or make claims without evidence."
        )
        messages.append({"role": "system", "content": explanation_prompt})
        
        # Call model for explanation
        try:
            resolved_model = session.get("model") or "llama3"
            response = await self.ollama_client.chat(
                messages=messages,
                tools=[],  # No tools needed for explanation
                model=resolved_model,
            )
            
            content = getattr(response, "content", "")
            
            # Add assistant message to session
            self.copilot_store.add_message(session, "assistant", content)
            self.copilot_store.save_session(session)
            
            yield {"type": "message", "content": content}
            yield {"type": "final", "content": content}
            
        except Exception as exc:
            logger.error(f"Model explanation failed: {exc}")
            yield {
                "type": "message",
                "content": f"Workflow completed. {exc}",
            }
            yield {
                "type": "final",
                "content": f"Workflow completed. {exc}",
            }

    def _build_context(self, session: dict[str, Any], mode: str) -> dict[str, Any]:
        """Build bounded context from app state using real AgentContextService contract."""
        # Use existing AgentContextService for bounded context
        context = self.context_service.build_context(
            overrides=session.get("last_context_overrides", {}),
        )
        
        # Add tool run history
        tool_runs = session.get("tool_runs", [])
        if tool_runs:
            context["recent_tool_runs"] = [
                {
                    "tool_name": tr["tool_name"],
                    "status": tr["status"],
                    "result_summary": tr.get("result_summary"),
                }
                for tr in tool_runs[-5:]  # Last 5 runs
            ]
        
        # Add active jobs
        active_jobs = session.get("active_jobs", [])
        if active_jobs:
            context["active_jobs"] = active_jobs
        
        return context

    def _build_messages(
        self,
        session: dict[str, Any],
        context: dict[str, Any],
        mode: str,
    ) -> list[dict[str, Any]]:
        """Build prompt messages from session and context."""
        messages = []
        
        # System prompt based on mode
        system_prompt = self._get_system_prompt(mode, context)
        messages.append({"role": "system", "content": system_prompt})
        
        # Add context as a system message
        context_msg = f"Current application context:\n{json.dumps(context, indent=2)}"
        messages.append({"role": "system", "content": context_msg})
        
        # Add conversation history, preserving tool_calls and tool_call_id.
        # The model/tool message protocol requires:
        #  - assistant messages that requested tools keep their tool_calls
        #  - tool messages keep the matching tool_call_id so the model can
        #    associate each result with the call that produced it.
        for msg in session.get("messages", []):
            message_dict = {
                "role": msg["role"],
                "content": msg["content"],
            }
            # Preserve tool_calls if present (for assistant messages with tool calls)
            if "tool_calls" in msg and msg["tool_calls"]:
                message_dict["tool_calls"] = msg["tool_calls"]
            # Preserve tool_call_id for tool-result messages
            if msg.get("role") == "tool" and msg.get("tool_call_id"):
                message_dict["tool_call_id"] = msg["tool_call_id"]
            messages.append(message_dict)

        return messages

    def _get_system_prompt(self, mode: str, context: dict[str, Any]) -> str:
        """Get system prompt based on mode."""
        base_prompt = (
            "You are an AI copilot for a Freqtrade trading strategy development application. "
            "You help users analyze strategies, run backtests, optimize parameters, and "
            "improve their trading strategies. Always base your responses on real backend "
            "evidence from tool results. Do not make claims without evidence.\n\n"
            "PAIR DISCOVERY POLICY\n"
            "When the user mentions a strategy by any name and asks for pair discovery or profitable pairs:\n"
            "1. Call read_strategy_file to read the strategy BEFORE asking any clarifying questions.\n"
            "2. Determine the timeframe directly from the strategy file.\n"
            "3. If a timerange is missing, ask ONLY for that one thing.\n"
            "4. Do NOT ask the user for configuration details — the backend automatically uses settings.default_config_file_path.\n"
            "5. Call get_pair_universe to get real available candidates before running pair explorer.\n"
            "6. Propose run_pair_explorer using the SAME strategy parameters.\n"
            "7. Answer ONLY from measured results. Never hardcode profitability claims or hallucinate best pairs."
        )
        
        if mode == "autoquant":
            base_prompt += (
                "\n\nYou are in AutoQuant mode. Guide the user through the full "
                "validation pipeline: Pair Explorer, Backtest, Optimizer, Stress Lab, "
                "and Temporal Stress Test. Ensure each step completes successfully "
                "before proceeding to the next."
            )
        
        return base_prompt

    def _extract_tool_calls(self, response: Any) -> list[dict[str, Any]]:
        """Extract tool calls from Ollama response."""
        tool_calls = []
        
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tool_call in response.tool_calls:
                if isinstance(tool_call, dict):
                    call_id = tool_call.get("tool_call_id") or tool_call.get("id")
                    function = tool_call.get("function") or {}
                    name = tool_call.get("name") or function.get("name")
                    arguments = tool_call.get("arguments")
                    if arguments is None:
                        arguments = function.get("arguments") or {}
                else:
                    call_id = getattr(tool_call, "tool_call_id", None) or getattr(tool_call, "id", None)
                    function = getattr(tool_call, "function", None)
                    name = getattr(function, "name", None)
                    arguments = getattr(function, "arguments", {}) or {}

                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                
                if name:
                    item = {"name": name, "arguments": arguments}
                    if call_id:
                        item["tool_call_id"] = str(call_id)
                    tool_calls.append(item)
        
        return tool_calls
