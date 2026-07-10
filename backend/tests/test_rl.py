"""Tests for reinforcement learning modules."""

import pytest
import numpy as np
import pandas as pd
from pathlib import Path

from backend.services.auto_quant.rl.rl_environment import (
    TradingConfig,
    TradingEnv,
    create_trading_env,
    create_vectorized_env,
)
from backend.services.auto_quant.rl.rl_agents import (
    AgentConfig,
    AgentFactory,
    MultiAgentEnsemble,
    create_agent,
    create_ensemble,
)
from backend.services.auto_quant.rl.rl_training import (
    TrainingConfig,
    TrainingResult,
    RLTrainer,
    train_rl_agent,
)
from backend.services.auto_quant.rl.rl_inference import (
    InferenceResult,
    RLInference,
    load_rl_agent,
    predict_with_model,
)


@pytest.fixture
def sample_ohlcv_data():
    """Create sample OHLCV data for testing."""
    np.random.seed(42)
    n_points = 1000
    dates = pd.date_range(end=pd.Timestamp.now(), periods=n_points, freq='H')
    
    df = pd.DataFrame({
        'open': np.cumsum(np.random.randn(n_points) * 0.01) + 100,
        'high': np.cumsum(np.random.randn(n_points) * 0.01) + 100 + np.random.rand(n_points) * 0.5,
        'low': np.cumsum(np.random.randn(n_points) * 0.01) + 100 - np.random.rand(n_points) * 0.5,
        'close': np.cumsum(np.random.randn(n_points) * 0.01) + 100,
        'volume': np.random.randint(1000, 10000, n_points),
    }, index=dates)
    
    return df


class TestTradingEnv:
    """Tests for trading environment."""
    
    def test_create_trading_env(self, sample_ohlcv_data):
        """Test creation of trading environment."""
        config = TradingConfig()
        env = create_trading_env(sample_ohlcv_data, config)
        
        assert isinstance(env, TradingEnv)
        assert env.config.initial_balance == 10000.0
        assert env.config.lookback_window == 50
    
    def test_trading_env_reset(self, sample_ohlcv_data):
        """Test environment reset."""
        env = create_trading_env(sample_ohlcv_data)
        obs, info = env.reset()
        
        assert isinstance(obs, np.ndarray)
        assert isinstance(info, dict)
        assert "balance" in info
        assert "position" in info
    
    def test_trading_env_step(self, sample_ohlcv_data):
        """Test environment step."""
        env = create_trading_env(sample_ohlcv_data)
        obs, info = env.reset()
        
        action = np.array([0.5, 0.0, 0.0])  # Position size, entry, exit
        obs, reward, terminated, truncated, info = env.step(action)
        
        assert isinstance(obs, np.ndarray)
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)
    
    def test_trading_env_observation_space(self, sample_ohlcv_data):
        """Test observation space."""
        env = create_trading_env(sample_ohlcv_data)
        
        assert env.observation_space.shape[0] > 0
        assert env.action_space.shape[0] == 3
    
    def test_create_vectorized_env(self, sample_ohlcv_data):
        """Test vectorized environment creation."""
        env = create_vectorized_env(sample_ohlcv_data, n_envs=2)
        
        assert env is not None


class TestAgentFactory:
    """Tests for agent factory."""
    
    def test_agent_config(self):
        """Test agent configuration."""
        config = AgentConfig()
        
        assert config.algorithm == "ppo"
        assert config.learning_rate == 3e-4
        assert config.n_steps == 2048
    
    def test_create_agent_ppo(self, sample_ohlcv_data):
        """Test creating PPO agent."""
        env = create_trading_env(sample_ohlcv_data)
        config = AgentConfig(algorithm="ppo")
        
        try:
            agent = AgentFactory.create_agent("ppo", env, config)
            assert agent is not None
        except ImportError:
            pytest.skip("stable-baselines3 not installed")
    
    def test_create_agent_a2c(self, sample_ohlcv_data):
        """Test creating A2C agent."""
        env = create_trading_env(sample_ohlcv_data)
        config = AgentConfig(algorithm="a2c")
        
        try:
            agent = AgentFactory.create_agent("a2c", env, config)
            assert agent is not None
        except ImportError:
            pytest.skip("stable-baselines3 not installed")
    
    def test_create_agent_invalid(self, sample_ohlcv_data):
        """Test creating agent with invalid algorithm."""
        env = create_trading_env(sample_ohlcv_data)
        config = AgentConfig(algorithm="invalid")
        
        with pytest.raises(ValueError):
            AgentFactory.create_agent("invalid", env, config)


