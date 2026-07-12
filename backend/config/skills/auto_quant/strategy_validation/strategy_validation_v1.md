# Strategy Validation Skill — `strategy_validation_v1`

## Purpose and scope

Stage 1 of AutoQuant answers one question: *Is this strategy file viable enough to continue?*

This skill documents a repeatable validation workflow for a single uploaded strategy. It does not optimize parameters, modify strategy source, or skip later stages. It only rejects clearly broken inputs so Stage 2 does not waste time on invalid material.

This skill is docs-first and static. No runtime loader, pipeline hook, API route, or frontend change is introduced here.

## Required inputs

- `strategy_path` — filesystem path to the Python strategy file.
- `strategy_name` — expected class name from metadata or filename.
- `user_data_dir` — root containing `data/`, `strategies/`, and `user_data/`.
- `timeframe` — preferred timeframe string, e.g. `5m`, `1h`, `4h`, `1d`. Optional when the strategy declares its own timeframe.
- `timerange` — optional backtest timerange, e.g. `20230101-20231231`.
- `pairs` — optional pair list; if omitted, use the project default available universe.
- `startup_candle_count` — optional override; if missing, infer from strategy or use a conservative minimum.
- `max_backtest_days` — optional smoke-test data window limit.

## Check ordering

The skill performs checks in this order. A later stage can still warn or recover from an earlier soft failure, but the first hard failure typically ends Stage 1.

1. Python syntax validation
2. Import resolution
3. Strategy load into Freqtrade `IStrategy` interface
4. Required class and method existence
5. Timeframe detection and validation
6. Startup candle requirement check
7. Pair and historical-data availability
8. Smoke backtest
9. Zero-trade diagnosis

## Python syntax and import checks

Syntax check target: the raw `.py` file.

Recommended checks:
- Parse with `ast.parse` or equivalent.
- Reject `SyntaxError` and `IndentationError` as hard failures.
- After successful parse, attempt module import in an isolated review context.
- Treat `ImportError` and missing optional dependency warnings as soft failures with a clear "install dependency" recommendation.
- Treat missing strategy class or mismatched filename-to-class mapping as a hard failure.

## Freqtrade strategy loading checks

Load the strategy through the Freqtrade strategy source loader or parser used by the project.

Recommended checks:
- Can the strategy be instantiated after imports succeed?
- Does it declare an informative `INTERFACE_VERSION`, if present?
- Does it reference unknown indicators or deprecated indicator names that would break real backtests?

## Required strategy class and method checks

Treat the current primary strategy methods as:
- `populate_indicators`
- `populate_entry_trend`
- `populate_exit_trend`

Treat the following as legacy interfaces:
- `populate_buy_trend` maps to legacy buy-entry behavior.
- `populate_sell_trend` maps to legacy sell-exit behavior.

Optional callbacks:
- `custom_exit` is optional. Do not require it.

Contract attributes:
- `stoploss` should be treated as a strategy attribute or method according to the actual project and Freqtrade contract.
- `minimal_roi` should be treated according to the actual project and Freqtrade contract.

Missing primary methods should be reported as hard failures unless the docs explicitly state alternate entry/exit hooks are supported.

## Timeframe detection and validation

Rules:
- If the strategy declares `timeframe`, prefer it and treat the supplied `timeframe` input as optional.
- If the strategy does not declare `timeframe` and the supplied `timeframe` is missing, report a soft failure.
- If the provided or detected timeframe is unsupported by available data or the project config, report a soft failure with a suggested replacement from the supported timeframe list.
- Timeframe mismatch between strategy and requested data should be a warning, not an automatic fail.

## Startup candle requirements

Rules:
- If the strategy defines `startup_candle_count`, use it.
- If missing, compute from indicator lookahead or use a project-default minimum.
- If data coverage is shorter than required startup candles, report a soft failure.
- Soft failure output must include the exact pair/timerange that is too short so Stage 2 can fix it.

## Pair and historical-data availability

Rules:
- Keep pair and data checks basic. Full pair-universe construction and historical-data preparation belong to Stage 2.
- Verify the pairs needed for the smoke backtest have cached OHLCV data.
- Verify data density and timeframe alignment for those pairs.
- If data is missing, classify as soft failure and recommend a data download or pair reduction.
- If some pairs are valid and others are not, allow a warning-level result rather than rejecting the whole strategy.

## Smoke backtest

A reduced-cost Freqtrade backtest used to confirm the strategy can run end-to-end.

