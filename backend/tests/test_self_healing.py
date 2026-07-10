"""Self-healing retry approval tests for the current AutoQuant flow."""

from __future__ import annotations

import pytest

from backend.services.auto_quant.ai_suggestions import (
    ai_assistance_summary,
    approve_suggestion,
    create_pending_suggestion,
    optimization_stage_index,
    reject_suggestion,
)

from .test_helpers import _make_state


def test_pending_ai_suggestion_does_not_mutate_retry_settings(tmp_path):
    state = _make_state(
        str(tmp_path),
        hyperopt_loss="ProfitLockinHyperOptLoss",
        hyperopt_spaces=["buy", "stoploss", "roi"],
        hyperopt_epochs=100,
        param_overrides={"use_atr": False},
    )

    suggestion = create_pending_suggestion(
        state=state,
        trigger="negative_baseline",
        failure_reason="FAIL_NEGATIVE_BASELINE",
        retry_attempt=1,
        source="deterministic",
    )

    assert state.pending_ai_suggestion_id == suggestion["id"]
    assert suggestion["status"] == "pending"
    assert state.retry_count == 0
    assert state.hyperopt_loss == "ProfitLockinHyperOptLoss"
    assert state.hyperopt_spaces == ["buy", "stoploss", "roi"]
    assert state.hyperopt_epochs == 100
    assert state.param_overrides == {"use_atr": False}


def test_approve_ai_suggestion_applies_validated_changes_and_resumes_from_optimization(tmp_path):
    state = _make_state(
        str(tmp_path),
        hyperopt_loss="ProfitLockinHyperOptLoss",
        hyperopt_spaces=["buy", "stoploss", "roi"],
        hyperopt_epochs=100,
    )
    suggestion = create_pending_suggestion(
        state=state,
        trigger="wfo_pass_rate",
        failure_reason="segment_pass_rate_below_50%",
        retry_attempt=1,
        source="deterministic",
        proposed_changes={
            "hyperopt_loss": "SharpeHyperOptLoss",
            "hyperopt_spaces": ["roi", "stoploss"],
            "hyperopt_epochs": 150,
            "param_overrides": {"use_atr": True, "use_adx": True},
        },
    )

    approved = approve_suggestion(state, suggestion["id"])

    assert approved["status"] == "approved"
    assert state.pending_ai_suggestion_id is None
    assert state.status == "running"
    assert state.current_stage == optimization_stage_index()
    assert state.retry_count == 1
    assert state.hyperopt_loss == "SharpeHyperOptLoss"
    assert state.hyperopt_spaces == ["roi", "stoploss"]
    assert state.hyperopt_epochs == 150
    assert state.param_overrides == {"use_atr": True, "use_adx": True}
    assert state.retry_history[-1]["ai_suggestion_id"] == suggestion["id"]
    assert state.retry_history[-1]["approved"] is True


def test_reject_ai_suggestion_applies_nothing_and_exposes_manual_actions(tmp_path):
    state = _make_state(
        str(tmp_path),
        hyperopt_loss="ProfitLockinHyperOptLoss",
        hyperopt_spaces=["buy", "stoploss", "roi"],
        hyperopt_epochs=100,
        param_overrides={"use_ema_cross": False},
    )
    suggestion = create_pending_suggestion(
        state=state,
        trigger="sharp_peak",
        failure_reason="FAIL_SHARP_PEAK",
        retry_attempt=1,
        source="deterministic",
    )

    rejected = reject_suggestion(state, suggestion["id"])
    summary = ai_assistance_summary(state)

    assert rejected["status"] == "rejected"
    assert state.pending_ai_suggestion_id is None
    assert state.status == "awaiting_user_approval"
    assert state.retry_count == 0
    assert state.hyperopt_loss == "ProfitLockinHyperOptLoss"
    assert state.hyperopt_spaces == ["buy", "stoploss", "roi"]
    assert state.hyperopt_epochs == 100
    assert state.param_overrides == {"use_ema_cross": False}
    assert {action["id"] for action in summary["manual_next_actions"]} >= {
        "inspect_logs",
        "cancel_run",
        "new_run",
    }


def test_non_pending_suggestion_cannot_be_approved_or_rejected_again(tmp_path):
    state = _make_state(str(tmp_path))
    suggestion = create_pending_suggestion(
        state=state,
        trigger="wfo_pass_rate",
        failure_reason="segment_pass_rate_below_50%",
        retry_attempt=1,
        source="deterministic",
    )

    approve_suggestion(state, suggestion["id"])

    with pytest.raises(RuntimeError):
        approve_suggestion(state, suggestion["id"])
    with pytest.raises(RuntimeError):
        reject_suggestion(state, suggestion["id"])
