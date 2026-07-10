"""Chat endpoint for AI agent router.

Legacy AI Agent chat endpoint - now delegates to unified WorkflowCopilot.
This is a compatibility adapter that maintains the legacy response format
while using the new unified copilot for actual tool execution.
"""

import uuid

from fastapi import APIRouter, Request

from .schemas import ChatRequest, ChatResponse


def register_chat_endpoint(router: APIRouter) -> None:
    """Register chat endpoint on the given router."""
    
    @router.post(
        "/chat",
        summary="Chat with AI agent using Ollama",
        description="Send a message to the AI agent which will use Ollama to process it and optionally call tools.",
    )
    async def chat_with_ai_agent(body: ChatRequest, request: Request) -> ChatResponse:
        """Chat with AI agent - delegates to unified WorkflowCopilot.
        
        This is a compatibility adapter that forwards requests to the new
        WorkflowCopilot while maintaining the legacy response format.
        """
        from ...services.ai.copilot_session_store import CopilotSessionStore
        from ...services.ai.workflow_copilot import WorkflowCopilot
        from ...services.ai.workflow_tool_executor import WorkflowToolExecutor
        from ...services.ai.ollama_config import config_from_settings
        from ...services.ai.ollama_client import OllamaClient
        from ...services.agent_context import AgentContextService
        from . import candidate
        
        try:
            services = request.app.state.services
            settings = services.settings_store.load()
            
            # Build copilot dependencies
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
            
            ollama_config = config_from_settings(settings)
            ollama_client = OllamaClient(config=ollama_config)
            
            copilot = WorkflowCopilot(
                services=services,
                session_store=session_store,
                copilot_store=copilot_store,
                executor=executor,
                context_service=context_service,
                ollama_client=ollama_client,
                root_dir=services.root_dir,
            )
            
            # Use existing session or create new one
            session_id = body.session_id or str(uuid.uuid4())
            
            # Process turn through copilot (non-streaming for compatibility)
            events = []
            tool_calls = []
            final_response = ""
            
            async for event in copilot.process_turn(
                session_id=session_id,
                user_message=body.message,
                model=body.model or settings.ollama_model,
                mode="autoquant",  # AI agent defaults to autoquant mode
                stream=False,
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
            
            return ChatResponse(
                response=final_response or "No response generated.",
                session_id=session_id,
                tool_calls=tool_calls,
            )
            
        except RuntimeError as e:
            # If copilot cannot be created
            session_id = body.session_id if body.session_id else "unknown"
            return ChatResponse(
                response=f"Ollama is not configured or unavailable: {str(e)}",
                session_id=session_id,
                tool_calls=[]
            )
        except Exception as e:
            # If copilot fails, return a simple response
            session_id = body.session_id if body.session_id else "unknown"
            return ChatResponse(
                response=f"AI agent chat failed: {str(e)}. Please ensure Ollama is configured and running.",
                session_id=session_id,
                tool_calls=[]
            )
