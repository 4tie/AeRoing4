"""Data processing functions for Ollama AI service."""

import re
from typing import Any


def clean_json_response(response: str) -> str:
    """Strip conversational text and markdown blocks from AI response.
    
    This function handles various AI response formats:
    - Markdown code blocks (```json ... ```)
    - Conversational prefixes ("Here is the analysis:")
    - Conversational suffixes
    - Multiple JSON blocks
    
    Args:
        response: Raw AI response text
        
    Returns:
        Cleaned JSON string or original if no JSON found
    """
    if not response:
        return response
    
    cleaned = response.strip()
    
    # Remove markdown code blocks
    # Pattern: ```json or ``` followed by content and ```
    code_block_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    matches = re.findall(code_block_pattern, cleaned)
    
    if matches:
        # Take the last code block (most likely to be the actual JSON)
        cleaned = matches[-1].strip()
    
    # Remove common conversational prefixes
    prefix_patterns = [
        r"^Here is (?:the )?(?:analysis|response|result|output):\s*",
        r"^The (?:analysis|response|result|output) (?:is|follows):\s*",
        r"^Analysis:\s*",
        r"^Response:\s*",
        r"^Result:\s*",
        r"^Output:\s*",
    ]
    
    for pattern in prefix_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    
    # Remove conversational suffixes
    suffix_patterns = [
        r"\s*(?:Let me know if you need anything else|Hope this helps|Is there anything else)\.?\s*$",
        r"\s*(?:Please let me know if you have any questions)\.?\s*$",
    ]
    
    for pattern in suffix_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    
    # Try to extract JSON object if still surrounded by text
    # Look for { ... } pattern
    json_pattern = r"\{[\s\S]*\}"
    json_matches = re.findall(json_pattern, cleaned)
    
    if json_matches:
        # Take the largest JSON object (most likely to be complete)
        cleaned = max(json_matches, key=len)
    
    return cleaned.strip()


def summarize_hyperopt_trials(trials: list[dict[str, Any]]) -> str:
    """Calculate statistics and correlations from hyperopt trials.
    
    This function pre-processes hyperopt trial data to create a concise
    summary for AI analysis, avoiding context window overflow.
    
    Args:
        trials: List of trial dicts with params_dict and loss
        
    Returns:
        Concise text summary of trial statistics
    """
    if not trials:
        return "No trials available for analysis"
    
    # Extract parameters and losses
    param_names = set()
    param_values: dict[str, list[float]] = {}
    losses: list[float] = []
    
    for trial in trials:
        params_dict = trial.get("params_dict", {})
        loss = trial.get("loss")
        
        if loss is not None:
            losses.append(float(loss))
        
        for param_name, param_value in params_dict.items():
            param_names.add(param_name)
            if param_name not in param_values:
                param_values[param_name] = []
            
            # Convert to float if possible
            try:
                param_values[param_name].append(float(param_value))
            except (ValueError, TypeError):
                pass
    
    if not losses:
        return "No valid loss values in trials"
    
    # Calculate loss statistics
    loss_mean = sum(losses) / len(losses)
    loss_std = (sum((x - loss_mean) ** 2 for x in losses) / len(losses)) ** 0.5
    loss_min = min(losses)
    loss_max = max(losses)
    
    summary_parts = [f"Loss: mean={loss_mean:.4f}, std={loss_std:.4f}, min={loss_min:.4f}, max={loss_max:.4f}"]
    
    # Calculate parameter statistics
    for param_name in sorted(param_names):
        values = param_values.get(param_name, [])
        if not values:
            continue
        
        param_mean = sum(values) / len(values)
        param_std = (sum((x - param_mean) ** 2 for x in values) / len(values)) ** 0.5
        param_min = min(values)
        param_max = max(values)
        
        # Check if clustered at boundaries (within 5% of range)
        param_range = param_max - param_min
        if param_range > 0:
            at_lower_bound = abs(param_min - param_mean) < 0.05 * param_range
            at_upper_bound = abs(param_max - param_mean) < 0.05 * param_range
            
            bound_info = ""
            if at_lower_bound:
                bound_info = " (clustered at lower bound)"
            elif at_upper_bound:
                bound_info = " (clustered at upper bound)"
        else:
            bound_info = " (constant)"
        
        summary_parts.append(
            f"{param_name}: mean={param_mean:.4f}, std={param_std:.4f}, "
            f"min={param_min:.4f}, max={param_max:.4f}{bound_info}"
        )
    
    # Calculate correlation with loss (simplified)
    correlation_parts = []
    for param_name in sorted(param_names):
        values = param_values.get(param_name, [])
        if len(values) != len(losses):
            continue
        
        # Simple correlation calculation
        if len(values) < 2:
            continue
        
        try:
            mean_x = sum(values) / len(values)
            mean_y = sum(losses) / len(losses)
            
            numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(values, losses))
            denominator_x = sum((x - mean_x) ** 2 for x in values) ** 0.5
            denominator_y = sum((y - mean_y) ** 2 for y in losses) ** 0.5
            
            if denominator_x > 0 and denominator_y > 0:
                correlation = numerator / (denominator_x * denominator_y)
                
                if abs(correlation) < 0.1:
                    correlation_parts.append(f"{param_name} has negligible correlation with loss ({correlation:.2f})")
                elif abs(correlation) > 0.7:
                    correlation_parts.append(f"{param_name} has strong correlation with loss ({correlation:.2f})")
        except (ZeroDivisionError, ValueError):
            pass
    
    if correlation_parts:
        summary_parts.append("Correlations: " + "; ".join(correlation_parts))
    
    return "; ".join(summary_parts)


