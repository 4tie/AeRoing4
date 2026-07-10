"""Public utility functions for state management."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any

from ..config import (
    BROAD_UNIVERSE_PAIRS,
    MAX_DRAWDOWN_THRESHOLD,
    MIN_OOS_PROFIT,
    MIN_PROFIT_FACTOR,
    MIN_SHARPE,
    MIN_WIN_RATE,
    MONTE_CARLO_THRESHOLD,
    STAGE_NAMES,
)
from ..logging import logger
from ...policy import get_policy_versions, normalize_decimal
from .data_structures import PipelineState, StageState, _states, _cancel_flags, _queues, _event_history, _EVENT_HISTORY_MAX
from .persistence import _run_dir, _save_state_to_disk, _write_versioned_json


def get_states() -> dict[str, PipelineState]:
    """Return the in-memory state registry."""
    return _states


def get_cancel_flags() -> dict[str, bool]:
    """Return the in-memory cancel flag registry."""
    return _cancel_flags


def record_event(run_id: str, event: dict[str, Any]) -> None:
    """Keep a bounded per-run event history for observability clients."""
    history = _event_history.setdefault(run_id, deque(maxlen=_EVENT_HISTORY_MAX))
    history.append(event)


def get_event_history(run_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """Return recent events emitted for a pipeline run."""
    history = list(_event_history.get(run_id, []))
    return history[-max(1, limit):]


def create_run(
    *,
    strategy: str,
    timeframe: str,
    in_sample_range: str,
    out_sample_range: str,
    exchange: str,
    config_file: str,
    freqtrade_path: str,
    user_data_dir: str,
    max_drawdown_threshold: float = MAX_DRAWDOWN_THRESHOLD,  # 0.30 = 30%
    min_win_rate: float = MIN_WIN_RATE,  # 0.40 = 40%
    min_profit_factor: float = MIN_PROFIT_FACTOR,
    min_sharpe: float = MIN_SHARPE,
    monte_carlo_threshold: float = MONTE_CARLO_THRESHOLD,
    hyperopt_loss: str = "ProfitLockinHyperOptLoss",
    hyperopt_spaces: list | None = None,
    hyperopt_epochs: int = 100,
    hyperopt_workers: int = 2,
    min_oos_profit: float = 0.0,
    wfo_enabled: bool = False,
    wfo_is_months: int = 3,
    wfo_oos_months: int = 1,
    wfo_recency_weight: float = 1.0,
    planned_wfo_windows: list | None = None,
    ensemble_enabled: bool = False,
    pair: str | None = None,
    pair_universe: list | None = None,
    ai_enabled: bool = True,
    data_healing_warmup_candles: int = 200,
    data_healing_timeout: int = 300,
    strategy_source: str = "existing",
    trading_style: str = "swing",
    risk_profile: str = "balanced",
    analysis_depth: str = "deep",
    uploaded_strategy_id: str | None = None,
    advanced_overrides: dict | None = None,
    auto_discovery_enabled: bool = False,
    discovery_results: dict | None = None,
    validation_notes: list | None = None,
    run_config_snapshot: dict | None = None,
    policy_versions: dict | None = None,
    selected_timeframe: str | None = None,
    selected_pair_universe: list | None = None,
    workflow_mode: str = "auto_quant",
    max_attempts: int = 3,
) -> str:
    import uuid
    run_id = str(uuid.uuid4())
    stages = [StageState(index=i + 1, name=STAGE_NAMES[i]) for i in range(len(STAGE_NAMES))]
    state = PipelineState(
        run_id=run_id,
        strategy=strategy,
        timeframe=timeframe,
        in_sample_range=in_sample_range,
        out_sample_range=out_sample_range,
        exchange=exchange,
        config_file=config_file,
        freqtrade_path=freqtrade_path,
        user_data_dir=user_data_dir,
        stages=stages,
        created_at=_now(),
        max_drawdown_threshold=normalize_decimal(max_drawdown_threshold, MAX_DRAWDOWN_THRESHOLD),
        min_win_rate=normalize_decimal(min_win_rate, MIN_WIN_RATE),
        min_profit_factor=min_profit_factor,
        min_sharpe=min_sharpe,
        monte_carlo_threshold=normalize_decimal(monte_carlo_threshold, MONTE_CARLO_THRESHOLD),
        hyperopt_loss=hyperopt_loss,
        hyperopt_spaces=hyperopt_spaces if hyperopt_spaces is not None else ["stoploss", "roi"],
        hyperopt_epochs=hyperopt_epochs,
        hyperopt_workers=hyperopt_workers,
        min_oos_profit=normalize_decimal(min_oos_profit, MIN_OOS_PROFIT),
        wfo_enabled=wfo_enabled,
        wfo_is_months=wfo_is_months,
        wfo_oos_months=wfo_oos_months,
        wfo_recency_weight=wfo_recency_weight,
        planned_wfo_windows=planned_wfo_windows if planned_wfo_windows is not None else [],
        ensemble_enabled=ensemble_enabled,
        pair=pair or None,
        pair_universe=pair_universe if pair_universe is not None else BROAD_UNIVERSE_PAIRS,
        ai_enabled=ai_enabled,
        data_healing_warmup_candles=data_healing_warmup_candles,
        data_healing_timeout=data_healing_timeout,
        phase1_heal_attempts=0,
        strategy_source=strategy_source,
        trading_style=trading_style,
        risk_profile=risk_profile,
        analysis_depth=analysis_depth,
        uploaded_strategy_id=uploaded_strategy_id,
        advanced_overrides=advanced_overrides or {},
        auto_discovery_enabled=auto_discovery_enabled,
        discovery_results=discovery_results or {},
        validation_notes=validation_notes or [],
        run_config_snapshot=run_config_snapshot or {},
        policy_versions=policy_versions or get_policy_versions(),
        selected_timeframe=selected_timeframe or timeframe,
        selected_pair_universe=selected_pair_universe or (pair_universe if pair_universe is not None else BROAD_UNIVERSE_PAIRS),
        workflow_mode=workflow_mode,
        max_attempts=max(1, min(int(max_attempts or 3), 10)),
    )
    if state.workflow_mode == "validate_existing":
        state.strategy_source = "existing"
        state.max_retries = max(0, state.max_attempts - 1)
    _states[run_id] = state
    _queues[run_id] = []
    _cancel_flags[run_id] = False
    _event_history[run_id] = deque(maxlen=_EVENT_HISTORY_MAX)
    logger.info(
        "create_run: new run %s | strategy=%s | tf=%s | IS=%s | OOS=%s | exchange=%s | config=%s",
        run_id, strategy, timeframe, in_sample_range, out_sample_range, exchange, config_file,
    )
    if state.run_config_snapshot:
        state.artifact_versions.update(
            _write_versioned_json(
                _run_dir(state),
                "run_config_snapshot",
                state.run_config_snapshot,
                legacy_name="run_config_snapshot.json",
            )
        )
    _save_state_to_disk(state)
    return run_id


def get_state(run_id: str) -> PipelineState | None:
    return _states.get(run_id)


def get_queue(run_id: str) -> asyncio.Queue:
    """Subscribe to a pipeline's event stream. Returns a dedicated Queue."""
    q: asyncio.Queue = asyncio.Queue(maxsize=2000)
    _queues.setdefault(run_id, []).append(q)
    return q


