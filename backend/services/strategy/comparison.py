"""services/strategy/comparison.py contains backend logic for comparison.

This file is intentionally documented in plain English so readers can follow
what each section does even without deep Python experience.
"""

from __future__ import annotations
from pathlib import Path

from ...models import ComparisonMetric, ComparisonResult, MetricLabel, PairComparison, RunMetadata, RunType
from ...utils import read_json


class ComparisonEngine:
    """ComparisonEngine contains class-level backend logic."""
    FAVORABLE_DIRECTIONS = {
        "net_profit_pct": "higher",
        "final_balance": "higher",
        "max_drawdown_pct": "lower",
        "total_trades": "higher",
        "trades_per_day": "higher",
        "win_rate_pct": "higher",
        "expectancy": "higher",
        "profit_factor": "higher",
        "sharpe_ratio": "higher",
    }

    def compare(
        self,
        baseline_metadata: RunMetadata,
        candidate_metadata: RunMetadata,
        baseline_summary: dict,
        candidate_summary: dict,
        baseline_pairs: list[dict],
        candidate_pairs: list[dict],
        baseline_params: dict | None = None,
        candidate_params: dict | None = None,
    ) -> ComparisonResult:
        """compare implements function-level backend logic."""
        metrics: list[ComparisonMetric] = []
        suspicious_reasons: list[str] = []
        thresholds = {"relative_unchanged": 0.01, "overfit_profit_gain": 0.25, "overfit_trade_drop": 0.40}

        for metric_name in [
            "net_profit_pct",
            "final_balance",
            "max_drawdown_pct",
            "total_trades",
            "trades_per_day",
            "win_rate_pct",
            "expectancy",
            "profit_factor",
            "sharpe_ratio",
        ]:
            metrics.append(
                self._compare_metric(
                    metric_name,
                    baseline_summary.get(metric_name),
                    candidate_summary.get(metric_name),
                )
            )

        baseline_profit = baseline_summary.get("net_profit_pct")
        candidate_profit = candidate_summary.get("net_profit_pct")
        baseline_trades = baseline_summary.get("total_trades")
        candidate_trades = candidate_summary.get("total_trades")
        if (
            isinstance(baseline_profit, (int, float))
            and isinstance(candidate_profit, (int, float))
            and isinstance(baseline_trades, (int, float))
            and isinstance(candidate_trades, (int, float))
            and baseline_profit != 0
            and baseline_trades != 0
        ):
            profit_delta = (candidate_profit - baseline_profit) / abs(baseline_profit)
            trade_delta = (candidate_trades - baseline_trades) / abs(baseline_trades)
            if profit_delta > 0.25 and trade_delta < -0.40:
                suspicious_reasons.append(
                    "Net profit improved by more than 25% while total trades dropped by more than 40%."
                )

        baseline_expectancy = baseline_summary.get("expectancy")
        candidate_expectancy = candidate_summary.get("expectancy")
        baseline_sharpe = baseline_summary.get("sharpe_ratio")
        candidate_sharpe = candidate_summary.get("sharpe_ratio")
        if (
            isinstance(baseline_sharpe, (int, float))
            and isinstance(candidate_sharpe, (int, float))
            and isinstance(baseline_expectancy, (int, float))
            and isinstance(candidate_expectancy, (int, float))
            and candidate_sharpe > baseline_sharpe
            and candidate_expectancy <= baseline_expectancy
            and isinstance(baseline_trades, (int, float))
            and isinstance(candidate_trades, (int, float))
            and candidate_trades < baseline_trades
        ):
            suspicious_reasons.append(
                "Sharpe ratio improved while expectancy did not, and trade count fell."
            )

        if suspicious_reasons:
            for metric in metrics:
                if metric.metric_name in {"net_profit_pct", "total_trades", "sharpe_ratio"}:
                    metric.label = MetricLabel.SUSPICIOUS

        pair_differences = self._compare_pairs(baseline_pairs, candidate_pairs)
        pair_list_changes = self._compare_pair_lists(baseline_params or {}, candidate_params or {})

        return ComparisonResult(
            baseline_run_id=baseline_metadata.run_id,
            candidate_run_id=candidate_metadata.run_id,
            candidate_run_type=candidate_metadata.run_type,
            metrics=metrics,
            pair_differences=pair_differences,
            suspicious_reasons=suspicious_reasons,
            thresholds=thresholds,
            pair_list_changes=pair_list_changes,
        )

    def _compare_metric(self, metric_name: str, baseline_value, candidate_value) -> ComparisonMetric:
        """_compare_metric implements function-level backend logic."""
        favorable = self.FAVORABLE_DIRECTIONS.get(metric_name, "either")
        threshold_value = 0.01
        if baseline_value is None or candidate_value is None:
            return ComparisonMetric(
                metric_name=metric_name,
                baseline_value=baseline_value,
                candidate_value=candidate_value,
                absolute_delta=None,
                relative_delta=None,
                threshold_value=threshold_value,
                favorable_direction=favorable,
                label=MetricLabel.UNCHANGED,
            )

        absolute_delta = float(candidate_value) - float(baseline_value)
        if baseline_value == 0:
            relative_delta = None
            is_unchanged = abs(absolute_delta) < threshold_value
        else:
            relative_delta = absolute_delta / abs(float(baseline_value))
            is_unchanged = abs(relative_delta) < threshold_value

        if is_unchanged:
            label = MetricLabel.UNCHANGED
        else:
            if favorable == "lower":
                label = MetricLabel.IMPROVED if absolute_delta < 0 else MetricLabel.REGRESSED
            else:
                label = MetricLabel.IMPROVED if absolute_delta > 0 else MetricLabel.REGRESSED

        return ComparisonMetric(
            metric_name=metric_name,
            baseline_value=baseline_value,
            candidate_value=candidate_value,
            absolute_delta=absolute_delta,
            relative_delta=relative_delta,
            threshold_value=threshold_value,
            favorable_direction=favorable,
            label=label,
        )

    def _compare_pairs(self, baseline_pairs: list[dict], candidate_pairs: list[dict]) -> list[PairComparison]:
        """_compare_pairs implements function-level backend logic."""
        baseline_index = {item["pair"]: item for item in baseline_pairs}
        candidate_index = {item["pair"]: item for item in candidate_pairs}
        pair_names = sorted(set(baseline_index) | set(candidate_index))
        results: list[PairComparison] = []
        for pair in pair_names:
            baseline_profit = baseline_index.get(pair, {}).get("net_profit_currency")
            candidate_profit = candidate_index.get(pair, {}).get("net_profit_currency")
            if baseline_profit is None:
                label = MetricLabel.IMPROVED
            elif candidate_profit is None:
                label = MetricLabel.REGRESSED
            else:
                delta = float(candidate_profit) - float(baseline_profit)
                label = MetricLabel.UNCHANGED if abs(delta) < 0.01 else (
                    MetricLabel.IMPROVED if delta > 0 else MetricLabel.REGRESSED
                )
            results.append(
                PairComparison(
                    pair=pair,
                    baseline_net_profit=baseline_profit,
                    candidate_net_profit=candidate_profit,
                    label=label,
                )
            )
        return results

    def _compare_pair_lists(self, baseline_params: dict, candidate_params: dict) -> dict[str, list[str]]:
        """_compare_pair_lists implements function-level backend logic."""
        baseline_pairs = set(baseline_params.get("pair_list") or [])
        candidate_pairs = set(candidate_params.get("pair_list") or [])
        return {
            "added": sorted(candidate_pairs - baseline_pairs),
            "removed": sorted(baseline_pairs - candidate_pairs),
        }
