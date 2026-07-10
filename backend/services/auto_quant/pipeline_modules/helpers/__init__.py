"""Helpers package for pipeline modules."""

from .subprocess_helpers import (
    _run_subprocess,
    _should_forward,
    _classify_subprocess_error,
)
from .validation_helpers import (
    _start_stage,
    _pass_stage,
    _fail_stage,
    _emit,
)
from .artifact_helpers import (
    _find_backtest_result,
    _read_latest_freqtrade_backtest,
    _extract_backtest_summary,
    _extract_trade_count,
    _extract_per_pair_results,
    _extract_trade_distribution,
)
from .config_helpers import (
    _backtest_cmd,
    _extract_hyperopt_best,
    _inject_params,
    _aggregate_wfa_parameters,
    _create_temp_config_with_fee_override,
    _create_temp_config_with_max_open_trades,
    _extract_last_close_price,
    strategy_path_args,
)

__all__ = [
    # Subprocess helpers
    "_run_subprocess",
    "_should_forward",
    "_classify_subprocess_error",
    # Validation helpers
    "_start_stage",
    "_pass_stage",
    "_fail_stage",
    "_emit",
    # Artifact helpers
    "_find_backtest_result",
    "_read_latest_freqtrade_backtest",
    "_extract_backtest_summary",
    "_extract_trade_count",
    "_extract_per_pair_results",
    "_extract_trade_distribution",
    # Config helpers
    "_backtest_cmd",
    "_extract_hyperopt_best",
    "_inject_params",
    "_aggregate_wfa_parameters",
    "_create_temp_config_with_fee_override",
    "_create_temp_config_with_max_open_trades",
    "_extract_last_close_price",
    "strategy_path_args",
]
