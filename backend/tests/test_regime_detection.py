"""Tests for regime detection modules."""

import pytest
import numpy as np
import pandas as pd
from pathlib import Path
import tempfile
import pickle

from backend.services.auto_quant.regime_features import (
    extract_regime_features,
    normalize_features_percentile,
    get_feature_columns,
    RegimeFeatures,
)
from backend.services.auto_quant.regime_detection import (
    RegimeDetector,
    RegimeDetectionResult,
    create_regime_detector,
    REGIME_BULL,
    REGIME_CHOPPY,
    REGIME_HIGH_VOL_TREND,
    REGIME_CRISIS,
    REGIME_LABELS,
    N_REGIMES,
)
from backend.services.auto_quant.regime_adapter import (
    RegimeAdapter,
    RegimeConfig,
    DEFAULT_REGIME_CONFIGS,
    create_regime_adapter,
    get_regime_specific_ai_prompt,
)


@pytest.fixture
def sample_ohlcv_data():
    """Create sample OHLCV data for testing."""
    np.random.seed(42)
    n_points = 500
    dates = pd.date_range(end=pd.Timestamp.now(), periods=n_points, freq='D')
    
    # Generate synthetic OHLCV data with some trend
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
    
    return df


class TestRegimeFeatures:
    """Tests for regime feature extraction."""
    
    def test_extract_regime_features(self, sample_ohlcv_data):
        """Test feature extraction from OHLCV data."""
        df_features = extract_regime_features(sample_ohlcv_data)
        
        # Check that features were extracted
        assert len(df_features) == len(sample_ohlcv_data)
        
        # Check for expected feature columns
        feature_cols = get_feature_columns()
        for col in feature_cols:
            assert col in df_features.columns
        
        # Check that OHLCV columns are preserved
        for col in ['open', 'high', 'low', 'close', 'volume']:
            assert col in df_features.columns
    
    def test_extract_regime_features_missing_columns(self):
        """Test feature extraction with missing required columns."""
        df = pd.DataFrame({'close': [1, 2, 3]})
        
        with pytest.raises(ValueError, match="Missing required columns"):
            extract_regime_features(df)
    
    def test_normalize_features_percentile(self, sample_ohlcv_data):
        """Test percentile normalization of features."""
        df_features = extract_regime_features(sample_ohlcv_data)
        df_norm = normalize_features_percentile(df_features)
        
        # Check that normalized columns exist
        feature_cols = get_feature_columns()
        for col in feature_cols:
            norm_col = f'{col}_norm'
            assert norm_col in df_norm.columns
            # Check values are in [0, 1] range
            assert df_norm[norm_col].min() >= 0
            assert df_norm[norm_col].max() <= 1
    
    def test_get_feature_columns(self):
        """Test feature column list."""
        cols = get_feature_columns()
        assert isinstance(cols, list)
        assert len(cols) > 0
        assert 'sma_short' in cols
        assert 'rsi' in cols
        assert 'atr' in cols


