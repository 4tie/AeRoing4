"""Ollama sensitivity fix AI function."""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..ai.ollama_client import CircuitBreaker
from .ollama_client import create_ollama_client_from_settings
from .ollama_data_processing import clean_json_response
from .ollama_validation import SAFE_RANGES, validate_ollama_suggestions

logger = logging.getLogger(__name__)

# Global circuit breaker for ollama API calls
_ollama_circuit_breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=300)


def detect_strategy_type(strategy_name: str) -> dict[str, str]:
    """Detect strategy type and characteristics from strategy name."""
    strategy_lower = strategy_name.lower()
    
    if "adaptive" in strategy_lower:
        return {
            "type": "regime-switching",
            "description": "Regime-switching strategy that adapts parameters based on market conditions",
            "characteristics": ["ATR-based regime detection", "dual parameter sets", "dynamic adjustment"]
        }
    elif "multi" in strategy_lower or "ma" in strategy_lower:
        return {
            "type": "multi-indicator",
            "description": "Multi-indicator strategy using multiple technical indicators",
            "characteristics": ["multiple signal sources", "weighted consensus", "diversified signals"]
        }
    elif "trend" in strategy_lower or "momentum" in strategy_lower:
        return {
            "type": "trend-following",
            "description": "Trend-following strategy that rides market momentum",
            "characteristics": ["momentum-based", "trend detection", "breakout signals"]
        }
    else:
        return {
            "type": "unknown",
            "description": "Custom strategy with unknown characteristics",
            "characteristics": ["custom logic", "unknown parameters"]
        }


def _analyze_market_conditions(
    timeframe: str,
    in_sample_range: str,
    exchange: str,
) -> dict[str, str]:
    """Analyze market conditions based on timeframe, date range, and exchange."""
    timeframe_map = {
        "1m": ("scalping", "high"),
        "3m": ("scalping", "high"),
        "5m": ("scalping", "high"),
        "15m": ("intraday", "medium"),
        "30m": ("intraday", "medium"),
        "1h": ("intraday", "medium"),
        "4h": ("swing", "low"),
        "1d": ("swing", "low"),
    }
    
    timeframe_type, volatility = timeframe_map.get(timeframe, ("intraday", "medium"))
    duration_days = 30
    
    exchange_type = "spot"
    if "future" in exchange.lower():
        exchange_type = "futures"
    
    return {
        "timeframe_type": timeframe_type,
        "volatility_regime": volatility,
        "duration_days": duration_days,
        "exchange_type": exchange_type,
    }


