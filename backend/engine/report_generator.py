"""
Report Generator Engine
Pure business logic for generating strategy reports
No dependencies on FastAPI, file I/O, or external services
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ReportSection:
    """A section of a strategy report"""
    title: str
    content: str
    order: int


@dataclass
class StrategyReport:
    """Complete strategy report"""
    strategy_id: str
    strategy_name: str
    generated_at: str
    sections: List[ReportSection]
    metrics: Dict[str, Any]
    ai_explanation: str
    recommendation: str


class ReportGeneratorEngine:
    """
    Pure business logic for generating strategy reports
    Can be tested independently without FastAPI or file I/O
    """
    
    def __init__(self):
        pass
    
    def generate_report(
        self,
        strategy_id: str,
        strategy_name: str,
        metrics: Dict[str, Any],
        validation_results: Optional[Dict[str, Any]] = None,
        walk_forward_results: Optional[Dict[str, Any]] = None,
        robustness_results: Optional[Dict[str, Any]] = None,
        pair_results: Optional[Dict[str, Any]] = None,
        score_card: Optional[Dict[str, Any]] = None
    ) -> StrategyReport:
        """
        Generate comprehensive strategy report
        
        Args:
            strategy_id: Strategy identifier
            strategy_name: Strategy name
            metrics: Performance metrics
            validation_results: Validation stage results
            walk_forward_results: Walk-forward test results
            robustness_results: Robustness test results
            pair_results: Multi-pair test results
            score_card: Score card with breakdown
        
        Returns:
            StrategyReport with all sections
        """
        
        sections = []
        
        # Section 1: Strategy Overview
        sections.append(ReportSection(
            title="Strategy Overview",
            content=self._generate_overview(strategy_name, metrics),
            order=1
        ))
        
        # Section 2: Performance Metrics
        sections.append(ReportSection(
            title="Performance Metrics",
            content=self._generate_metrics_section(metrics),
            order=2
        ))
        
        # Section 3: Validation Results
        if validation_results:
            sections.append(ReportSection(
                title="Validation Results",
                content=self._generate_validation_section(validation_results),
                order=3
            ))
        
        # Section 4: Walk-Forward Results
        if walk_forward_results:
            sections.append(ReportSection(
                title="Walk-Forward Analysis",
                content=self._generate_walk_forward_section(walk_forward_results),
                order=4
            ))
        
        # Section 5: Robustness Results
        if robustness_results:
            sections.append(ReportSection(
                title="Robustness Testing",
                content=self._generate_robustness_section(robustness_results),
                order=5
            ))
        
        # Section 6: Pair Analysis
        if pair_results:
            sections.append(ReportSection(
                title="Multi-Pair Analysis",
                content=self._generate_pair_section(pair_results),
                order=6
            ))
        
        # Section 7: Score Card
        if score_card:
            sections.append(ReportSection(
                title="Score Card",
                content=self._generate_score_card_section(score_card),
                order=7
            ))
        
        # AI Explanation
        ai_explanation = self._generate_ai_explanation(
            metrics, validation_results, walk_forward_results, robustness_results
        )
        
        # Recommendation
        recommendation = self._generate_recommendation(
            metrics, validation_results, walk_forward_results, robustness_results, score_card
        )
        
        return StrategyReport(
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            generated_at=datetime.now().isoformat(),
            sections=sections,
            metrics=metrics,
            ai_explanation=ai_explanation,
            recommendation=recommendation
        )
    
    def _generate_overview(self, strategy_name: str, metrics: Dict[str, Any]) -> str:
        """Generate strategy overview section"""
        return f"""
# Strategy Overview

**Strategy Name**: {strategy_name}
**Total Trades**: {metrics.get('trades', 0)}
**Win Rate**: {metrics.get('win_rate', 0):.2f}%
**Profit Factor**: {metrics.get('profit_factor', 0):.2f}
**Max Drawdown**: {metrics.get('drawdown', 0):.2f}%

