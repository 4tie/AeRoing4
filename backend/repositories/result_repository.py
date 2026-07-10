"""
Result Repository
Data access layer for backtest results
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass
class BacktestResult:
    """Backtest result data model"""
    result_id: str
    strategy_id: str
    strategy_name: str
    timeframe: str
    pairs: List[str]
    metrics: Dict[str, Any]
    equity_curve: List[Dict[str, Any]]
    drawdown_curve: List[Dict[str, Any]]
    trades: List[Dict[str, Any]]
    created_at: str


class ResultRepository:
    """Repository for backtest results"""
    
    def __init__(self, data_dir: str = "user_data/backtest_results"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def save(self, result: BacktestResult) -> bool:
        """Save backtest result to disk"""
        try:
            result_file = self.data_dir / f"{result.result_id}.json"
            with open(result_file, 'w') as f:
                json.dump({
                    'result_id': result.result_id,
                    'strategy_id': result.strategy_id,
                    'strategy_name': result.strategy_name,
                    'timeframe': result.timeframe,
                    'pairs': result.pairs,
                    'metrics': result.metrics,
                    'equity_curve': result.equity_curve,
                    'drawdown_curve': result.drawdown_curve,
                    'trades': result.trades,
                    'created_at': result.created_at,
                }, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving result: {e}")
            return False
    
    def load(self, result_id: str) -> Optional[BacktestResult]:
        """Load backtest result from disk"""
        try:
            result_file = self.data_dir / f"{result_id}.json"
            if not result_file.exists():
                return None
            
            with open(result_file, 'r') as f:
                data = json.load(f)
            
            return BacktestResult(
                result_id=data['result_id'],
                strategy_id=data['strategy_id'],
                strategy_name=data['strategy_name'],
                timeframe=data['timeframe'],
                pairs=data['pairs'],
                metrics=data['metrics'],
                equity_curve=data['equity_curve'],
                drawdown_curve=data['drawdown_curve'],
                trades=data['trades'],
                created_at=data['created_at'],
            )
        except Exception as e:
            print(f"Error loading result: {e}")
            return None
    
    def list_all(self) -> List[BacktestResult]:
        """List all backtest results"""
        results = []
        for result_file in self.data_dir.glob("*.json"):
            result = self.load(result_file.stem)
            if result:
                results.append(result)
        return results
    
    def delete(self, result_id: str) -> bool:
        """Delete backtest result"""
        try:
            result_file = self.data_dir / f"{result_id}.json"
            if result_file.exists():
                result_file.unlink()
                return True
            return False
        except Exception as e:
            print(f"Error deleting result: {e}")
            return False