class TestRegimeDetection:
    """Tests for regime detection using HMM."""
    
    def test_create_regime_detector(self):
        """Test regime detector creation."""
        detector = create_regime_detector()
        
        assert detector.n_components == N_REGIMES
        assert detector.covariance_type == "full"
        assert detector.n_iter == 100
        assert not detector.is_trained
        assert detector.model is None
    
    def test_regime_detector_train(self, sample_ohlcv_data):
        """Test training regime detector."""
        detector = create_regime_detector(n_components=4, n_iter=10)
        
        # Train with reduced iterations for testing
        detector.train(sample_ohlcv_data, n_iter=10)
        
        assert detector.is_trained
        assert detector.model is not None
        assert len(detector.regime_mapping) == 4
    
    def test_regime_detector_train_insufficient_data(self):
        """Test training with insufficient data."""
        detector = create_regime_detector()
        
        # Create small dataset
        df = pd.DataFrame({
            'open': [1, 2, 3],
            'high': [2, 3, 4],
            'low': [0.5, 1.5, 2.5],
            'close': [1.5, 2.5, 3.5],
            'volume': [100, 200, 300],
        })
        
        with pytest.raises(ValueError, match="Insufficient training data"):
            detector.train(df)
    
    def test_regime_detector_predict(self, sample_ohlcv_data):
        """Test regime prediction."""
        detector = create_regime_detector(n_components=4, n_iter=10)
        detector.train(sample_ohlcv_data, n_iter=10)
        
        result = detector.predict(sample_ohlcv_data)
        
        assert isinstance(result, RegimeDetectionResult)
        assert result.regime in REGIME_LABELS
        assert isinstance(result.probabilities, dict)
        assert len(result.probabilities) == 4
        assert 0 <= result.confidence <= 1
        assert isinstance(result.features, dict)
    
    def test_regime_detector_predict_untrained(self, sample_ohlcv_data):
        """Test prediction without training."""
        detector = create_regime_detector()
        
        with pytest.raises(RuntimeError, match="Model not trained"):
            detector.predict(sample_ohlcv_data)
    
    def test_regime_detector_predict_sequence(self, sample_ohlcv_data):
        """Test sequence prediction."""
        detector = create_regime_detector(n_components=4, n_iter=10)
        detector.train(sample_ohlcv_data, n_iter=10)
        
        # Use smaller dataset for sequence prediction
        df_small = sample_ohlcv_data.iloc[:100]
        results = detector.predict_sequence(df_small)
        
        assert len(results) == len(df_small)
        for result in results:
            assert isinstance(result, RegimeDetectionResult)
            assert result.regime in REGIME_LABELS
    
    def test_regime_detector_save_load(self, sample_ohlcv_data):
        """Test saving and loading model."""
        detector = create_regime_detector(n_components=4, n_iter=10)
        detector.train(sample_ohlcv_data, n_iter=10)
        
        # Save model
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "test_model.pkl"
            detector.save_model(model_path)
            
            assert model_path.exists()
            
            # Load model
            detector2 = create_regime_detector()
            detector2.load_model(model_path)
            
            assert detector2.is_trained
            assert detector2.model is not None
            assert detector2.regime_mapping == detector.regime_mapping
    
    def test_regime_detector_load_nonexistent(self):
        """Test loading non-existent model."""
        detector = create_regime_detector()
        
        with pytest.raises(FileNotFoundError):
            detector.load_model(Path("/nonexistent/path/model.pkl"))
    
    def test_anti_flicker_mechanism(self, sample_ohlcv_data):
        """Test anti-flicker mechanism for regime stability."""
        detector = create_regime_detector(n_components=4, n_iter=10)
        detector.train(sample_ohlcv_data, n_iter=10)
        
        # Predict multiple times
        results = []
        for i in range(5):
            result = detector.predict(sample_ohlcv_data)
            results.append(result.regime)
        
        # Check that anti-flicker is working (should not flicker wildly)
        # With anti-flicker threshold of 3, we expect some stability
        # This is a basic check - in practice, you'd want more sophisticated testing
        assert len(set(results)) <= 3  # Should not have all different regimes


