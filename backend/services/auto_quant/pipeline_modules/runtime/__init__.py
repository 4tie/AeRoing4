"""Runtime package for pipeline stage state management."""

from .lifecycle_helpers import (
    _start_stage,
    _pass_stage,
    _fail_stage,
    _emit,
    build_stage_payload,
)
from .validation_helpers import (
    is_validate_existing,
    ensure_validation_attempt,
    update_validation_attempt,
    finalize_rejection_report,
)
from .metrics_helpers import (
    _record_best_observed,
    _best_observed_sort_key,
    _first_number,
    _recommended_next_experiment,
    _metrics_from,
)
from .normalization_helpers import (
    build_stage_cards,
    build_workflow_summary,
    derive_error_object,
    build_stage_card,
    make_error_object,
    _input_summary_for,
    _output_summary_for,
    _derive_warnings,
    _retry_attempts_for,
    _auto_fix_for,
    _suggestions_for,
    _stage_progress_for,
    _status_kind,
    _event_stage_percent,
    _error_details_from_data,
    _slug_code,
    _strip_ui_keys,
    _coerce_string_list,
    _dedupe,
)

__all__ = [
    # Lifecycle helpers
    "_start_stage",
    "_pass_stage",
    "_fail_stage",
    "_emit",
    "build_stage_payload",
    # Validation helpers
    "is_validate_existing",
    "ensure_validation_attempt",
    "update_validation_attempt",
    "finalize_rejection_report",
    # Metrics helpers
    "_record_best_observed",
    "_best_observed_sort_key",
    "_first_number",
    "_recommended_next_experiment",
    "_metrics_from",
    # Normalization helpers
    "build_stage_cards",
    "build_workflow_summary",
    "derive_error_object",
    "build_stage_card",
    "make_error_object",
    "_input_summary_for",
    "_output_summary_for",
    "_derive_warnings",
    "_retry_attempts_for",
    "_auto_fix_for",
    "_suggestions_for",
    "_stage_progress_for",
    "_status_kind",
    "_event_stage_percent",
    "_error_details_from_data",
    "_slug_code",
    "_strip_ui_keys",
    "_coerce_string_list",
    "_dedupe",
]
