"""Ollama WFA fix AI function."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..ai.ollama_client import CircuitBreaker
from .ollama_client import create_ollama_client_from_settings
from .ollama_data_processing import clean_json_response
from .ollama_sensitivity_fix import _analyze_market_conditions, _extract_tried_combinations, detect_strategy_type
from .ollama_validation import validate_ollama_suggestions

logger = logging.getLogger(__name__)

# Global circuit breaker for ollama API calls
_ollama_circuit_breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=300)


async def ask_ollama_for_wfa_fix(
    wfa_results: list[dict[str, Any]],
    current_state: Any,
) -> dict[str, Any] | None:
    """Ask Ollama for intelligent parameter adjustments to fix WFO failures.

    This function analyzes Walk-Forward Analysis failures (< 50% segment pass rate)
    and uses Ollama to suggest parameter adjustments for the retry attempt.

    Args:
        wfa_results: List of WFA segment results with profit, status, ranges, etc.
        current_state: Current PipelineState with hyperopt settings

    Returns:
        Dict with suggested adjustments or None if ollama unavailable/failed:
        {
            "hyperopt_loss": str,  # e.g., "SharpeHyperOptLoss"
            "hyperopt_spaces": list[str],  # e.g., ["buy", "stoploss", "roi"]
            "hyperopt_epochs": int,  # e.g., 100
            "param_overrides": dict,  # e.g., {"use_ema_cross": True}
            "reasoning": str,  # AI explanation for the suggestions
        }
    """
    if not current_state.ai_metrics:
        current_state.ai_metrics = {
            "total_calls": 0,
            "json_parse_success": 0,
            "timeout_count": 0,
            "suggestion_applied_count": 0,
        }

    current_state.ai_metrics["total_calls"] += 1

    client = create_ollama_client_from_settings(current_state.user_data_dir)
    if client is None:
        logger.warning("Ollama client not available for WFA fix")
        return None

    if not _ollama_circuit_breaker.should_allow_call():
        logger.warning("Circuit breaker is open - skipping ollama call")
        return None

    if not await client.check_health():
        logger.warning("Ollama health check failed for WFA fix")
        _ollama_circuit_breaker.record_failure()
        return None

    total_segments = len(wfa_results)
    passing_segments = [r for r in wfa_results if r.get("status") in ("passed", "warning")]
    pass_rate = len(passing_segments) / total_segments if total_segments > 0 else 0.0

    profits = [r.get("profit", 0) for r in wfa_results if r.get("profit") is not None]
    avg_profit = sum(profits) / len(profits) if profits else 0.0
    min_profit = min(profits) if profits else 0.0
    max_profit = max(profits) if profits else 0.0

    if not wfa_results or total_segments == 0:
        logger.warning("No WFA results provided for analysis")
        return None

    segment_summary = "\n".join([
        f"Segment {r.get('window', '?')}: IS={r.get('is_range', 'N/A')}, "
        f"OOS={r.get('oos_range', 'N/A')}, profit={r.get('profit', 0):.2f}%, "
        f"status={r.get('status', 'unknown')}"
        for r in wfa_results
    ])

    strategy_info = detect_strategy_type(current_state.strategy)
    market_info = _analyze_market_conditions(
        current_state.timeframe,
        current_state.in_sample_range,
        current_state.exchange
    )

    tried_combinations = _extract_tried_combinations(current_state.retry_history)

    retry_summary = "\n".join([
        f"Attempt {a.get('attempt', '?')}: loss={a.get('loss')}, spaces={a.get('spaces')}, "
        f"epochs={a.get('epochs')}, profit={a.get('profit')}, reason={a.get('reason')}"
        for a in current_state.retry_history[-3:]
    ]) if current_state.retry_history else "No previous attempts"

    constraint_str = "\n".join([
        f"- loss={loss}, spaces={list(spaces)}, epochs={epochs}"
        for loss, spaces, epochs in tried_combinations
    ]) if tried_combinations else "No previous attempts"

    system_prompt = """You are an expert trading strategy optimization assistant specializing in Walk-Forward Analysis failures.
Your task is to analyze WFA segment failures (low segment pass rate) and suggest intelligent parameter adjustments.

