"""Optimizer trial execution and metrics calculation.

Handles trial backtest execution, metrics extraction, and scoring.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from ...models import (
    AcceptanceStatus,
    OptimizerScoreMetric,
    OptimizerScoreWeights,
    OptimizerSession,
    OptimizerTrial,
    OptimizerTrialMetrics,
    OptimizerTrialStatus,
    ParamsSchema,
    RunRequest,
    StrategyRecord,
    VersionChangeType,
    VersionCreationSource,
    VersionMetadata,
)
from ...utils import atomic_write_json, atomic_write_text, utc_now
from ..execution.backtest_runner import BacktestRunner
from ..storage.run_repository import RunRepository
from ..strategy.version_manager import VersionManager


class OptimizerTrialExecutor:
    """Handles individual trial execution and metrics extraction."""

    def __init__(
        self,
        backtest_runner: BacktestRunner,
        run_repository: RunRepository,
        version_manager: VersionManager,
    ) -> None:
        self.backtest_runner = backtest_runner
        self.run_repository = run_repository
        self.version_manager = version_manager

    def extract_trial_metrics(
        self,
        run_id: str,
        score_metric: OptimizerScoreMetric,
        score_weights: OptimizerScoreWeights | None = None,
    ) -> OptimizerTrialMetrics | None:
        """Build the metric bundle used for ranking completed trials."""
        try:
            detail = self.run_repository.load_detail(run_id)
            summary = detail.parsed_summary
            if summary is None:
                return None
            score = self.compute_score(summary, score_metric, score_weights)
            return OptimizerTrialMetrics(
                net_profit_pct=summary.net_profit_pct,
                net_profit_abs=summary.net_profit_currency,
                win_rate_pct=summary.win_rate_pct,
                max_drawdown_pct=summary.max_drawdown_pct,
                max_drawdown_abs=summary.max_drawdown_currency,
                total_trades=summary.total_trades,
                profit_factor=summary.profit_factor,
                sharpe_ratio=summary.sharpe_ratio,
                score=score,
            )
        except Exception:
            return None

    def compute_score(
        self,
        summary: Any,
        metric: OptimizerScoreMetric,
        weights: OptimizerScoreWeights | None = None,
    ) -> float | None:
        """Convert trial metrics into a single comparable score."""
        if metric == OptimizerScoreMetric.TOTAL_PROFIT_PCT:
            return summary.net_profit_pct
        if metric == OptimizerScoreMetric.NET_PROFIT_ABS:
            return summary.net_profit_currency
        if metric == OptimizerScoreMetric.SHARPE_RATIO:
            return summary.sharpe_ratio
        if metric == OptimizerScoreMetric.PROFIT_FACTOR:
            return summary.profit_factor
        if metric == OptimizerScoreMetric.WIN_RATE:
            return summary.win_rate_pct
        if metric == OptimizerScoreMetric.MAX_DRAWDOWN_PCT:
            if summary.max_drawdown_pct is None:
                return None
            return -abs(float(summary.max_drawdown_pct))
        if metric == OptimizerScoreMetric.TOTAL_TRADES:
            if summary.total_trades is None:
                return None
            return float(summary.total_trades)
        weights = weights or OptimizerScoreWeights()
        score = 0.0
        weight_total = 0.0
        if summary.net_profit_pct is not None and weights.net_profit_pct != 0.0:
            score += summary.net_profit_pct * weights.net_profit_pct
            weight_total += abs(weights.net_profit_pct)
        if summary.net_profit_currency is not None and weights.net_profit_abs != 0.0:
            score += summary.net_profit_currency * weights.net_profit_abs
            weight_total += abs(weights.net_profit_abs)
        if summary.sharpe_ratio is not None and weights.sharpe_ratio != 0.0:
            score += summary.sharpe_ratio * weights.sharpe_ratio
            weight_total += abs(weights.sharpe_ratio)
        if summary.profit_factor is not None and weights.profit_factor != 0.0:
            score += min(summary.profit_factor, 100.0) * weights.profit_factor
            weight_total += abs(weights.profit_factor)
        if summary.win_rate_pct is not None and weights.win_rate_pct != 0.0:
            score += summary.win_rate_pct * weights.win_rate_pct
            weight_total += abs(weights.win_rate_pct)
        if summary.max_drawdown_pct is not None and weights.max_drawdown_pct != 0.0:
            score -= abs(float(summary.max_drawdown_pct)) * weights.max_drawdown_pct
            weight_total += abs(weights.max_drawdown_pct)
        if summary.total_trades is not None and weights.total_trades != 0.0:
            score += float(summary.total_trades) * weights.total_trades
            weight_total += abs(weights.total_trades)
        if weight_total == 0:
            return None
        return score

    def extract_run_failure_reason(self, run_id: str) -> str:
        """Read run artifacts and return a short reason when a trial fails."""
        try:
            run_dir = self.run_repository.find_run_dir(run_id)
            log_path = run_dir / "logs.txt"
            if not log_path.exists():
                return "No logs were produced for this run."
            content = log_path.read_text(encoding="utf-8", errors="replace").strip()
            if not content:
                return "Backtest failed without logs."
            for line in reversed(content.splitlines()):
                trimmed = line.strip()
                if not trimmed:
                    continue
                if "No data found" in trimmed:
                    return trimmed
                if "failed to launch freqtrade process" in trimmed:
                    return trimmed
                if "raw_result.json was not produced" in trimmed:
                    return trimmed
                if trimmed.startswith("stderr:") or trimmed.startswith("ERROR"):
                    return trimmed
            return content.splitlines()[-1].strip()
        except Exception:
            return "Backtest failed and failure reason could not be retrieved."

    def build_trial_params(
        self, parent_params: ParamsSchema, trial_parameters: dict[str, Any]
    ) -> ParamsSchema:
        """Build trial-specific params using the canonical version-manager merge logic."""
        self.validate_advanced_params(trial_parameters)
        return self.version_manager.merge_trial_parameters(parent_params, trial_parameters)

    def inject_params_into_source(self, source: str, params: ParamsSchema) -> str:
        """Delegate source injection to the shared version-manager implementation."""
        return self.version_manager.inject_params_into_source(source, params)

    def create_trial_version(
        self,
        strategy_name: str,
        parent_version_id: str,
        strategy_source: str,
        trial_params: ParamsSchema,
        trial_number: int,
    ) -> VersionMetadata:
        """Create a temporary trial version with modified parameters."""

        # Generate a unique trial version ID
        trial_version_id = f"opt_{parent_version_id}_t{trial_number:04d}_{uuid.uuid4().hex[:8]}"
        
        # Create the version directory
        version_dir = self.version_manager.version_dir(strategy_name, trial_version_id)
        version_dir.mkdir(parents=True, exist_ok=False)
        
        # Inject trial parameters into the strategy source
        modified_source = self.inject_params_into_source(strategy_source, trial_params)
        
        # Write the strategy source and params
        trial_params = trial_params.model_copy(update={"version_id": trial_version_id, "extracted_at": utc_now()})
        atomic_write_text(version_dir / "strategy.py", modified_source)
        atomic_write_json(version_dir / "params.json", trial_params.model_dump(mode="json"))
        atomic_write_json(
            version_dir / "trial_parameters.json",
            trial_params.model_dump(mode="json"),
        )
        atomic_write_json(
            version_dir / "trial_metadata.json",
            {
                "trial_number": trial_number,
                "created_at": utc_now().isoformat(),
                "parent_version_id": parent_version_id,
            },
        )
        
        # Create metadata for the trial version (as CANDIDATE so it can be rejected later)
        metadata = VersionMetadata(
            version_id=trial_version_id,
            strategy_name=strategy_name,
            parent_version_id=parent_version_id,
            created_at=utc_now(),
            change_type=VersionChangeType.OPTIMIZATION,
            creation_source=VersionCreationSource.OPTIMIZER_TRIAL,
            proposal_id=None,
            source_run_id=None,
            acceptance_status=AcceptanceStatus.CANDIDATE,
            accepted_at=None,
            rejected_at=None,
            result_summary_run_id=None,
            quality_gate_results=[],  # Skip quality gate for trial versions
        )
        atomic_write_json(version_dir / "metadata.json", metadata.model_dump(mode="json"))
        
        return metadata

    def validate_advanced_params(self, trial_parameters: dict[str, Any]) -> None:
        """Validate advanced trial parameters, raising ValueError on constraint violations."""
        # Stoploss must be negative
        if "stoploss__value" in trial_parameters:
            sl = float(trial_parameters["stoploss__value"])
            if sl >= 0.0:
                raise ValueError("Stoploss must be negative")

        # ROI values must be positive and decrease as time increases
        roi_entries: list[tuple[int, float]] = []
        for key, value in trial_parameters.items():
            if key.startswith("roi__"):
                time_key = int(key[5:])
                roi_val = float(value)
                if roi_val <= 0.0:
                    raise ValueError(
                        f"ROI value for key {time_key} must be positive"
                    )
                roi_entries.append((time_key, roi_val))
        if len(roi_entries) > 1:
            roi_entries.sort(key=lambda x: x[0])
            for i in range(len(roi_entries) - 1):
                _t_early, v_early = roi_entries[i]
                _t_late, v_late = roi_entries[i + 1]
                if v_early < v_late:
                    raise ValueError("ROI targets must decrease over time")

        # Trailing interdependency
        trailing_stop_val = trial_parameters.get("trailing__stop")
        if trailing_stop_val is True:
            tp = trial_parameters.get("trailing__positive")
            to = trial_parameters.get("trailing__offset")
            if tp is not None and to is not None:
                if float(to) >= float(tp):
                    raise ValueError(
                        "Trailing offset must be less than trailing positive"
                    )
