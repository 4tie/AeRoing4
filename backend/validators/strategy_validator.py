"""
Strategy Validator
Validation rules for trading strategies
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of validation"""
    passed: bool
    errors: List[str]
    warnings: List[str]


class StrategyValidator:
    """Validator for trading strategies"""
    
    def __init__(self):
        pass
    
    def validate_code(self, code: str) -> ValidationResult:
        """
        Validate strategy code syntax
        
        Args:
            code: Strategy code
        
        Returns:
            ValidationResult with pass/fail status
        """
        errors = []
        warnings = []
        
        # Check if code is empty
        if not code or not code.strip():
            errors.append("Strategy code is empty")
        
        # Check for required methods
        required_methods = ['populate_indicators', 'populate_buy_trend', 'populate_sell_trend']
        for method in required_methods:
            if f'def {method}' not in code:
                errors.append(f"Missing required method: {method}")
        
        # Check for IStrategy inheritance
        if 'IStrategy' not in code:
            warnings.append("Strategy may not inherit from IStrategy")
        
        # Check for timeframe
        if 'timeframe' not in code:
            warnings.append("Strategy may not define timeframe")
        
        passed = len(errors) == 0
        
        return ValidationResult(
            passed=passed,
            errors=errors,
            warnings=warnings
        )
    
    def validate_metadata(self, metadata: Dict[str, Any]) -> ValidationResult:
        """
        Validate strategy metadata
        
        Args:
            metadata: Strategy metadata
        
        Returns:
            ValidationResult with pass/fail status
        """
        errors = []
        warnings = []
        
        # Check required fields
        required_fields = ['name', 'timeframe']
        for field in required_fields:
            if field not in metadata or not metadata[field]:
                errors.append(f"Missing required field: {field}")
        
        # Check timeframe validity
        valid_timeframes = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']
        timeframe = metadata.get('timeframe', '')
        if timeframe and timeframe not in valid_timeframes:
            warnings.append(f"Timeframe {timeframe} may not be valid")
        
        # Check pairs
        pairs = metadata.get('pairs', [])
        if not pairs:
            warnings.append("No trading pairs specified")
        
        passed = len(errors) == 0
        
        return ValidationResult(
            passed=passed,
            errors=errors,
            warnings=warnings
        )