DIAGNOSIS CONTEXT: WFA SEGMENT PASS RATE FAILURE.
This means the strategy parameters do not generalize across different time periods. Less than 50% of WFA segments passed OOS validation.

RECOMMENDATION MANDATES FOR LOW PASS RATE:
- The strategy is likely overfitted to specific market conditions.
- Consider widening search spaces to allow more parameter exploration.
- Consider switching to more robust loss functions (e.g., SharpeHyperOptLoss).
- Force core trend/volatility filters to improve generalization (e.g., suggest 'use_ema_cross': true, 'use_atr': true).
- Increase hyperopt epochs to give the algorithm more time to find robust parameters.

CRITICAL RISK RULE: You can only make parameter search spaces and conditions stricter or structurally wider to find alpha. Never weaken risk filters.

Respond ONLY with valid JSON in this exact format:
{
    "hyperopt_loss": "loss_function_name",
    "hyperopt_spaces": ["space1", "space2"],
    "hyperopt_epochs": integer,
    "param_overrides": {"param_name": value},
    "reasoning": "brief explanation of your suggestions"
}

Valid hyperopt_loss functions: SharpeHyperOptLoss, ProfitDrawDownHyperOptLoss, CalmarHyperOptLoss, OnlyProfitHyperOptLoss
Valid hyperopt_spaces: buy, sell, roi, stoploss, trailing, default, all
param_overrides can include: use_ema_cross, use_atr, use_rsi, use_macd, use_bb, use_adx (boolean values)

IMPORTANT: You MUST NOT suggest parameter combinations that have already been tried and failed.
"""

    user_prompt = f"""WFA FAILURE ANALYSIS:

SEGMENT PASS RATE: {pass_rate:.1%} ({len(passing_segments)}/{total_segments} segments passed)
- Required threshold: 50%
- Current status: FAILED

PROFIT STATISTICS:
- Average profit: {avg_profit:.2f}%
- Min profit: {min_profit:.2f}%
- Max profit: {max_profit:.2f}%

SEGMENT DETAILS:
{segment_summary}

STRATEGY CONTEXT:
- Strategy name: {current_state.strategy}
- Strategy type: {strategy_info['type']}
- Strategy description: {strategy_info['description']}
- Strategy characteristics: {', '.join(strategy_info['characteristics'])}

MARKET CONDITIONS:
- Timeframe: {current_state.timeframe} ({market_info['timeframe_type']} trading)
- Volatility regime: {market_info['volatility_regime']}
- In-sample range: {current_state.in_sample_range} (~{market_info['duration_days']} days)
- Exchange: {current_state.exchange} ({market_info['exchange_type']})

WFO CONFIGURATION:
- IS months: {current_state.wfo_is_months}
- OOS months: {current_state.wfo_oos_months}
- Recency weight: {current_state.wfo_recency_weight}

CURRENT HYPEROPT SETTINGS:
- Loss function: {current_state.hyperopt_loss}
- Search spaces: {list(current_state.hyperopt_spaces)}
- Epochs: {current_state.hyperopt_epochs}

RETRY HISTORY:
{retry_summary}

ALREADY TRIED COMBINATIONS (DO NOT SUGGEST THESE):
{constraint_str}

Based on the low segment pass rate, suggest parameter adjustments to improve generalization.

Consider:
1. Strategy type: {strategy_info['type']} strategies may benefit from specific loss functions
2. Market conditions: {market_info['timeframe_type']} on {market_info['volatility_regime']} volatility may require different approaches
3. Segment pattern: If profits vary wildly, consider more robust loss functions
4. Avoid repetition: Do not suggest combinations that have already been tried

