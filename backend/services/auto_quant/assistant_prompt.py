"""Prompt and context helpers for the AutoQuant copilot.

This module is intentionally pure/read-only. It converts the broader agent
context into a bounded prompt payload for Ollama without starting runs, editing
files, exporting artifacts, or mutating backend state.
"""

from __future__ import annotations

import json
from typing import Any

AUTOQUANT_ASSISTANT_CONTEXT_SCHEMA = "autoquant_assistant_context_v1"
AUTOQUANT_ASSISTANT_PROMPT_VERSION = "autoquant_copilot_prompt_v1"
MAX_CONTEXT_CHARS = 36000
MAX_STAGE_COUNT = 12
MAX_ERROR_COUNT = 8
MAX_PAIR_COUNT = 30

AUTOQUANT_COPILOT_SYSTEM_PROMPT = """You are Fourty, the AutoQuant copilot inside the Strategy Lab app.

Mission:
Help the user understand and improve the current AutoQuant workflow using only
backend-provided context. Act like an app-native trading validation copilot, not
a generic chatbot.

Core operating rule:
AI suggests -> backend validates -> Freqtrade tests -> AutoQuant decides.

Hard rules:
- Treat the AutoQuant context JSON as the source of truth.
- Never invent metrics, selected pairs, timeframe, run status, failures, scores,
  readiness labels, or validation results.
- Never promise profit, safety, or live-trading success.
- Be read-only by default. You may recommend actions, but you must not claim to
  run, rerun, export, promote, edit, write files, deploy, or start live/dry-run
  trading unless the backend confirms that action happened.
- Any write/run/export/promote action requires explicit user confirmation and a
  backend action endpoint. When a user asks for such an action, explain what
  would be done and ask them to confirm through the UI.
- Distinguish controlled validation failures from system errors.
- Explain failures plainly: what failed, what evidence shows it, why it matters,
  and the safest next action.
- Recommend next actions based on validation stage, metrics, warnings, and
  errors already present in context.

Response contract:
1. Start with the current status in one or two sentences.
2. If there is a failure or warning, explain it in plain language.
3. Cite available backend facts by naming the stage/metric; do not fabricate
   numbers.
4. Give 1-3 concrete next actions, marking each as read-only, needs confirmation,
   or blocked.
5. Keep the answer concise unless analysis_depth is deep or the user asks for a
   detailed explanation.
"""


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _bounded_list(values: Any, limit: int) -> list[Any]:
    items = list(values) if isinstance(values, list) else []
    return items[: max(0, limit)]


def _safe_get(mapping: dict[str, Any], *path: str, default: Any = None) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current is not None else default


def _compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}


def _stage_context(stage: Any) -> dict[str, Any]:
    item = _as_dict(stage)
    data = _as_dict(item.get("data"))
    error = item.get("error") or data.get("error")
    errors = item.get("errors") or data.get("errors") or ([error] if error else [])
    warnings = item.get("warnings") or data.get("warnings") or []
    suggestions = item.get("suggestions") or data.get("suggestions") or []

    return _compact_dict(
        {
            "index": item.get("index"),
            "name": item.get("name") or item.get("stage"),
            "status": item.get("status"),
            "message": item.get("message"),
            "input_summary": item.get("input_summary") or data.get("input_summary"),
            "output_summary": item.get("output_summary") or data.get("output_summary"),
            "metrics": item.get("metrics") or data.get("metrics") or data,
            "warnings": warnings,
            "errors": errors,
            "retry_attempts": item.get("retry_attempts") or data.get("retry_attempts"),
            "suggestions": suggestions,
        }
    )


def _extract_run_config(auto_quant: dict[str, Any], optimizer: dict[str, Any]) -> dict[str, Any]:
    state = _as_dict(auto_quant.get("state"))
    config = _first_present(
        state.get("run_config"),
        state.get("config"),
        state.get("run_config_snapshot"),
        auto_quant.get("run_config"),
        auto_quant.get("config"),
        optimizer.get("config"),
    )
    return _as_dict(config)


