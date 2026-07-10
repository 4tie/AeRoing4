"""Algorithmic search helpers for strategy optimizer trial selection."""

from __future__ import annotations

import random
from typing import Any

from ...models import (
    OptimizerSession,
    OptimizerTrialStatus,
    ParameterSearchSpace,
    ParameterSearchType,
    SearchStrategy,
)

GRID_SCAN_LIMIT = 100_000


def select_parameters_for_trial(
    session: OptimizerSession,
    spaces: list[ParameterSearchSpace],
    trial_number: int,
) -> dict[str, Any]:
    """Choose the next trial parameter set from the configured search strategy."""
    strategy = session.config.search_strategy
    if strategy == SearchStrategy.RANDOM:
        return _random_search(spaces, trial_number)
    if strategy == SearchStrategy.GRID:
        return _grid_search(session, spaces, trial_number)
    if strategy == SearchStrategy.BAYESIAN:
        return _bayesian_search(session, spaces, trial_number)
    if strategy == SearchStrategy.EVOLUTIONARY:
        return _evolutionary_search(session, spaces, trial_number)
    return _random_search(spaces, trial_number)


def _random_search(spaces: list[ParameterSearchSpace], trial_number: int) -> dict[str, Any]:
    """Sample parameter values independently at random."""
    params: dict[str, Any] = {}
    roi_spaces = [s for s in spaces if s.name.startswith("roi__")]
    other_spaces = [s for s in spaces if not s.name.startswith("roi__")]

    if roi_spaces:
        params.update(_sample_roi_monotonic(roi_spaces, trial_number))

    for space in other_spaces:
        params[space.name] = _sample_one(space, trial_number)

    return params


def _grid_search(
    session: OptimizerSession,
    spaces: list[ParameterSearchSpace],
    trial_number: int,
) -> dict[str, Any]:
    """Select parameter values from deterministic grid combinations."""
    total = _grid_total_count(spaces)
    if total <= 0:
        return {}

    epoch_start = max(int(session.grid_epoch_start_trial or 1), 1)
    local_index = max(trial_number - epoch_start, 0)

    roi_spaces = [s for s in spaces if s.name.startswith("roi__")]
    if roi_spaces:
        return _grid_roi_candidate(spaces, roi_spaces, local_index, total)

    index = min(local_index, total - 1)
    return _grid_candidate_at(spaces, index)


def _bayesian_search(
    session: OptimizerSession,
    spaces: list[ParameterSearchSpace],
    trial_number: int,
) -> dict[str, Any]:
    """Choose parameters using lightweight history-aware exploration."""
    completed = [
        t for t in (session.trials or [])
        if t.status == OptimizerTrialStatus.COMPLETED and t.metrics is not None
    ]
    if not completed:
        return _random_search(spaces, trial_number)

    best = max(completed, key=lambda t: t.metrics.score or float("-inf"))
    params: dict[str, Any] = {}
    roi_spaces = [s for s in spaces if s.name.startswith("roi__")]
    other_spaces = [s for s in spaces if not s.name.startswith("roi__")]

    if roi_spaces:
        params.update(_sample_roi_monotonic(roi_spaces, trial_number))

    for space in other_spaces:
        previous = best.parameters.get(space.name)
        if (
            space.param_type in {ParameterSearchType.INT, ParameterSearchType.DECIMAL}
            and previous is not None
        ):
            if isinstance(previous, (int, float)) and space.min_value is not None and space.max_value is not None:
                span = float(space.max_value) - float(space.min_value)
                delta = max(span * 0.1, float(space.step or 1.0))
                if space.param_type == ParameterSearchType.INT:
                    candidates = [int(previous), int(previous + delta), int(previous - delta)]
                else:
                    candidates = [float(previous), float(previous + delta), float(previous - delta)]
                candidates = [c for c in candidates if c is not None]
                candidates = [
                    min(max(c, float(space.min_value)), float(space.max_value))
                    for c in candidates
                ]
                params[space.name] = random.choice(candidates)
                continue
        if space.param_type == ParameterSearchType.CATEGORICAL and space.choices:
            params[space.name] = previous if previous in space.choices else random.choice(space.choices)
        elif space.param_type == ParameterSearchType.BOOLEAN:
            params[space.name] = previous if isinstance(previous, bool) else random.choice(space.choices or [True, False])
        else:
            params[space.name] = _sample_one(space, trial_number)

    return params