def _analyze_historical_success_rates(
    retry_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze retry history to identify successful parameter patterns."""
    if not retry_history:
        return {
            "loss_success_rates": {},
            "spaces_success_rates": {},
            "epochs_success_rates": {},
            "best_combinations": [],
        }
    
    loss_attempts: dict[str, list[dict]] = {}
    spaces_attempts: dict[tuple, list[dict]] = {}
    epochs_attempts: dict[int, list[dict]] = {}
    
    for attempt in retry_history:
        loss = attempt.get("loss", "")
        spaces = tuple(sorted(attempt.get("spaces", [])))
        epochs = attempt.get("epochs", 0)
        passed = attempt.get("passed", False)
        
        if loss:
            if loss not in loss_attempts:
                loss_attempts[loss] = []
            loss_attempts[loss].append({"passed": passed, "profit": attempt.get("profit")})
        
        if spaces:
            if spaces not in spaces_attempts:
                spaces_attempts[spaces] = []
            spaces_attempts[spaces].append({"passed": passed, "profit": attempt.get("profit")})
        
        if epochs:
            if epochs not in epochs_attempts:
                epochs_attempts[epochs] = []
            epochs_attempts[epochs].append({"passed": passed, "profit": attempt.get("profit")})
    
    loss_success_rates = {}
    for loss, attempts in loss_attempts.items():
        passed_count = sum(1 for a in attempts if a["passed"])
        loss_success_rates[loss] = passed_count / len(attempts) if attempts else 0
    
    spaces_success_rates = {}
    for spaces, attempts in spaces_attempts.items():
        passed_count = sum(1 for a in attempts if a["passed"])
        spaces_success_rates[spaces] = passed_count / len(attempts) if attempts else 0
    
    epochs_success_rates = {}
    for epochs, attempts in epochs_attempts.items():
        passed_count = sum(1 for a in attempts if a["passed"])
        epochs_success_rates[epochs] = passed_count / len(attempts) if attempts else 0
    
    best_combinations = []
    for attempt in retry_history:
        if attempt.get("passed", False) and attempt.get("profit") is not None:
            best_combinations.append({
                "loss": attempt.get("loss"),
                "spaces": attempt.get("spaces"),
                "epochs": attempt.get("epochs"),
                "profit": attempt.get("profit"),
            })
    
    best_combinations.sort(key=lambda x: x.get("profit", 0), reverse=True)
    best_combinations = best_combinations[:3]
    
    return {
        "loss_success_rates": loss_success_rates,
        "spaces_success_rates": spaces_success_rates,
        "epochs_success_rates": epochs_success_rates,
        "best_combinations": best_combinations,
    }


def _extract_tried_combinations(
    retry_history: list[dict[str, Any]],
) -> set[tuple]:
    """Extract all previously tried (loss, spaces, epochs) combinations."""
    tried = set()
    for attempt in retry_history:
        loss = attempt.get("loss", "")
        spaces = tuple(sorted(attempt.get("spaces", [])))
        epochs = attempt.get("epochs", 0)
        tried.add((loss, spaces, epochs))
    return tried


async def ask_ollama_for_sensitivity_fix(
    sensitivity_result: dict[str, Any],
    retry_history: list[dict[str, Any]],
    current_state: Any,
) -> dict[str, Any] | None:
    """Ask Ollama for intelligent parameter adjustments to fix sensitivity failures."""
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
        logger.warning("Ollama client not available for sensitivity fix")
        return None
    
    if not _ollama_circuit_breaker.should_allow_call():
        logger.warning("Circuit breaker is open - skipping ollama call")
        return None
    
    if not await client.check_health():
        logger.warning("Ollama health check failed for sensitivity fix")
        _ollama_circuit_breaker.record_failure()
        return None
    
    p_best = sensitivity_result.get("p_best")
    p_minus = sensitivity_result.get("p_minus")
    p_plus = sensitivity_result.get("p_plus")
    perturbed_param = sensitivity_result.get("param")
    failure_reason = sensitivity_result.get("failure_reason")
    
    strategy_info = detect_strategy_type(current_state.strategy)
    market_info = _analyze_market_conditions(
        current_state.timeframe,
        current_state.in_sample_range,
        current_state.exchange
    )
    success_analysis = _analyze_historical_success_rates(retry_history)
    tried_combinations = _extract_tried_combinations(retry_history)
    
    retry_summary = "\n".join([
        f"Attempt {a.get('attempt', '?')}: loss={a.get('loss')}, spaces={a.get('spaces')}, "
        f"epochs={a.get('epochs')}, profit={a.get('profit')}, reason={a.get('reason')}"
        for a in retry_history[-3:]
    ]) if retry_history else "No previous attempts"
    
    success_summary_parts = []
    if success_analysis["loss_success_rates"]:
        loss_rates = ", ".join([f"{k}: {v:.0%}" for k, v in success_analysis["loss_success_rates"].items()])
        success_summary_parts.append(f"Loss function success rates: {loss_rates}")
    if success_analysis["spaces_success_rates"]:
        spaces_rates = ", ".join([f"{k}: {v:.0%}" for k, v in success_analysis["spaces_success_rates"].items()])
        success_summary_parts.append(f"Spaces success rates: {spaces_rates}")
    if success_analysis["best_combinations"]:
        best_str = ", ".join([
            f"{c['loss']}+{c['spaces']} (profit={c['profit']:.2%})"
            for c in success_analysis["best_combinations"]
        ])
        success_summary_parts.append(f"Best performing combinations: {best_str}")
    success_summary = "\n".join(success_summary_parts) if success_summary_parts else "No historical data"
    
    if failure_reason == "FAIL_NEGATIVE_BASELINE":
        failure_guidance = (
            "DIAGNOSIS CONTEXT: FAIL_NEGATIVE_BASELINE.\n"
            "This means the current configuration is inherently losing money (profit < 0). Radical structural changes are needed.\n"
            "RECOMMENDATION MANDATES FOR NEGATIVE BASELINE:\n"
            "- Force core trend/volatility filters to True to stop bleeding (e.g., suggest 'use_ema_cross': true, 'use_atr': true).\n"
            "- Widen the search space to allow Freqtrade to discover profitable combinations (suggest ['buy', 'stoploss', 'roi']).\n"
            "- Suggest increasing hyperopt epochs to give the algorithm more time to escape the loss trap.\n"
            "- Consider switching to OnlyProfitHyperOptLoss to target pure return recovery."
        )
    else:
        failure_guidance = (
            "DIAGNOSIS CONTEXT: FAIL_SHARP_PEAK.\n"
            "This means the strategy is heavily overfitted to historical data.\n"
            "RECOMMENDATION MANDATES FOR SHARP PEAK:\n"
            "- Narrow down specific hyperopt spaces to prevent erratic hunting.\n"
            "- Recommend switching to stabilizing loss functions like 'SharpeHyperOptLoss' or 'ProfitDrawDownHyperOptLoss'."
        )
    
    constraint_str = "\n".join([
        f"- loss={loss}, spaces={list(spaces)}, epochs={epochs}"
        for loss, spaces, epochs in tried_combinations
    ]) if tried_combinations else "No previous attempts"
    
    system_prompt = """You are an expert trading strategy optimization assistant specializing in sensitivity check failures.
Your task is to analyze sensitivity check failures (Sharp Peak or Negative Baseline) and suggest intelligent parameter adjustments.

You must handle two types of failures:
1. 'FAIL_SHARP_PEAK': Strategy is overfitted. Nearby parameters cause massive variance.
2. 'FAIL_NEGATIVE_BASELINE': The strategy is dead-on-arrival (unprofitable, net profit < 0 across trials).

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
    
    user_prompt = f"""{failure_guidance}

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

SENSITIVITY FAILURE DETAILS:
- Best parameter profit: {p_best}
- Parameter -5% profit: {p_minus}
- Parameter +5% profit: {p_plus}
- Perturbed parameter: {perturbed_param}
- Failure reason: {failure_reason}

CURRENT HYPEROPT SETTINGS:
- Loss function: {current_state.hyperopt_loss}
- Search spaces: {list(current_state.hyperopt_spaces)}
- Epochs: {current_state.hyperopt_epochs}

RETRY HISTORY:
{retry_summary}

HISTORICAL SUCCESS PATTERNS:
{success_summary}

ALREADY TRIED COMBINATIONS (DO NOT SUGGEST THESE):
{constraint_str}

Based on the strategy type, market conditions, and historical patterns, suggest parameter adjustments.

Consider:
1. Strategy type: {strategy_info['type']} strategies may benefit from specific loss functions
2. Market conditions: {market_info['timeframe_type']} on {market_info['volatility_regime']} volatility may require different approaches
3. Historical patterns: Learn from which parameter combinations worked best in the past
4. Avoid repetition: Do not suggest combinations that have already been tried

Respond with JSON only."""
    
    try:
        response = await client.generate(user_prompt, system_prompt=system_prompt, feature="sensitivity_fix")
        if not response:
            logger.warning("Ollama returned empty response for sensitivity fix")
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
            
            suggested_loss = suggestions["hyperopt_loss"]
            suggested_spaces = tuple(sorted(suggestions["hyperopt_spaces"]))
            suggested_epochs = suggestions["hyperopt_epochs"]
            suggested_tuple = (suggested_loss, suggested_spaces, suggested_epochs)
            
            if suggested_tuple in tried_combinations:
                logger.warning(f"Ollama suggested already-tried combination: {suggested_tuple}")
                retry_system_prompt = system_prompt + "\n\nCRITICAL: Your previous suggestion was already tried. Suggest a DIFFERENT combination."
                retry_user_prompt = user_prompt + f"\n\nPREVIOUS SUGGESTION (REJECTED - ALREADY TRIED): {suggested_tuple}"
                
                try:
                    retry_response = await client.generate(retry_user_prompt, system_prompt=retry_system_prompt)
                    if retry_response:
                        retry_cleaned = clean_json_response(retry_response)
                        retry_suggestions = json.loads(retry_cleaned)
                        
                        retry_loss = retry_suggestions.get("hyperopt_loss", suggested_loss)
                        retry_spaces = tuple(sorted(retry_suggestions.get("hyperopt_spaces", list(suggested_spaces))))
                        retry_epochs = retry_suggestions.get("hyperopt_epochs", suggested_epochs)
                        retry_tuple = (retry_loss, retry_spaces, retry_epochs)
                        
                        if retry_tuple not in tried_combinations:
                            if all(field in retry_suggestions for field in required_fields):
                                if retry_suggestions["hyperopt_loss"] in valid_losses:
                                    retry_spaces_list = [s for s in retry_suggestions["hyperopt_spaces"] if s in valid_spaces]
                                    if retry_spaces_list:
                                        retry_suggestions["hyperopt_spaces"] = retry_spaces_list
                                        try:
                                            retry_epochs_int = int(retry_suggestions["hyperopt_epochs"])
                                            retry_suggestions["hyperopt_epochs"] = max(50, min(retry_epochs_int, 500))
                                        except (ValueError, TypeError):
                                            retry_suggestions["hyperopt_epochs"] = current_state.hyperopt_epochs
                                        
                                        if "param_overrides" not in retry_suggestions or not isinstance(retry_suggestions["param_overrides"], dict):
                                            retry_suggestions["param_overrides"] = {}
                                        
                                        logger.info(f"Ollama retry suggestion accepted: {retry_suggestions}")
                                        return retry_suggestions
                except Exception as retry_exc:
                    logger.warning(f"Retry attempt failed: {retry_exc}")
                
                logger.warning("Ollama could not suggest a unique combination - using fallback logic")
                return None
            
            logger.info(f"Ollama sensitivity fix suggestions: {suggestions}")
            _ollama_circuit_breaker.record_success()
            current_state.ai_metrics["suggestion_applied_count"] += 1
            
            current_state.ai_interactions.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "feature": "sensitivity_fix",
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
            
    except Exception as e:
        logger.warning(f"Error calling Ollama for sensitivity fix: {e}")
        _ollama_circuit_breaker.record_failure()
        return None
    finally:
        await client.close()