def release_queue(run_id: str, q: asyncio.Queue) -> None:
    try:
        _queues[run_id].remove(q)
    except (KeyError, ValueError):
        pass


def request_cancel(run_id: str) -> bool:
    if run_id not in _states:
        return False
    _cancel_flags[run_id] = True
    return True


def delete_run(run_id: str, user_data_dir: str) -> bool:
    """Delete a pipeline run from memory and disk.
    
    This will cancel the run if it's running, remove it from memory,
    and delete its directory from disk.
    """
    import shutil
    from pathlib import Path
    
    # Cancel if running
    if run_id in _cancel_flags:
        _cancel_flags[run_id] = True
    
    # Remove from memory
    if run_id in _states:
        del _states[run_id]
    if run_id in _queues:
        del _queues[run_id]
    if run_id in _cancel_flags:
        del _cancel_flags[run_id]
    if run_id in _event_history:
        del _event_history[run_id]
    
    # Delete from disk
    run_dir = Path(user_data_dir) / "auto_quant" / run_id
    if run_dir.exists():
        try:
            shutil.rmtree(run_dir)
            logger.info("delete_run: deleted run directory %s", run_dir)
        except Exception as e:
            logger.error("delete_run: failed to delete run directory %s: %s", run_dir, e)
            return False
    
    return True


def list_runs() -> list[dict]:
    result = []
    for state in _states.values():
        result.append(_state_snapshot(state))
    return result


def _state_snapshot(state: PipelineState) -> dict:
    total_stages = max(1, len(state.stages))
    progress = state.progress_percent
    if not progress and state.current_stage:
        progress = int(state.current_stage / total_stages * 100)
    return {
        "run_id": state.run_id,
        "strategy": state.strategy,
        "original_strategy": state.original_strategy,
        "original_strategy_hash": state.original_strategy_hash,
        "timeframe": state.timeframe,
        "selected_timeframe": state.selected_timeframe or state.timeframe,
        "in_sample_range": state.in_sample_range,
        "out_sample_range": state.out_sample_range,
        "exchange": state.exchange,
        "status": state.status,
        "current_stage": state.current_stage,
        "total_stages": total_stages,
        "progress": progress,
        "progress_percent": progress,
        "eta_seconds": state.eta_seconds,
        "progress_counters": state.progress_counters,
        "stages": [
            {"index": s.index, "name": s.name, "status": s.status,
             "message": s.message, "data": s.data,
             "started_at": s.started_at, "duration_s": s.duration_s}
            for s in state.stages
        ],
        "error": state.error,
        "created_at": state.created_at,
        "completed_at": state.completed_at,
        "report": state.report,
        "hyperopt_loss": state.hyperopt_loss,
        "hyperopt_spaces": state.hyperopt_spaces,
        "hyperopt_epochs": state.hyperopt_epochs,
        "thresholds": {
            "max_drawdown": state.max_drawdown_threshold,
            "min_win_rate": state.min_win_rate,
            "min_profit_factor": state.min_profit_factor,
            "min_sharpe": state.min_sharpe,
            "monte_carlo_threshold": state.monte_carlo_threshold,
        },
        "validation_status": state.validation_status,
        "readiness_label": state.readiness_label,
        "workflow_mode": state.workflow_mode,
        # Pair selection fields — needed by the frontend approval review panel
        "selected_pairs": state.selected_pairs or [],
        "user_approved_pairs": state.user_approved_pairs or [],
        "discovery_results": state.discovery_results or {},
    }


def _cancelled(run_id: str) -> bool:
    return _cancel_flags.get(run_id, False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
