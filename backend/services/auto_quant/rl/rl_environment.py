"""Trading environment for reinforcement learning agents.

This module implements a Gymnasium-compatible trading environment
for training deep reinforcement learning agents (A2C, PPO, SAC, etc.).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import gymnasium as gym
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class TradingConfig:
    """Configuration for trading environment."""
    
    initial_balance: float = 10000.0
    max_position_size: float = 1.0  # Maximum position as fraction of balance
    transaction_cost: float = 0.001  # 0.1% per trade
    lookback_window: int = 50  # Number of historical candles to include in state
    max_episode_length: int = 1000  # Maximum steps per episode


class TradingEnv(gym.Env):
    """Gymnasium trading environment for RL agents.
    
    State space: Technical indicators + regime features + position state
    Action space: Continuous position sizing + discrete entry/exit signals
    
    Reward function: Risk-adjusted returns with penalties for turnover and drawdown
    """
    
    metadata = {"render_modes": ["human"]}
    
    def __init__(
        self,
        data: pd.DataFrame,
        config: TradingConfig | None = None,
    ):
        """Initialize trading environment.
        
        Args:
            data: DataFrame with OHLCV data and technical indicators
            config: Trading configuration (default: TradingConfig())
        """
        super().__init__()
        
        self.config = config or TradingConfig()
        self.data = data.reset_index(drop=True)
        
        # Validate data
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        missing_cols = [col for col in required_cols if col not in self.data.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns: {missing_cols}")
        
        # Calculate returns
        self.data['returns'] = self.data['close'].pct_change()
        self.data['returns'] = self.data['returns'].fillna(0)
        
        # State space: [lookback_window * features] + [position, balance, unrealized_pnl]
        # Features: close, volume, returns (can be extended with more indicators)
        n_features = 3
        self.observation_space = gym.spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(self.config.lookback_window * n_features + 3,),
            dtype=np.float32,
        )
        
        # Action space: [position_size, entry_signal, exit_signal]
        # position_size: 0-1 (fraction of balance)
        # entry_signal: 0-1 (0=don't enter, 1=enter)
        # exit_signal: 0-1 (0=don't exit, 1=exit)
        self.action_space = gym.spaces.Box(
            low=0.0,
            high=1.0,
            shape=(3,),
            dtype=np.float32,
        )
        
        # Trading state
        self.current_step = 0
        self.balance = self.config.initial_balance
        self.position = 0.0  # Position size in base currency
        self.entry_price = 0.0
        self.unrealized_pnl = 0.0
        self.trade_count = 0
        self.total_reward = 0.0
        self.max_drawdown = 0.0
        self.peak_balance = self.config.initial_balance
        
        # Episode tracking
        self.episode_length = 0
        self.episode_returns = []
        
        logger.info(
            "TradingEnv initialized with %d data points, lookback=%d",
            len(self.data),
            self.config.lookback_window,
        )
    
    def reset(self, seed: int | None = None, options: dict | None = None):
        """Reset environment to initial state.
        
        Args:
            seed: Random seed
            options: Additional options
            
        Returns:
            Tuple of (observation, info)
        """
        super().reset(seed=seed)
        
        # Reset trading state
        self.current_step = self.config.lookback_window
        self.balance = self.config.initial_balance
        self.position = 0.0
        self.entry_price = 0.0
        self.unrealized_pnl = 0.0
        self.trade_count = 0
        self.total_reward = 0.0
        self.max_drawdown = 0.0
        self.peak_balance = self.config.initial_balance
        self.episode_length = 0
        self.episode_returns = []
        
        observation = self._get_observation()
        info = {"balance": self.balance, "position": self.position}
        
        return observation, info
    
    def step(self, action: np.ndarray):
        """Execute one step in the environment.
        
        Args:
            action: Array of [position_size, entry_signal, exit_signal]
            
        Returns:
            Tuple of (observation, reward, terminated, truncated, info)
        """
        # Extract action components
        position_size = action[0]
        entry_signal = action[1]
        exit_signal = action[2]
        
        # Get current price
        current_price = self.data.iloc[self.current_step]['close']
        
        # Calculate previous unrealized PnL
        prev_unrealized_pnl = self.unrealized_pnl
        
        # Execute exit signal
        if exit_signal > 0.5 and self.position > 0:
            # Close position
            pnl = (current_price - self.entry_price) * self.position
            transaction_cost = abs(pnl) * self.config.transaction_cost
            self.balance += pnl - transaction_cost
            self.position = 0.0
            self.entry_price = 0.0
            self.trade_count += 1
            self.unrealized_pnl = 0.0
        elif self.position > 0:
            # Update unrealized PnL
            self.unrealized_pnl = (current_price - self.entry_price) * self.position
        
        # Execute entry signal
        if entry_signal > 0.5 and self.position == 0:
            # Open position
            max_position = self.balance * self.config.max_position_size
            self.position = min(position_size * max_position, max_position) / current_price
            self.entry_price = current_price
            transaction_cost = self.position * current_price * self.config.transaction_cost
            self.balance -= transaction_cost
            self.trade_count += 1
        
        # Calculate total balance (including unrealized PnL)
        total_balance = self.balance + self.unrealized_pnl
        
        # Update peak balance and drawdown
        if total_balance > self.peak_balance:
            self.peak_balance = total_balance
        drawdown = (self.peak_balance - total_balance) / self.peak_balance
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
        
        # Calculate return for this step
        step_return = (total_balance - self.config.initial_balance) / self.config.initial_balance
        self.episode_returns.append(step_return)
        
        # Calculate reward
        reward = self._calculate_reward(total_balance, drawdown)
        self.total_reward += reward
        
        # Move to next step
        self.current_step += 1
        self.episode_length += 1
        
        # Check termination conditions
        terminated = self.current_step >= len(self.data) - 1
        truncated = self.episode_length >= self.config.max_episode_length
        
        # Get observation
        observation = self._get_observation()
        
        # Info dictionary
        info = {
            "balance": total_balance,
            "position": self.position,
            "unrealized_pnl": self.unrealized_pnl,
            "trade_count": self.trade_count,
            "max_drawdown": self.max_drawdown,
            "total_return": step_return,
        }
        
        return observation, reward, terminated, truncated, info
    
    def _get_observation(self) -> np.ndarray:
        """Get current observation (state).
        
        Returns:
            Numpy array with state features
        """
        # Get historical window
        start_idx = max(0, self.current_step - self.config.lookback_window)
        window = self.data.iloc[start_idx:self.current_step]
        
        # Pad if window is smaller than lookback_window
        if len(window) < self.config.lookback_window:
            padding = np.zeros((self.config.lookback_window - len(window), 3))
            window_data = np.vstack([
                padding,
                window[['close', 'volume', 'returns']].values,
            ])
        else:
            window_data = window[['close', 'volume', 'returns']].values
        
        # Flatten window data
        window_flat = window_data.flatten()
        
        # Add position state
        position_state = np.array([
            self.position,
            self.balance / self.config.initial_balance,  # Normalized balance
            self.unrealized_pnl / self.config.initial_balance,  # Normalized unrealized PnL
        ])
        
        # Concatenate
        observation = np.concatenate([window_flat, position_state]).astype(np.float32)
        
        return observation
    
    def _calculate_reward(self, total_balance: float, drawdown: float) -> float:
        """Calculate reward for current step.
        
        Reward function:
        - Base reward: Sharpe ratio over episode
        - Penalties:
          - Transaction costs (0.1% per trade)
          - Drawdown (exponential penalty)
          - Turnover (quadratic penalty)
        - Bonus:
          - Profit consistency (positive reward streaks)
        
        Args:
            total_balance: Current total balance
            drawdown: Current drawdown
            
        Returns:
            Reward value
        """
        # Calculate Sharpe ratio over episode
        if len(self.episode_returns) > 1:
            returns_array = np.array(self.episode_returns)
            sharpe = np.mean(returns_array) / (np.std(returns_array) + 1e-8)
        else:
            sharpe = 0.0
        
        # Base reward from Sharpe
        reward = sharpe * 0.1
        
        # Drawdown penalty (exponential)
        if drawdown > 0:
            dd_penalty = -np.exp(drawdown * 10) * 0.05
            reward += dd_penalty
        
        # Turnover penalty (quadratic)
        if self.trade_count > 0:
            turnover_penalty = -(self.trade_count ** 2) * 0.001
            reward += turnover_penalty
        
        # Profit consistency bonus
        if len(self.episode_returns) >= 2:
            if self.episode_returns[-1] > 0 and self.episode_returns[-2] > 0:
                reward += 0.01  # Bonus for positive streak
        
        return reward
    
    def render(self):
        """Render environment state (optional)."""
        pass


def create_trading_env(
    data: pd.DataFrame,
    config: TradingConfig | None = None,
) -> TradingEnv:
    """Factory function to create trading environment.
    
    Args:
        data: DataFrame with OHLCV data
        config: Trading configuration
        
    Returns:
        TradingEnv instance
    """
    return TradingEnv(data, config)


def create_vectorized_env(
    data: pd.DataFrame,
    n_envs: int = 4,
    config: TradingConfig | None = None,
) -> gym.Env:
    """Create vectorized environment for parallel training.
    
    Args:
        data: DataFrame with OHLCV data
        n_envs: Number of parallel environments
        config: Trading configuration
        
    Returns:
        Vectorized Gymnasium environment
    """
    def make_env():
        return create_trading_env(data, config)
    
    return gym.vector.AsyncVectorEnv([make_env for _ in range(n_envs)])


__all__ = [
    "TradingConfig",
    "TradingEnv",
    "create_trading_env",
    "create_vectorized_env",
]
