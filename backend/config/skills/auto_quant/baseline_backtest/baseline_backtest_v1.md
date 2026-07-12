# Baseline Backtest and Evaluation Skill — `baseline_backtest_v1`

## Purpose and scope

Stage 3 of AutoQuant establishes the strategy’s original, unoptimized performance on the deterministic pair universe and historical dataset approved by Stage 2.

This skill documents a reproducible baseline backtest workflow. It does not run Hyperopt, search for better parameters, modify strategy source, repair strategy logic, select pairs based on profitability, discard losing periods, change the approved timerange after seeing performance, or begin Stage 4. Those responsibilities belong to other stages.

This skill is docs-first and static. No runtime loader, pipeline hook, API route, or frontend change is introduced here.

## Stage boundaries

- Stage 1 determines whether the strategy is structurally viable.
- Stage 2 establishes the eligible market universe and complete historical-data requirements.
- Stage 3 measures the untouched strategy’s baseline behavior.
- Later stages may optimize or stress-test the strategy, but Stage 3 must remain an immutable reference.

Stage 3 must consume the recorded Stage 1 and Stage 2 outputs rather than independently inventing new strategy settings, pairs, timeframes, or timeranges.

## Required and optional inputs

Required inputs:
- `stage1_result` — Stage 1 structured output.
- `stage2_result` — Stage 2 structured output.
- `strategy_path` — filesystem path to the Python strategy file.
- `strategy_name` — strategy class name.
- `strategy_fingerprint` — strategy file hash or fingerprint.
- `configuration_fingerprint` — configuration hash or fingerprint.
- `exchange` — exchange identifier.
- `trading_mode` — spot or futures.
- `stake_currency` — stake currency.
- `approved_pairs` — pair universe from Stage 2.
- `main_timeframe` — primary strategy timeframe.
- `informative_timeframes` — additional required timeframes.
- `timerange` — exact evaluation timerange.
- `startup_candle_count` — warmup buffer.
- `data_directory` — path to local OHLCV data.

Optional execution inputs:
- `initial_balance`
- `stake_amount`
- `max_open_trades`
- `fee`
- `slippage_assumption`
- `position_stacking`
- `enable_protections`
- `dry_run_wallet`
- `minimum_trade_count`
- `minimum_active_days`
- `minimum_pair_coverage`
- `maximum_runtime_seconds`

Do not require an input if it can safely and deterministically be inherited from Stage 1, Stage 2, the strategy, or the existing project configuration. Every inherited or defaulted value must be recorded in the output with its source.

## Handoff validation

The skill performs deterministic checks in this order:

1. Stage 1 status permits continuation.
2. Stage 2 status permits continuation.
3. Stage 2 explicitly allows Stage 3.
4. At least one approved pair exists.
5. The pair universe matches the recorded Stage 2 output.
6. All required main and informative timeframe data are available.
7. The timerange and startup-candle buffer are satisfied.
8. The strategy file and configuration have not changed unexpectedly since validation.
9. Trading mode, exchange, stake currency, and pair format agree.
10. No unresolved blocking data issue remains.

A changed strategy or configuration fingerprint must not be silently ignored. It should produce a blocking result or require Stage 1 or Stage 2 to be rerun, depending on what changed.

## Reproducibility record

The baseline result must be reproducible from this record without guessing hidden defaults.

Required record fields:
- Strategy file fingerprint or hash.
- Strategy class name.
- Strategy version if present.
- Configuration fingerprint.
- AutoQuant skill version.
- Freqtrade version when available.
- Python version when available.
- Exchange.
- Trading mode.
- Stake currency.
- Approved pair universe.
- Main and informative timeframes.
- Exact timerange.
- Startup-candle count.
- Initial balance.
- Stake sizing behavior.
- Maximum open trades.
- Fee and slippage assumptions.
- Protections state.
- Relevant execution flags.
- Data snapshot or data fingerprints when supported.
- Backtest start and completion timestamps.
- Command or equivalent structured execution request.
- Artifact paths.

## Baseline execution workflow

The skill performs actions in this order:

1. Validate Stage 1 and Stage 2 handoffs.
2. Resolve all inherited settings and defaults.
3. Verify the strategy and configuration fingerprints.
4. Freeze the approved pair universe.
5. Freeze the timerange and required data snapshot.
6. Construct the baseline backtest request.
7. Run or describe the unoptimized backtest.
8. Capture process status, logs, warnings, and runtime.
9. Parse the backtest results.
10. Calculate performance and risk metrics.
11. Calculate per-pair and time-distribution diagnostics.
12. Detect result-quality problems.
13. Classify the baseline outcome.
14. Persist or describe the immutable baseline artifacts.
15. Decide whether Stage 4 may begin.

