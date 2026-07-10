from __future__ import annotations

from pathlib import Path

import pytest

from backend.services.auto_quant.ai_suggestions import (
    approve_suggestion,
    create_pending_suggestion,
    get_suggestion,
    normalize_ai_suggestions,
    reject_suggestion,
    validate_proposed_changes,
)
from backend.services.auto_quant.pipeline_modules.config import STAGE_NAMES
from backend.services.auto_quant.pipeline_modules.state import PipelineState, StageState


def _state(tmp_path: Path) -> PipelineState:
    return PipelineState(
        run_id="run-ai",
        strategy="TestStrategy",
        timeframe="5m",
        in_sample_range="20230101-20240101",
        out_sample_range="20240101-20240601",
        exchange="binance",
        config_file=str(tmp_path / "config.json"),
        freqtrade_path="freqtrade",
        user_data_dir=str(tmp_path / "user_data"),
        current_stage=1,
        stages=[StageState(index=i + 1, name=name) for i, name in enumerate(STAGE_NAMES)],
        hyperopt_loss="ProfitLockinHyperOptLoss",
        hyperopt_spaces=["stoploss", "roi"],
        hyperopt_epochs=100,
    )


def test_legacy_ai_suggestions_dict_normalizes_to_list() -> None:
    legacy = {"suggestion-a": {"summary": "Review retry"}}

    normalized = normalize_ai_suggestions(legacy)

    assert normalized == [{"id": "suggestion-a", "summary": "Review retry"}]


def test_pending_suggestion_does_not_mutate_config(tmp_path: Path) -> None:
    state = _state(tmp_path)

    suggestion = create_pending_suggestion(
        state=state,
        trigger="sharp_peak",
        failure_reason="sensitivity",
        retry_attempt=1,
        source="deterministic",
    )

    assert state.pending_ai_suggestion_id == suggestion["id"]
    assert state.hyperopt_loss == "ProfitLockinHyperOptLoss"
    assert state.hyperopt_spaces == ["stoploss", "roi"]
    assert state.hyperopt_epochs == 100
    assert state.param_overrides == {}


def test_approve_applies_validated_changes_through_state(tmp_path: Path) -> None:
    state = _state(tmp_path)
    suggestion = create_pending_suggestion(
        state=state,
        trigger="wfo_pass_rate",
        failure_reason="segment_pass_rate_below_50%",
        retry_attempt=1,
        source="deterministic",
        proposed_changes={
            "hyperopt_loss": "SharpeHyperOptLoss",
            "hyperopt_spaces": ["buy", "roi"],
            "hyperopt_epochs": 125,
            "param_overrides": {"use_atr": True},
        },
    )

    approved = approve_suggestion(state, suggestion["id"])

    assert approved["status"] == "approved"
    assert state.pending_ai_suggestion_id is None
    assert state.hyperopt_loss == "SharpeHyperOptLoss"
    assert state.hyperopt_spaces == ["buy", "roi"]
    assert state.hyperopt_epochs == 125
    assert state.param_overrides == {"use_atr": True}
    assert state.retry_count == 1
    assert state.current_stage == STAGE_NAMES.index("Standard Hyperopt") + 1


def test_reject_applies_nothing_and_exposes_manual_actions(tmp_path: Path) -> None:
    state = _state(tmp_path)
    suggestion = create_pending_suggestion(
        state=state,
        trigger="negative_baseline",
        failure_reason="FAIL_NEGATIVE_BASELINE",
        retry_attempt=1,
        source="deterministic",
    )

    rejected = reject_suggestion(state, suggestion["id"])

    assert rejected["status"] == "rejected"
    assert state.pending_ai_suggestion_id is None
    assert state.hyperopt_loss == "ProfitLockinHyperOptLoss"
    assert state.param_overrides == {}
    assert rejected["decision"]["manual_next_actions"]


def test_invalid_suggestion_states_raise(tmp_path: Path) -> None:
    state = _state(tmp_path)

    with pytest.raises(KeyError):
        get_suggestion(state, "missing") or (_ for _ in ()).throw(KeyError("missing"))

    with pytest.raises(ValueError):
        validate_proposed_changes({"live_trading": True})