class TestMultiAgentEnsemble:
    """Tests for multi-agent ensemble."""
    
    def test_create_ensemble(self, sample_ohlcv_data):
        """Test creating ensemble."""
        env = create_trading_env(sample_ohlcv_data)
        
        try:
            ensemble = create_ensemble(env, algorithms=["ppo"])
            assert isinstance(ensemble, MultiAgentEnsemble)
        except ImportError:
            pytest.skip("stable-baselines3 not installed")
    
    def test_ensemble_predict(self, sample_ohlcv_data):
        """Test ensemble prediction."""
        env = create_trading_env(sample_ohlcv_data)
        
        try:
            ensemble = create_ensemble(env, algorithms=["ppo"])
            obs, _ = env.reset()
            
            action = ensemble.predict_ensemble(obs)
            
            assert isinstance(action, np.ndarray)
            assert action.shape[0] == 3
        except ImportError:
            pytest.skip("stable-baselines3 not installed")
    
    def test_ensemble_predict_with_confidence(self, sample_ohlcv_data):
        """Test ensemble prediction with confidence."""
        env = create_trading_env(sample_ohlcv_data)
        
        try:
            ensemble = create_ensemble(env, algorithms=["ppo"])
            obs, _ = env.reset()
            
            action, confidence = ensemble.predict_with_confidence(obs)
            
            assert isinstance(action, np.ndarray)
            assert isinstance(confidence, float)
            assert 0 <= confidence <= 1
        except ImportError:
            pytest.skip("stable-baselines3 not installed")


class TestRLTraining:
    """Tests for RL training."""
    
    def test_training_config(self):
        """Test training configuration."""
        config = TrainingConfig()
        
        assert config.total_timesteps == 1000000
        assert config.checkpoint_interval == 100000
        assert config.use_ensemble is True
    
    def test_rl_trainer_init(self):
        """Test RL trainer initialization."""
        config = TrainingConfig()
        trainer = RLTrainer(config)
        
        assert trainer.config.total_timesteps == 1000000
        assert len(trainer.training_history) == 0
    
    def test_rl_trainer_train_short(self, sample_ohlcv_data):
        """Test short RL training run."""
        config = TrainingConfig(total_timesteps=100, use_ensemble=False)
        agent_config = AgentConfig(algorithm="ppo")
        
        try:
            trainer = RLTrainer(config, agent_config)
            result = trainer.train(sample_ohlcv_data)
            
            assert isinstance(result, TrainingResult)
            assert result.total_timesteps == 100
        except ImportError:
            pytest.skip("stable-baselines3 not installed")


class TestRLInference:
    """Tests for RL inference."""
    
    def test_inference_result(self):
        """Test inference result."""
        action = np.array([0.5, 0.0, 0.0])
        result = InferenceResult(
            action=action,
            confidence=0.8,
            position_size=0.5,
            entry_signal=0.0,
            exit_signal=0.0,
        )
        
        assert result.position_size == 0.5
        assert result.confidence == 0.8
        assert result.entry_signal == 0.0
    
    def test_inference_result_to_dict(self):
        """Test inference result to dict conversion."""
        action = np.array([0.5, 0.0, 0.0])
        result = InferenceResult(
            action=action,
            confidence=0.8,
            position_size=0.5,
            entry_signal=0.0,
            exit_signal=0.0,
        )
        
        d = result.to_dict()
        
        assert isinstance(d, dict)
        assert "action" in d
        assert "confidence" in d
        assert "position_size" in d
    
    def test_rl_inference_init(self):
        """Test RL inference initialization."""
        inference = RLInference("model_path", algorithm="ppo")
        
        assert inference.model_path == Path("model_path")
        assert inference.algorithm == "ppo"
        assert inference.use_ensemble is False


class TestRLIntegration:
    """Integration tests for RL workflow."""
    
    def test_full_rl_workflow(self, sample_ohlcv_data):
        """Test complete RL workflow."""
        try:
            # Create environment
            env = create_trading_env(sample_ohlcv_data)
            
            # Create agent
            agent = create_agent("ppo", env, AgentConfig())
            
            # Train briefly
            agent.learn(10)
            
            # Predict
            obs, _ = env.reset()
            action, _ = agent.predict(obs)
            
            assert isinstance(action, np.ndarray)
            assert action.shape[0] == 3
        except ImportError:
            pytest.skip("stable-baselines3 not installed")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
