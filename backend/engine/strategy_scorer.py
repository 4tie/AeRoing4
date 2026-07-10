"""
Strategy Scorer Engine
Pure business logic for scoring trading strategies
No dependencies on FastAPI, file I/O, or external services
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class StrategyScore:
    """Score breakdown for a strategy"""
    strategy_id: str
    overall_score: float  # 0-100
    expectancy_score: float  # 0-20 (20% weight)
    profit_factor_score: float  # 0-20 (20% weight)
    drawdown_score: float  # 0-20 (20% weight)
    walk_forward_score: float  # 0-15 (15% weight)
    robustness_score: float  # 0-15 (15% weight)
    pair_consistency_score: float  # 0-5 (5% weight)
    trade_quality_score: float  # 0-5 (5% weight)
    tier: str  # candidate, promising, validated, elite


class StrategyScorerEngine:
    """
    Pure business logic for scoring trading strategies
    Can be tested independently without FastAPI or file I/O
    """
    
    def __init__(self):
        # Scoring weights (must sum to 100)
        self.weights = {
            'expectancy': 20,
            'profit_factor': 20,
            'drawdown': 20,
            'walk_forward': 15,
            'robustness': 15,
            'pair_consistency': 5,
            'trade_quality': 5,
        }
    
    def score_strategy(
        self,
        strategy_id: str,
        metrics: Dict[str, Any],
        walk_forward_result: Optional[Dict[str, Any]] = None,
        robustness_result: Optional[Dict[str, Any]] = None,
        pair_results: Optional[Dict[str, Any]] = None
    ) -> StrategyScore:
        """
        Calculate comprehensive score for a strategy
        
        Args:
            strategy_id: Strategy identifier
            metrics: Strategy performance metrics
            walk_forward_result: Walk-forward test results
            robustness_result: Robustness test results
            pair_results: Multi-pair test results
        
        Returns:
            StrategyScore with breakdown
        """
        
        # Calculate individual component scores
        expectancy_score = self._score_expectancy(metrics)
        profit_factor_score = self._score_profit_factor(metrics)
        drawdown_score = self._score_drawdown(metrics)
        walk_forward_score = self._score_walk_forward(walk_forward_result)
        robustness_score = self._score_robustness(robustness_result)
        pair_consistency_score = self._score_pair_consistency(pair_results)
        trade_quality_score = self._score_trade_quality(metrics)
        
        # Calculate overall score
        overall_score = (
            expectancy_score * self.weights['expectancy'] / 20 +
            profit_factor_score * self.weights['profit_factor'] / 20 +
            drawdown_score * self.weights['drawdown'] / 20 +
            walk_forward_score * self.weights['walk_forward'] / 15 +
            robustness_score * self.weights['robustness'] / 15 +
            pair_consistency_score * self.weights['pair_consistency'] / 5 +
            trade_quality_score * self.weights['trade_quality'] / 5
        )
        
        # Determine tier
        tier = self._determine_tier(overall_score, walk_forward_score, robustness_score)
        
        return StrategyScore(
            strategy_id=strategy_id,
            overall_score=round(overall_score, 2),
            expectancy_score=round(expectancy_score, 2),
            profit_factor_score=round(profit_factor_score, 2),
            drawdown_score=round(drawdown_score, 2),
            walk_forward_score=round(walk_forward_score, 2),
            robustness_score=round(robustness_score, 2),
            pair_consistency_score=round(pair_consistency_score, 2),
            trade_quality_score=round(trade_quality_score, 2),
            tier=tier
        )
    
    def _score_expectancy(self, metrics: Dict[str, Any]) -> float:
        """Score expectancy (0-20)"""
        expectancy = metrics.get('expectancy', 0)
        
        if expectancy <= 0:
            return 0
        elif expectancy < 0.0001:
            return 5
        elif expectancy < 0.0005:
            return 10
        elif expectancy < 0.001:
            return 15
        else:
            return 20
    
    def _score_profit_factor(self, metrics: Dict[str, Any]) -> float:
        """Score profit factor (0-20)"""
        pf = metrics.get('profit_factor', 0)
        
        if pf <= 1.0:
            return 0
        elif pf < 1.2:
            return 5
        elif pf < 1.4:
            return 10
        elif pf < 1.6:
            return 15
        else:
            return 20
    
    def _score_drawdown(self, metrics: Dict[str, Any]) -> float:
        """Score drawdown (0-20, lower is better)"""
        dd = metrics.get('drawdown', 100)
        
        if dd >= 50:
            return 0
        elif dd < 10:
            return 20
        elif dd < 20:
            return 15
        elif dd < 30:
            return 10
        else:
            return 5
    
    def _score_walk_forward(self, walk_forward_result: Optional[Dict[str, Any]]) -> float:
        """Score walk-forward results (0-15)"""
        if not walk_forward_result:
            return 0
        
        pass_rate = walk_forward_result.get('pass_rate', 0)
        avg_degradation = walk_forward_result.get('avg_degradation', 100)
        
        # Score based on pass rate (60%+ is good)
        pass_score = min(pass_rate / 60 * 10, 10)
        
        # Score based on degradation (less than 40% is good)
        degradation_score = max(0, (40 - avg_degradation) / 40 * 5)
        
        return round(pass_score + degradation_score, 2)
    
    def _score_robustness(self, robustness_result: Optional[Dict[str, Any]]) -> float:
        """Score robustness (0-15)"""
        if not robustness_result:
            return 0
        
        robustness_score = robustness_result.get('robustness_score', 0)
        
        # Scale 0-1 to 0-15
        return round(robustness_score * 15, 2)
    
    def _score_pair_consistency(self, pair_results: Optional[Dict[str, Any]]) -> float:
        """Score pair consistency (0-5)"""
        if not pair_results:
            return 0
        
        pass_rate = pair_results.get('pass_rate', 0)
        
        # Score based on pass rate (60%+ is good)
        return round(min(pass_rate / 60 * 5, 5), 2)
    
    def _score_trade_quality(self, metrics: Dict[str, Any]) -> float:
        """Score trade quality (0-5)"""
        win_rate = metrics.get('win_rate', 0)
        trades = metrics.get('trades', 0)
        
        # Need sufficient trades
        if trades < 100:
            return 0
        
        # Score based on win rate (50%+ is good)
        return round(min(win_rate / 50 * 5, 5), 2)
    
    def _determine_tier(
        self,
        overall_score: float,
        walk_forward_score: float,
        robustness_score: float
    ) -> str:
        """Determine strategy tier based on scores"""
        
        if overall_score >= 80 and walk_forward_score >= 10 and robustness_score >= 10:
            return 'elite'
        elif overall_score >= 60 and walk_forward_score >= 7:
            return 'validated'
        elif overall_score >= 40:
            return 'promising'
        else:
            return 'candidate'
    
    def rank_strategies(self, scores: list[StrategyScore]) -> list[StrategyScore]:
        """Rank strategies by overall score"""
        return sorted(scores, key=lambda x: x.overall_score, reverse=True)