This strategy has been tested across multiple market conditions and timeframes.
"""
    
    def _generate_metrics_section(self, metrics: Dict[str, Any]) -> str:
        """Generate performance metrics section"""
        return f"""
# Performance Metrics

## Key Metrics
- **Profit Factor**: {metrics.get('profit_factor', 0):.2f}
- **Expectancy**: {metrics.get('expectancy', 0):.6f}
- **Max Drawdown**: {metrics.get('drawdown', 0):.2f}%
- **Sharpe Ratio**: {metrics.get('sharpe_ratio', 0):.2f}
- **Sortino Ratio**: {metrics.get('sortino_ratio', 0):.2f}
- **Calmar Ratio**: {metrics.get('calmar_ratio', 0):.2f}

## Trade Statistics
- **Total Trades**: {metrics.get('trades', 0)}
- **Win Rate**: {metrics.get('win_rate', 0):.2f}%
- **Max Consecutive Losses**: {metrics.get('max_consecutive_losses', 0)}
- **Total Profit**: ${metrics.get('total_profit', 0):.2f}
"""
    
    def _generate_validation_section(self, validation_results: Dict[str, Any]) -> str:
        """Generate validation results section"""
        return f"""
# Validation Results

## Stage Results
- **Discovery**: {'PASSED' if validation_results.get('discovery_passed') else 'FAILED'}
- **Validation**: {'PASSED' if validation_results.get('validation_passed') else 'FAILED'}
- **Elite Validation**: {'PASSED' if validation_results.get('elite_validation_passed') else 'FAILED'}

## Validation Metrics
{self._format_metrics(validation_results.get('metrics', {}))}
"""
    
    def _generate_walk_forward_section(self, walk_forward_results: Dict[str, Any]) -> str:
        """Generate walk-forward section"""
        return f"""
# Walk-Forward Analysis

## Overall Results
- **Pass Rate**: {walk_forward_results.get('pass_rate', 0):.1f}%
- **Average Degradation**: {walk_forward_results.get('avg_degradation', 0):.1f}%
- **Status**: {'PASSED' if walk_forward_results.get('passed') else 'FAILED'}

## Window Results
{self._format_window_results(walk_forward_results.get('windows', []))}
"""
    
    def _generate_robustness_section(self, robustness_results: Dict[str, Any]) -> str:
        """Generate robustness section"""
        return f"""
# Robustness Testing

## Robustness Score
- **Overall Score**: {robustness_results.get('robustness_score', 0):.2f}
- **Parameter Stability**: {robustness_results.get('parameter_stability', 0):.2f}
- **Slippage Tolerance**: {robustness_results.get('slippage_tolerance', 0):.2f}
- **Spread Tolerance**: {robustness_results.get('spread_tolerance', 0):.2f}
- **Volatility Tolerance**: {robustness_results.get('volatility_tolerance', 0):.2f}

## Fragility Flags
{self._format_flags(robustness_results.get('fragility_flags', []))}

## Recommendation
{robustness_results.get('recommendation', 'N/A')}
"""
    
    def _generate_pair_section(self, pair_results: Dict[str, Any]) -> str:
        """Generate pair analysis section"""
        return f"""
# Multi-Pair Analysis

## Overall Results
- **Pass Rate**: {pair_results.get('pass_rate', 0):.1f}%
- **Total Pairs Tested**: {pair_results.get('total_pairs', 0)}
- **Pairs Passed**: {pair_results.get('pairs_passed', 0)}

## Pair Breakdown
{self._format_pair_results(pair_results.get('pair_breakdown', []))}
"""
    
    def _generate_score_card_section(self, score_card: Dict[str, Any]) -> str:
        """Generate score card section"""
        return f"""
# Score Card

## Overall Score: {score_card.get('overall_score', 0):.1f}/100

