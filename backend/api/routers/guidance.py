"""Guidance API endpoints for AI-powered user guidance.

This module provides endpoints for the AI guidance assistant,
integrating with the existing Ollama service to provide
context-aware guidance for trading strategy development.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/guidance", tags=["guidance"])


class GuidanceRequest(BaseModel):
    """Request model for AI guidance."""
    context: dict
    user_input: str
    scenario: Optional[str] = None


class GuidanceResponse(BaseModel):
    """Response model for AI guidance."""
    title: str
    message: str
    steps: Optional[list[str]] = None
    recommendations: Optional[list[str]] = None
    issues: Optional[list[str]] = None
    metrics: Optional[list[str]] = None
    tips: Optional[list[str]] = None


@router.post("/ask")
async def ask_guidance(request: GuidanceRequest) -> GuidanceResponse:
    """Get AI guidance based on context and user input.
    
    This endpoint integrates with the Ollama service to provide
    context-aware guidance for trading strategy development.
    """
    try:
        # Import here to avoid circular dependencies
        from backend.services.auto_quant.ollama_service import (
            create_ollama_client_from_settings,
            create_strategy_lab_client,
        )
        
        # Build context-aware prompt
        prompt = _build_guidance_prompt(request.context, request.user_input, request.scenario)
        
        # Try to get AI response
        try:
            client = create_ollama_client_from_settings()
            response = client.generate(
                model="llama3.2",  # or configured model
                prompt=prompt,
                stream=False
            )
            
            # Parse AI response into structured format
            return _parse_ai_response(response["response"], request.scenario)
            
        except Exception as ai_error:
            # Fallback to rule-based guidance if AI unavailable
            return _get_rule_based_guidance(request.context, request.user_input, request.scenario)
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _build_guidance_prompt(context: dict, user_input: str, scenario: Optional[str]) -> str:
    """Build a context-aware prompt for the AI."""
    
    base_prompt = """You are an expert trading strategy assistant for FortiesR, a Freqtrade-based trading platform.
Your goal is to provide clear, actionable guidance for trading strategy development and optimization.

Current context:
"""
    
    # Add context information
    if context.get("currentPage"):
        base_prompt += f"- Current page: {context['currentPage']}\n"
    if context.get("strategy"):
        base_prompt += f"- Strategy: {context['strategy']}\n"
    if context.get("pipelineRunning"):
        base_prompt += f"- Pipeline status: Running at stage {context.get('pipelineStage', 'unknown')}\n"
    if context.get("backtestResults"):
        results = context['backtestResults']
        base_prompt += f"- Backtest results: Profit={results.get('profit', 'N/A')}, "
        base_prompt += f"Drawdown={results.get('drawdown', 'N/A')}, "
        base_prompt += f"Win Rate={results.get('winRate', 'N/A')}\n"
    
    # Add scenario-specific guidance
    if scenario == "new-strategy":
        base_prompt += """
The user wants to create a new trading strategy. Guide them through:
1. Understanding their trading style (scalping, intraday, swing)
2. Selecting appropriate timeframe
3. Choosing indicators and parameters
4. Testing and validation steps

Provide step-by-step guidance with specific recommendations."""
        
    elif scenario == "improve-strategy":
        base_prompt += """
The user wants to improve an existing strategy. Analyze their situation and provide:
1. Identification of potential issues
2. Specific parameter adjustments
3. Suggested optimization approaches
4. Validation recommendations

Focus on practical, actionable improvements."""
        
    elif scenario == "analyze-backtest":
        base_prompt += """
The user wants to analyze backtest results. Provide:
1. Analysis of key metrics (profit, drawdown, win rate, etc.)
2. Identification of strengths and weaknesses
3. Recommendations for improvement
4. Next steps for validation

Be specific about what the metrics mean and how to interpret them."""
        
    elif scenario == "optimize-parameters":
        base_prompt += """
The user wants to optimize strategy parameters. Guide them on:
1. Which parameters to optimize (ROI, stoploss, indicators)
2. Genetic algorithm configuration
3. Search space definitions
4. Interpreting optimization results

Provide practical configuration advice."""
        
    elif scenario == "debug-strategy":
        base_prompt += """
The user is debugging a failing strategy. Help them:
1. Identify common failure patterns
2. Debug specific issues (no trades, all losses, etc.)
3. Suggest fixes and improvements
4. Validate the fixes

Focus on systematic debugging approaches."""
    
    # Add user's specific input
    base_prompt += f"\nUser's specific input: {user_input}\n"
    
    base_prompt += """