Recommended defaults:
- Limit to 1-2 pairs when the full validation universe is large.
- Limit to a recent but meaningful timerange slice if none was provided.
- Capture result summary, trade list, and log output.

## Zero-trade diagnosis

A zero-trade smoke result is **not** automatically a hard failure.

Possible causes to diagnose:
- Dataset or timerange too narrow.
- Pairs not volatile enough for the chosen timeframe.
- Startup candles consuming all available bars.
- Protections or blocking conditions that never clear.
- Entry AND exit conditions that are logically incompatible.
- Strategy is actually a `noop` subclass or indicator-only file.
- Required data or indicators returning `NaN` on the tested window.

Output for zero-trade result:
- status = `soft_failure` or `warning`, not `hard_failure` by default.
- warnings listing the most likely causes.
- recommended_next_action = `adjust_pairs`, `adjust_timeframe`, `adjust_timerange`, `review_conditions`, or `continue`.

## Outcome taxonomy

Use these four outcomes consistently.

| Outcome | Meaning | Stage 2 gate |
|---|---|---|
| `pass` | All checks succeeded; smoke backtest ran and produced trades, or zero trades were diagnosed as expected dataset limits. | Allowed |
| `warning` | Strategy loaded and ran, but something is suspicious or suboptimal. Stage 2 may continue with caution. | Allowed with note |
| `soft_failure` | Problem is likely fixable without rewriting strategy logic, such as data, pairs, timeframe, or configuration mismatch. | Blocked until fix is applied |
| `hard_failure` | Strategy file is structurally invalid, missing required methods, cannot load, or produces no trades despite ideal conditions. | Blocked until strategy is materially changed |

## Structured outputs

Return one structured result object containing:

- `status`: one of `pass`, `warning`, `soft_failure`, `hard_failure`
- `errors`: list of hard failures
- `warnings`: list of soft issues or suspicious conditions
- `diagnostics`: list of short statements explaining what was checked and what was found
- `detected`: detected settings including:
  - `timeframe`
  - `startup_candle_count`
  - `strategy_class`
  - `methods_found`
  - `legacy_methods_found`
  - `data_pairs_checked`
  - `data_pairs_available`
  - `smoke_run_trades`
- `recommended_next_action`: one of:
  - `continue`
  - `adjust_pairs`
  - `adjust_timeframe`
  - `adjust_timerange`
  - `download_data`
  - `review_conditions`
  - `fix_strategy`

## Stage 2 readiness criteria

Stage 2 may begin only if the final Stage 1 result is `pass` or `warning`.

Stage 2 must be blocked if:
- status is `hard_failure`
- status is `soft_failure` with zero recommended resolution from the current environment
- required primary methods are missing
- strategy file raises an exception during normal load
- actual runtime behavior contradicts declared timeframe or pair universe in an unrecoverable way

## Definition

```json
{
  "id": "strategy_validation_v1",
  "name": "Strategy Validation",
  "version": "1.0.0",
  "description": "Validates strategy syntax, Freqtrade loadability, required methods, timeframe and startup candle requirements, pair/data availability, and a small smoke backtest. Distinguishes hard failure, soft failure, warning, and pass. Zero-trade results are diagnosed, not automatically rejected.",
  "enabled": true,
  "applies_to": {
    "stages": ["stage1_validation"],
    "gates": ["initial"]
  },
  "config": {
    "type": "object",
    "required": ["strategy_path", "strategy_name", "user_data_dir"],
    "properties": {
      "strategy_path": { "type": "string" },
      "strategy_name": { "type": "string" },
      "user_data_dir":  { "type": "string" },
      "timeframe":      { "type": "string" },
      "timerange":      { "type": "string" },
      "pairs":          { "type": "array", "items": { "type": "string" } },
      "startup_candle_count": { "type": "integer", "minimum": 1 },
      "max_backtest_days": { "type": "integer", "minimum": 1 },
      "smoke_pairs_limit": { "type": "integer", "minimum": 1 }
    }
  },
  "tags": ["validation", "smoke", "stage1"],
  "author": "AutoQuant",
  "dependencies": [],
  "preconditions": [],
  "rollback": { "enabled": false, "max_attempts": 0 },
  "timeout_seconds": 900,
  "permissions": {
    "read_results": true,
    "write_artifacts": true,
    "modify_strategy": false
  },
  "docs": "backend/config/skills/auto_quant/strategy_validation/strategy_validation_v1.md"
}
```