## Required baseline metrics

Activity:
- Total trades.
- Winning trades.
- Losing trades.
- Draw trades.
- Win rate.
- Average trades per day.
- Active trading days.
- Average trade duration.
- Long-trade count.
- Short-trade count.
- Rejected or blocked entry signals when available.

Return:
- Starting balance.
- Ending balance.
- Absolute profit.
- Total profit percentage.
- Average profit per trade.
- Median profit per trade.
- Best trade.
- Worst trade.
- Profit by pair.
- Profit by direction.
- Profit by exit reason.

Risk:
- Maximum absolute drawdown.
- Maximum relative drawdown.
- Drawdown start and end.
- Drawdown duration.
- Exposure.
- Losing streak.
- Winning streak.
- Daily return variability.
- Downside deviation when supported.

Quality:
- Profit factor.
- Expectancy.
- Expectancy ratio when supported.
- Sharpe ratio when supported.
- Sortino ratio when supported.
- Calmar ratio when supported.
- Risk-to-reward measurements.
- Break-even win rate when derivable.

Use `null`, `not_available`, or an equivalent explicit representation when the underlying backtest does not provide enough information. Do not fabricate unsupported metrics.

## Result-quality diagnostics

The skill must identify suspicious baseline results, including:
- Zero trades.
- Too few trades for useful comparison.
- Trades concentrated in one pair.
- Trades concentrated in a very short section of the timerange.
- One trade or one pair producing most of the profit.
- Unrealistically high returns.
- Implausibly low drawdown.
- Missing fees.
- Missing or unrealistic slippage assumptions.
- Data gaps.
- Startup-candle contamination.
- Lookahead-bias warnings.
- Recursive-analysis or unstable-indicator warnings.
- Unsupported informative data.
- Excessive rejected signals.
- Excessive duration or timeout.
- Backtest process errors.
- Parsed results that disagree with process status.
- Long and short behavior inconsistent with trading mode.
- No losing trades despite a large sample, requiring additional review.
- Open trades left at the end of the test.
- Result artifacts that cannot be reproduced from the recorded inputs.

Diagnostics must distinguish between poor strategy performance and unreliable evidence. A losing but technically valid baseline can still be useful. An apparently profitable but unreliable baseline must not be treated as a pass.

## Zero-trade handling

A zero-trade baseline must be diagnosed rather than automatically classified as a hard failure.

Possible causes:
- Entry conditions never became true.
- Pair universe is unsuitable.
- Timerange is too narrow.
- Startup candles consume the usable data.
- Informative data are missing.
- Protections block all entries.
- Trading mode conflicts with the strategy.
- Indicators remain `NaN`.
- Strategy callbacks or conditions reject entries.
- The strategy is intentionally inactive.
- The strategy changed after Stage 1.
- The Stage 2 universe does not match strategy requirements.

Output distinctions:
- A technically successful backtest with zero trades.
- A backtest that failed to execute.
- A backtest with signals but blocked entries.
- A strategy that produced no entry signals.
- Missing data that prevented signal calculation.

## Baseline acceptance policy

Do not require the baseline to be profitable merely to continue.

A valid negative baseline may continue when later stages are designed to evaluate or improve it.

Stage 4 readiness should focus on:
- Execution validity.
- Reproducibility.
- Sufficient evidence.
- Adequate trade count.
- Adequate pair and time coverage.
- Absence of unresolved data or bias problems.
- Availability of a stable comparison baseline.

Performance thresholds such as minimum profit factor or maximum drawdown should be configurable rather than silently hard-coded.

## Outcome taxonomy

Use these four outcomes consistently.

| Outcome | Meaning | Stage 4 gate |
|---|---|---|
| `pass` | Baseline completed successfully, is reproducible, contains sufficient evidence, and has no blocking integrity problem. The strategy does not have to be profitable. | Allowed |
| `warning` | Baseline is technically valid and can be used, but contains non-blocking concerns such as weak profitability, moderate concentration, low but still usable trade count, minor warnings, or limited pair diversity. Stage 4 may continue with warnings recorded. | Allowed with note |
| `soft_failure` | Baseline cannot currently serve as a reliable reference, but the problem is likely repairable without rewriting the strategy. Examples: insufficient timerange, missing data, too few trades, incorrect configuration, recoverable timeout, missing fee or slippage assumption, pair universe needing Stage 2 review. | Blocked until resolved |
| `hard_failure` | Baseline cannot be produced or trusted because of a structural or unrecoverable problem. Examples: invalid Stage 1 or Stage 2 handoff, strategy cannot execute, corrupted or unparseable result, reproducibility record cannot be established, confirmed lookahead bias, strategy or configuration changed without revalidation, no compatible market universe, execution repeatedly crashes under valid inputs. | Blocked until materially changed |