def _evolutionary_search(
    session: OptimizerSession,
    spaces: list[ParameterSearchSpace],
    trial_number: int,
) -> dict[str, Any]:
    """Mutate strong prior trials and blend with random exploration."""
    completed = [t for t in (session.trials or []) if t.status == OptimizerTrialStatus.COMPLETED]
    if not completed:
        return _random_search(spaces, trial_number)

    parent = random.choice(completed)
    params = dict(parent.parameters)
    roi_spaces = [s for s in spaces if s.name.startswith("roi__")]
    other_spaces = [s for s in spaces if not s.name.startswith("roi__")]

    if roi_spaces and random.random() > 0.5:
        params.update(_sample_roi_monotonic(roi_spaces, trial_number))

    for space in other_spaces:
        if random.random() > 0.5:
            continue
        current = params.get(space.name)
        if space.param_type == ParameterSearchType.INT and isinstance(current, int):
            step = int(space.step or 1)
            direction = random.choice([-1, 1])
            value = min(max(current + direction * step, int(space.min_value or 0)), int(space.max_value or current))
            params[space.name] = value
        elif space.param_type == ParameterSearchType.DECIMAL and isinstance(current, (int, float)):
            step = float(space.step or 0.01)
            direction = random.choice([-1, 1])
            value = round(
                min(max(float(current) + direction * step, float(space.min_value or 0.0)), float(space.max_value or current)),
                6,
            )
            params[space.name] = value
        elif space.param_type == ParameterSearchType.CATEGORICAL and space.choices:
            choices = [c for c in space.choices if c != current]
            params[space.name] = random.choice(choices) if choices else current
        elif space.param_type == ParameterSearchType.BOOLEAN:
            params[space.name] = not bool(current if current is not None else False)

    return params


def _grid_total_count(spaces: list[ParameterSearchSpace]) -> int:
    """Count grid combinations without materializing the cartesian product."""
    if not spaces:
        return 0
    total = 1
    for space in spaces:
        total *= _grid_value_count(space)
    return total


