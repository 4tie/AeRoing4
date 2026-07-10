"""Regression tests for Performance tab router contracts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api.routers import performance as performance_router
from backend.core.errors import BackendError
from backend.models import (
    BacktestAdvancedMetrics,
    PairResult,
    ParsedSummary,
    RunDetail,
    RunMetadata,
    RunStatus,
    RunType,
)


def _metadata(**overrides) -> RunMetadata:
    base = {
        "run_id": "run-1",
        "strategy_name": "DemoStrategy",
        "strategy_version_id": "v1",
        "parent_version_id": None,
        "baseline_run_id": None,
        "run_type": RunType.BASELINE,
        "run_status": RunStatus.COMPLETED,
        "created_at": datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
        "completed_at": datetime(2024, 1, 1, 12, 3, tzinfo=UTC),
        "freqtrade_exit_code": 0,
        "config_file": "config.json",
        "timerange": "20240101-20240201",
        "timeframe": "1h",
        "pairs": ["BTC/USDT"],
        "max_open_trades": 1,
    }
    base.update(overrides)
    return RunMetadata(**base)


def _summary(**overrides) -> ParsedSummary:
    base = {
        "run_id": "run-1",
        "starting_balance": 1000,
        "final_balance": 1100,
        "net_profit_currency": 100,
        "net_profit_pct": 10.0,
        "total_trades": 12,
        "trades_per_day": 2.0,
        "win_rate_pct": 66.7,
        "loss_rate_pct": 33.3,
        "max_drawdown_pct": 4.2,
        "max_drawdown_currency": 42,
        "avg_trade_duration_minutes": 30,
        "profit_factor": 1.8,
        "expectancy": 0.4,
        "sharpe_ratio": 1.2,
        "sortino_ratio": 1.4,
        "calmar_ratio": 2.0,
        "exit_reason_distribution": [],
    }
    base.update(overrides)
    return ParsedSummary(**base)


def _pair_result() -> PairResult:
    return PairResult(
        pair="BTC/USDT",
        net_profit_currency=100,
        net_profit_pct=10,
        total_trades=12,
        win_count=8,
        loss_count=4,
        win_rate_pct=66.7,
        avg_trade_result_pct=0.8,
        avg_trade_duration_minutes=30,
        pair_classification=None,
        classification_rationale=None,
    )


def _detail(**overrides) -> RunDetail:
    base = {
        "metadata": _metadata(),
        "parsed_summary": _summary(),
        "pair_results": [_pair_result()],
        "trades": [],
        "advanced_metrics": BacktestAdvancedMetrics(profit_factor=1.8),
        "freqtrade_command": "freqtrade backtesting",
        "artifacts": {},
    }
    base.update(overrides)
    return RunDetail(**base)


class FakeRunRepository:
    def __init__(self, metadata: RunMetadata | None = None, detail: RunDetail | None = None) -> None:
        self.metadata = metadata or _metadata()
        self.detail = detail or _detail(metadata=self.metadata)

    def list_runs(self, strategy: str) -> list[RunMetadata]:
        assert strategy == "DemoStrategy"
        return [self.metadata]

    def find_run_dir(self, _run_id: str):
        return SimpleNamespace(__truediv__=lambda _self, _other: None)

    def load_detail(self, run_id: str) -> RunDetail:
        assert run_id == "run-1"
        return self.detail

    def load_metadata(self, run_id: str) -> RunMetadata:
        assert run_id == "run-1"
        return self.metadata


class FakeVersionManager:
    def __init__(self, version_dir) -> None:
        self._version_dir = version_dir

    def load_params(self, _strategy_name: str, _version_id: str):
        return SimpleNamespace(model_dump=lambda mode="json": {"buy": {"window": 14}})

    def get_current_pointer(self, _strategy_name: str):
        return SimpleNamespace(accepted_version_id="v2")

    def version_dir(self, _strategy_name: str, _version_id: str):
        return self._version_dir


def _services(tmp_path, repository: FakeRunRepository | None = None, version_manager=None):
    return SimpleNamespace(
        run_repository=repository or FakeRunRepository(),
        version_manager=version_manager or FakeVersionManager(tmp_path),
    )


@pytest.fixture(autouse=True)
def _run_to_thread_inline(monkeypatch):
    async def inline_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(performance_router.asyncio, "to_thread", inline_to_thread)


def test_list_performance_runs_returns_summary_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(performance_router, "_load_parsed_summary", lambda _repo, _run_id: _summary())

    body = asyncio.run(
        performance_router.list_performance_runs(
            "DemoStrategy",
            _services(tmp_path),
        )
    )

    assert body["strategy"] == "DemoStrategy"
    assert body["total"] == 1
    row = body["runs"][0]
    assert row["run_id"] == "run-1"
    assert row["run_status"] == "completed"
    assert row["net_profit_pct"] == 10.0
    assert row["profit_factor"] == 1.8


def test_get_performance_run_returns_detail_payload(tmp_path):
    body = asyncio.run(performance_router.get_performance_run("run-1", _services(tmp_path)))

    assert body["run_id"] == "run-1"
    assert body["metadata"]["strategy_name"] == "DemoStrategy"
    assert body["parsed_summary"]["net_profit_pct"] == 10.0
    assert body["pair_results"][0]["pair"] == "BTC/USDT"
    assert body["advanced_metrics"]["profit_factor"] == 1.8
    assert body["params_snapshot"] == {"buy": {"window": 14}}
    assert body["freqtrade_command"] == "freqtrade backtesting"


def test_apply_run_parameters_writes_to_current_version(tmp_path):
    body = asyncio.run(performance_router.apply_run_parameters("run-1", _services(tmp_path)))

    assert body["ok"] is True
    assert body["strategy_name"] == "DemoStrategy"
    assert body["source_version_id"] == "v1"
    assert body["target_version_id"] == "v2"
    assert (tmp_path / "params.json").exists()


def test_apply_run_parameters_requires_current_pointer(tmp_path):
    version_manager = FakeVersionManager(tmp_path)
    version_manager.get_current_pointer = lambda _strategy_name: None

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            performance_router.apply_run_parameters(
                "run-1",
                _services(tmp_path, version_manager=version_manager),
            )
        )

    assert exc_info.value.status_code == 409
    assert "has no accepted version" in exc_info.value.detail


def test_repository_backend_errors_are_preserved(tmp_path):
    repository = FakeRunRepository()
    repository.list_runs = lambda _strategy: (_ for _ in ()).throw(
        BackendError("missing repo", status_code=503)
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            performance_router.list_performance_runs(
                "DemoStrategy",
                _services(tmp_path, repository=repository),
            )
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "missing repo"
