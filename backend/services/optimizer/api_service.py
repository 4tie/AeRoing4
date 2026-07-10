"""Optimizer API helper services.

These functions keep route handlers focused on HTTP wiring while preserving
the existing Optimizer tab contracts and response payloads.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from ...api.session_store import SessionStore
from ...core.optimizer_errors import OptimizerError, OptimizerErrorCode

logger = logging.getLogger(__name__)

TERMINAL_PHASES = {"completed", "failed", "cancelled"}
MAX_MONITOR_TIME = 3600
POLL_INTERVAL = 4.0


def enum_value(value: Any) -> Any:
    """Return enum.value when present, otherwise the original value."""
    return getattr(value, "value", value)


def optimizer_error_status(exc: OptimizerError) -> int:
    """Map internal optimizer errors to stable frontend-friendly HTTP codes."""
    if exc.code == OptimizerErrorCode.SESSION_NOT_FOUND:
        return 404
    if exc.code in {
        OptimizerErrorCode.SESSION_ALREADY_RUNNING,
        OptimizerErrorCode.RESOURCE_LOCKED,
        OptimizerErrorCode.BACKTEST_RUNNER_BUSY,
    }:
        return 409
    if exc.code in {
        OptimizerErrorCode.INVALID_PARAMETERS,
        OptimizerErrorCode.TRIAL_VALIDATION_FAILED,
        OptimizerErrorCode.VALIDATION_ERROR,
    }:
        return 400
    if exc.code == OptimizerErrorCode.TIMEOUT_EXPIRED:
        return 504
    return 500


def load_session_or_404(services: Any, session_id: str):
    """Load an optimizer session and map store errors to HTTP exceptions."""
    try:
        session = services.optimizer_store.load_session(session_id)
    except OptimizerError as exc:
        raise HTTPException(status_code=optimizer_error_status(exc), detail=exc.message)
    except Exception as exc:
        logger.error("Error loading optimizer session %s: %s", session_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load optimizer session: {exc}",
        )
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Optimizer session '{session_id}' not found.",
        )
    return session


def space_by_name(session) -> dict[str, str]:
    spaces = getattr(getattr(session, "config", None), "search_spaces", []) or []
    return {
        space.name: enum_value(space.space) or ""
        for space in spaces
        if getattr(space, "name", None)
    }


def flat_params_to_freqtrade_format(
    strategy_name: str,
    parameters: dict,
    spaces_by_name: dict[str, str] | None = None,
) -> dict:
    """Convert flat optimizer trial keys into Freqtrade-compatible nested format."""
    buy: dict = {}
    sell: dict = {}
    roi: dict = {}
    stoploss: float | None = None
    trailing: dict = {}
    custom: dict = {}
    protection: dict = {}
    spaces_by_name = spaces_by_name or {}

    for key, value in parameters.items():
        if key.startswith("buy__"):
            buy[key[5:]] = value
        elif key.startswith("sell__"):
            sell[key[6:]] = value
        elif key.startswith("roi__"):
            roi[key[5:]] = value
        elif key == "stoploss__value":
            stoploss = value
        elif key == "trailing__stop":
            trailing["trailing_stop"] = value
        elif key in ("trailing__positive", "trailing__positive_offset"):
            trailing["trailing_stop_positive"] = value
        elif key == "trailing__offset":
            trailing["trailing_stop_positive_offset"] = value
        elif key == "trailing__only_offset_is_reached":
            trailing["trailing_only_offset_is_reached"] = value
        else:
            space = spaces_by_name.get(key)
            if space == "buy":
                buy[key] = value
            elif space == "sell":
                sell[key] = value
            elif space == "protection":
                protection[key] = value
            elif space == "custom":
                custom[key] = value

    params = {
        "buy": buy,
        "sell": sell,
        "roi": roi,
        "trailing": trailing,
    }
    if stoploss is not None:
        params["stoploss"] = stoploss
    if protection:
        params["protection"] = protection
    if custom:
        params["custom"] = custom

    return {
        "strategy_name": strategy_name,
        "params": params,
    }


def get_trial_by_number(session, trial_number: int):
    trial = next((t for t in session.trials if t.trial_number == trial_number), None)
    if trial is None:
        logger.warning("Trial #%s not found in session %s", trial_number, session.session_id)
        raise HTTPException(
            status_code=404,
            detail=f"Trial #{trial_number} not found in session '{session.session_id}'.",
        )
    return trial


async def monitor_optimizer(
    services,
    store: SessionStore,
    api_session_id: str,
    optimizer_session_id: str,
) -> None:
    """Poll the internal optimizer store until the session reaches a terminal phase."""
    start_time = datetime.now(tz=UTC)

    logger.info("Starting optimizer monitoring for session %s", optimizer_session_id)

    while True:
        if (datetime.now(tz=UTC) - start_time).total_seconds() > MAX_MONITOR_TIME:
            error_msg = f"Optimizer monitoring timed out after {MAX_MONITOR_TIME} seconds"
            logger.error("%s for session %s", error_msg, optimizer_session_id)
            store.update(
                api_session_id,
                status="failed",
                completed_at=datetime.now(tz=UTC),
                error=error_msg,
            )
            try:
                await services.strategy_optimizer.cancel_session(optimizer_session_id)
            except Exception as cancel_exc:
                logger.error("Failed to cancel timed-out session: %s", cancel_exc)
            return

        await asyncio.sleep(POLL_INTERVAL)
        try:
            session = services.optimizer_store.load_session(optimizer_session_id)
        except FileNotFoundError:
            error_msg = f"Optimizer session '{optimizer_session_id}' not found in store."
            logger.error(error_msg)
            store.update(
                api_session_id,
                status="failed",
                completed_at=datetime.now(tz=UTC),
                error=error_msg,
            )
            return
        except Exception as exc:
            error_msg = f"Failed to load optimizer session: {exc}"
            logger.error(error_msg)
            store.update(
                api_session_id,
                status="failed",
                completed_at=datetime.now(tz=UTC),
                error=error_msg,
            )
            return

        if session is None:
            error_msg = f"Optimizer session '{optimizer_session_id}' returned null from store."
            logger.error(error_msg)
            store.update(
                api_session_id,
                status="failed",
                completed_at=datetime.now(tz=UTC),
                error=error_msg,
            )
            return

        phase_value = enum_value(session.phase)
        if phase_value in TERMINAL_PHASES:
            final_status = (
                "completed" if phase_value == "completed"
                else "cancelled" if phase_value == "cancelled"
                else "failed"
            )
            best_score: float | None = (
                session.best_metrics.score if session.best_metrics else None
            )
            logger.info(
                "Optimizer session %s completed with status: %s",
                optimizer_session_id,
                final_status,
            )
            store.update(
                api_session_id,
                status=final_status,
                completed_at=datetime.now(tz=UTC),
                result={
                    "optimizer_session_id": optimizer_session_id,
                    "phase": phase_value,
                    "total_trials": session.total_trials,
                    "completed_trials": session.completed_trials,
                    "failed_trials": session.failed_trials,
                    "best_trial_number": session.best_trial_number,
                    "best_score": best_score,
                    "stop_reason": session.stop_reason,
                },
            )
            return
