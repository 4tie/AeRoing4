# AeRoing4 Portfolio Baseline Documentation

## Overview

This document explains the Portfolio Baseline functionality added to AeRoing4 Milestone 6, which extends the workflow with three new steps: Pair Selection, Portfolio Baseline, and Initial Champion creation.

## Difference Between Pair Discovery and Pair Selection

**Pair Discovery** evaluates a universe of trading pairs to determine which are technically usable for the strategy. It performs data readiness checks, runs individual pair backtests, and ranks candidates based on performance metrics. Pair Discovery answers "which pairs could potentially work with this strategy?"

**Pair Selection** chooses a specific subset of pairs from the Pair Discovery results to form the actual trading portfolio. It applies selection policy rules to determine the final pair set that will be used in portfolio execution. Pair Selection answers "which specific pairs will we actually trade together?"

The key distinction is that Pair Discovery is about evaluation and ranking, while Pair Selection is about choosing a concrete portfolio configuration.

## AUTO_BEST_N Selection Mode

AUTO_BEST_N automatically selects the top N qualified pairs from Pair Discovery results based on deterministic ranking order.

**Rules:**
- Only selects pairs with VALID_CANDIDATE status
- Preserves deterministic ranking order from Pair Discovery
- Never selects pairs with DATA_UNAVAILABLE, EXECUTION_FAILURE, ZERO_TRADES, or INSUFFICIENT_TRADES status
- Default target count is 4 pairs (configurable)
- If fewer qualified pairs exist than requested, returns PARTIAL_SELECTION or INSUFFICIENT_QUALIFIED_PAIRS outcome
- Does not silently include rejected pairs to reach the requested count

**Configuration:**
- `pair_selection_mode`: "AUTO_BEST_N"
- `target_pair_count`: Number of pairs to select (default: 4)

## MANUAL Selection Mode

MANUAL selection allows users to explicitly specify which pairs to trade from the Pair Discovery results.

**Rules:**
- Every requested pair must exist in the discovery results
- Pairs must be technically usable (not DATA_UNAVAILABLE or EXECUTION_FAILURE)
- Non-qualified pairs can be selected with explicit warnings
- Returns validation errors for invalid requests
- Preserves discovery evidence including warnings for non-qualified selections

**Configuration:**
- `pair_selection_mode`: "MANUAL"
- `manually_selected_pairs`: List of pair names to select

For AeRoing4 v1, manual mode may select only technically usable discovery pairs but must preserve warnings if the pair was not ranked as VALID_CANDIDATE.

## Why Individual Pair Results Are Not Summed

The Portfolio Baseline is **not** equivalent to summing individual pair results. This is because:

1. **Shared Capital Constraints**: When pairs trade together under shared wallet constraints, capital availability affects execution. A profitable trade on one pair may consume capital that prevents a trade on another pair.

2. **Correlation Effects**: Pairs may move together, creating portfolio-level dynamics that don't appear in isolated pair results.

3. **Order Execution**: Real portfolio execution involves order sequencing and market impact that differs from theoretical individual pair backtests.

4. **Risk Management**: Portfolio-level risk management (max open trades, position sizing) creates interdependencies between pairs.

Therefore, the real portfolio backtest result is authoritative and must come from one actual multi-pair portfolio execution.

## Shared Capital Constraints

The Portfolio Baseline uses shared capital constraints that mirror real trading conditions:

- **Wallet Configuration**: Total available capital for the portfolio
- **Stake Configuration**: How capital is allocated per trade (fixed amount, percentage, etc.)
- **Max Open Trades**: Maximum number of concurrent positions across all pairs
- **Position Sizing**: Capital is divided among active trades based on configuration

These constraints mean that the portfolio result is not simply the sum of individual pair results - capital availability and position limits create real dependencies between pairs.

## Wallet and Stake Behavior

**Wallet Configuration:**
- Defines total available capital for the portfolio
- Can be configured as absolute amount or percentage of account
- Persists in baseline result for reproducibility

**Stake Configuration:**
- Determines how capital is allocated per trade
- Options include: fixed amount, percentage of wallet, percentage of available capital
- Affects how many pairs can trade simultaneously given max_open_trades

**Example:**
- Wallet: $10,000
- Stake: 5% of wallet per trade
- Max Open Trades: 4
- Result: Each trade uses $500, up to 4 concurrent trades = $2,000 max exposure

## Max Open Trades

`max_open_trades` limits the number of concurrent positions across all selected pairs in the portfolio baseline:

- Prevents over-concentration in too many simultaneous positions
- Enforces risk management at portfolio level
- Affects capital allocation and trade sequencing
- Must be respected during portfolio backtest execution

This constraint creates dependencies between pairs - if max_open_trades is 3 and 4 pairs are selected, the 4th pair can only trade when one of the other positions closes.

## Canonical Portfolio Baseline Metrics

The Portfolio Baseline uses the Metrics Single Source of Truth (SSOT) system to produce canonical metrics:

- **Metrics Version**: All metrics are tagged with the current METRICS_VERSION for provenance
- **Canonical Adapters**: Uses official adapters/calculator, not private calculations
- **Provenance Tracking**: Each metric records its source run ID and artifact
- **Availability States**: Preserves unavailable metrics rather than substituting zeros
- **No Private Copies**: Does not calculate private copies of Profit Factor, Expectancy, Sharpe, Sortino, Calmar, Drawdown, or Average Trade Duration

**Canonical Metrics Include:**
- Net profit (absolute and percentage)
- Total trades
- Win rate
- Profit factor
- Expectancy
- Sharpe ratio
- Sortino ratio
- Calmar ratio
- Maximum drawdown
- Average trade duration

## Per-Pair Contribution

The Portfolio Baseline extracts reliable per-pair contribution from the real portfolio backtest result:

**For each selected pair:**
- Trade count
- Net profit absolute
- Net profit percentage (if reliably attributable)
- Win rate
- Contribution to total portfolio profit (percentage)
- Contribution to total trade count (percentage)

**Availability Rules:**
- Does not invent unavailable metrics
- Does not convert unavailable values to zero
- Uses explicit availability metadata
- Only includes metrics that are reliably attributable to individual pairs

This data helps understand which pairs drive portfolio performance without making assumptions about unavailable data.

## Concentration Summary

The Portfolio Baseline includes a simple deterministic concentration analysis to understand portfolio concentration:

**Concentration Flags:**
- **BALANCED_CONTRIBUTION**: No single pair dominates (< 40% profit contribution)
- **MODERATE_CONCENTRATION**: One pair contributes 40-60% of profit
- **HIGH_PAIR_CONCENTRATION**: One pair contributes > 60% of profit

**Metrics Provided:**
- Top pair profit contribution share
- Top pair trade share
- Number of profitable contributing pairs
- Number of losing contributing pairs
- Total contributing pairs
- Pair contribution distribution

**Policy Version:** PORTFOLIO_CONCENTRATION_POLICY_VERSION = "1.0.0"

This evidence is intentionally simple - it does not implement risk parity, mean-variance optimization, or correlation optimization. Those are reserved for later diagnosis stages.

## Exit Reason Evidence

The Portfolio Baseline normalizes and persists exit reason distribution from the portfolio backtest:

**For each exit reason:**
- Reason name (e.g., "stop_loss", "take_profit", "timeout")
- Count (number of trades with this exit reason)
- Percentage of trades (count / total trades)
- Total profit contribution (if reliably available)
- Average result (if reliably available)

**Purpose:**
- This data supports future deterministic Diagnosis
- Does not interpret exit reasons in this milestone
- Only normalizes and persists evidence for later analysis

**Availability:**
- Missing exit reason data is preserved as unavailable
- Does not invent or substitute missing values

## Initial Champion Creation

After a technically valid Portfolio Baseline completes, the system creates the first actual ChampionReference.

**Source Type:** BASELINE

**Champion References:**
- Immutable/run-local strategy artifact
- Strategy hash
- Parameter artifact/reference
- Parameter hash
- Portfolio Baseline metrics snapshot
- Pair selection hash
- Selected pair set
- Timeframe
- Configuration identity
- Creation timestamp

**Important:**
- Does not create the champion from fake or synthetic data
- Does not create an initial champion if the portfolio execution itself failed
- A losing but technically valid baseline may still become the initial champion

## Why a Losing Valid Baseline May Still Become the Initial Champion

A losing Portfolio Baseline (e.g., Net Profit = -8%) can still become the initial champion because:

1. **Reference Point**: The initial champion serves as the reference point for future controlled research, regardless of profitability.

2. **Technical Validity**: If the baseline executed successfully and produced valid metrics, it represents a real strategy state that can be improved upon.

3. **Measurement Goal**: The baseline goal is measurement, not profitability. Losing baselines provide valuable information about strategy performance.

