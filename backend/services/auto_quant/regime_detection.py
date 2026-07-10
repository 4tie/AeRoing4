"""Market regime detection using Hidden Markov Models.

This module implements a Gaussian HMM classifier that identifies market regimes
(Bull, Choppy, High-Vol Trend, Crisis) based on technical indicators and
statistical features. The model is trained on historical data and provides
posterior probabilities for each regime.
"""

from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from hmmlearn import hmm

from .regime_features import extract_regime_features, get_feature_columns, normalize_features_percentile

logger = logging.getLogger(__name__)


# Regime definitions
REGIME_BULL = "bull"
REGIME_CHOPPY = "choppy"
REGIME_HIGH_VOL_TREND = "high_vol_trend"
REGIME_CRISIS = "crisis"

REGIME_LABELS = [REGIME_BULL, REGIME_CHOPPY, REGIME_HIGH_VOL_TREND, REGIME_CRISIS]
N_REGIMES = len(REGIME_LABELS)


@dataclass
class RegimeDetectionResult:
    """Result of regime detection for a single time point."""
    
    regime: str
    probabilities: dict[str, float]
    confidence: float
    features: dict[str, float]
    timestamp: str
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "regime": self.regime,
            "probabilities": self.probabilities,
            "confidence": self.confidence,
            "features": self.features,
            "timestamp": self.timestamp,
        }


