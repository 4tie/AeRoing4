# Pair and Data Discovery Skill — `pair_data_discovery_v1`

## Purpose and scope

Stage 2 of AutoQuant answers one question: *Which pairs and historical datasets are suitable for later evaluation?*

This skill documents a deterministic discovery and data-planning workflow that takes a successful Stage 1 result and produces an eligible pair universe plus a data-readiness plan. It does not optimize the strategy, rank pairs by profitability, modify strategy source code, or run the full baseline evaluation. Those responsibilities belong to later stages.

This skill is docs-first and static. No runtime loader, pipeline hook, API route, or frontend change is introduced here.

## Separation from Stage 1

- Stage 1 checks whether enough pair and historical data exist for a small smoke backtest, and whether the strategy file is structurally valid.
- Stage 2 builds the full eligible pair universe and prepares complete data requirements for later evaluation.
- Stage 2 must not repeat Python syntax, strategy-loading, or required-method validation unless the Stage 1 handoff is invalid.

## Required inputs

- `stage1_result` — Stage 1 structured output.
- `exchange` — exchange identifier.
- `trading_mode` — spot or futures.
- `stake_currency` — stake currency.
- `candidate_pairs` — optional initial candidate list.
- `pair_whitelist` — optional inclusion list.
- `pair_blacklist` — optional exclusion list.
- `main_timeframe` — primary strategy timeframe.
- `informative_timeframes` — additional required timeframes.
- `informative_pairs` — pairs needed for informative data.
- `timerange` — evaluation timerange.
- `startup_candle_count` — required warmup buffer.
- `data_directory` — path to local OHLCV data.
- `minimum_history_days` — minimum acceptable history length.
- `minimum_candle_coverage` — minimum acceptable coverage ratio.
- `maximum_pair_count` — deterministic upper bound for selected universe.
- Optional liquidity, volume, spread, market-age, and volatility limits.

Do not require values that can safely be detected from Stage 1 or existing project configuration.

## Check ordering

The skill performs checks in this order.

1. Validate the Stage 1 handoff.
2. Resolve exchange, trading mode, and stake currency.
3. Build the initial candidate-pair universe.
4. Remove inactive, unsupported, malformed, and blacklisted markets.
5. Confirm spot or futures compatibility.
6. Exclude unsupported leveraged or derivative tokens when appropriate.
7. Apply configurable liquidity, volume, spread, precision, minimum-stake, market-age, and volatility filters.
8. Detect all required main and informative timeframes.
9. Detect all required informative pairs.
10. Calculate the required historical-data window, including startup-candle buffer.
11. Inspect locally available OHLCV data.
12. Detect missing pairs, missing timeframes, insufficient history, gaps, duplicate candles, and invalid timestamps.
13. Produce a data-download or repair plan without executing it.
14. Select the Stage 2 eligible pair universe.
15. Determine whether Stage 3 may begin.

## Stage 1 handoff validation

Rules:
- If `stage1_result.status` is `pass` or an explicitly permitted `warning`, continue.
- If `stage1_result.status` is `hard_failure`, stop and set `recommended_next_action` to `review_stage1`.
- If `stage1_result.status` is `soft_failure`, block Stage 3 unless the environment explicitly resolves the issue.
- If required Stage 1 outputs are missing, treat as a handoff failure.

## Exchange, trading mode, and stake currency

Rules:
- Resolve exchange from provided value or project config.
- Validate trading mode compatibility with candidate pairs.
- Reject spot-only pairs in futures mode, and vice versa, unless explicitly allowed.
- Record resolved values in outputs even when they are inherited from config.

## Candidate-pair universe construction

Rules:
- Start from `candidate_pairs`, `pair_whitelist`, project config, exchange metadata, or a deterministic fallback.
- Do not rank by strategy profitability at this stage.
- Use deterministic selection rules so repeated runs produce the same universe.

## Market filtering

Exclude pairs when:
- Market is inactive or delisted.
- Pair format is malformed.
- Pair is in `pair_blacklist`.
- Pair conflicts with `pair_whitelist`.
- Pair does not match the exchange quote/stake currency format.
- Spot/futures compatibility is incorrect.
- Pair involves an unsupported leveraged or derivative token for the current mode.
- Precision, minimum order, or minimum stake constraints cannot be met.

Each excluded pair must include one or more machine-readable exclusion reasons.

## Timeframe and informative-pair detection

Rules:
- Use `main_timeframe` from Stage 1 or provided input.
- Expand with `informative_timeframes`.
- Resolve `informative_pairs` with explicit pair/timeframe mappings.
- If an informative pair is missing from the candidate universe, mark it as data-missing rather than silently dropping the requirement.

## Historical-data window calculation

Rules:
- Base window on `timerange`.
- Add `startup_candle_count` buffer to the start.
- Respect `minimum_history_days`.
- Produce a required start timestamp, end timestamp, and buffer summary.

## Local data inspection

