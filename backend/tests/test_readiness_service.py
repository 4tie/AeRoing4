from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace as NS

from backend.services.readiness_service import ReadinessService


class FakeRunRepository:
    def __init__(self, details: dict[str, object] | None = None) -> None:
        self.details = details or {}

    def load_detail(self, run_id: str) -> object | None:
        return self.details.get(run_id)


class FakeSessionStore:
    def __init__(self, sessions: dict[str, dict] | None = None) -> None:
        self.sessions = sessions or {}

    def get(self, session_id: str) -> dict | None:
        return self.sessions.get(session_id)


def _detail(
    *,
    drawdown: float = 8.0,
    profit_factor: float = 1.8,
    trades: int = 160,
    net_profit: float = 24.0,
    pairs: list[float] | None = None,
) -> NS:
    pair_profits = pairs if pairs is not None else [100.0, 80.0, 45.0, 30.0]
    return NS(
        metadata=NS(run_id="bt-1", strategy_name="AIStrategy", timeframe="15m"),
        parsed_summary=NS(
            net_profit_pct=net_profit,
            profit_factor=profit_factor,
            max_drawdown_pct=drawdown,
            total_trades=trades,
            win_rate_pct=56.0,
            expectancy=0.18,
            exit_reason_distribution=[
                NS(reason="roi", count=78),
                NS(reason="exit_signal", count=54),
                NS(reason="stop_loss", count=18),
            ],
        ),
        pair_results=[
            NS(pair=f"PAIR{i}/USDT", net_profit_currency=value, net_profit_pct=value / 10)
            for i, value in enumerate(pair_profits, start=1)
        ],
    )


def _temporal_session(*, worst_profit: float = 2.0) -> dict:
    return {
        "session_id": "temp-1",
        "status": "completed",
        "result": {
            "mode": "time_split",
            "consistency_score": 0.82,
            "worst_net_profit_pct": worst_profit,
            "max_drawdown_variance": 4.0,
            "segments": [
                {"label": "A", "status": "completed", "net_profit_pct": 4.0, "max_drawdown_pct": 5.0},
                {"label": "B", "status": "completed", "net_profit_pct": worst_profit, "max_drawdown_pct": 8.0},
                {"label": "C", "status": "completed", "net_profit_pct": 3.0, "max_drawdown_pct": 6.0},
            ],
        },
    }


def _service(repo: FakeRunRepository, session_store: FakeSessionStore | None = None) -> ReadinessService:
    return ReadinessService(
        root_dir=Path(__file__).resolve().parents[2],
        run_repository=repo,
        session_store=session_store,
    )


def _gate(report: dict, key: str) -> dict:
    return next(gate for gate in report["gates"] if gate["key"] == key)


def test_score_passes_with_strong_backtest_oos_and_balanced_pairs() -> None:
    service = _service(
        FakeRunRepository({"bt-1": _detail()}),
        FakeSessionStore({"temp-1": _temporal_session()}),
    )

    report = service.build_report(backtest_run_id="bt-1", temporal_stress_session_id="temp-1")

    assert report["status"] == "ready"
    assert report["overall_score"] >= 75
    assert report["blocking_failures"] == []
    assert _gate(report, "validation.oos_wfo_evidence")["status"] == "pass"


def test_fail_on_high_drawdown() -> None:
    service = _service(
        FakeRunRepository({"bt-1": _detail(drawdown=42.0)}),
        FakeSessionStore({"temp-1": _temporal_session()}),
    )

    report = service.build_report(backtest_run_id="bt-1", temporal_stress_session_id="temp-1")

    assert report["status"] == "not_ready"
    assert _gate(report, "backtest.max_drawdown")["status"] == "fail"
    assert any(item["gate"] == "backtest.max_drawdown" for item in report["blocking_failures"])


def test_warn_on_missing_oos_wfo() -> None:
    report = _service(FakeRunRepository({"bt-1": _detail()})).build_report(backtest_run_id="bt-1")

    assert report["status"] == "watch"
    assert _gate(report, "validation.oos_wfo_evidence")["status"] == "missing"
    assert any(warning["code"] == "missing_oos_wfo" for warning in report["warnings"])


def test_fail_on_pair_concentration_over_70_percent() -> None:
    service = _service(
        FakeRunRepository({"bt-1": _detail(pairs=[100.0, 10.0, 5.0, -3.0])}),
        FakeSessionStore({"temp-1": _temporal_session()}),
    )

    report = service.build_report(backtest_run_id="bt-1", temporal_stress_session_id="temp-1")

    assert report["status"] == "not_ready"
    assert _gate(report, "pairs.dominant_pair_concentration")["status"] == "fail"
    assert any(item["gate"] == "pairs.dominant_pair_concentration" for item in report["blocking_failures"])


def test_insufficient_data_with_invalid_ids() -> None:
    report = _service(FakeRunRepository()).build_report(backtest_run_id="missing-run")

    assert report["status"] == "insufficient_data"
    assert report["overall_score"] == 0
    assert report["missing_sources"][0]["source"] == "backtest_run"


def test_temporal_stress_worst_segment_affects_score() -> None:
    strong = _service(
        FakeRunRepository({"bt-1": _detail()}),
        FakeSessionStore({"temp-1": _temporal_session(worst_profit=2.0)}),
    ).build_report(backtest_run_id="bt-1", temporal_stress_session_id="temp-1")
    weak = _service(
        FakeRunRepository({"bt-1": _detail()}),
        FakeSessionStore({"temp-1": _temporal_session(worst_profit=-7.0)}),
    ).build_report(backtest_run_id="bt-1", temporal_stress_session_id="temp-1")

    assert _gate(weak, "stress.temporal_worst_segment")["status"] == "fail"
    assert weak["overall_score"] < strong["overall_score"]
