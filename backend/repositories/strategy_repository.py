"""
Strategy Repository
Data access layer for trading strategies
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import json
from pathlib import Path
from datetime import datetime


@dataclass
class Strategy:
    """Trading strategy data model"""
    strategy_id: str
    name: str
    code: str
    timeframe: str
    pairs: List[str]
    status: str  # draft, candidate, promising, validated, elite
    tier: str
    metrics: Optional[Dict[str, Any]]
    created_at: str
    updated_at: str


class StrategyRepository:
    """Repository for trading strategies"""
    
    def __init__(self, data_dir: str = "user_data/strategies"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def save(self, strategy: Strategy) -> bool:
        """Save strategy to disk"""
        try:
            strategy_file = self.data_dir / f"{strategy.strategy_id}.json"
            with open(strategy_file, 'w') as f:
                json.dump({
                    'strategy_id': strategy.strategy_id,
                    'name': strategy.name,
                    'code': strategy.code,
                    'timeframe': strategy.timeframe,
                    'pairs': strategy.pairs,
                    'status': strategy.status,
                    'tier': strategy.tier,
                    'metrics': strategy.metrics,
                    'created_at': strategy.created_at,
                    'updated_at': strategy.updated_at,
                }, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving strategy: {e}")
            return False
    
    def load(self, strategy_id: str) -> Optional[Strategy]:
        """Load strategy from disk"""
        try:
            strategy_file = self.data_dir / f"{strategy_id}.json"
            if not strategy_file.exists():
                return None
            
            with open(strategy_file, 'r') as f:
                data = json.load(f)
            
            return Strategy(
                strategy_id=data['strategy_id'],
                name=data['name'],
                code=data['code'],
                timeframe=data['timeframe'],
                pairs=data['pairs'],
                status=data['status'],
                tier=data['tier'],
                metrics=data.get('metrics'),
                created_at=data['created_at'],
                updated_at=data['updated_at'],
            )
        except Exception as e:
            print(f"Error loading strategy: {e}")
            return None
    
    def list_all(self, status: Optional[str] = None) -> List[Strategy]:
        """List all strategies, optionally filtered by status"""
        strategies = []
        for strategy_file in self.data_dir.glob("*.json"):
            strategy = self.load(strategy_file.stem)
            if strategy:
                if status is None or strategy.status == status:
                    strategies.append(strategy)
        return sorted(strategies, key=lambda x: x.updated_at, reverse=True)
    
    def delete(self, strategy_id: str) -> bool:
        """Delete strategy"""
        try:
            strategy_file = self.data_dir / f"{strategy_id}.json"
            if strategy_file.exists():
                strategy_file.unlink()
                return True
            return False
        except Exception as e:
            print(f"Error deleting strategy: {e}")
            return False
    
    def update_status(self, strategy_id: str, status: str, tier: Optional[str] = None) -> bool:
        """Update strategy status"""
        strategy = self.load(strategy_id)
        if not strategy:
            return False
        
        strategy.status = status
        if tier:
            strategy.tier = tier
        strategy.updated_at = datetime.now().isoformat()
        
        return self.save(strategy)
