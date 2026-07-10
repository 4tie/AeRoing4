"""Auto Safe optimizer search-space policy.

This module intentionally avoids scoring and metric formulas. It only decides
which parameter search spaces are enabled in conservative optimizer mode.
"""

from __future__ import annotations

from typing import Any

from ...models import (
    AutoLockEvent,
    OptimizerParameterMode,
    OptimizerSession,
    OptimizerTrialStatus,
    ParameterSearchSpace,
    SearchStrategy,
)
from ...utils import utc_now

AUTO_SAFE_INITIAL_CAP = 6
AUTO_SAFE_RUNTIME_TARGET = 4
AUTO_SAFE_GUARD_WINDOW = 5
AUTO_SAFE_TRIGGER_COUNT = 3
SAFE_CORE_SPACES = {"buy", "sell"}


def apply_auto_safe_initial_spaces(
    spaces: list[ParameterSearchSpace],
) -> list[ParameterSearchSpace]:
    """Enable only conservative buy/sell strategy params, capped by source order."""
    enabled_count = 0
    updated: list[ParameterSearchSpace] = []
    for space in spaces:
        group = infer_space(space)
        should_enable = (
            group in SAFE_CORE_SPACES
            and bool(space.optimizable)
            and enabled_count < AUTO_SAFE_INITIAL_CAP
        )
        if should_enable:
            enabled_count += 1
        updated.append(space.model_copy(update={"enabled": should_enable}))
    return updated


def build_auto_safe_narrowing_event(
    session: OptimizerSession,
    next_trial_number: int,
) -> tuple[list[ParameterSearchSpace], AutoLockEvent | None]:
    """Return narrowed search spaces and an audit event when the guard triggers."""
    if session.config.parameter_mode != OptimizerParameterMode.AUTO_SAFE:
        return session.config.search_spaces, None

    reason = _guard_reason(session)
    if reason is None:
        return session.config.search_spaces, None

    enabled_spaces = [s for s in session.config.search_spaces if s.enabled]
    locked_names = _select_runtime_locks(enabled_spaces)
    if not locked_names:
        return session.config.search_spaces, None

    locked = set(locked_names)
    updated_spaces = [
        s.model_copy(update={"enabled": False}) if s.name in locked else s
        for s in session.config.search_spaces
    ]
    before_count = len(enabled_spaces)
    after_count = sum(1 for s in updated_spaces if s.enabled)

    grid_epoch_before: int | None = None
    grid_epoch_after: int | None = None
    grid_epoch_start_trial: int | None = None
    if session.config.search_strategy == SearchStrategy.GRID:
        grid_epoch_before = session.grid_epoch
        grid_epoch_after = session.grid_epoch + 1
        grid_epoch_start_trial = next_trial_number

    event = AutoLockEvent(
        created_at=utc_now(),
        trial_number=next_trial_number,
        reason=reason,
        locked_params=locked_names,
        before_enabled_count=before_count,
        after_enabled_count=after_count,
        grid_epoch_before=grid_epoch_before,
        grid_epoch_after=grid_epoch_after,
        grid_epoch_start_trial=grid_epoch_start_trial,
    )
    return updated_spaces, event


def infer_space(space: ParameterSearchSpace | dict[str, Any]) -> str:
    """Infer the optimizer group for a search space."""
    if isinstance(space, dict):
        raw_space = space.get("space")
        name = str(space.get("name") or "")
    else:
        raw_space = space.space
        name = space.name
    if raw_space:
        return str(raw_space)
    if name.startswith("roi__"):
        return "roi"
    if name.startswith("trailing__"):
        return "trailing"
    if name.startswith("stoploss__"):
        return "stoploss"
    return "custom"


def _guard_reason(session: OptimizerSession) -> str | None:
    terminal = [
        trial
        for trial in session.trials
        if _status_value(trial.status) in {
            OptimizerTrialStatus.COMPLETED.value,
            OptimizerTrialStatus.FAILED.value,
            OptimizerTrialStatus.PRUNED.value,
        }
    ]
    latest = terminal[-AUTO_SAFE_GUARD_WINDOW:]
    if len(latest) < AUTO_SAFE_TRIGGER_COUNT:
        return None

    failed_count = sum(
        1
        for trial in latest
        if _status_value(trial.status) == OptimizerTrialStatus.FAILED.value
    )
    zero_trade_count = sum(
        1
        for trial in latest
        if _status_value(trial.status) == OptimizerTrialStatus.COMPLETED.value
        and trial.metrics is not None
        and trial.metrics.total_trades == 0
    )

    failure_triggered = failed_count >= AUTO_SAFE_TRIGGER_COUNT
    zero_trade_triggered = zero_trade_count >= AUTO_SAFE_TRIGGER_COUNT
    if failure_triggered and zero_trade_triggered:
        return "repeated_failures_and_zero_trade_trials"
    if failure_triggered:
        return "repeated_failures"
    if zero_trade_triggered:
        return "zero_trade_trials"
    return None


def _select_runtime_locks(enabled_spaces: list[ParameterSearchSpace]) -> list[str]:
    non_core = [s.name for s in enabled_spaces if infer_space(s) not in SAFE_CORE_SPACES]
    if non_core:
        return non_core

    if len(enabled_spaces) <= AUTO_SAFE_RUNTIME_TARGET:
        return []

    counts = {
        "buy": sum(1 for s in enabled_spaces if infer_space(s) == "buy"),
        "sell": sum(1 for s in enabled_spaces if infer_space(s) == "sell"),
    }
    locked: list[str] = []
    remaining_count = len(enabled_spaces)

    for space in reversed(enabled_spaces):
        if remaining_count <= AUTO_SAFE_RUNTIME_TARGET:
            break
        group = infer_space(space)
        if group in SAFE_CORE_SPACES and counts[group] <= 1:
            continue
        locked.append(space.name)
        remaining_count -= 1
        if group in counts:
            counts[group] -= 1

    locked.reverse()
    return locked


def _status_value(status: Any) -> str:
    return str(getattr(status, "value", status))