def _grid_candidate_at(
    spaces: list[ParameterSearchSpace],
    index: int,
) -> dict[str, Any]:
    """Build one grid candidate by mixed-radix indexing."""
    counts = [_grid_value_count(space) for space in spaces]
    params: dict[str, Any] = {}
    for i, space in enumerate(spaces):
        suffix = 1
        for count in counts[i + 1:]:
            suffix *= count
        value_index = (index // max(suffix, 1)) % max(counts[i], 1)
        params[space.name] = _grid_value_at(space, value_index)
    return params


def _grid_roi_candidate(
    spaces: list[ParameterSearchSpace],
    roi_spaces: list[ParameterSearchSpace],
    target_index: int,
    total: int,
) -> dict[str, Any]:
    """Find the target monotonic ROI grid candidate with bounded scanning."""
    valid_seen = 0
    last_valid: dict[str, Any] | None = None
    scan_limit = min(total, GRID_SCAN_LIMIT)
    for index in range(scan_limit):
        candidate = _grid_candidate_at(spaces, index)
        if not _is_roi_monotonic(candidate, roi_spaces):
            continue
        last_valid = candidate
        if valid_seen >= target_index:
            return candidate
        valid_seen += 1
    return last_valid or {}


def _grid_value_count(space: ParameterSearchSpace) -> int:
    if space.param_type == ParameterSearchType.BOOLEAN:
        return max(len(space.choices or [True, False]), 1)
    if space.param_type == ParameterSearchType.CATEGORICAL:
        return max(len(space.choices or [space.default]), 1)
    if space.param_type == ParameterSearchType.INT:
        lo = int(space.min_value) if space.min_value is not None else 1
        hi = int(space.max_value) if space.max_value is not None else lo
        step = max(int(space.step) if space.step is not None else 1, 1)
        if hi < lo:
            return 1
        return max(((hi - lo) // step) + 1, 1)
    if space.param_type == ParameterSearchType.DECIMAL:
        lo = float(space.min_value) if space.min_value is not None else 0.0
        hi = float(space.max_value) if space.max_value is not None else lo
        step = float(space.step) if space.step is not None else 0.01
        if step <= 0 or hi < lo:
            return 1
        return max(int(round((hi - lo) / step)) + 1, 1)
    return 1


def _grid_value_at(space: ParameterSearchSpace, index: int) -> Any:
    if space.param_type == ParameterSearchType.BOOLEAN:
        choices = space.choices or [True, False]
        return choices[min(index, len(choices) - 1)]
    if space.param_type == ParameterSearchType.CATEGORICAL:
        choices = space.choices or [space.default]
        return choices[min(index, len(choices) - 1)]
    if space.param_type == ParameterSearchType.INT:
        lo = int(space.min_value) if space.min_value is not None else 1
        hi = int(space.max_value) if space.max_value is not None else lo
        step = max(int(space.step) if space.step is not None else 1, 1)
        return min(lo + index * step, hi)
    if space.param_type == ParameterSearchType.DECIMAL:
        lo = float(space.min_value) if space.min_value is not None else 0.0
        hi = float(space.max_value) if space.max_value is not None else lo
        step = float(space.step) if space.step is not None else 0.01
        if step <= 0:
            return lo
        value = min(lo + index * step, hi)
        decimals = len(str(step).rstrip("0").split(".")[-1]) if "." in str(step) else 2
        return round(value, decimals)
    return space.default


def _sample_roi_monotonic(
    roi_spaces: list[ParameterSearchSpace], trial_number: int
) -> dict[str, Any]:
    """Sample ROI parameters ensuring monotonic decrease over time."""
    if not roi_spaces:
        return {}

    sorted_spaces = sorted(roi_spaces, key=lambda s: int(s.name[5:]))
    roi_params: dict[str, Any] = {}
    previous_max = None

    for space in sorted_spaces:
        lo = float(space.min_value) if space.min_value is not None else 0.001
        hi = float(space.max_value) if space.max_value is not None else 0.30
        if previous_max is not None:
            hi = min(hi, previous_max)
        if hi < lo:
            hi = lo
        step = float(space.step) if space.step is not None else 0.001
        steps_count = max(int(round((hi - lo) / step)), 1)
        idx = random.randint(0, steps_count)
        value = lo + idx * step
        decimals = len(str(step).rstrip("0").split(".")[-1]) if "." in str(step) else 3
        value = round(min(max(value, lo), hi), decimals)
        roi_params[space.name] = value
        previous_max = value

    return roi_params


def _is_roi_monotonic(candidate: dict[str, Any], roi_spaces: list[ParameterSearchSpace]) -> bool:
    """Check whether ROI values decrease over time."""
    roi_entries: list[tuple[int, float]] = []
    for space in roi_spaces:
        if space.name in candidate:
            roi_entries.append((int(space.name[5:]), float(candidate[space.name])))
    if len(roi_entries) <= 1:
        return True
    roi_entries.sort(key=lambda x: x[0])
    return all(roi_entries[i][1] >= roi_entries[i + 1][1] for i in range(len(roi_entries) - 1))


def _sample_one(space: ParameterSearchSpace, trial_number: int) -> Any:
    """Sample one value from one search-space definition."""
    if space.param_type == ParameterSearchType.BOOLEAN:
        return random.choice(space.choices or [True, False])
    if space.param_type == ParameterSearchType.CATEGORICAL:
        choices = space.choices or []
        return random.choice(choices) if choices else space.default
    if space.param_type == ParameterSearchType.INT:
        lo = int(space.min_value) if space.min_value is not None else 1
        hi = int(space.max_value) if space.max_value is not None else 100
        step = int(space.step) if space.step is not None else 1
        candidates = list(range(lo, hi + 1, max(step, 1)))
        return random.choice(candidates) if candidates else lo
    if space.param_type == ParameterSearchType.DECIMAL:
        lo = float(space.min_value) if space.min_value is not None else 0.0
        hi = float(space.max_value) if space.max_value is not None else 1.0
        step = float(space.step) if space.step is not None else 0.01
        steps_count = max(int(round((hi - lo) / step)), 1)
        idx = random.randint(0, steps_count)
        value = lo + idx * step
        decimals = len(str(step).rstrip("0").split(".")[-1]) if "." in str(step) else 2
        return round(min(max(value, lo), hi), decimals)
    return space.default