Respond with JSON only."""

    try:
        response = await asyncio.wait_for(
            client.generate(user_prompt, system_prompt=system_prompt, feature="wfa_fix"),
            timeout=30.0
        )
        if not response:
            logger.warning("Ollama returned empty response for WFA fix")
            _ollama_circuit_breaker.record_failure()
            current_state.ai_metrics["timeout_count"] += 1
            return None

        cleaned = clean_json_response(response)

        try:
            suggestions = json.loads(cleaned)
            current_state.ai_metrics["json_parse_success"] += 1

            required_fields = ["hyperopt_loss", "hyperopt_spaces", "hyperopt_epochs"]
            for field in required_fields:
                if field not in suggestions:
                    logger.warning(f"Ollama response missing required field: {field}")
                    return None

            valid_losses = ["SharpeHyperOptLoss", "ProfitDrawDownHyperOptLoss", "CalmarHyperOptLoss", "OnlyProfitHyperOptLoss"]
            if suggestions["hyperopt_loss"] not in valid_losses:
                logger.warning(f"Invalid hyperopt_loss: {suggestions['hyperopt_loss']}")
                suggestions["hyperopt_loss"] = "SharpeHyperOptLoss"

            valid_spaces = ["buy", "sell", "roi", "stoploss", "trailing", "default", "all"]
            if isinstance(suggestions["hyperopt_spaces"], list):
                suggestions["hyperopt_spaces"] = [s for s in suggestions["hyperopt_spaces"] if s in valid_spaces]
                if not suggestions["hyperopt_spaces"]:
                    suggestions["hyperopt_spaces"] = ["buy", "stoploss", "roi"]
            else:
                suggestions["hyperopt_spaces"] = ["buy", "stoploss", "roi"]

            try:
                epochs = int(suggestions["hyperopt_epochs"])
                suggestions["hyperopt_epochs"] = max(50, min(epochs, 500))
            except (ValueError, TypeError):
                suggestions["hyperopt_epochs"] = current_state.hyperopt_epochs

            if "param_overrides" not in suggestions or not isinstance(suggestions["param_overrides"], dict):
                suggestions["param_overrides"] = {}

            is_valid, validation_error = validate_ollama_suggestions(suggestions)
            if not is_valid:
                logger.warning(f"Ollama suggestions failed validation: {validation_error}")
                _ollama_circuit_breaker.record_failure()
                return None

            if tried_combinations:
                suggested_combo = (
                    suggestions["hyperopt_loss"],
                    tuple(sorted(suggestions["hyperopt_spaces"])) if isinstance(suggestions["hyperopt_spaces"], list) else suggestions["hyperopt_spaces"],
                    suggestions["hyperopt_epochs"]
                )
                if suggested_combo in tried_combinations:
                    logger.warning(f"Ollama suggested already-tried combination: {suggested_combo}")

                    retry_suggestions = suggestions.copy()
                    if isinstance(retry_suggestions["hyperopt_spaces"], list):
                        if "default" not in retry_suggestions["hyperopt_spaces"]:
                            retry_suggestions["hyperopt_spaces"].append("default")
                        elif "trailing" not in retry_suggestions["hyperopt_spaces"]:
                            retry_suggestions["hyperopt_spaces"].append("trailing")
                    retry_suggestions["hyperopt_epochs"] = min(500, retry_suggestions["hyperopt_epochs"] + 50)

                    is_retry_valid, retry_validation_error = validate_ollama_suggestions(retry_suggestions)
                    if is_retry_valid:
                        logger.info(f"Ollama retry suggestion accepted: {retry_suggestions}")
                        return retry_suggestions

                    logger.warning("Ollama could not suggest a unique combination - using fallback logic")
                    return None

            logger.info(f"Ollama WFA fix suggestions: {suggestions}")
            _ollama_circuit_breaker.record_success()
            current_state.ai_metrics["suggestion_applied_count"] += 1

            current_state.ai_interactions.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "feature": "wfa_fix",
                "success": True,
                "reasoning": suggestions.get("reasoning", ""),
                "suggestions": {
                    "hyperopt_loss": suggestions.get("hyperopt_loss"),
                    "hyperopt_spaces": suggestions.get("hyperopt_spaces"),
                    "hyperopt_epochs": suggestions.get("hyperopt_epochs"),
                },
            })

            return suggestions

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Ollama JSON response: {e}")
            _ollama_circuit_breaker.record_failure()
            return None

    except asyncio.TimeoutError:
        logger.warning("Ollama WFA fix request timed out (30s) - using fallback logic")
        _ollama_circuit_breaker.record_failure()
        current_state.ai_metrics["timeout_count"] += 1
        return None
    except Exception as e:
        logger.warning(f"Error calling Ollama for WFA fix: {e}")
        _ollama_circuit_breaker.record_failure()
        return None
    finally:
        await client.close()
