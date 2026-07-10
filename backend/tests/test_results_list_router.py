"""Regression tests for GET /api/results contract."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

from backend.api.routers import results_list
from backend.models import ParsedSummary, RunMetadata, RunStatus, RunType


def _metadata(run_id: str, status: RunStatus = RunStatus.COMPLETED) -> RunMetadata:
    return RunMetadata(
        run_id=run_id,
        strategy_name="DemoStrategy",
        strategy_version_id="v1",
        parent_version_id=None,
        baseline_run_id=None,
        run_type=RunType.BASELINE,
        run_status=status,
        created_at=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
        completed_at=datetime(2024, 1, 1, 12, 0, 3, tzinfo=UTC),
        freqtrade_exit_code=0 if status == RunStatus.COMPLETED else None,
        config_file="config.json",
        timerange="20240101-20240201",
        timeframe="1h",
        pairs=["BTC/USDT"],
        max_open_trades=1,
    )


def _summary() -> dict:
    return ParsedSummary(
        run_id="completed-run",
        starting_balance=1000,
        final_balance=1100,
        net_profit_currency=100,
        net_profit_pct=10.0,
        total_trades=12,
        trades_per_day=2.0,
        win_rate_pct=66.7,
        loss_rate_pct=33.3,
        max_drawdown_pct=4.2,
        max_drawdown_currency=42,
        avg_trade_duration_minutes=30,
        profit_factor=1.8,
        expectancy=0.4,
        sharpe_ratio=1.2,
        sortino_ratio=1.4,
        calmar_ratio=2.0,
        exit_reason_distribution=[],
    ).model_dump(mode="json")


class FakeRunRepository:
    def __init__(self, root) -> None:
        self.root = root
        self.list_calls = 0

    def list_runs(self):
        self.list_calls += 1
        return [
            _metadata("completed-run"),
            _metadata("running-run", RunStatus.RUNNING),
        ]

    def find_run_dir(self, run_id: str):
        return self.root / run_id


def _services(repository: FakeRunRepository):
    return SimpleNamespace(run_repository=repository)


def test_list_results_returns_completed_runs_with_summary_and_duration(tmp_path):
    repository = FakeRunRepository(tmp_path)
    run_dir = tmp_path / "completed-run"
    run_dir.mkdir()
    (run_dir / "parsed_summary.json").write_text(
        json.dumps(_summary()),
        encoding="utf-8",
    )
    results_list.invalidate_results_cache()

    body = asyncio.run(results_list.list_results(_services(repository)))

    assert len(body.results) == 1
    item = body.results[0]
    assert item.run_id == "completed-run"
    assert item.strategy_name == "DemoStrategy"
    assert item.duration_ms == 3000.0
    assert item.parsed_summary is not None
    assert item.parsed_summary.net_profit_pct == 10.0


def test_list_results_uses_ttl_cache_until_invalidated(tmp_path):
    repository = FakeRunRepository(tmp_path)
    (tmp_path / "completed-run").mkdir()
    results_list.invalidate_results_cache()

    first = asyncio.run(results_list.list_results(_services(repository)))
    second = asyncio.run(results_list.list_results(_services(repository)))
    assert first is second
    assert repository.list_calls == 1

    results_list.invalidate_results_cache()
    third = asyncio.run(results_list.list_results(_services(repository)))
    assert third is not first
    assert repository.list_calls == 2