class RegimeDetector:
    """HMM-based regime detector with training and inference capabilities."""
    
    def __init__(
        self,
        n_components: int = N_REGIMES,
        covariance_type: str = "full",
        n_iter: int = 100,
        random_state: int = 42,
    ):
        """Initialize regime detector.
        
        Args:
            n_components: Number of hidden states (regimes)
            covariance_type: Covariance type for HMM ('full', 'diag', 'spherical', 'tied')
            n_iter: Maximum number of EM iterations
            random_state: Random seed for reproducibility
        """
        self.n_components = n_components
        self.covariance_type = covariance_type
        self.n_iter = n_iter
        self.random_state = random_state
        
        self.model: hmm.GaussianHMM | None = None
        self.feature_columns: list[str] = get_feature_columns()
        self.regime_mapping: dict[int, str] = {}
        self.is_trained = False
        
        # Anti-flicker buffer
        self.regime_history: list[str] = []
        self.anti_flicker_threshold = 3  # Require 3 consecutive bars for regime change
        
    def train(
        self,
        df: pd.DataFrame,
        feature_columns: list[str] | None = None,
    ) -> None:
        """Train HMM model on historical data.
        
        Args:
            df: DataFrame with OHLCV data
            feature_columns: List of feature columns to use (default: all)
        """
        logger.info("Training regime detector on %d rows", len(df))
        
        if feature_columns is None:
            feature_columns = self.feature_columns
        
        # Extract features
        df_features = extract_regime_features(df)
        
        # Normalize features
        df_norm = normalize_features_percentile(df_features, feature_columns=feature_columns)
        
        # Get normalized feature columns
        norm_columns = [f'{col}_norm' for col in feature_columns]
        
        # Prepare training data (drop NaN)
        train_data = df_norm[norm_columns].dropna()
        
        if len(train_data) < 1000:
            raise ValueError(f"Insufficient training data: {len(train_data)} rows (minimum 1000)")
        
        # Convert to numpy array
        X = train_data.values
        
        # Initialize HMM
        self.model = hmm.GaussianHMM(
            n_components=self.n_components,
            covariance_type=self.covariance_type,
            n_iter=self.n_iter,
            random_state=self.random_state,
            verbose=True,
        )
        
        # Train model
        logger.info("Starting HMM training with %d features", X.shape[1])
        self.model.fit(X)
        logger.info("HMM training completed. Converged: %s", self.model.monitor_.converged)
        
        # Map hidden states to regime labels based on emission characteristics
        self._map_states_to_regimes(train_data, norm_columns)
        
        self.is_trained = True
        logger.info("Regime detector trained successfully")
    
    def _map_states_to_regimes(
        self,
        df: pd.DataFrame,
        norm_columns: list[str],
    ) -> None:
        """Map HMM hidden states to regime labels based on emission characteristics.
        
        This analyzes the mean feature values for each state and assigns
        regime labels based on typical characteristics:
        - Bull: High trend, low volatility, positive momentum
        - Choppy: Low trend, low volatility, range-bound
        - High-Vol Trend: High trend, high volatility
        - Crisis: Negative trend, high volatility
        """
        # Get state assignments for training data
        X = df[norm_columns].values
        states = self.model.predict(X)
        
        # Calculate mean feature values per state
        state_means = {}
        for state in range(self.n_components):
            state_mask = states == state
            state_features = X[state_mask]
            state_means[state] = np.mean(state_features, axis=0)
        
        # Analyze characteristics of each state
        state_characteristics = {}
        for state, means in state_means.items():
            # Index mapping (simplified - in production use actual column indices)
            trend_idx = 0  # sma_short_norm
            vol_idx = 12   # atr_norm
            mom_idx = 19   # rsi_norm
            
            state_characteristics[state] = {
                "trend": means[trend_idx],
                "volatility": means[vol_idx],
                "momentum": means[mom_idx],
            }
        
        # Assign regime labels based on characteristics
        # Sort states by trend strength
        sorted_by_trend = sorted(
            state_characteristics.items(),
            key=lambda x: x[1]["trend"],
            reverse=True
        )
        
        # Sort states by volatility
        sorted_by_vol = sorted(
            state_characteristics.items(),
            key=lambda x: x[1]["volatility"],
            reverse=True
        )
        
        # Heuristic mapping (can be refined with manual labeling)
        # Highest trend + moderate vol = Bull
        # Lowest trend + low vol = Choppy
        # High trend + high vol = High-Vol Trend
        # Lowest trend + high vol = Crisis
        
        assigned = set()
        
        # Find Bull (highest trend, not highest volatility)
        for state, chars in sorted_by_trend:
            if state not in assigned and chars["volatility"] < 0.7:
                self.regime_mapping[state] = REGIME_BULL
                assigned.add(state)
                break
        
        # Find Crisis (lowest trend, highest volatility)
        for state, chars in reversed(sorted_by_trend):
            if state not in assigned and chars["volatility"] > 0.7:
                self.regime_mapping[state] = REGIME_CRISIS
                assigned.add(state)
                break
        
        # Find High-Vol Trend (high trend, high volatility)
        for state, chars in sorted_by_trend:
            if state not in assigned and chars["volatility"] > 0.6:
                self.regime_mapping[state] = REGIME_HIGH_VOL_TREND
                assigned.add(state)
                break
        
        # Remaining state is Choppy
        for state in range(self.n_components):
            if state not in assigned:
                self.regime_mapping[state] = REGIME_CHOPPY
                assigned.add(state)
        
        logger.info("State to regime mapping: %s", self.regime_mapping)
    
    def predict(
        self,
        df: pd.DataFrame,
        feature_columns: list[str] | None = None,
    ) -> RegimeDetectionResult:
        """Predict regime for the most recent data point.
        
        Args:
            df: DataFrame with OHLCV data (at least one row)
            feature_columns: List of feature columns to use (default: all)
            
        Returns:
            RegimeDetectionResult with regime, probabilities, and confidence
        """
        if not self.is_trained or self.model is None:
            raise RuntimeError("Model not trained. Call train() first.")
        
        if feature_columns is None:
            feature_columns = self.feature_columns
        
        # Extract features
        df_features = extract_regime_features(df)
        
        # Normalize features
        df_norm = normalize_features_percentile(df_features, feature_columns=feature_columns)
        
        # Get normalized feature columns
        norm_columns = [f'{col}_norm' for col in feature_columns]
        
        # Get most recent data point
        latest = df_norm[norm_columns].iloc[-1:].values
        
        # Predict state and get posterior probabilities
        state = self.model.predict(latest)[0]
        posteriors = self.model.predict_proba(latest)[0]
        
        # Map state to regime
        regime = self.regime_mapping.get(state, REGIME_CHOPPY)
        
        # Build probabilities dict
        probabilities = {
            REGIME_LABELS[i]: float(posteriors[i])
            for i in range(len(REGIME_LABELS))
        }
        
        # Calculate confidence (max probability)
        confidence = float(np.max(posteriors))
        
        # Get feature values
        features = df_features.iloc[-1].to_dict()
        
        # Apply anti-flicker
        regime = self._apply_anti_flicker(regime)
        
        # Create result
        timestamp = datetime.now(timezone.utc).isoformat()
        result = RegimeDetectionResult(
            regime=regime,
            probabilities=probabilities,
            confidence=confidence,
            features=features,
            timestamp=timestamp,
        )
        
        return result
    
    def _apply_anti_flicker(self, new_regime: str) -> str:
        """Apply anti-flicker mechanism to stabilize regime labels.
        
        Requires N consecutive bars of the same regime before switching.
        """
        self.regime_history.append(new_regime)
        
        # Keep only recent history
        if len(self.regime_history) > 10:
            self.regime_history = self.regime_history[-10:]
        
        # Check if we have enough history
        if len(self.regime_history) < self.anti_flicker_threshold:
            # Not enough history, return most common in history
            from collections import Counter
            return Counter(self.regime_history).most_common(1)[0][0]
        
        # Check last N entries
        recent = self.regime_history[-self.anti_flicker_threshold:]
        
        # If all recent entries are the same, allow the switch
        if all(r == recent[0] for r in recent):
            return recent[0]
        
        # Otherwise, return the previous regime
        return self.regime_history[-2] if len(self.regime_history) >= 2 else new_regime
    
    def predict_sequence(
        self,
        df: pd.DataFrame,
        feature_columns: list[str] | None = None,
    ) -> list[RegimeDetectionResult]:
        """Predict regime for a sequence of data points.
        
        Args:
            df: DataFrame with OHLCV data
            feature_columns: List of feature columns to use (default: all)
            
        Returns:
            List of RegimeDetectionResult for each row
        """
        if not self.is_trained or self.model is None:
            raise RuntimeError("Model not trained. Call train() first.")
        
        if feature_columns is None:
            feature_columns = self.feature_columns
        
        # Extract features
        df_features = extract_regime_features(df)
        
        # Normalize features
        df_norm = normalize_features_percentile(df_features, feature_columns=feature_columns)
        
        # Get normalized feature columns
        norm_columns = [f'{col}_norm' for col in feature_columns]
        
        # Get data
        X = df_norm[norm_columns].values
        
        # Predict states and get posteriors
        states = self.model.predict(X)
        posteriors = self.model.predict_proba(X)
        
        # Build results
        results = []
        for i in range(len(df)):
            state = states[i]
            regime = self.regime_mapping.get(state, REGIME_CHOPPY)
            
            probabilities = {
                REGIME_LABELS[j]: float(posteriors[i][j])
                for j in range(len(REGIME_LABELS))
            }
            
            confidence = float(np.max(posteriors[i]))
            features = df_features.iloc[i].to_dict()
            
            # Reset anti-flicker for sequence prediction
            if i == 0:
                self.regime_history = []
            
            regime = self._apply_anti_flicker(regime)
            
            result = RegimeDetectionResult(
                regime=regime,
                probabilities=probabilities,
                confidence=confidence,
                features=features,
                timestamp=df.index[i] if hasattr(df.index[i], 'isoformat') else str(df.index[i]),
            )
            results.append(result)
        
        return results
    
    def save_model(self, path: Path) -> None:
        """Save trained model to disk.
        
        Args:
            path: Path to save the model
        """
        if not self.is_trained or self.model is None:
            raise RuntimeError("Model not trained. Cannot save.")
        
        path.parent.mkdir(parents=True, exist_ok=True)
        
        model_data = {
            "model": self.model,
            "regime_mapping": self.regime_mapping,
            "feature_columns": self.feature_columns,
            "n_components": self.n_components,
            "covariance_type": self.covariance_type,
            "n_iter": self.n_iter,
            "random_state": self.random_state,
        }
        
        with open(path, "wb") as f:
            pickle.dump(model_data, f)
        
        logger.info("Model saved to %s", path)
    
    def load_model(self, path: Path) -> None:
        """Load trained model from disk.
        
        Args:
            path: Path to load the model from
        """
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")
        
        with open(path, "rb") as f:
            model_data = pickle.load(f)
        
        self.model = model_data["model"]
        self.regime_mapping = model_data["regime_mapping"]
        self.feature_columns = model_data["feature_columns"]
        self.n_components = model_data["n_components"]
        self.covariance_type = model_data["covariance_type"]
        self.n_iter = model_data["n_iter"]
        self.random_state = model_data["random_state"]
        
        self.is_trained = True
        logger.info("Model loaded from %s", path)


def create_regime_detector(
    n_components: int = N_REGIMES,
    covariance_type: str = "full",
    n_iter: int = 100,
    random_state: int = 42,
) -> RegimeDetector:
    """Factory function to create a RegimeDetector instance.
    
    Args:
        n_components: Number of hidden states (regimes)
        covariance_type: Covariance type for HMM
        n_iter: Maximum number of EM iterations
        random_state: Random seed for reproducibility
        
    Returns:
        Configured RegimeDetector instance
    """
    return RegimeDetector(
        n_components=n_components,
        covariance_type=covariance_type,
        n_iter=n_iter,
        random_state=random_state,
    )


__all__ = [
    "REGIME_BULL",
    "REGIME_CHOPPY",
    "REGIME_HIGH_VOL_TREND",
    "REGIME_CRISIS",
    "REGIME_LABELS",
    "N_REGIMES",
    "RegimeDetectionResult",
    "RegimeDetector",
    "create_regime_detector",
]
