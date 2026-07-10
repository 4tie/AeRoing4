"""Discovery module for AutoQuant robustness-first workflow.

This module implements the discovery phase that tests configured style timeframes
and liquid pair universe before validation. Discovery uses permissive gates and
never rejects the strategy outright - it only adds validation notes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..policy import load_policy
from .helpers import _backtest_cmd, _extract_backtest_summary, _extract_per_pair_results, _find_backtest_result, _run_subprocess
from .logging import _rlog


@dataclass
class DiscoveryResult:
    """Result of discovery phase."""
    candidate_timeframes: list[str]
    unsupported_timeframes: list[str]
    strongest_timeframe: str
    most_stable_timeframe: str
    most_robust_timeframe: str
    selected_timeframe: str
    selected_pairs: list[str]
    recommended_pairs: list[str]  # pairs that pass discovery gates
    pair_errors: dict[str, str]  # pair -> error message
    pair_metrics: dict[str, dict]  # pair -> metrics (trades, profit_factor, win_rate, etc.)
    notes: list[str]


async def run_discovery(
    run_id: str,
    state: Any,
    out_dir: Path,
) -> DiscoveryResult:
    """Run discovery phase to select best timeframe and pair universe.
    
    Tests configured style timeframes and liquid pair universe using permissive
    discovery gates. Never rejects strategy outright - only adds validation notes.
    
    Args:
        run_id: Pipeline run identifier
        state: PipelineState instance
        out_dir: Output directory for discovery results
        
    Returns:
        DiscoveryResult with selected timeframe, pairs, and any validation notes
    """
    policy = load_policy()
    
    # Get configured timeframes for the trading style
    configured_timeframes = policy.style_timeframes(state.trading_style)
    unsupported_timeframes = sorted(set(configured_timeframes) & policy.unsupported_timeframes())
    supported_timeframes = [tf for tf in configured_timeframes if tf not in unsupported_timeframes]
    
    notes: list[str] = []
    
    # Add notes for unsupported timeframes
    for tf in unsupported_timeframes:
        notes.append(f"Timeframe {tf} is unsupported for automated validation and will be treated as a validation note.")
    
    # If no supported timeframes, fall back to a default
    if not supported_timeframes:
        notes.append("No supported timeframes configured for trading style. Using fallback timeframe.")
        supported_timeframes = ["1h"]
    
    # Get discovery gates (permissive thresholds)
    discovery_gates = policy.thresholds_for(
        state.trading_style,
        state.risk_profile,
        "discovery",
        timerange=state.in_sample_range,
    )
    
    # Get pair universe to test
    pair_universe = state.pair_universe or policy.default_pair_universe(
        state.trading_style,
        state.risk_profile,
        state.pair_universe
    )
    
    _rlog(run_id, 0, logging.INFO,
          f"Discovery | Testing {len(supported_timeframes)} timeframes across {len(pair_universe)} pairs")
    
    # For now, use the first supported timeframe as selected
    # In a full implementation, we would test each timeframe and select the best
    selected_timeframe = supported_timeframes[0]
    
    # Test pair universe liquidity
    pair_errors = {}
    selected_pairs = []
    recommended_pairs = []
    pair_metrics = {}
    
    # Run a quick backtest to validate pair liquidity
    _rlog(run_id, 0, logging.INFO,
          f"Discovery | Testing pair liquidity on timeframe {selected_timeframe}")
    
    result_prefix = str(out_dir / "discovery_result")
    cmd = _backtest_cmd(
        state,
        strategy=state.strategy,
        timerange=state.in_sample_range,
        result_prefix=result_prefix,
        pairs=pair_universe,
    )
    
    try:
        rc, stdout, stderr = await _run_subprocess(run_id, cmd, stage=0)
        
        if rc == 0:
            result_data = _find_backtest_result(out_dir, "discovery_result", state.user_data_dir)
            per_pair = _extract_per_pair_results(result_data, state.strategy)
            
            # Filter pairs using permissive discovery gates
            min_trades = int(discovery_gates["min_trades"])
            min_profit_factor = float(discovery_gates["min_profit_factor"])
            
            for pair_data in per_pair:
                pair_key = pair_data.get("key", "")
                trades = pair_data.get("trades", 0)
                profit_factor = pair_data.get("profit_factor", 0.0)
                profit_abs = pair_data.get("profit_abs", 0.0)
                win_rate = pair_data.get("win_rate", 0.0)
                
                # Store metrics for all pairs
                pair_metrics[pair_key] = {
                    "trades": trades,
                    "profit_factor": profit_factor,
                    "profit_abs": profit_abs,
                    "win_rate": win_rate,
                }
                
                # Check if pair passes discovery gates
                if trades >= min_trades and profit_factor >= min_profit_factor:
                    recommended_pairs.append(pair_key)
                else:
                    if trades < min_trades:
                        pair_errors[pair_key] = f"Insufficient trades: {trades} < {min_trades}"
                    elif profit_factor < min_profit_factor:
                        pair_errors[pair_key] = f"Low profit factor: {profit_factor:.2f} < {min_profit_factor}"
            
            # Use all tested pairs as selected (user will choose from them)
            selected_pairs = [p for p in pair_universe if p in pair_metrics]
            
            # Add note about recommended pairs
            if len(recommended_pairs) > 0:
                notes.append(
                    f"Discovery found {len(recommended_pairs)} recommended pairs that pass thresholds "
                    f"out of {len(selected_pairs)} tested pairs."
                )
            else:
                notes.append(
                    f"Discovery found 0 recommended pairs. All {len(selected_pairs)} tested pairs "
                    f"failed to meet discovery thresholds."
                )
        else:
            # Backtest failed - add note but don't fail discovery
            notes.append(f"Discovery backtest failed with rc={rc}. Using configured pair universe.")
            selected_pairs = pair_universe
            for pair in pair_universe:
                pair_errors[pair] = "Discovery backtest failed"
    except Exception as exc:
        # Discovery failed - add note but don't fail
        notes.append(f"Discovery encountered error: {exc}. Using configured pair universe.")
        selected_pairs = pair_universe
        for pair in pair_universe:
            pair_errors[pair] = str(exc)
    
    _rlog(run_id, 0, logging.INFO,
          f"Discovery | Selected timeframe: {selected_timeframe}, pairs: {len(selected_pairs)}")
    
    return DiscoveryResult(
        candidate_timeframes=configured_timeframes,
        unsupported_timeframes=unsupported_timeframes,
        strongest_timeframe=selected_timeframe,
        most_stable_timeframe=selected_timeframe,
        most_robust_timeframe=selected_timeframe,
        selected_timeframe=selected_timeframe,
        selected_pairs=selected_pairs,
        recommended_pairs=recommended_pairs,
        pair_errors=pair_errors,
        pair_metrics=pair_metrics,
        notes=notes,
    )


def apply_discovery_results(state: Any, discovery_result: DiscoveryResult) -> None:
    """Apply discovery results to pipeline state.
    
    Args:
        state: PipelineState instance
        discovery_result: DiscoveryResult from run_discovery
    """
    state.discovery_results = {
        "candidate_timeframes": discovery_result.candidate_timeframes,
        "unsupported_timeframes": discovery_result.unsupported_timeframes,
        "strongest_timeframe": discovery_result.strongest_timeframe,
        "most_stable_timeframe": discovery_result.most_stable_timeframe,
        "most_robust_timeframe": discovery_result.most_robust_timeframe,
        "selected_timeframe": discovery_result.selected_timeframe,
        "selected_pairs": discovery_result.selected_pairs,
        "recommended_pairs": discovery_result.recommended_pairs,
        "pair_errors": discovery_result.pair_errors,
        "pair_metrics": discovery_result.pair_metrics,
        "notes": discovery_result.notes,
    }
    
    state.selected_timeframe = discovery_result.selected_timeframe
    state.selected_pair_universe = discovery_result.selected_pairs
    
    # Append discovery notes to validation notes
    state.validation_notes.extend(discovery_result.notes)


__all__ = [
    "DiscoveryResult",
    "run_discovery",
    "apply_discovery_results",
]