class TestRegimeAdapter:
    """Tests for regime-aware parameter adaptation."""
    
    def test_create_regime_adapter(self):
        """Test regime adapter creation."""
        adapter = create_regime_adapter()
        
        assert adapter.use_soft_allocation is True
        assert len(adapter.regime_configs) == 4
    
    def test_get_config(self):
        """Test getting regime configuration."""
        adapter = create_regime_adapter()
        
        config = adapter.get_config(REGIME_BULL)
        
        assert isinstance(config, RegimeConfig)
        assert config.regime == REGIME_BULL
        assert config.hyperopt_loss == "OnlyProfitHyperOptLoss"
        assert "buy" in config.hyperopt_spaces
    
    def test_get_config_invalid_regime(self):
        """Test getting configuration for invalid regime."""
        adapter = create_regime_adapter()
        
        # Should fallback to choppy for invalid regime
        config = adapter.get_config("invalid_regime")
        assert config.regime == REGIME_CHOPPY
    
    def test_adapt_parameters_hard_switch(self):
        """Test hard switching regime adaptation."""
        adapter = create_regime_adapter(use_soft_allocation=False)
        
        params = adapter.adapt_parameters(REGIME_BULL)
        
        assert params["hyperopt_loss"] == "OnlyProfitHyperOptLoss"
        assert "buy" in params["hyperopt_spaces"]
        assert params["allocation_method"] == "hard_switch"
        assert "param_overrides" in params
    
    def test_adapt_parameters_soft_allocation(self):
        """Test soft allocation regime adaptation."""
        adapter = create_regime_adapter(use_soft_allocation=True)
        
        probabilities = {
            REGIME_BULL: 0.6,
            REGIME_CHOPPY: 0.2,
            REGIME_HIGH_VOL_TREND: 0.1,
            REGIME_CRISIS: 0.1,
        }
        
        params = adapter.adapt_parameters(REGIME_BULL, probabilities)
        
        assert params["allocation_method"] == "soft_allocation"
        assert "regime_weights" in params
        assert params["regime_weights"][REGIME_BULL] == 0.6
    
    def test_get_regime_description(self):
        """Test getting regime description."""
        adapter = create_regime_adapter()
        
        description = adapter.get_regime_description(REGIME_BULL)
        
        assert isinstance(description, str)
        assert len(description) > 0
        assert "bull" in description.lower()
    
    def test_update_config(self):
        """Test updating regime configuration."""
        adapter = create_regime_adapter()
        
        new_config = RegimeConfig(
            regime=REGIME_BULL,
            hyperopt_loss="SharpeHyperOptLoss",
            hyperopt_spaces=["sell"],
            param_overrides={},
            description="Test config",
        )
        
        adapter.update_config(REGIME_BULL, new_config)
        
        updated = adapter.get_config(REGIME_BULL)
        assert updated.hyperopt_loss == "SharpeHyperOptLoss"
        assert updated.hyperopt_spaces == ["sell"]
    
    def test_get_all_configs(self):
        """Test getting all regime configurations."""
        adapter = create_regime_adapter()
        
        configs = adapter.get_all_configs()
        
        assert isinstance(configs, dict)
        assert len(configs) == 4
        for regime in REGIME_LABELS:
            assert regime in configs


class TestRegimeIntegration:
    """Integration tests for regime detection workflow."""
    
    def test_full_workflow(self, sample_ohlcv_data):
        """Test complete workflow: train, predict, adapt."""
        # Train detector
        detector = create_regime_detector(n_components=4, n_iter=10)
        detector.train(sample_ohlcv_data, n_iter=10)
        
        # Predict regime
        result = detector.predict(sample_ohlcv_data)
        
        # Adapt parameters
        adapter = create_regime_adapter()
        params = adapter.adapt_parameters(result.regime, result.probabilities)
        
        assert result.regime in REGIME_LABELS
        assert params["hyperopt_loss"] in [
            "OnlyProfitHyperOptLoss",
            "SharpeHyperOptLoss",
            "ProfitDrawDownHyperOptLoss",
            "CalmarHyperOptLoss",
        ]
    
    def test_regime_specific_ai_prompt(self):
        """Test generation of regime-specific AI prompt."""
        prompt = get_regime_specific_ai_prompt(
            regime=REGIME_BULL,
            regime_probabilities={REGIME_BULL: 0.7, REGIME_CHOPPY: 0.3},
        )
        
        assert isinstance(prompt, str)
        assert "BULL" in prompt
        assert "OnlyProfitHyperOptLoss" in prompt
        assert "regime" in prompt.lower()
    
    def test_default_regime_configs(self):
        """Test default regime configurations."""
        assert len(DEFAULT_REGIME_CONFIGS) == 4
        
        for regime in REGIME_LABELS:
            assert regime in DEFAULT_REGIME_CONFIGS
            config = DEFAULT_REGIME_CONFIGS[regime]
            assert isinstance(config, RegimeConfig)
            assert config.regime == regime


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