def summarize_market_conditions(price_data: list[dict[str, Any]]) -> str:
    """Extract volatility and regime information from price data.
    
    This function pre-processes price data to create a concise summary
    for AI analysis, avoiding context window overflow.
    
    Args:
        price_data: List of price data points with timestamp, open, high, low, close
        
    Returns:
        Concise text summary of market conditions
    """
    if not price_data or len(price_data) < 2:
        return "Insufficient price data for analysis"
    
    # Extract close prices
    closes = []
    for point in price_data:
        close = point.get("close")
        if close is not None:
            try:
                closes.append(float(close))
            except (ValueError, TypeError):
                pass
    
    if len(closes) < 2:
        return "Insufficient valid close prices for analysis"
    
    # Calculate returns
    returns = []
    for i in range(1, len(closes)):
        ret = (closes[i] - closes[i-1]) / closes[i-1]
        returns.append(ret)
    
    # Calculate volatility (std of returns)
    if returns:
        mean_return = sum(returns) / len(returns)
        volatility = (sum((r - mean_return) ** 2 for r in returns) / len(returns)) ** 0.5
        volatility_pct = volatility * 100
    else:
        volatility_pct = 0.0
    
    # Calculate ATR (Average True Range) - simplified
    atr_values = []
    for i in range(1, len(price_data)):
        prev = price_data[i-1]
        curr = price_data[i]
        
        try:
            high = float(curr.get("high", 0))
            low = float(curr.get("low", 0))
            prev_close = float(prev.get("close", 0))
            
            tr1 = high - low
            tr2 = abs(high - prev_close)
            tr3 = abs(low - prev_close)
            
            atr = max(tr1, tr2, tr3)
            atr_values.append(atr)
        except (ValueError, TypeError):
            pass
    
    if atr_values:
        atr = sum(atr_values) / len(atr_values)
    else:
        atr = 0.0
    
    # Detect regime
    if volatility_pct > 2.0:
        regime = "high volatility"
    elif volatility_pct < 0.5:
        regime = "low volatility"
    else:
        regime = "normal volatility"
    
    # Trend detection (simple linear regression slope)
    if len(closes) >= 10:
        x = list(range(len(closes)))
        mean_x = sum(x) / len(x)
        mean_y = sum(closes) / len(closes)
        
        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, closes))
        denominator = sum((xi - mean_x) ** 2 for xi in x)
        
        if denominator > 0:
            slope = numerator / denominator
            trend_strength = abs(slope) / mean_y if mean_y != 0 else 0
            
            if trend_strength > 0.01:
                trend = "strong"
            elif trend_strength > 0.005:
                trend = "moderate"
            else:
                trend = "weak"
            
            trend_direction = "upward" if slope > 0 else "downward"
        else:
            trend = "weak"
            trend_direction = "neutral"
    else:
        trend = "insufficient data"
        trend_direction = "neutral"
    
    return (
        f"Regime: {regime}; "
        f"Volatility: {volatility_pct:.2f}%; "
        f"ATR: {atr:.6f}; "
        f"Trend: {trend} {trend_direction}"
    )


def summarize_failure_metrics(failed_metrics: dict[str, Any]) -> str:
    """Format failed metrics for AI analysis.
    
    This function formats failed metrics into a concise summary
    for AI diagnosis, avoiding context window overflow.
    
    Args:
        failed_metrics: Dict of failed metrics including thresholds
        
    Returns:
        Concise text summary of failure analysis
    """
    if not failed_metrics:
        return "Noailure metrics available"
    
    summary_parts = []
    
    # Common metric mappings
    metric_names = {
        "profit": "Profit",
        "profit_total": "Profit",
        "max_drawdown": "Max Drawdown",
        "max_drawdown_account": "Max Drawdown",
        "win_rate": "Win Rate",
        "profit_factor": "Profit Factor",
        "sharpe_ratio": "Sharpe Ratio",
        "sharpe": "Sharpe Ratio",
    }
    
    # Extract failed checks
    checks = failed_metrics.get("checks", {})
    
    for metric_key, check_info in checks.items():
        if isinstance(check_info, dict):
            passed = check_info.get("passed", True)
            if not passed:
                value = check_info.get("value", "N/A")
                threshold = check_info.get("threshold", "N/A")
                metric_name = metric_names.get(metric_key, metric_key.replace("_", " ").title())
                summary_parts.append(f"Failed: {metric_name}={value} (threshold: {threshold})")
    
    # If no checks, look for raw metrics
    if not summary_parts:
        for metric_key, metric_name in metric_names.items():
            if metric_key in failed_metrics:
                value = failed_metrics[metric_key]
                threshold_key = f"min_{metric_key}" if not metric_key.startswith("min_") else f"{metric_key.replace('min_', '')}_threshold"
                threshold = failed_metrics.get(threshold_key, failed_metrics.get(f"max_{metric_key}", "N/A"))
                
                summary_parts.append(f"{metric_name}={value} (threshold: {threshold})")
    
    # Add reason if available
    reason = failed_metrics.get("reason")
    if reason:
        summary_parts.append(f"Reason: {reason}")
    
    return "; ".join(summary_parts) if summary_parts else "No specific failure information"
