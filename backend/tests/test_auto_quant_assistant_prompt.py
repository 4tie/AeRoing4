from __future__ import annotations

from backend.services.auto_quant.assistant_prompt import (
    AUTOQUANT_ASSISTANT_CONTEXT_SCHEMA,
    build_autoquant_context,
    build_autoquant_prompt_messages,
    build_autoquant_user_message,
)


def _agent_context() -> dict:
    return {
        "app": {"active_tab": "autoquant", "active_panel": "workflow"},
        "active": {
            "active_tab": "autoquant",
            "active_panel": "workflow",
            "strategy_name": "AIStrategy",
            "auto_quant_run_id": "run-1",
            "sources": {"active_tab": "ui_state"},
        },
        "auto_quant": {
            "run_id": "run-1",
            "strategy_name": "AIStrategy",
            "status": "failed",
            "current_stage": 4,
            "progress_percent": 50,
            "metrics": {
                "score": 0.12,
                "validation_status": "failed",
                "readiness_label": "Rejected",
                "score_explanation": "Failed validation thresholds.",
            },
            "state": {
                "timeframe": "5m",
                "run_config": {
                    "risk_profile": "conservative",
                    "trading_style": "scalping",
                    "analysis_depth": "deep",
                    "selected_pairs": ["BTC/USDT", "ETH/USDT"],
                },
            },
            "stage_reports": [
                {
                    "index": 4,
                    "name": "Validation",
                    "status": "failed",
                    "message": "OOS retention below threshold.",
                    "data": {"profit_factor": 0.92, "min_profit_factor": 1.2},
                    "suggestions": ["Repair entry filters before another run."],
                }
            ],
        },
        "warnings": ["No active optimizer session is selected."],
    }


def test_build_autoquant_context_extracts_copilot_fields() -> None:
    context = build_autoquant_context(_agent_context())

    assert context["schema_version"] == AUTOQUANT_ASSISTANT_CONTEXT_SCHEMA
    assert context["selected_strategy"] == "AIStrategy"
    assert context["timeframe"] == "5m"
    assert context["pairs"] == ["BTC/USDT", "ETH/USDT"]
    assert context["run_status"]["status"] == "failed"
    assert context["user_profile"]["risk_profile"] == "conservative"
    assert context["user_profile"]["trading_style"] == "scalping"
    assert context["user_profile"]["analysis_depth"] == "deep"
    assert context["guardrails"]["read_only_default"] is True
    assert context["guardrails"]["confirmation_required_for_write_or_run_actions"] is True


def test_build_autoquant_context_surfaces_failures_without_inventing_crash() -> None:
    context = build_autoquant_context(_agent_context())

    assert context["stages"][0]["name"] == "Validation"
    assert context["stages"][0]["status"] == "failed"
    assert any(error["severity"] == "failed" for error in context["latest_errors"])
    assert any("OOS retention" in error["message"] for error in context["latest_errors"])


def test_user_message_wrapper_contains_context_and_confirmation_rule() -> None:
    context = build_autoquant_context(_agent_context())
    wrapped = build_autoquant_user_message("Why did it fail?", context)

    assert "Why did it fail?" in wrapped
    assert "AutoQuant backend context JSON" in wrapped
    assert '"selected_strategy": "AIStrategy"' in wrapped
    assert "requiring user confirmation" in wrapped


def test_prompt_messages_use_autoquant_system_prompt_and_history() -> None:
    messages = build_autoquant_prompt_messages(
        "What should I do next?",
        _agent_context(),
        history=[{"role": "user", "content": "previous"}, {"role": "assistant", "content": "answer"}],
    )

    assert messages[0]["role"] == "system"
    assert "AI suggests -> backend validates -> Freqtrade tests -> AutoQuant decides" in messages[0]["content"]
    assert messages[1]["content"] == "previous"
    assert messages[2]["content"] == "answer"
    assert messages[-1]["role"] == "user"
    assert "What should I do next?" in messages[-1]["content"]
