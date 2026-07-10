from __future__ import annotations

from backend.services.auto_quant.ai_suggestions import create_pending_suggestion
from backend.services.auto_quant.pipeline_modules.config import STAGE_NAMES
from backend.services.auto_quant.pipeline_modules.state import PipelineState, StageState
from backend.services.auto_quant.pipeline import _states


def _install_state(tmp_path) -> PipelineState:
    state = PipelineState(
        run_id="route-ai",
        strategy="TestStrategy",
        timeframe="5m",
        in_sample_range="20230101-20240101",
        out_sample_range="20240101-20240601",
        exchange="binance",
        config_file=str(tmp_path / "config.json"),
        freqtrade_path="freqtrade",
        user_data_dir=str(tmp_path / "user_data"),
        status="awaiting_user_approval",
        stages=[StageState(index=i + 1, name=name) for i, name in enumerate(STAGE_NAMES)],
        hyperopt_loss="ProfitLockinHyperOptLoss",
    )
    create_pending_suggestion(
        state=state,
        trigger="sharp_peak",
        failure_reason="sensitivity",
        retry_attempt=1,
        source="deterministic",
        proposed_changes={"hyperopt_loss": "OnlyProfitHyperOptLoss"},
    )
    _states[state.run_id] = state
    return state


def test_ai_suggestions_list_and_unknown(app_with_service, tmp_path):
    client, _, _settings = app_with_service
    state = _install_state(tmp_path)

    response = client.get(f"/api/auto-quant/{state.run_id}/ai-suggestions")

    assert response.status_code == 200
    data = response.json()
    assert data["pending_ai_suggestion_id"] == state.pending_ai_suggestion_id
    assert len(data["suggestions"]) == 1

    missing = client.get("/api/auto-quant/missing-run/ai-suggestions")
    assert missing.status_code == 404


def test_approve_suggestion_applies_and_schedules_resume(app_with_service, tmp_path, monkeypatch):
    client, _, _settings = app_with_service
    state = _install_state(tmp_path)
    scheduled = []

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()

    monkeypatch.setattr("backend.api.routers.auto_quant.asyncio.create_task", fake_create_task)

    response = client.post(
        f"/api/auto-quant/{state.run_id}/ai-suggestions/{state.pending_ai_suggestion_id}/approve"
    )

    assert response.status_code == 200
    assert response.json()["suggestion"]["status"] == "approved"
    assert state.pending_ai_suggestion_id is None
    assert state.hyperopt_loss == "OnlyProfitHyperOptLoss"
    assert scheduled


def test_reject_suggestion_leaves_manual_actions(app_with_service, tmp_path):
    client, _, _settings = app_with_service
    state = _install_state(tmp_path)

    response = client.post(
        f"/api/auto-quant/{state.run_id}/ai-suggestions/{state.pending_ai_suggestion_id}/reject"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["suggestion"]["status"] == "rejected"
    assert data["suggestion"]["decision"]["manual_next_actions"]
    assert state.pending_ai_suggestion_id is None
    assert state.hyperopt_loss == "ProfitLockinHyperOptLoss"


def test_approve_non_pending_returns_409(app_with_service, tmp_path):
    client, _, _settings = app_with_service
    state = _install_state(tmp_path)
    suggestion_id = state.pending_ai_suggestion_id
    state.ai_suggestions[0]["status"] = "rejected"

    response = client.post(f"/api/auto-quant/{state.run_id}/ai-suggestions/{suggestion_id}/approve")

    assert response.status_code == 409