## Structured output

Return one structured result object containing:

- `skill_id`
- `skill_version`
- `run_id`
- `status`
- `errors`
- `warnings`
- `diagnostics`
- `stage1_reference`
- `stage2_reference`
- `strategy`
- `strategy_fingerprint`
- `configuration_fingerprint`
- `environment`
- `execution_settings`
- `approved_pairs`
- `main_timeframe`
- `informative_timeframes`
- `timerange`
- `data_snapshot`
- `process_result`
- `activity_metrics`
- `return_metrics`
- `risk_metrics`
- `quality_metrics`
- `pair_metrics`
- `direction_metrics`
- `exit_reason_metrics`
- `time_distribution`
- `concentration_analysis`
- `zero_trade_analysis`
- `result_integrity`
- `artifacts`
- `recommended_next_action`
- `stage4_allowed`

Recommended next actions:
- `continue`
- `review_warnings`
- `increase_timerange`
- `review_pair_universe`
- `download_or_repair_data`
- `adjust_execution_config`
- `review_strategy_conditions`
- `rerun_stage1`
- `rerun_stage2`
- `investigate_bias`
- `investigate_execution_failure`
- `stop`

## Stage 4 readiness

Stage 4 may begin only when:
- Stage 1 and Stage 2 references are valid.
- The baseline completed successfully.
- The result is reproducible.
- The strategy and configuration fingerprints match the validated inputs.
- The approved pair universe and timerange are recorded.
- Data-integrity checks have no blocking issue.
- The sample contains enough evidence under configurable thresholds.
- No confirmed lookahead-bias or equivalent integrity failure exists.
- Stage 3 status is `pass` or an explicitly permitted `warning`.
- `stage4_allowed` is `true`.

Stage 4 must be blocked for unresolved `soft_failure` or any `hard_failure`.

## Definition

```json
{
  "id": "baseline_backtest_v1",
  "name": "Baseline Backtest and Evaluation",
  "version": "1.0.0",
  "description": "Runs a reproducible unoptimized baseline backtext on the Stage 2 approved pair universe, calculates performance and risk metrics, detects result-quality problems, and decides whether Stage 4 may begin. Does not optimize parameters or modify strategy source.",
  "enabled": true,
  "applies_to": {
    "stages": ["stage3_baseline"],
    "gates": ["post_pair_discovery"]
  },
  "config": {
    "type": "object",
    "required": ["stage1_result", "stage2_result", "strategy_path", "strategy_name", "strategy_fingerprint", "configuration_fingerprint", "exchange", "trading_mode", "stake_currency", "approved_pairs", "main_timeframe", "timerange", "startup_candle_count", "data_directory"],
    "properties": {
      "stage1_result": { "type": "object" },
      "stage2_result": { "type": "object" },
      "strategy_path": { "type": "string" },
      "strategy_name": { "type": "string" },
      "strategy_fingerprint": { "type": "string" },
      "configuration_fingerprint": { "type": "string" },
      "exchange": { "type": "string" },
      "trading_mode": { "type": "string" },
      "stake_currency": { "type": "string" },
      "approved_pairs": { "type": "array", "items": { "type": "string" } },
      "main_timeframe": { "type": "string" },
      "informative_timeframes": { "type": "array", "items": { "type": "string" } },
      "timerange": { "type": "string" },
      "startup_candle_count": { "type": "integer", "minimum": 1 },
      "data_directory": { "type": "string" },
      "initial_balance": { "type": "number" },
      "stake_amount": { "type": "number" },
      "max_open_trades": { "type": "integer", "minimum": 1 },
      "fee": { "type": "number" },
      "slippage_assumption": { "type": "number" },
      "position_stacking": { "type": "boolean" },
      "enable_protections": { "type": "boolean" },
      "dry_run_wallet": { "type": "number" },
      "minimum_trade_count": { "type": "integer", "minimum": 1 },
      "minimum_active_days": { "type": "integer", "minimum": 1 },
      "minimum_pair_coverage": { "type": "number", "minimum": 0, "maximum": 1 },
      "maximum_runtime_seconds": { "type": "integer", "minimum": 1 }
    }
  },
  "tags": ["baseline", "backtest", "stage3", "evaluation"],
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
  "docs": "backend/config/skills/auto_quant/baseline_backtest/baseline_backtest_v1.md"
}
```