Rules:
- Inspect OHLCV data in `data_directory`.
- Verify presence for every required pair and timeframe.
- Detect missing files, missing timeframes, insufficient history, gaps, duplicate candles, and invalid timestamps.
- Compute coverage ratios against `minimum_candle_coverage`.

## Data plan

Stage 2 must produce a non-executing plan describing:
- Which pairs need data.
- Which timeframes are required.
- Required start and end dates.
- Startup-candle buffer.
- Missing-data intervals.
- Whether existing data can be incrementally extended.
- Whether a pair should be removed instead of downloaded.
- Estimated data readiness status.

## Outcome taxonomy

Use these four outcomes consistently.

| Outcome | Meaning | Stage 3 gate |
|---|---|---|
| `pass` | Eligible pair universe and required data are ready. | Allowed |
| `warning` | Usable universe exists, but non-blocking issues remain. | Allowed with note |
| `soft_failure` | Missing or incomplete data can likely be repaired or downloaded. | Blocked until repaired |
| `hard_failure` | No valid market universe can be constructed, exchange or trading mode is incompatible, or Stage 1 handoff is invalid. | Blocked until materially changed |

## Structured output

Return one structured result object containing:

- `status`
- `errors`
- `warnings`
- `diagnostics`
- `exchange`
- `trading_mode`
- `stake_currency`
- `main_timeframe`
- `required_timeframes`
- `required_informative_pairs`
- `candidate_pairs`
- `eligible_pairs`
- `excluded_pairs`
- `exclusion_reasons`
- `data_ready_pairs`
- `data_missing_pairs`
- `data_gaps`
- `required_timerange`
- `startup_buffer`
- `download_plan`
- `recommended_next_action`
- `stage3_allowed`

Recommended next actions:
- `continue`
- `download_data`
- `extend_data`
- `repair_data`
- `reduce_pair_universe`
- `adjust_filters`
- `change_exchange`
- `change_trading_mode`
- `review_stage1`

## Stage 3 readiness

Stage 3 may begin only when:
- Stage 1 ended with `pass` or an explicitly permitted `warning`.
- At least one eligible pair remains.
- All required main and informative timeframes are available for the evaluation window.
- Startup-candle requirements are satisfied.
- Blocking data gaps have been resolved or are covered by an approved repair plan.
- The selected universe is deterministic and recorded.
- Stage 2 status is `pass` or an explicitly permitted `warning`.

Stage 3 must be blocked for unresolved `soft_failure` or any `hard_failure`.

## Pair-selection rules

Pair selection must be based on market and data suitability, not on the strategy's eventual profitability.

Considered factors:
- Active market status.
- Correct quote or stake currency.
- Spot or futures compatibility.
- Blacklist and whitelist handling.
- Pair precision.
- Minimum order or stake constraints.
- Market age.
- Historical-data coverage.
- Candle continuity and density.
- Liquidity and volume.
- Spread.
- Configurable volatility limits.
- Informative-pair dependencies.
- Deterministic maximum-pair limit.

Each excluded pair must include one or more machine-readable exclusion reasons.

## Definition

```json
{
  "id": "pair_data_discovery_v1",
  "name": "Pair and Data Discovery",
  "version": "1.0.0",
  "description": "Determines eligible market pairs and required historical datasets for later AutoQuant evaluation. Builds the full eligible pair universe, validates data readiness, and produces a download or repair plan. Does not optimize the strategy or rank pairs by profitability.",
  "enabled": true,
  "applies_to": {
    "stages": ["stage2_pair_data_discovery"],
    "gates": ["post_validation"]
  },
  "config": {
    "type": "object",
    "required": ["stage1_result", "exchange", "trading_mode", "stake_currency", "main_timeframe", "data_directory"],
    "properties": {
      "stage1_result": { "type": "object" },
      "exchange": { "type": "string" },
      "trading_mode": { "type": "string" },
      "stake_currency": { "type": "string" },
      "candidate_pairs": { "type": "array", "items": { "type": "string" } },
      "pair_whitelist": { "type": "array", "items": { "type": "string" } },
      "pair_blacklist": { "type": "array", "items": { "type": "string" } },
      "main_timeframe": { "type": "string" },
      "informative_timeframes": { "type": "array", "items": { "type": "string" } },
      "informative_pairs": { "type": "array", "items": { "type": "string" } },
      "timerange": { "type": "string" },
      "startup_candle_count": { "type": "integer", "minimum": 1 },
      "data_directory": { "type": "string" },
      "minimum_history_days": { "type": "integer", "minimum": 1 },
      "minimum_candle_coverage": { "type": "number", "minimum": 0, "maximum": 1 },
      "maximum_pair_count": { "type": "integer", "minimum": 1 },
      "liquidity_limit": { "type": "number" },
      "volume_limit": { "type": "number" },
      "spread_limit": { "type": "number" },
      "market_age_days": { "type": "integer", "minimum": 1 },
      "volatility_limit": { "type": "number" }
    }
  },
  "tags": ["discovery", "data", "stage2", "pairs"],
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
  "docs": "backend/config/skills/auto_quant/pair_data_discovery/pair_data_discovery_v1.md"
}
```