def _extract_latest_errors(context: dict[str, Any], stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    warnings = _as_list(context.get("warnings"))
    for warning in warnings[-MAX_ERROR_COUNT:]:
        errors.append({"source": "context_warning", "severity": "warning", "message": str(warning)})

    auto_quant = _as_dict(context.get("auto_quant"))
    state = _as_dict(auto_quant.get("state"))
    for key in ("error", "last_error", "failure_reason"):
        value = state.get(key) or auto_quant.get(key)
        if value:
            errors.append({"source": f"auto_quant.{key}", "severity": "error", "message": str(value)})

    for stage in stages:
        stage_name = stage.get("name") or stage.get("index") or "stage"
        for warning in _as_list(stage.get("warnings"))[-2:]:
            errors.append({"source": str(stage_name), "severity": "warning", "message": str(warning)})
        for error in _as_list(stage.get("errors"))[-2:]:
            errors.append({"source": str(stage_name), "severity": "error", "message": str(error)})
        status = str(stage.get("status") or "").lower()
        if status in {"failed", "error", "blocked"} and stage.get("message"):
            errors.append({"source": str(stage_name), "severity": status, "message": str(stage["message"])})

    events = _as_list(_safe_get(auto_quant, "events", "recent", default=[]))
    for event in events[-MAX_ERROR_COUNT:]:
        item = _as_dict(event)
        level = str(item.get("level") or item.get("severity") or "").lower()
        if level in {"warning", "error", "failed", "failure"}:
            errors.append(
                {
                    "source": str(item.get("stage") or item.get("source") or "event"),
                    "severity": level,
                    "message": str(item.get("message") or item),
                }
            )

    return errors[-MAX_ERROR_COUNT:]


def build_autoquant_context(
    agent_context: dict[str, Any],
    *,
    user_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a bounded AutoQuant-specific context payload for Ollama."""
    context = _as_dict(agent_context)
    active = _as_dict(context.get("active"))
    app = _as_dict(context.get("app"))
    ui_state = _as_dict(app.get("ui_state"))
    auto_quant = _as_dict(context.get("auto_quant"))
    optimizer = _as_dict(context.get("optimizer"))
    backtest = _as_dict(context.get("backtest"))
    strategy = _as_dict(context.get("strategy"))
    run_config = _extract_run_config(auto_quant, optimizer)

    raw_stages = _first_present(auto_quant.get("stage_reports"), _safe_get(auto_quant, "state", "stages"), [])
    stages = [_stage_context(stage) for stage in _bounded_list(raw_stages, MAX_STAGE_COUNT)]
    latest_errors = _extract_latest_errors(context, stages)

    pairs = _first_present(
        run_config.get("selected_pairs"),
        run_config.get("pairs"),
        _safe_get(backtest, "metadata", "pairs"),
        _safe_get(optimizer, "config", "pairs"),
        [],
    )

    normalized_user_profile = _compact_dict(
        {
            "risk_profile": _first_present(
                (user_profile or {}).get("risk_profile"),
                run_config.get("risk_profile"),
                ui_state.get("risk_profile"),
            ),
            "trading_style": _first_present(
                (user_profile or {}).get("trading_style"),
                run_config.get("trading_style"),
                ui_state.get("trading_style"),
            ),
            "analysis_depth": _first_present(
                (user_profile or {}).get("analysis_depth"),
                run_config.get("analysis_depth"),
                ui_state.get("analysis_depth"),
                "normal",
            ),
        }
    )

    return _compact_dict(
        {
            "schema_version": AUTOQUANT_ASSISTANT_CONTEXT_SCHEMA,
            "prompt_version": AUTOQUANT_ASSISTANT_PROMPT_VERSION,
            "current_tab_context": _compact_dict(
                {
                    "active_tab": active.get("active_tab") or app.get("active_tab"),
                    "active_panel": active.get("active_panel") or app.get("active_panel"),
                    "sources": active.get("sources"),
                }
            ),
            "selected_strategy": _first_present(
                active.get("strategy_name"),
                auto_quant.get("strategy_name"),
                strategy.get("strategy_name"),
                optimizer.get("strategy_name"),
                backtest.get("strategy_name"),
                run_config.get("strategy"),
            ),
            "timeframe": _first_present(
                run_config.get("timeframe"),
                _safe_get(auto_quant, "state", "timeframe"),
                _safe_get(backtest, "metadata", "timeframe"),
                _safe_get(optimizer, "config", "timeframe"),
            ),
            "pairs": _bounded_list(pairs, MAX_PAIR_COUNT),
            "pairs_truncated": isinstance(pairs, list) and len(pairs) > MAX_PAIR_COUNT,
            "user_profile": normalized_user_profile,
            "run_status": _compact_dict(
                {
                    "run_id": auto_quant.get("run_id") or active.get("auto_quant_run_id"),
                    "status": auto_quant.get("status"),
                    "current_stage": auto_quant.get("current_stage"),
                    "progress_percent": auto_quant.get("progress_percent"),
                    "validation_status": _safe_get(auto_quant, "metrics", "validation_status"),
                    "readiness_label": _safe_get(auto_quant, "metrics", "readiness_label"),
                    "score": _safe_get(auto_quant, "metrics", "score"),
                    "score_explanation": _safe_get(auto_quant, "metrics", "score_explanation"),
                }
            ),
            "metrics": _compact_dict(
                {
                    "auto_quant": auto_quant.get("metrics"),
                    "optimizer": optimizer.get("metrics"),
                    "backtest": backtest.get("metrics"),
                }
            ),
            "latest_errors": latest_errors,
            "stages": stages,
            "guardrails": {
                "read_only_default": True,
                "must_not_promise_profit": True,
                "must_not_invent_metrics": True,
                "confirmation_required_for_write_or_run_actions": True,
                "allowed_without_confirmation": ["explain", "diagnose", "summarize", "recommend_next_actions"],
                "blocked_without_backend_confirmation": [
                    "start_run",
                    "rerun_stage",
                    "run_backtest",
                    "run_optimizer",
                    "export",
                    "promote_candidate",
                    "edit_strategy",
                    "deploy_live",
                    "deploy_dry_run",
                ],
            },
        }
    )


def build_autoquant_user_message(user_message: str, assistant_context: dict[str, Any]) -> str:
    """Wrap the user's text with a backend-owned context payload."""
    context_json = json.dumps(assistant_context, indent=2, sort_keys=True, default=str)
    if len(context_json) > MAX_CONTEXT_CHARS:
        context_json = context_json[:MAX_CONTEXT_CHARS] + f"\n...[context truncated {len(context_json) - MAX_CONTEXT_CHARS} chars]"

    return (
        "User message:\n"
        f"{user_message.strip()}\n\n"
        "AutoQuant backend context JSON. Use this as source of truth:\n"
        "```json\n"
        f"{context_json}\n"
        "```\n\n"
        "Answer as the AutoQuant copilot. Recommend only safe next actions. "
        "Mark write/run/export/promote actions as requiring user confirmation."
    )


def build_autoquant_prompt_messages(
    user_message: str,
    agent_context: dict[str, Any],
    *,
    history: list[dict[str, Any]] | None = None,
    user_profile: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Build Ollama chat messages for the AutoQuant copilot."""
    assistant_context = build_autoquant_context(agent_context, user_profile=user_profile)
    previous = [
        {"role": str(item.get("role")), "content": str(item.get("content", ""))}
        for item in (history or [])[-6:]
        if item.get("role") in {"user", "assistant"} and item.get("content")
    ]
    return [
        {"role": "system", "content": AUTOQUANT_COPILOT_SYSTEM_PROMPT},
        *previous,
        {"role": "user", "content": build_autoquant_user_message(user_message, assistant_context)},
    ]