4. **Research Continuity**: Having a baseline champion allows the research loop to begin with a known state, even if that state is unprofitable.

5. **Improvement Path**: Future experiments can be compared against this baseline to measure improvement, whether the baseline is profitable or not.

The key requirement is technical validity of execution, not profitability of results.

## Original Strategy Protection

Portfolio Baseline and Initial Champion setup must not overwrite the user's original strategy:

**Protection Mechanisms:**
- Initial champion references immutable source version or run-local copied artifact
- Original source strategy file hash is verified before and after milestone execution
- Strategy file is never mutated during champion creation
- Champions reference run-local artifact copies only

**Artifact References:**
- `strategy_artifact`: Reference to run-local strategy file copy
- `parameter_artifact`: Reference to run-local parameter file copy
- `original_source_path`: Original user file path (for audit)
- `original_source_hash`: Hash of original at time of capture (immutable reference)

This ensures the user's original strategy remains intact while the research system works with immutable copies.

## Restart and Idempotency Behavior

The system supports restart scenarios with deterministic behavior:

**Scenario A: Pair Discovery Complete**
- Selection persisted → Restart → Selection remains identical
- Selection hash ensures reproducibility

**Scenario B: Portfolio Baseline Completed**
- Restart → Result reloads → No duplicate baseline backtest created
- Input identity hash prevents re-execution

**Scenario C: Initial Champion Created**
- Restart → ResearchState points to same champion
- ChampionStore lineage remains intact

**Scenario D: Portfolio Baseline Was Running**
- Restart → Explicit reconciliation state
- No silent duplicate execution

**Input Identity:**
Portfolio Baseline input identity includes:
- Strategy hash
- Parameter hash
- Selected pair-set hash
- Timeframe
- DEVELOP timerange
- Wallet config
- Stake config
- Max open trades
- Exchange
- Trading mode
- Freqtrade config identity
- Metrics version
- Protocol version

Same completed valid input → reuse according to explicit policy
Changed meaningful input → new baseline execution identity

## Selection Freeze Behavior

After Portfolio Baseline execution begins, the selected pair set becomes immutable for the current research lineage:

**Freeze Rules:**
- Selected pairs cannot be changed after baseline starts
- Selection hash is persisted
- Freeze timestamp is recorded
- Any pair change requires new research lineage/run

**Prevention:**
- Does not allow: baseline runs → result seen → pairs changed → baseline rerun repeatedly
- Without starting a new explicit research lineage/run or policy-approved research action

**Idempotency:**
- Duplicate baseline results do not create duplicate champion records
- Same input identity produces same champion reference
- Champion identity is deterministic based on immutable inputs

## Research Protocol Integration

Portfolio Baseline must access DEVELOP zone only through Research Protocol:

**Access Request:**
- Before Portfolio Baseline execution, request access through DataZoneGuard
- Persist ledger access entry ID
- Store concrete DEVELOP timerange
- Record strategy hash, parameter hash, pair_set_hash, protocol version

**Zone Restrictions:**
- Portfolio Baseline cannot use CONFIRMATION zone
- Portfolio Baseline cannot use FINAL_UNSEEN zone
- Access to these zones is denied by DataZoneGuard

**Protocol Versioning:**
- All protocol interactions are versioned
- Protocol version is persisted in baseline result
- Ensures reproducibility and auditability

## Research State Integration

After Initial Champion creation, ResearchState is updated:

**Updated Fields:**
- `current_champion_id`: ID of the newly created champion
- `current_champion_strategy_hash`: Strategy hash of the champion
- `current_champion_parameter_hash`: Parameter hash of the champion
- `research_status`: Updated to reflect champion initialization

**Separation of Concerns:**
- ResearchState stores the current research reference (pointer)
- ChampionStore stores lineage records (full history)
- Workflow State remains the execution-stage owner
- ResearchState does not duplicate full champion history

**Update Timing:**
- ResearchState is updated only after champion creation
- Not updated during baseline execution
- Not updated during pair selection

## Summary

The Portfolio Baseline extension adds three critical steps to AeRoing4:

1. **Pair Selection**: Chooses specific pairs from discovery results using AUTO_BEST_N or MANUAL modes
2. **Portfolio Baseline**: Executes real multi-pair portfolio backtest under shared capital constraints
3. **Initial Champion**: Creates the first research champion from the baseline result

These steps ensure that research begins with a measured, reproducible portfolio baseline that respects real trading constraints, provides canonical metrics, and establishes a clear reference point for future research improvements.