Provide your response in a structured format with:
- A clear title
- A concise message
- Step-by-step guidance (if applicable)
- Specific recommendations
- Any issues detected
- Key metrics to watch
- General tips

Keep responses practical and actionable. Avoid overly technical jargon."""
    
    return base_prompt


def _parse_ai_response(ai_response: str, scenario: Optional[str]) -> GuidanceResponse:
    """Parse AI response into structured format."""
    
    # This is a simplified parser - in production, you'd want more sophisticated parsing
    # potentially using structured outputs from the AI model
    
    lines = ai_response.split('\n')
    
    response = GuidanceResponse(
        title="AI Guidance",
        message=ai_response[:200] + "..." if len(ai_response) > 200 else ai_response,
        steps=[],
        recommendations=[],
        issues=[],
        metrics=[],
        tips=[]
    )
    
    # Try to extract structured information
    current_section = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if "title" in line.lower() or "**title**" in line.lower():
            response.title = line.replace("*", "").replace("Title:", "").strip()
        elif "step" in line.lower() and line[0].isdigit():
            response.steps.append(line)
        elif "recommend" in line.lower():
            response.recommendations.append(line)
        elif "issue" in line.lower():
            response.issues.append(line)
        elif "metric" in line.lower():
            response.metrics.append(line)
        elif "tip" in line.lower():
            response.tips.append(line)
    
    # If no structured content found, use the whole response as message
    if not any([response.steps, response.recommendations, response.issues]):
        response.message = ai_response
    
    return response


def _get_rule_based_guidance(context: dict, user_input: str, scenario: Optional[str]) -> GuidanceResponse:
    """Get rule-based guidance when AI is unavailable."""
    
    scenario_guidance = {
        "new-strategy": GuidanceResponse(
            title="Creating a New Strategy",
            message="Since AI is unavailable, here's a manual approach:",
            steps=[
                "1. Go to Strategy Lab tab",
                "2. Choose a strategy template (RSI, MACD, Bollinger, etc.)",
                "3. Select your trading style (scalping, intraday, swing)",
                "4. Choose timeframe (1m, 5m, 15m, 1h, 4h, 1d)",
                "5. Select trading pairs",
                "6. Configure initial parameters",
                "7. Run backtest to test",
            ],
            tips=[
                "Start with simple strategies and build complexity",
                "Test on multiple timeframes to find what works",
                "Use pair filtering to focus on profitable pairs",
            ]
        ),
        "improve-strategy": GuidanceResponse(
            title="Improving Existing Strategy",
            message="Manual approach for strategy improvement:",
            steps=[
                "1. Analyze backtest results",
                "2. Identify weak areas (low win rate, high drawdown, etc.)",
                "3. Go to Optimizer tab",
                "4. Configure genetic optimization",
                "5. Run evolution to find better parameters",
                "6. Test optimized parameters",
            ],
            recommendations=[
                "Try genetic optimization to find better parameters",
                "Filter pairs to only profitable ones",
                "Adjust timeframe - shorter timeframes may work better",
                "Add entry/exit filters to reduce bad trades",
            ]
        ),
        "analyze-backtest": GuidanceResponse(
            title="Analyzing Backtest Results",
            message="Key metrics to review:",
            metrics=[
                "Profit Factor: Should be > 1.5",
                "Win Rate: Should be > 40%",
                "Max Drawdown: Should be < 20%",
                "Sharpe Ratio: Should be > 1.0",
                "Profit per pair: Check which pairs perform best",
            ]
        ),
        "optimize-parameters": GuidanceResponse(
            title="Parameter Optimization",
            message="Using genetic algorithms:",
            steps=[
                "1. Define search spaces (parameters to vary)",
                "2. Set population size (50-100)",
                "3. Set generations (20-50)",
                "4. Choose optimization spaces (ROI, stoploss, indicators)",
                "5. Run optimization",
                "6. Review best performers",
            ]
        ),
        "debug-strategy": GuidanceResponse(
            title="Debugging Failing Strategy",
            message="Common issues and fixes:",
            issues=[
                "No trades: Check indicator parameters and entry conditions",
                "All losses: Review stoploss and exit conditions",
                "Overfitting: Reduce complexity, add regularization",
                "Poor performance: Try different timeframe or pairs",
            ]
        ),
    }
    
    return scenario_guidance.get(scenario, GuidanceResponse(
        title="General Guidance",
        message="AI guidance unavailable. Here are some tips:",
        tips=[
            "Start with simple strategies and build complexity",
            "Always test on out-of-sample data",
            "Use pair filtering to focus on profitable pairs",
            "Monitor drawdown carefully - it's your risk",
            "Paper trade before live trading",
        ]
    ))