## Score Breakdown
- **Expectancy (20%)**: {score_card.get('expectancy_score', 0):.1f}/20
- **Profit Factor (20%)**: {score_card.get('profit_factor_score', 0):.1f}/20
- **Drawdown (20%)**: {score_card.get('drawdown_score', 0):.1f}/20
- **Walk Forward (15%)**: {score_card.get('walk_forward_score', 0):.1f}/15
- **Robustness (15%)**: {score_card.get('robustness_score', 0):.1f}/15
- **Pair Consistency (5%)**: {score_card.get('pair_consistency_score', 0):.1f}/5
- **Trade Quality (5%)**: {score_card.get('trade_quality_score', 0):.1f}/5

## Tier: {score_card.get('tier', 'candidate').upper()}
"""
    
    def _generate_ai_explanation(
        self,
        metrics: Dict[str, Any],
        validation_results: Optional[Dict[str, Any]],
        walk_forward_results: Optional[Dict[str, Any]],
        robustness_results: Optional[Dict[str, Any]]
    ) -> str:
        """Generate AI explanation"""
        explanation = f"""
This strategy demonstrates {'strong' if metrics.get('profit_factor', 0) > 1.5 else 'moderate'} performance characteristics.
"""
        
        if walk_forward_results:
            if walk_forward_results.get('pass_rate', 0) > 60:
                explanation += "The walk-forward analysis shows good consistency across different time periods. "
            else:
                explanation += "The walk-forward analysis indicates some inconsistency across time periods. "
        
        if robustness_results:
            if robustness_results.get('robustness_score', 0) > 0.7:
                explanation += "Robustness testing confirms the strategy handles market perturbations well. "
            else:
                explanation += "Robustness testing suggests the strategy may be sensitive to parameter changes. "
        
        return explanation
    
    def _generate_recommendation(
        self,
        metrics: Dict[str, Any],
        validation_results: Optional[Dict[str, Any]],
        walk_forward_results: Optional[Dict[str, Any]],
        robustness_results: Optional[Dict[str, Any]],
        score_card: Optional[Dict[str, Any]]
    ) -> str:
        """Generate deployment recommendation"""
        
        if score_card and score_card.get('tier') == 'elite':
            return "READY FOR DRY-RUN TESTING"
        elif score_card and score_card.get('tier') == 'validated':
            return "READY FOR PAPER TRADING"
        elif score_card and score_card.get('tier') == 'promising':
            return "REQUIRES FURTHER VALIDATION"
        else:
            return "NOT RECOMMENDED FOR TRADING"
    
    def _format_metrics(self, metrics: Dict[str, Any]) -> str:
        """Format metrics for display"""
        lines = []
        for key, value in metrics.items():
            lines.append(f"- **{key}**: {value}")
        return "\n".join(lines)
    
    def _format_window_results(self, windows: List[Dict[str, Any]]) -> str:
        """Format window results for display"""
        lines = []
        for window in windows[:5]:  # Show first 5
            lines.append(f"- Window {window.get('window_id', 'N/A')}: "
                        f"Train {window.get('train_profit', 0):.2f}, "
                        f"Test {window.get('test_profit', 0):.2f}, "
                        f"Degradation {window.get('degradation', 0):.1f}%")
        return "\n".join(lines)
    
    def _format_flags(self, flags: List[str]) -> str:
        """Format fragility flags for display"""
        if not flags:
            return "No fragility flags detected."
        return "\n".join(f"- {flag}" for flag in flags)
    
    def _format_pair_results(self, pair_breakdown: List[Dict[str, Any]]) -> str:
        """Format pair results for display"""
        lines = []
        for pair in pair_breakdown[:10]:  # Show first 10
            lines.append(f"- {pair.get('pair', 'N/A')}: "
                        f"PF {pair.get('profit_factor', 0):.2f}, "
                        f"DD {pair.get('drawdown', 0):.2f}%, "
                        f"{'PASSED' if pair.get('passed') else 'FAILED'}")
        return "\n".join(lines)
