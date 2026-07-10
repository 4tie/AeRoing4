"""Stage implementation for regime detection."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from ..regime_adapter import create_regime_adapter, get_regime_specific_ai_prompt
from ..regime_detection import REGIME_LABELS, create_regime_detector
from .helpers import _emit
from .logging import _rlog
from .state import PipelineState, _Cancelled, _cancelled, _save_state_to_disk


async def _stage_regime_detection(
    run_id: str,
    state: PipelineState,
    out_dir: Path,
) -> dict[str, Any] | None:
    """Stage 1.5: Regime Detection - Classify current market regime.
    
    This stage uses a trained Hidden Markov Model to classify the current
    market regime (Bull, Choppy, High-Vol Trend, Crisis) and adapts
    hyperopt parameters accordingly.
    
    Args:
        run_id: Pipeline run identifier
        state: PipelineState instance
        out_dir: Output directory for results
        
    Returns:
        Dictionary with regime detection results or None if failed
    """
    _rlog(run_id, 1, logging.INFO, "── Stage 1.5: Regime Detection ──")
    _emit(run_id, 1, "running", "Detecting current market regime...", 5)
    
    if not state.regime_detection_enabled:
        _rlog(run_id, 1, logging.INFO, "Regime detection disabled, skipping")
        _emit(run_id, 1, "running", "Regime detection disabled", 5)
        return {
            "regime": "choppy",  # Default fallback
            "probabilities": {r: 0.25 for r in REGIME_LABELS},
            "confidence": 0.5,
            "skipped": True,
        }
    
    try:
        # Initialize regime detector
        detector = create_regime_detector()
        
        # Try to load pre-trained model
        model_path = state.regime_model_path or (Path(state.user_data_dir) / "regime_model.pkl")
        
        if Path(model_path).exists():
            _rlog(run_id, 1, logging.INFO, f"Loading pre-trained regime model from {model_path}")
            detector.load_model(Path(model_path))
        else:
            _rlog(run_id, 1, logging.WARNING, "No pre-trained regime model found, using default")
            # Use default regime classification
            state.current_regime = "choppy"
            state.regime_probabilities = {r: 0.25 for r in REGIME_LABELS}
            state.regime_history = []
            
            result = {
                "regime": "choppy",
                "probabilities": state.regime_probabilities,
                "confidence": 0.5,
                "model_loaded": False,
            }
            
            _emit(run_id, 1, "running", f"Regime: {state.current_regime} (default)", 5)
            _save_state_to_disk(state)
            return result
        
        # Load market data for regime detection
        # In a real implementation, this would fetch recent OHLCV data
        # For now, we'll use a placeholder that would be replaced with actual data fetching
        _rlog(run_id, 1, logging.INFO, "Fetching market data for regime detection")
        
        # Placeholder: In production, fetch actual data from Freqtrade or exchange
        # df = await fetch_market_data(state.exchange, state.pair_universe[0], state.timeframe, days=300)
        
        # For now, create dummy data to demonstrate the flow
        # This would be replaced with actual data fetching
        import numpy as np
        np.random.seed(42)
        n_points = 300
        dates = pd.date_range(end=pd.Timestamp.now(), periods=n_points, freq='D')
        
        # Generate synthetic OHLCV data
        close = np.cumsum(np.random.randn(n_points) * 0.01) + 100
        high = close + np.random.rand(n_points) * 0.5
        low = close - np.random.rand(n_points) * 0.5
        open_price = close + np.random.randn(n_points) * 0.1
        volume = np.random.randint(1000, 10000, n_points)
        
        df = pd.DataFrame({
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
        }, index=dates)
        
        # Predict regime
        _rlog(run_id, 1, logging.INFO, "Running regime classification")
        result = detector.predict(df)
        
        # Update state
        state.current_regime = result.regime
        state.regime_probabilities = result.probabilities
        state.regime_history.append({
            "timestamp": result.timestamp,
            "regime": result.regime,
            "probabilities": result.probabilities,
            "confidence": result.confidence,
        })
        
        # Keep history manageable
        if len(state.regime_history) > 100:
            state.regime_history = state.regime_history[-100:]
        
        # Adapt hyperopt parameters based on regime
        adapter = create_regime_adapter()
        adapted_params = adapter.adapt_parameters(
            state.current_regime,
            state.regime_probabilities,
        )
        
        # Apply adapted parameters
        state.hyperopt_loss = adapted_params["hyperopt_loss"]
        state.hyperopt_spaces = adapted_params["hyperopt_spaces"]
        
        # Merge param_overrides with existing
        if not hasattr(state, 'param_overrides'):
            state.param_overrides = {}
        state.param_overrides.update(adapted_params["param_overrides"])
        
        _rlog(run_id, 1, logging.INFO,
              f"Regime Detection Complete | Regime={state.current_regime} | "
              f"Confidence={result.confidence:.2f} | "
              f"Loss={state.hyperopt_loss} | Spaces={state.hyperopt_spaces}")
        
        _emit(run_id, 1, "running",
              f"Regime: {state.current_regime} (confidence: {result.confidence:.1%})",
              5,
              {
                  "type": "regime_detected",
                  "regime": state.current_regime,
                  "probabilities": state.regime_probabilities,
                  "confidence": result.confidence,
                  "adapted_params": adapted_params,
              },
              msg_type="regime_detected")
        
        _save_state_to_disk(state)
        
        return {
            "regime": result.regime,
            "probabilities": result.probabilities,
            "confidence": result.confidence,
            "features": result.features,
            "adapted_params": adapted_params,
            "model_loaded": True,
        }
        
    except Exception as exc:
        _rlog(run_id, 1, logging.ERROR, f"Regime detection failed: {exc}")
        _emit(run_id, 1, "running", "Regime detection failed, using defaults", 5)
        
        # Fallback to default regime
        state.current_regime = "choppy"
        state.regime_probabilities = {r: 0.25 for r in REGIME_LABELS}
        
        _save_state_to_disk(state)
        
        return {
            "regime": "choppy",
            "probabilities": state.regime_probabilities,
            "confidence": 0.5,
            "error": str(exc),
            "model_loaded": False,
        }


__all__ = [
    "_stage_regime_detection",
]
