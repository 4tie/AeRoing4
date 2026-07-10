"""
Backtest Engine
Pure business logic for backtesting strategies
No dependencies on FastAPI, file I/O, or external services
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum


class BacktestStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class BacktestConfig:
    """Configuration for backtest"""
    strategy_id: str
    strategy_code: str
    timeframe: str
    pairs: List[str]
    start_date: str
    end_date: str
    stake_amount: float
    max_open_trades: int = 5
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@dataclass
class BacktestResult:
    """Result of a backtest"""
    backtest_id: str
    strategy_id: str
    status: BacktestStatus
    metrics: Dict[str, Any]
    equity_curve: List[Dict[str, Any]]
    drawdown_curve: List[Dict[str, Any]]
    trades: List[Dict[str, Any]]
    errors: List[str]
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class BacktestEngine:
    """
    Pure business logic for backtesting strategies
    Can be tested independently without FastAPI or file I/O
    """
    
    def __init__(self):
        self.backtests: Dict[str, BacktestResult] = {}
    
    def run_backtest(self, config: BacktestConfig) -> BacktestResult:
        """
        Run a backtest with the given configuration
        
        Args:
            config: Backtest configuration
        
        Returns:
            BacktestResult with metrics and curves
        """
        
        backtest_id = f"bt_{config.strategy_id}_{config.timeframe}"
        
        # Create pending result
        result = BacktestResult(
            backtest_id=backtest_id,
            strategy_id=config.strategy_id,
            status=BacktestStatus.RUNNING,
            metrics={},
            equity_curve=[],
            drawdown_curve=[],
            trades=[],
            errors=[]
        )
        
        self.backtests[backtest_id] = result
        
        # In a real implementation, this would call Freqtrade
        # For now, return a mock result
        result.status = BacktestStatus.COMPLETED
        result.metrics = self._generate_mock_metrics(config)
        result.equity_curve = self._generate_mock_equity_curve()
        result.drawdown_curve = self._generate_mock_drawdown_curve()
        result.trades = self._generate_mock_trades()
        
        return result
    
    def _generate_mock_metrics(self, config: BacktestConfig) -> Dict[str, Any]:
        """Generate mock backtest metrics"""
        import random
        
        return {
            'profit_factor': round(random.uniform(1.0, 2.5), 2),
            'drawdown': round(random.uniform(5, 30), 2),
            'expectancy': round(random.uniform(0.0001, 0.002), 6),
            'trades': random.randint(100, 500),
            'win_rate': round(random.uniform(40, 60), 2),
            'sharpe_ratio': round(random.uniform(0.5, 2.0), 2),
            'sortino_ratio': round(random.uniform(0.7, 2.5), 2),
            'calmar_ratio': round(random.uniform(0.3, 1.5), 2),
            'total_profit': round(random.uniform(100, 1000), 2),
            'max_consecutive_losses': random.randint(3, 10),
        }
    
    def _generate_mock_equity_curve(self) -> List[Dict[str, Any]]:
        """Generate mock equity curve"""
        import random
        
        curve = []
        equity = 1000
        for i in range(100):
            change = random.uniform(-20, 30)
            equity += change
            curve.append({
                'timestamp': f'day_{i}',
                'equity': round(equity, 2)
            })
        return curve
    
    def _generate_mock_drawdown_curve(self) -> List[Dict[str, Any]]:
        """Generate mock drawdown curve"""
        import random
        
        curve = []
        peak_equity = 1000
        current_equity = 1000
        
        for i in range(100):
            change = random.uniform(-20, 30)
            current_equity += change
            if current_equity > peak_equity:
                peak_equity = current_equity
            
            drawdown = ((peak_equity - current_equity) / peak_equity) * 100
            curve.append({
                'timestamp': f'day_{i}',
                'drawdown': round(max(0, drawdown), 2)
            })
        return curve
    
    def _generate_mock_trades(self) -> List[Dict[str, Any]]:
        """Generate mock trades"""
        import random
        
        trades = []
        for i in range(50):
            trades.append({
                'trade_id': f'trade_{i}',
                'pair': random.choice(['BTC/USDT', 'ETH/USDT', 'BNB/USDT']),
                'enter_date': f'day_{i}',
                'exit_date': f'day_{i + random.randint(1, 5)}',
                'profit': round(random.uniform(-50, 100), 2),
                'profit_pct': round(random.uniform(-5, 10), 2),
            })
        return trades
    
    def get_backtest_result(self, backtest_id: str) -> Optional[BacktestResult]:
        """Get backtest result by ID"""
        return self.backtests.get(backtest_id)
    
    def cancel_backtest(self, backtest_id: str) -> bool:
        """Cancel a running backtest"""
        if backtest_id in self.backtests:
            self.backtests[backtest_id].status = BacktestStatus.FAILED
            self.backtests[backtest_id].errors.append("Backtest cancelled")
            return True
        return False
