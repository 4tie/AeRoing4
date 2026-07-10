"""Data structures and persistence for the Auto-Quant pipeline.

This module acts as a coordinator, importing and re-exporting state functions
from the state_modules subpackage to maintain backward compatibility.
"""

from .state_modules import (
    # Data structures
    StageState,
    PipelineState,
    _Cancelled,
    _states,
    _cancel_flags,
    _queues,
    _event_history,
    _EVENT_HISTORY_MAX,
    # Persistence
    _state_file,
    _run_dir,
    _write_versioned_json,
    _save_state_to_disk,
    load_runs_from_disk,
    # Utilities
    get_states,
    get_cancel_flags,
    record_event,
    get_event_history,
    create_run,
    get_state,
    get_queue,
    release_queue,
    request_cancel,
    delete_run,
    list_runs,
    _state_snapshot,
    _cancelled,
    _now,
)

__all__ = [
    # Data structures
    "StageState",
    "PipelineState",
    "_Cancelled",
    "_states",
    "_cancel_flags",
    "_queues",
    "_event_history",
    "_EVENT_HISTORY_MAX",
    # Persistence
    "_state_file",
    "_run_dir",
    "_write_versioned_json",
    "_save_state_to_disk",
    "load_runs_from_disk",
    # Utilities
    "get_states",
    "get_cancel_flags",
    "record_event",
    "get_event_history",
    "create_run",
    "get_state",
    "get_queue",
    "release_queue",
    "request_cancel",
    "delete_run",
    "list_runs",
    "_state_snapshot",
    "_cancelled",
    "_now",
]
