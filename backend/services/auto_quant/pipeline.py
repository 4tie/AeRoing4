"""Auto-Quant Factory pipeline facade.

The implementation lives in ``pipeline_modules``.  This module keeps the older
single-file API intact so routers and tests can still import and monkeypatch
``backend.services.auto_quant.pipeline`` directly.
"""

from __future__ import annotations

from pathlib import Path

from backend.services.auto_quant.monte_carlo import run_monte_carlo
from backend.services.auto_quant.ollama_service import detect_strategy_type
from backend.services.auto_quant.pipeline_modules import config as _config
from backend.services.auto_quant.pipeline_modules import helpers as _helpers
from backend.services.auto_quant.pipeline_modules import logging as _logging
from backend.services.auto_quant.pipeline_modules import orchestrator as _orchestrator
from backend.services.auto_quant.pipeline_modules import stage_runtime as _stage_runtime
from backend.services.auto_quant.pipeline_modules import stages_assessment as _assessment
from backend.services.auto_quant.pipeline_modules import stages_optimization as _optimization
from backend.services.auto_quant.pipeline_modules import stages_validation as _validation
from backend.services.auto_quant.pipeline_modules import state as _state
from backend.services.auto_quant.sensitivity import run_sensitivity_check

BROAD_UNIVERSE_PAIRS = _config.BROAD_UNIVERSE_PAIRS
DEFAULT_STRESS_PAIRS = _config.DEFAULT_STRESS_PAIRS
MAX_DRAWDOWN_THRESHOLD = _config.MAX_DRAWDOWN_THRESHOLD
MIN_OOS_PROFIT = _config.MIN_OOS_PROFIT
MIN_PROFIT_FACTOR = _config.MIN_PROFIT_FACTOR
MIN_SHARPE = _config.MIN_SHARPE
MIN_WIN_RATE = _config.MIN_WIN_RATE
MONTE_CARLO_THRESHOLD = _config.MONTE_CARLO_THRESHOLD
STAGE_NAMES = _config.STAGE_NAMES
get_timeframe_thresholds = _config.get_timeframe_thresholds

PipelineState = _state.PipelineState
StageState = _state.StageState

logger = _logging.logger
_AsyncQueueHandler = _logging._AsyncQueueHandler
_rlog = _logging._rlog

_states = _state._states
_queues = _state._queues
_cancel_flags = _state._cancel_flags

_run_subprocess = _helpers._run_subprocess
_should_forward = _helpers._should_forward
_classify_subprocess_error = _helpers._classify_subprocess_error
_backtest_cmd = _helpers._backtest_cmd
_extract_hyperopt_best = _helpers._extract_hyperopt_best
_inject_params = _helpers._inject_params
_find_backtest_result = _helpers._find_backtest_result
_read_latest_freqtrade_backtest = _helpers._read_latest_freqtrade_backtest
_extract_backtest_summary = _helpers._extract_backtest_summary
_extract_trade_count = _helpers._extract_trade_count
_extract_per_pair_results = _helpers._extract_per_pair_results
_start_stage = _stage_runtime._start_stage
_pass_stage = _stage_runtime._pass_stage
_fail_stage = _stage_runtime._fail_stage
_emit = _stage_runtime._emit

_save_state_to_disk = _state._save_state_to_disk
_state_snapshot = _state._state_snapshot
_cancelled = _state._cancelled
_now = _state._now
_Cancelled = _state._Cancelled
record_event = _state.record_event
get_event_history = _state.get_event_history

_merge_timeranges = _orchestrator._merge_timeranges

_extract_oos_profit_ratios = _assessment._extract_oos_profit_ratios


def _sync_facade_patches() -> None:
    """Propagate monkeypatched facade symbols into refactored modules."""
    _state._save_state_to_disk = _save_state_to_disk
    _state._state_snapshot = _state_snapshot
    _state._cancelled = _cancelled
    _state.record_event = record_event

    _helpers._run_subprocess = _run_subprocess
    _helpers._classify_subprocess_error = _classify_subprocess_error
    _helpers._backtest_cmd = _backtest_cmd
    _helpers._extract_hyperopt_best = _extract_hyperopt_best
    _helpers._inject_params = _inject_params
    _helpers._find_backtest_result = _find_backtest_result
    _helpers._read_latest_freqtrade_backtest = _read_latest_freqtrade_backtest
    _helpers._extract_backtest_summary = _extract_backtest_summary
    _helpers._extract_trade_count = _extract_trade_count
    _helpers._extract_per_pair_results = _extract_per_pair_results
    _helpers._start_stage = _start_stage
    _helpers._pass_stage = _pass_stage
    _helpers._fail_stage = _fail_stage
    _helpers._emit = _emit

    _orchestrator._run_subprocess = _run_subprocess
    _orchestrator._pass_stage = _pass_stage
    _orchestrator._fail_stage = _fail_stage
    _orchestrator._emit = _emit
    _orchestrator._stage_oos_validation = _stage_oos_validation

    for module in (_optimization, _validation, _assessment):
        if hasattr(module, "_run_subprocess"):
            module._run_subprocess = _run_subprocess
        if hasattr(module, "_classify_subprocess_error"):
            module._classify_subprocess_error = _classify_subprocess_error
        if hasattr(module, "_backtest_cmd"):
            module._backtest_cmd = _backtest_cmd
        if hasattr(module, "_extract_backtest_summary"):
            module._extract_backtest_summary = _extract_backtest_summary
        if hasattr(module, "_extract_trade_count"):
            module._extract_trade_count = _extract_trade_count
        if hasattr(module, "_extract_per_pair_results"):
            module._extract_per_pair_results = _extract_per_pair_results
        if hasattr(module, "_find_backtest_result"):
            module._find_backtest_result = _find_backtest_result
        if hasattr(module, "_extract_hyperopt_best"):
            module._extract_hyperopt_best = _extract_hyperopt_best
        if hasattr(module, "_inject_params"):
            module._inject_params = _inject_params
        if hasattr(module, "_start_stage"):
            module._start_stage = _start_stage
        if hasattr(module, "_pass_stage"):
            module._pass_stage = _pass_stage
        if hasattr(module, "_fail_stage"):
            module._fail_stage = _fail_stage
        if hasattr(module, "_emit"):
            module._emit = _emit
        if hasattr(module, "_cancelled"):
            module._cancelled = _cancelled
        if hasattr(module, "_save_state_to_disk"):
            module._save_state_to_disk = _save_state_to_disk

    _assessment._extract_oos_profit_ratios = _extract_oos_profit_ratios
    _assessment.run_monte_carlo = run_monte_carlo


