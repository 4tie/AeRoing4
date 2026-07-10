"""External integration wrapper for Ollama AI generation."""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from backend.services.ai.ollama_client import OllamaClient


@dataclass
class AIRequest:
    """Request for AI generation"""
    prompt: str
    model: str = "llama2"
    temperature: float = 0.7
    max_tokens: int = 1000


@dataclass
class AIResponse:
    """Response from AI service"""
    success: bool
    text: str
    model: str
    errors: List[str]


class AIExecutor:
    """Executor for Ollama AI service"""
    
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.client = OllamaClient(base_url=base_url, model="", timeout=60.0, strict_json=False)
    
    async def execute(self, request: AIRequest) -> AIResponse:
        """
        Execute AI generation using Ollama
        
        Args:
            request: AI request
        
        Returns:
            AIResponse with generated text
        """
        errors = []
        try:
            text = await self.client.generate(
                request.prompt,
                model=request.model,
                options={"temperature": request.temperature, "num_predict": request.max_tokens},
                feature="ai_executor",
            )
            if text is None:
                return AIResponse(
                    success=False,
                    text="",
                    model=request.model,
                    errors=["Ollama returned an empty or invalid response"],
                )
            return AIResponse(
                success=True,
                text=text,
                model=request.model,
                errors=[]
            )
        except Exception as e:
            errors.append(f"AI execution failed: {str(e)}")
            return AIResponse(
                success=False,
                text='',
                model=request.model,
                errors=errors
            )
    
    async def close(self):
        """Close HTTP client"""
        await self.client.close()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
