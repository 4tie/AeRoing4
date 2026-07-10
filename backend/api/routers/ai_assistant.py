"""Router: /api/ai

Local-LLM powered assistant using Ollama.

GET  /api/ai/models            — fetches available models from the configured
                                  Ollama instance ({ollama_api_url}/api/tags).
POST /api/ai/explain-strategy  — reads a strategy .py file and returns a
                                  plain-language explanation via the configured
                                  Ollama model.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...core.errors import BackendError
from ...services.agent_context import AgentContextService
from ...services.ai.ollama_client import OllamaClient, build_headers
from ...services.ai.ollama_config import config_from_settings
from ...services.ai.copilot_session_store import CopilotSessionStore
from ...services.ai.workflow_copilot import WorkflowCopilot
from ...services.ai.workflow_tool_executor import WorkflowToolExecutor
from ...services.assistant_service import AssistantService
from . import candidate

router = APIRouter(prefix="/api/ai", tags=["AI Assistant"])

DEFAULT_TIMEOUT_GENERATE = 120.0
DEFAULT_TIMEOUT_TAGS = 30.0


def _build_headers(base_url: str, *, include_content_type: bool = False, api_key: str | None = None) -> dict[str, str]:
    """Return the standard HTTP headers for Ollama requests.

    * ``Host``         — derived from the configured URL so reverse-proxies and
                         Cloudflare / Tailscale tunnels receive the correct header.
    * ``Accept``       — always ``application/json``.
    * ``Content-Type`` — ``application/json`` for POST bodies (optional for GETs).
    * ``Authorization`` — Bearer token when accessing Ollama Cloud API.
    """
    return build_headers(base_url, include_content_type=include_content_type, api_key=api_key)

SYSTEM_PROMPT = (
    "You are a friendly trading mentor. "
    "Read the following Freqtrade Python strategy code. "
    "Explain its core logic — buy conditions, sell conditions, and indicators used — "
    "in simple, non-technical language. "
    "Use real-world analogies like buying/selling a car or real estate to explain "
    "the concepts where helpful. "
    "Structure your answer with clear sections: Indicators Used, Buy Logic, Sell Logic, "
    "and a short Overall Summary. "
    "Keep it concise and friendly."
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _read_strategy_source(strategies_dir: str, strategy_name: str) -> str:
    path = Path(strategies_dir) / f"{strategy_name}.py"
    if not path.exists():
        raise FileNotFoundError(
            f"Strategy file '{strategy_name}.py' not found in {strategies_dir}"
        )
    return path.read_text(encoding="utf-8", errors="replace")


def _ollama_error(exc: Exception) -> HTTPException:
    """Convert common httpx errors into friendly 503/502/500 responses."""
    if isinstance(exc, httpx.ConnectError):
        return HTTPException(
            status_code=503,
            detail=(
                "Could not connect to Ollama. "
                "Check the Ollama API URL in Settings and ensure Ollama is running."
            ),
        )
    if isinstance(exc, httpx.TimeoutException):
        return HTTPException(
            status_code=503,
            detail=(
                "Ollama took too long to respond. "
                "Try a smaller/faster model or check that Ollama is not overloaded."
            ),
        )
    if isinstance(exc, httpx.HTTPStatusError):
        detail = f"Ollama returned HTTP {exc.response.status_code}."
        try:
            detail = exc.response.json().get("error", detail)
        except Exception:
            pass
        return HTTPException(status_code=502, detail=detail)
    return HTTPException(status_code=500, detail=f"Unexpected Ollama error: {exc}")


# ── models endpoint ───────────────────────────────────────────────────────────

@router.get(
    "/health",
    summary="Check Ollama service health",
    description=(
        "Pings the configured Ollama instance to check if it's reachable. "
        "Returns health status, latency, and error information if applicable."
    ),
)
async def health_check(request: Request) -> dict:
    services = request.app.state.services
    cfg = services.settings_store.load()
    timeout = float(cfg.ollama_timeout if cfg.ollama_timeout else DEFAULT_TIMEOUT_TAGS)
    config = config_from_settings(cfg, health_timeout=timeout, require_model=False)
    if config is None:
        return {
            "status": "unhealthy",
            "reachable": False,
            "latency_ms": 0,
            "error": "Ollama API URL not configured",
            "ollama_api_url": "",
            "provider": cfg.ollama_provider,
        }
    client = OllamaClient(config=config)
    try:
        result = await client.health()
        result["provider"] = cfg.ollama_provider
        return result
    finally:
        await client.close()


@router.get(
    "/models",
    summary="List available Ollama models",
    description=(
        "Calls {ollama_api_url}/api/tags on the configured Ollama instance and "
        "returns a sorted list of model names. Returns 503 if unreachable."
    ),
)
async def list_models(request: Request) -> dict:
    services = request.app.state.services
    cfg = services.settings_store.load()
    timeout = float(cfg.ollama_timeout if cfg.ollama_timeout else DEFAULT_TIMEOUT_TAGS)
    config = config_from_settings(cfg, health_timeout=timeout, require_model=False)
    if config is None:
        return {
            "models": [],
            "reachable": False,
            "ollama_api_url": "",
            "error": "Ollama API URL not configured",
        }
    client = OllamaClient(config=config)
    try:
        return await client.list_models()
    finally:
        await client.close()


@router.get(
    "/metrics",
    summary="Get Ollama reliability metrics",
    description=(
        "Returns current reliability metrics including circuit breaker state, "
        "success rate, average latency, and request counts."
    ),
)
async def get_metrics(request: Request) -> dict:
    services = request.app.state.services
    cfg = services.settings_store.load()
    config = config_from_settings(cfg, require_model=False)
    if config is None:
        return {
            "error": "Ollama API URL not configured",
            "metrics": None,
        }
    client = OllamaClient(config=config)
    try:
        metrics = client.get_metrics()
        return {
            "metrics": metrics,
            "settings": {
                "retry_delays": cfg.ollama_retry_delays,
                "circuit_breaker_threshold": cfg.ollama_circuit_breaker_threshold,
                "circuit_breaker_cooldown": cfg.ollama_circuit_breaker_cooldown,
                "connection_pool_size": cfg.ollama_connection_pool_size,
                "connection_keepalive": cfg.ollama_connection_keepalive,
            },
        }
    finally:
        await client.close()


@router.get(
    "/health-monitor",
    summary="Get Ollama health monitor state",
    description=(
        "Returns the current health monitor state including health status, "
        "last check time, and consecutive failures/successes."
    ),
)
async def get_health_monitor_state(request: Request) -> dict:
    from ...services.ai.ollama_health_monitor import get_health_monitor

    services = request.app.state.services
    cfg = services.settings_store.load()
    try:
        monitor = await get_health_monitor(
            cfg.user_data_directory_path,
            check_interval=cfg.ollama_health_check_interval if cfg.ollama_enable_health_check else 0,
            enabled=cfg.ollama_enable_health_check,
        )
        return monitor.get_health_state()
    except Exception as exc:
        return {
            "error": str(exc),
            "healthy": None,
            "monitor_enabled": cfg.ollama_enable_health_check,
        }


@router.post(
    "/health-monitor/reset",
    summary="Reset Ollama health monitor failure count",
    description=(
        "Resets the consecutive failure count in the health monitor to allow recovery "
        "after configuration changes or Ollama restarts."
    ),
)
async def reset_health_monitor(request: Request) -> dict:
    from ...services.ai.ollama_health_monitor import get_health_monitor

    services = request.app.state.services
    cfg = services.settings_store.load()
    try:
        monitor = await get_health_monitor(
            cfg.user_data_directory_path,
            check_interval=cfg.ollama_health_check_interval if cfg.ollama_enable_health_check else 0,
            enabled=cfg.ollama_enable_health_check,
        )
        monitor.reset_failure_count()
        return {"status": "reset", "message": "Health monitor failure count reset"}
    except Exception as exc:
        return {
            "error": str(exc),
            "status": "failed",
        }


@router.post(
    "/health-monitor/check",
    summary="Force immediate health check",
    description=(
        "Forces an immediate health check and returns the updated state."
    ),
)
async def force_health_check(request: Request) -> dict:
    from ...services.ai.ollama_health_monitor import get_health_monitor

    services = request.app.state.services
    cfg = services.settings_store.load()
    try:
        monitor = await get_health_monitor(
            cfg.user_data_directory_path,
            check_interval=cfg.ollama_health_check_interval if cfg.ollama_enable_health_check else 0,
            enabled=cfg.ollama_enable_health_check,
        )
        return await monitor.force_check()
    except Exception as exc:
        return {
            "error": str(exc),
            "healthy": None,
            "monitor_enabled": cfg.ollama_enable_health_check,
        }


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message for the assistant.")
    session_id: str | None = Field(default=None, description="Existing assistant chat session id.")
    model: str | None = Field(default=None, description="Optional Ollama model override.")
    mode: str = Field(
        default="auto",
        description="Assistant mode: auto, chat, analysis, autoquant, strategylab, optimizer.",
    )
    context_overrides: dict | None = Field(
        default=None,
        description="Optional active context ids: strategy_name, optimizer_session_id, backtest_run_id, etc.",
    )
    include_strategy_source: bool = Field(
        default=False,
        description="Attach allowlisted strategy .py/.json content to the prompt.",
    )
    auto_confirm: bool = Field(
        default=False,
        description=(
            "When true, guarded tools (backtest/optimizer/pair-explorer) that pass a "
            "cheap local pre-check (strategy exists, timerange sane, pairs valid) are "
            "auto-executed without waiting for the confirmation click. If the pre-check "
            "fails, the tool still pauses for manual confirmation. No real-money path."
        ),
    )


class ConfirmActionRequest(BaseModel):
    action_type: str
    payload: dict = Field(default_factory=dict)
    session_id: str | None = None
    user_message: str | None = None
    confirmation_token: str | None = None


class CopilotChatRequest(BaseModel):
    message: str = Field(..., description="User message for the copilot.")
    session_id: str | None = Field(default=None, description="Existing copilot session id.")
    model: str | None = Field(default=None, description="Optional Ollama model override.")
    mode: str = Field(default="analysis", description="Copilot mode: analysis, autoquant, strategylab.")
    context_overrides: dict | None = Field(
        default=None,
        description="Optional active context ids: strategy_name, optimizer_session_id, etc.",
    )


class ConfirmToolActionRequest(BaseModel):
    action_id: str = Field(..., description="Action ID to confirm.")
    session_id: str = Field(..., description="Copilot session ID.")


def _copilot_mode(mode: str) -> str:
    if mode in {"autoquant", "strategylab", "optimizer"}:
        return mode
    return "analysis"


def _assistant_message_record(content: str) -> dict[str, str]:
    return {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "content": content,
        "created_at": datetime.now(tz=UTC).isoformat(),
    }


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


def _persist_copilot_context_summary(
    copilot: WorkflowCopilot,
    session_id: str,
    summary: dict,
    context_overrides: dict,
) -> None:
    try:
        session = copilot.copilot_store.load_session(session_id)
    except Exception:
        return
    session["last_context_summary"] = summary
    session["last_context_overrides"] = context_overrides
    copilot.copilot_store.save_session(session)


COPILOT_CONFIRM_ACTION_TYPES = {
    "confirm_tool_action",
    "confirm_copilot_tool_action",
    "confirm_workflow_tool_action",
}


def _is_copilot_confirmation(body: ConfirmActionRequest) -> bool:
    return body.action_type in COPILOT_CONFIRM_ACTION_TYPES


def _copilot_confirmation_ids(body: ConfirmActionRequest) -> tuple[str, str]:
    session_id = body.session_id or body.payload.get("session_id")
    action_id = body.payload.get("action_id")
    if not session_id:
        raise BackendError("session_id is required for copilot tool confirmation.", status_code=422)
    if not action_id:
        raise BackendError("payload.action_id is required for copilot tool confirmation.", status_code=422)
    return str(session_id), str(action_id)


def _copilot_confirmation_stream(
    body: ConfirmActionRequest,
    request: Request,
) -> StreamingResponse:
    session_id, action_id = _copilot_confirmation_ids(body)
    copilot = _workflow_copilot(request)

    async def event_stream():
        try:
            async for event in copilot.resume_after_confirmation(
                session_id=session_id,
                action_id=action_id,
                stream=True,
            ):
                yield _sse(str(event.get("type") or "copilot_event"), event)
        except Exception as exc:
            yield _sse("error", {"type": "error", "message": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── chat assistant endpoints ──────────────────────────────────────────────────

@router.post(
    "/chat",
    summary="Chat with the guarded Strategy Lab AI assistant",
    description=(
        "Builds a bounded backend-owned context snapshot, sends it to Ollama via "
        "/api/chat, saves chat history, and returns proposed read-only/guarded actions."
    ),
)
async def chat(body: ChatRequest, request: Request) -> dict:
    try:
        if not body.message.strip():
            raise BackendError("Message is required.", status_code=422)

        service = _assistant_service(request)
        settings = request.app.state.services.settings_store.load()
        resolved_mode = service._resolve_mode(body.mode, body.message)
        _, resolved_model = service._resolve_model_pair(settings, body.model, resolved_mode)
        copilot_mode = _copilot_mode(resolved_mode)
        context = service._build_context(
            body.context_overrides or {},
            include_strategy_source=body.include_strategy_source,
        )
        summary = service.context_summary(context)
        actions = service.available_actions(context)
        copilot = _workflow_copilot(request, model_override=resolved_model)
        session_id = body.session_id or str(uuid.uuid4())

        events: list[dict] = []
        message_parts: list[str] = []
        final_content: str | None = None
        async for event in copilot.process_turn(
            session_id=session_id,
            user_message=body.message,
            model=resolved_model,
            mode=copilot_mode,
            stream=False,
            context_overrides=body.context_overrides or {},
            auto_confirm=body.auto_confirm,
        ):
            events.append(event)
            if event.get("type") == "message":
                message_parts.append(str(event.get("content", "")))
            elif event.get("type") == "final":
                final_content = str(event.get("content", ""))

        final_event = events[-1] if events else {"type": "error", "message": "No events generated"}
        if final_event.get("type") == "error" and not (final_content or message_parts):
            raise BackendError(str(final_event.get("message") or "AI chat failed."), status_code=503)

        content = final_content if final_content is not None else "".join(message_parts)
        if not content:
            content = "No response generated."
        _persist_copilot_context_summary(copilot, session_id, summary, body.context_overrides or {})
        return {
            "session_id": session_id,
            "model": resolved_model,
            "message": _assistant_message_record(content),
            "context_summary": summary,
            "available_actions": actions,
            "workflow_events": events,
        }
    except BackendError as exc:
        _raise_backend(exc)


@router.post(
    "/chat/stream",
    summary="Stream a Strategy Lab AI assistant response",
)
async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
    try:
        if not body.message.strip():
            raise BackendError("Message is required.", status_code=422)
        service = _assistant_service(request)
        settings = request.app.state.services.settings_store.load()
        resolved_mode = service._resolve_mode(body.mode, body.message)
        _, resolved_model = service._resolve_model_pair(settings, body.model, resolved_mode)
        copilot_mode = _copilot_mode(resolved_mode)
        context = service._build_context(
            body.context_overrides or {},
            include_strategy_source=body.include_strategy_source,
        )
        summary = service.context_summary(context)
        actions = service.available_actions(context)
        copilot = _workflow_copilot(request, model_override=resolved_model)
        session_id = body.session_id or str(uuid.uuid4())
    except BackendError as exc:
        _raise_backend(exc)

    async def stream():
        yield _sse("meta", {
            "session_id": session_id,
            "model": resolved_model,
            "mode": copilot_mode,
            "context_summary": summary,
            "available_actions": actions,
        })
        message_parts: list[str] = []
        final_content: str | None = None
        async for event in copilot.process_turn(
            session_id=session_id,
            user_message=body.message,
            model=resolved_model,
            mode=copilot_mode,
            stream=True,
            context_overrides=body.context_overrides or {},
            auto_confirm=body.auto_confirm,
        ):
            event_type = event.get("type")
            if event_type == "message":
                content = str(event.get("content", ""))
                message_parts.append(content)
                yield _sse("token", {"content": content})
            elif event_type == "final":
                final_content = str(event.get("content", ""))
            elif event_type == "error":
                yield _sse("error", {"detail": event.get("message")})
                return
            else:
                yield _sse(str(event_type or "copilot_event"), event)

        content = final_content if final_content is not None else "".join(message_parts)
        if not content:
            content = "No response generated."
        _persist_copilot_context_summary(copilot, session_id, summary, body.context_overrides or {})
        yield _sse("done", {
            "session_id": session_id,
            "message": _assistant_message_record(content),
            "context_summary": summary,
            "available_actions": actions,
        })

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get(
    "/chat/{session_id}",
    summary="Load a persisted assistant chat session",
)
async def get_chat_session(session_id: str, request: Request) -> dict:
    try:
        return _assistant_service(request).load_session(session_id)
    except BackendError as exc:
        _raise_backend(exc)


@router.post(
    "/actions/confirm",
    summary="Confirm a guarded assistant action",
    description=(
        "Executes only allowlisted assistant actions. Guarded actions require "
        "confirmation_token='CONFIRM'. Destructive actions are rejected in MVP."
    ),
    response_model=None,
)
async def confirm_action(body: ConfirmActionRequest, request: Request):
    try:
        if _is_copilot_confirmation(body):
            return _copilot_confirmation_stream(body, request)
        return _assistant_service(request).confirm_action(
            action_type=body.action_type,
            payload=body.payload,
            session_id=body.session_id,
            user_message=body.user_message,
            confirmation_token=body.confirmation_token,
        )
    except BackendError as exc:
        _raise_backend(exc)


# ── workflow copilot endpoints ───────────────────────────────────────────────────


def _workflow_copilot(request: Request, model_override: str | None = None) -> WorkflowCopilot:
    """Build WorkflowCopilot instance for request."""
    services = request.app.state.services
    settings = services.settings_store.load()
    
    # Build dependencies
    copilot_store = CopilotSessionStore(settings.user_data_directory_path)
    session_store = request.app.state.session_store
    context_service = AgentContextService(
        root_dir=services.root_dir,
        run_repository=services.run_repository,
        settings_store=services.settings_store,
        version_manager=services.version_manager,
        strategy_optimizer=getattr(services, "strategy_optimizer", None),
        backtest_runner=services.backtest_runner,
        optimizer_store=getattr(services, "optimizer_store", None),
        sweep_store=getattr(services, "sweep_store", None),
        run_detail_callable=services.run_detail,
        log_broadcaster=getattr(request.app.state, "log_broadcaster", None),
        session_store=session_store,
        candidate_run_lookup=candidate.candidate_run_manager.get_run,
    )
    
    executor = WorkflowToolExecutor(
        services=services,
        session_store=session_store,
        copilot_store=copilot_store,
        root_dir=services.root_dir,
    )
    
    ollama_config = config_from_settings(settings, model_override=model_override)
    if ollama_config is None:
        raise BackendError(
            "No AI model configured. Go to Settings -> AI Assistant, refresh models, select one, and save.",
            status_code=422,
        )
    ollama_client = OllamaClient(config=ollama_config)
    
    return WorkflowCopilot(
        services=services,
        session_store=session_store,
        copilot_store=copilot_store,
        executor=executor,
        context_service=context_service,
        ollama_client=ollama_client,
        root_dir=services.root_dir,
    )


@router.post(
    "/copilot/chat",
    summary="Chat with the unified workflow copilot",
    description=(
        "Processes user requests through the model-tool-result loop. "
        "Supports tool execution, confirmation, and long-running job observation."
    ),
)
async def copilot_chat(body: CopilotChatRequest, request: Request) -> dict:
    """Non-streaming copilot chat endpoint."""
    copilot = _workflow_copilot(request, model_override=body.model)
    session_id = body.session_id or str(uuid.uuid4())
    
    # Collect all events from the async generator
    events = []
    async for event in copilot.process_turn(
        session_id=session_id,
        user_message=body.message,
        model=body.model,
        mode=body.mode,
        stream=False,
    ):
        events.append(event)
    
    # Return final state
    final_event = events[-1] if events else {"type": "error", "message": "No events generated"}
    
    return {
        "session_id": session_id,
        "events": events,
        "final": final_event,
    }


@router.post(
    "/copilot/chat/stream",
    summary="Stream workflow copilot response",
    description=(
        "Streams copilot events including messages, tool calls, and results "
        "via Server-Sent Events."
    ),
)
async def copilot_chat_stream(body: CopilotChatRequest, request: Request) -> StreamingResponse:
    """Streaming copilot chat endpoint."""
    copilot = _workflow_copilot(request, model_override=body.model)
    session_id = body.session_id or str(uuid.uuid4())
    
    async def event_stream():
        async for event in copilot.process_turn(
            session_id=session_id,
            user_message=body.message,
            model=body.model,
            mode=body.mode,
            stream=True,
        ):
            yield f"data: {json.dumps(event)}\n\n"
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post(
    "/copilot/actions/confirm",
    summary="Confirm a pending tool action",
    description=(
        "Confirms and executes a pending tool action that requires user confirmation, "
        "observes job completion, and resumes model reasoning with the tool result."
    ),
)
async def copilot_confirm_action(body: ConfirmToolActionRequest, request: Request) -> StreamingResponse:
    """Confirm and execute a pending tool action, then resume orchestration."""
    return _copilot_confirmation_stream(
        ConfirmActionRequest(
            action_type="confirm_tool_action",
            session_id=body.session_id,
            payload={"action_id": body.action_id},
        ),
        request,
    )


@router.get(
    "/copilot/sessions",
    summary="List copilot sessions",
    description="Returns all copilot sessions with metadata.",
)
async def list_copilot_sessions(request: Request) -> dict:
    """List all copilot sessions."""
    services = request.app.state.services
    settings = services.settings_store.load()
    copilot_store = CopilotSessionStore(settings.user_data_directory_path)
    
    sessions = copilot_store.list_sessions()
    return {"sessions": sessions}


@router.get(
    "/copilot/sessions/{session_id}",
    summary="Get copilot session",
    description="Returns full copilot session data including messages and tool runs.",
)
async def get_copilot_session(session_id: str, request: Request) -> dict:
    """Get a copilot session by ID."""
    services = request.app.state.services
    settings = services.settings_store.load()
    copilot_store = CopilotSessionStore(settings.user_data_directory_path)
    
    try:
        session = copilot_store.load_session(session_id)
        return session
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── explain endpoint ──────────────────────────────────────────────────────────

class ExplainRequest(BaseModel):
    strategy_name: str = Field(..., description="Strategy filename without .py")
    model: str | None = Field(
        default=None,
        description="Ollama model to use; falls back to ollama_model from settings.",
    )


def _assistant_service(request: Request) -> AssistantService:
    services = request.app.state.services
    context_service = AgentContextService(
        root_dir=services.root_dir,
        run_repository=services.run_repository,
        settings_store=services.settings_store,
        version_manager=services.version_manager,
        strategy_optimizer=getattr(services, "strategy_optimizer", None),
        backtest_runner=services.backtest_runner,
        optimizer_store=getattr(services, "optimizer_store", None),
        sweep_store=getattr(services, "sweep_store", None),
        run_detail_callable=services.run_detail,
        log_broadcaster=getattr(request.app.state, "log_broadcaster", None),
        session_store=getattr(request.app.state, "session_store", None),
        candidate_run_lookup=candidate.candidate_run_manager.get_run,
    )
    return AssistantService(
        settings_store=services.settings_store,
        context_service=context_service,
        optimizer_store=getattr(services, "optimizer_store", None),
        version_manager=services.version_manager,
        exported_trial_store=getattr(services, "exported_trial_store", None),
        root_dir=services.root_dir,
    )


def _raise_backend(exc: BackendError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post(
    "/explain-strategy",
    summary="Explain a strategy's logic using the configured local Ollama LLM",
    description=(
        "Reads the strategy .py file, sends it to the Ollama instance at the "
        "configured ollama_api_url, and returns a plain-language explanation. "
        "The model is taken from settings unless overridden in the request body."
    ),
)
async def explain_strategy(body: ExplainRequest, request: Request) -> dict:
    services = request.app.state.services
    settings = services.settings_store.load()
    strategies_dir = settings.strategies_directory_path

    try:
        strategy_source = _read_strategy_source(strategies_dir, body.strategy_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    ollama_model = body.model or settings.ollama_model
    timeout = float(settings.ollama_timeout if settings.ollama_timeout else DEFAULT_TIMEOUT_GENERATE)

    if not settings.ollama_api_url:
        raise HTTPException(
            status_code=400,
            detail="Ollama API URL not configured in Settings",
        )
    if not ollama_model:
        raise HTTPException(
            status_code=422,
            detail="Ollama model not configured in Settings",
        )

    config = config_from_settings(settings, model_override=ollama_model, timeout=timeout, require_model=True)
    client = OllamaClient(config=config)
    try:
        explanation = await client.generate(
            f"Strategy code:\n{strategy_source}",
            system_prompt=SYSTEM_PROMPT,
            model=ollama_model,
            feature="explain_strategy",
        )
    finally:
        await client.close()

    if explanation is None:
        raise HTTPException(status_code=502, detail="Ollama returned an empty or invalid response.")

    return {
        "strategy_name": body.strategy_name,
        "model": ollama_model,
        "explanation": explanation,
    }


# ── AutoQuant AI Agent endpoint ───────────────────────────────────────────────────

class AutoQuantRequest(BaseModel):
    message: str = Field(..., description="User message to the AutoQuant AI agent")
    session_id: str | None = Field(None, description="Session ID for tracking")
    model: str | None = Field(None, description="Ollama model to use (optional)")
    context_overrides: dict | None = Field(default_factory=dict, description="Optional assistant context overrides")


class ChartGenerationRequest(BaseModel):
    chart_type: str = Field(..., description="Chart type: bar, pie, line")
    data: list[dict] = Field(..., description="Chart data as list of dicts")
    title: str = Field(default="", description="Chart title")
    xlabel: str = Field(default="", description="X-axis label (for bar/line)")
    ylabel: str = Field(default="", description="Y-axis label (for bar/line)")
    width: int = Field(default=800, description="Image width in pixels")
    height: int = Field(default=400, description="Image height in pixels")


@router.post(
    "/autoquant",
    summary="Chat with AutoQuant AI agent",
    description="Send a message to the AutoQuant AI agent which will use Ollama to execute the full 8-step AutoQuant workflow with tool calling capabilities. Now delegates to the unified WorkflowCopilot.",
)
async def autoquant_chat(body: AutoQuantRequest, request: Request) -> dict:
    """Chat with AutoQuant AI agent - delegates to unified WorkflowCopilot.
    
    This is a compatibility adapter that forwards requests to the new
    WorkflowCopilot in autoquant mode while maintaining the legacy response format.
    """
    copilot = _workflow_copilot(request, model_override=body.model)
    
    # Use existing session or create new one
    session_id = body.session_id or str(uuid.uuid4())
    
    try:
        # Process turn through copilot (non-streaming for compatibility)
        events = []
        tool_calls = []
        final_response = ""
        
        async for event in copilot.process_turn(
            session_id=session_id,
            user_message=body.message,
            model=body.model,
            mode="autoquant",
            stream=False,
            context_overrides=body.context_overrides or {},
        ):
            events.append(event)
            
            if event["type"] == "message":
                final_response += event.get("content", "")
            elif event["type"] == "tool_confirmation_required":
                # For compatibility, extract tool calls from confirmation event
                tool_calls.append({
                    "name": event["tool_name"],
                    "arguments": event["arguments"],
                    "action_id": event["action_id"],
                })
            elif event["type"] == "tool_result":
                # Add tool result to response for compatibility
                final_response += f"\n\nTool '{event['tool_name']}' completed."
        
        return {
            "response": final_response or "No response generated.",
            "session_id": session_id,
            "tool_calls": tool_calls,
            "model": body.model or request.app.state.services.settings_store.load().ollama_model,
        }
        
    except RuntimeError as e:
        # If copilot cannot be created
        return {
            "response": f"Ollama is not configured or unavailable: {str(e)}",
            "session_id": session_id,
            "tool_calls": [],
            "error": "Ollama not configured"
        }
    except Exception as e:
        # If copilot fails, return a simple response
        return {
            "response": f"AutoQuant AI agent chat failed: {str(e)}. Please ensure Ollama is configured and running.",
            "session_id": session_id,
            "tool_calls": [],
            "error": str(e)
        }


@router.post(
    "/generate-chart",
    summary="Generate chart image for AI analysis",
    description="Generate a chart image (bar, pie, or line) from provided data and return base64-encoded PNG.",
)
async def generate_chart(body: ChartGenerationRequest) -> dict:
    """Generate a chart image using matplotlib."""
    from ...services.chart_generator import get_chart_generator

    chart_gen = get_chart_generator()

    try:
        if body.chart_type == "bar":
            img_base64 = chart_gen.generate_bar_chart(
                data=body.data,
                title=body.title,
                xlabel=body.xlabel,
                ylabel=body.ylabel,
                width=body.width,
                height=body.height,
            )
        elif body.chart_type == "pie":
            img_base64 = chart_gen.generate_pie_chart(
                data=body.data,
                title=body.title,
                width=body.width,
                height=body.height,
            )
        elif body.chart_type == "line":
            img_base64 = chart_gen.generate_line_chart(
                data=body.data,
                title=body.title,
                xlabel=body.xlabel,
                ylabel=body.ylabel,
                width=body.width,
                height=body.height,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported chart type: {body.chart_type}. Supported types: bar, pie, line"
            )

        return {
            "image": f"data:image/png;base64,{img_base64}",
            "chart_type": body.chart_type,
            "width": body.width,
            "height": body.height,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chart generation failed: {str(exc)}")