def create_run(**kwargs) -> str:
    _sync_facade_patches()
    return _state.create_run(**kwargs)


def get_state(run_id: str) -> PipelineState | None:
    return _state.get_state(run_id)


def get_states() -> dict[str, PipelineState]:
    return _state.get_states()


def get_queue(run_id: str):
    return _state.get_queue(run_id)


def release_queue(run_id: str, q) -> None:
    _state.release_queue(run_id, q)


def request_cancel(run_id: str) -> bool:
    return _state.request_cancel(run_id)


def delete_run(run_id: str, user_data_dir: str) -> bool:
    return _state.delete_run(run_id, user_data_dir)


def get_cancel_flags() -> dict[str, bool]:
    return _state.get_cancel_flags()


def list_runs() -> list[dict]:
    _sync_facade_patches()
    return _state.list_runs()


def load_runs_from_disk(user_data_dir: str) -> None:
    _sync_facade_patches()
    _state.load_runs_from_disk(user_data_dir)


async def run_pipeline(run_id: str) -> None:
    _sync_facade_patches()
    return await _orchestrator.run_pipeline(run_id)


def launch_pipeline_task(run_id: str):
    """Schedule the pipeline to run in the background, guarding against
    double-launching an orchestrator task for the same run_id (e.g. a user
    double-clicking resume, or a resume racing with an already-running task).
    Returns the asyncio.Task, or None if one was already active."""
    _sync_facade_patches()
    return _orchestrator.launch_pipeline_task(run_id)


async def _stage_hyperopt(run_id: str, state: PipelineState, out_dir: Path) -> dict | None:
    _sync_facade_patches()
    return await _optimization._stage_hyperopt(run_id, state, out_dir)


async def _stage_hyperopt_standard(
    run_id: str, state: PipelineState, out_dir: Path
) -> dict | None:
    _sync_facade_patches()
    return await _optimization._stage_hyperopt_standard(run_id, state, out_dir)


async def _stage_hyperopt_wfo(
    run_id: str, state: PipelineState, out_dir: Path
) -> dict | None:
    _sync_facade_patches()
    return await _optimization._stage_hyperopt_wfo(run_id, state, out_dir)


async def _stage_patch(
    run_id: str, state: PipelineState, out_dir: Path, best_params: dict
) -> Path | None:
    _sync_facade_patches()
    return await _optimization._stage_patch(run_id, state, out_dir, best_params)


async def _stage_sanity_backtest(
    run_id: str, state: PipelineState, out_dir: Path
) -> dict | None:
    _sync_facade_patches()
    return await _validation._stage_sanity_backtest(run_id, state, out_dir)


async def _stage_oos_validation(
    run_id: str, state: PipelineState, out_dir: Path, optimized_path: Path
) -> dict | str | None:
    _sync_facade_patches()
    return await _validation._stage_oos_validation(run_id, state, out_dir, optimized_path)


async def _stage_stress_test(
    run_id: str, state: PipelineState, out_dir: Path, optimized_path: Path
) -> dict | None:
    _sync_facade_patches()
    return await _validation._stage_stress_test(run_id, state, out_dir, optimized_path)


async def _stage_risk_assessment(
    run_id: str, state: PipelineState, out_dir: Path, stress_result: dict
) -> dict | None:
    _sync_facade_patches()
    return await _assessment._stage_risk_assessment(run_id, state, out_dir, stress_result)


async def _stage_delivery(
    run_id: str,
    state: PipelineState,
    out_dir: Path,
    optimized_path: Path,
    best_params: dict,
    s1_result: dict,
    oos_result: dict,
    stress_result: dict,
    risk_result: dict,
) -> None:
    _sync_facade_patches()
    await _assessment._stage_delivery(
        run_id,
        state,
        out_dir,
        optimized_path,
        best_params,
        s1_result,
        oos_result,
        stress_result,
        risk_result,
    )


__all__ = [
    "run_pipeline",
    "PipelineState",
    "StageState",
    "create_run",
    "get_state",
    "get_states",
    "get_queue",
    "release_queue",
    "request_cancel",
    "delete_run",
    "get_cancel_flags",
    "record_event",
    "get_event_history",
    "list_runs",
    "load_runs_from_disk",
    "STAGE_NAMES",
    "DEFAULT_STRESS_PAIRS",
    "BROAD_UNIVERSE_PAIRS",
    "MAX_DRAWDOWN_THRESHOLD",
    "MIN_OOS_PROFIT",
    "MIN_PROFIT_FACTOR",
    "MIN_SHARPE",
    "MIN_WIN_RATE",
    "MONTE_CARLO_THRESHOLD",
    "get_timeframe_thresholds",
    "logger",
    "run_sensitivity_check",
    "detect_strategy_type",
]
