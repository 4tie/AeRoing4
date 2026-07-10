"""services/storage/run_repository.py contains backend logic for run repository.

This file is intentionally documented in plain English so readers can follow
what each section does even without deep Python experience.
"""

from __future__ import annotations
from pathlib import Path

from ...core.errors import BackendError
from ...models import (
    BacktestAdvancedMetrics,
    BacktestCharts,
    BacktestTrade,
    PairResult,
    PairTradeBreakdown,
    ParsedSummary,
    RunDetail,
    RunMetadata,
)
from ...services.interfaces import IRunRepository
from ...utils import atomic_write_json, read_json


class RunRepository(IRunRepository):
    """RunRepository contains class-level backend logic."""
    def __init__(self, backtest_results_root: Path) -> None:
        """__init__ implements function-level backend logic."""
        self.backtest_results_root = backtest_results_root

    def strategy_root(self, strategy_name: str) -> Path:
        """strategy_root implements function-level backend logic."""
        if not strategy_name:
            raise BackendError("Strategy name is required.", status_code=400)
        return self.backtest_results_root / strategy_name

    def run_dir(self, strategy_name: str, run_id: str) -> Path:
        """run_dir implements function-level backend logic."""
        return self.strategy_root(strategy_name) / run_id

    def find_run_dir(self, run_id: str) -> Path:
        """find_run_dir implements function-level backend logic."""
        matches = list(self.backtest_results_root.glob(f"*/{run_id}"))
        if not matches:
            raise BackendError(f"Run '{run_id}' was not found.", status_code=404)
        if len(matches) > 1:
            raise BackendError(f"Run id '{run_id}' is ambiguous.", status_code=409)
        return matches[0]

    def list_runs(self, strategy_name: str | None = None) -> list[RunMetadata]:
        """list_runs implements function-level backend logic."""
        roots = [self.strategy_root(strategy_name)] if strategy_name else [
            path for path in self.backtest_results_root.iterdir() if path.is_dir()
        ]
        runs: list[RunMetadata] = []
        for root in roots:
            if not root.exists():
                continue
            for metadata_path in root.glob("*/metadata.json"):
                runs.append(RunMetadata.model_validate(read_json(metadata_path)))
        runs.sort(key=lambda item: item.created_at, reverse=True)
        return runs

    def load_metadata(self, run_id: str) -> RunMetadata:
        """load_metadata implements function-level backend logic."""
        return RunMetadata.model_validate(read_json(self.find_run_dir(run_id) / "metadata.json"))

    def save_metadata(self, run_id: str, metadata: RunMetadata) -> None:
        """save_metadata implements function-level backend logic."""
        atomic_write_json(
            self.find_run_dir(run_id) / "metadata.json",
            metadata.model_dump(mode="json"),
        )

    def load_detail(self, run_id: str) -> RunDetail:
        """load_detail implements function-level backend logic."""
        run_dir = self.find_run_dir(run_id)
        metadata = RunMetadata.model_validate(read_json(run_dir / "metadata.json"))
        pair_results = [
            PairResult.model_validate(item)
            for item in (read_json(run_dir / "pair_results.json", default=[]) or [])
        ]
        pair_classifications = read_json(run_dir / "pair_classifications.json", default={}) or {}
        if pair_classifications:
            pair_results = [
                pair.model_copy(update=pair_classifications.get(pair.pair, {})) for pair in pair_results
            ]

        parsed_summary_raw = read_json(run_dir / "parsed_summary.json")
        trades_raw = read_json(run_dir / "trades.json", default=[]) or []
        trades_by_pair_raw = read_json(run_dir / "trades_by_pair.json", default={}) or {}
        advanced_metrics_raw = read_json(run_dir / "advanced_metrics.json")
        charts_raw = read_json(run_dir / "charts.json")

        artifacts = {
            path.name: str(path.resolve())
            for path in sorted(run_dir.iterdir())
            if path.is_file()
        }
        return RunDetail(
            metadata=metadata,
            parsed_summary=(
                ParsedSummary.model_validate(parsed_summary_raw) if parsed_summary_raw else None
            ),
            pair_results=pair_results,
            trades=[BacktestTrade.model_validate(item) for item in trades_raw if isinstance(item, dict)],
            trades_by_pair={
                str(pair): PairTradeBreakdown.model_validate(payload)
                for pair, payload in trades_by_pair_raw.items()
                if isinstance(payload, dict)
            },
            advanced_metrics=(
                BacktestAdvancedMetrics.model_validate(advanced_metrics_raw)
                if advanced_metrics_raw
                else None
            ),
            charts=(BacktestCharts.model_validate(charts_raw) if charts_raw else None),
            freqtrade_command=(
                (run_dir / "freqtrade_command.txt").read_text(encoding="utf-8")
                if (run_dir / "freqtrade_command.txt").exists()
                else None
            ),
            artifacts=artifacts,
        )

    def load_trades(self, run_id: str):
        """load_trades implements function-level backend logic."""
        try:
            run_dir = self.find_run_dir(run_id)
        except BackendError:
            # Try to find in AutoQuant directory
            autoquant_root = self.backtest_results_root.parent / "auto_quant"
            autoquant_run_dir = autoquant_root / run_id
            if autoquant_run_dir.exists():
                run_dir = autoquant_run_dir
            else:
                raise

        # First try to load from trades.json (standard backtest format)
        trades_json = run_dir / "trades.json"
        if trades_json.exists():
            trades_data = read_json(trades_json, default=[]) or []
            return trades_data

        # Try to load from AutoQuant stage2_result.json
        stage2_result = run_dir / "stage2_result.json"
        if stage2_result.exists():
            stage2_data = read_json(stage2_result, default={}) or {}
            # Extract trades from the result structure
            if "strategy" in stage2_data:
                for strategy_name, strategy_data in stage2_data["strategy"].items():
                    if "trades" in strategy_data:
                        return strategy_data["trades"]

        return []
