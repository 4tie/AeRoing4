"""
Backtest Validator
Validation rules for backtest results
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of validation"""
    passed: bool
    errors: List[str]
    warnings: List[str]
    metrics: Dict[str, Any]


class BacktestValidator:
    """Validator for backtest results"""
    
    def __init__(self, thresholds: Optional[Dict[str, Any]] = None):
        self.thresholds = thresholds or self._default_thresholds()
    
    def _default_thresholds(self) -> Dict[str, Any]:
        """Default validation thresholds"""
        return {
            'min_profit_factor': 1.0,
            'max_drawdown': 50.0,
            'min_trades': 50,
            'min_win_rate': 30.0,
            'min_expectancy': 0.0,
        }
    
    def validate(self, metrics: Dict[str, Any]) -> ValidationResult:
        """
        Validate backtest metrics against thresholds
        
        Args:
            metrics: Backtest metrics
        
        Returns:
            ValidationResult with pass/fail status
        """
        errors = []
        warnings = []
        
        # Check profit factor
        pf = metrics.get('profit_factor', 0)
        if pf < self.thresholds['min_profit_factor']:
            errors.append(f"Profit factor {pf:.2f} below threshold {self.thresholds['min_profit_factor']}")
        
        # Check drawdown
        dd = metrics.get('drawdown', 100)
        if dd > self.thresholds['max_drawdown']:
            errors.append(f"Drawdown {dd:.2f}% exceeds threshold {self.thresholds['max_drawdown']}%")
        
        # Check trade count
        trades = metrics.get('trades', 0)
        if trades < self.thresholds['min_trades']:
            errors.append(f"Trade count {trades} below minimum {self.thresholds['min_trades']}")
        
        # Check win rate
        win_rate = metrics.get('win_rate', 0)
        if win_rate < self.thresholds['min_win_rate']:
            warnings.append(f"Win rate {win_rate:.2f}% below recommended {self.thresholds['min_win_rate']}%")
        
        # Check expectancy
        expectancy = metrics.get('expectancy', 0)
        if expectancy < self.thresholds['min_expectancy']:
            errors.append(f"Expectancy {expectancy:.6f} below minimum {self.thresholds['min_expectancy']}")
        
        passed = len(errors) == 0
        
        return ValidationResult(
            passed=passed,
            errors=errors,
            warnings=warnings,
            metrics=metrics
        )
    
    def set_thresholds(self, thresholds: Dict[str, Any]):
        """Update validation thresholds"""
        self.thresholds = {**self.thresholds, **thresholds}
