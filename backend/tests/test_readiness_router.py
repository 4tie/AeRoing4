from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace as NS

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routers import readiness


class MissingRunRepository:
    def load_detail(self, run_id: str) -> None:
        return None


def test_readiness_report_returns_stable_schema() -> None:
    app = FastAPI()
    app.state.services = NS(
        root_dir=Path(__file__).resolve().parents[2],
        run_repository=MissingRunRepository(),
        optimizer_store=None,
        sweep_store=None,
    )
    app.include_router(readiness.router)

    response = TestClient(app).get("/api/readiness/report", params={"backtest_run_id": "unknown"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "candidate_readiness_v1"
    assert payload["status"] == "insufficient_data"
    assert payload["overall_score"] == 0
    assert "gates" in payload
    assert "blocking_failures" in payload
    assert "warnings" in payload
    assert "draft_next_actions" in payload
    assert payload["missing_sources"][0]["source"] == "backtest_run"
