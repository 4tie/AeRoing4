# REAL FREQTRADE VERIFICATION PLAN
**Status:** Plan only. No code changes. No implementation until explicitly approved.

## Official Verification Interpretation (Updated 2026-07-11)

**Real Freqtrade execution: verified**
- Freqtrade 2026.6 binary runs successfully
- Manual backtest executes and produces artifacts (.zip, .meta.json)
- Environment: 4t virtual environment at `L:\M4tie\Documents\AeRoing4\4t`

**Real artifact output: verified**
- Freqtrade writes files to `user_data/backtest_results/`
- Artifacts include `.zip` and `.meta.json` files
- File structure matches expected format

**Parser/artifact conversion: verified**
- `test_real_freqtrade_smoke.py` passes (5/5 tests)
- `ResultParser` successfully converts artifacts to `parsed_summary.json`
- `CanonicalMetricsSnapshot.model_validate_json` succeeds

**Full E2E: not verified**
- Real Focused Hyperopt: not yet verified
- Real Confirmation: not yet verified
- Real Final Unseen: not yet verified
- Real Delivery: not yet verified
- Full end-to-end pipeline with real Freqtrade: not yet verified

---

## REAL STAGE VERIFICATION PLAN (Updated 2026-07-11)

**Goal:** Verify the remaining stages with real Freqtrade, step by step, without turning this into a long expensive full pipeline run.

**Environment:** 4t virtual environment at `L:\M4tie\Documents\AeRoing4\4t`

**Freqtrade Binary:** `L:\M4tie\Documents\AeRoing4\4t\Scripts\freqtrade.exe`

**Config:** `L:\M4tie\Documents\AeRoing4\user_data\config.json`

**User Data:** `L:\M4tie\Documents\AeRoing4\user_data`

---

### Stage 1: Real Focused Hyperopt Smoke

**Exact Inputs:**
- Strategy: `AIStrategy` (from `user_data/strategies/AIStrategy.py`)
- Timerange: `20240101-20240131` (short 1-month window)
- Pairs: `BTC/USDT` only (single pair for speed)
- Timeframe: `5m`
- Config: `user_data/config.json` (dry_run: true enforced)
- Params override: `{"rsi_threshold": 35}` (simple single-parameter mutation)

**Exact Command/Test Target:**
```powershell
L:\M4tie\Documents\AeRoing4\4t\Scripts\python.exe -m pytest backend/tests/aeroing4/research/test_real_freqtrade_smoke.py::test_real_focused_hyperopt_smoke -v
```
(Note: This test does not yet exist and must be created as part of implementation)

**Expected Artifact:**
- `user_data/backtest_results/backtest-result-*.zip` containing backtest output
- `parsed_summary.json` with valid `CanonicalMetricsSnapshot`
- `FocusedHyperoptResult` with real `execution_id` and real metrics

**Pass/Fail/Skip/Block Criteria:**
- **PASS:** Real backtest executes with params_override, `parsed_summary.json` produced, metrics parsed successfully, `FocusedHyperoptService` returns result with real `execution_id`, no fallback to fake metrics
- **FAIL:** Backtest runs but metrics indicate no edge (PF < 1.0, or 0 trades)
- **SKIP:** `freqtrade` binary not detected → `SKIPPED: REAL_FREQTRADE_UNAVAILABLE`
- **BLOCKED:** Config missing, config `dry_run=false`, strategy file missing, or params_override invalid
- **SYSTEM_FAILURE:** Freqtrade process crashes, parser fails, or `parsed_summary.json` malformed/absent

**Verification Flag Updated:**
- `real_hyperopt_verified = true` (only on PASS)

**Estimated Runtime Risk:** Low (1-2 minutes for single pair, 1-month timerange)

**Cleanup Rules:**
- Delete temporary backtest results: `Remove-Item -Recurse -Force user_data/backtest_results/backtest-result-*`
- Do not delete original strategy files
- Do not modify `user_data/strategies/`

---

### Stage 2: Real Confirmation Smoke

**Exact Inputs:**
- Frozen Champion: `AIStrategy` with parameters from Stage 1 (or baseline if Stage 1 skipped)
- Timerange: `20240201-20240229` (different 1-month window for OOS)
- Pairs: `BTC/USDT` only
- Timeframe: `5m`
- Config: `user_data/config.json` (dry_run: true enforced)
- Zone: `CONFIRMATION` (access guard check required)

**Exact Command/Test Target:**
```powershell
L:\M4tie\Documents\AeRoing4\4t\Scripts\python.exe -m pytest backend/tests/aeroing4/research/test_real_freqtrade_smoke.py::test_real_confirmation_smoke -v
```
(Note: This test does not yet exist and must be created as part of implementation)

**Expected Artifact:**
- `user_data/backtest_results/backtest-result-*.zip` containing confirmation backtest
- `parsed_summary.json` with valid `CanonicalMetricsSnapshot`
- `ConfirmationResult` with real `execution_id`, real metrics, and decision (PASS/FAIL/INCONCLUSIVE)
- `ResearchProtocolState.confirmation_passed = true` (if decision is PASS)

**Pass/Fail/Skip/Block Criteria:**
- **PASS:** Frozen Champion executes on CONFIRMATION timerange, metrics parsed, `ConfirmationPolicy` returns PASS, `ConfirmationResult` persisted with real `execution_id`, protocol state updated
- **FAIL:** Frozen Champion executes, metrics parsed, `ConfirmationPolicy` returns FAIL (PF below threshold or expectancy negative)
- **SKIP:** Freqtrade unavailable → `SKIPPED: REAL_FREQTRADE_UNAVAILABLE`
- **BLOCKED:** `CONFIRMATION` zone access denied by `DataZoneGuard`, protocol gate false, or Champion hash mismatch
- **SYSTEM_FAILURE:** Freqtrade process failure, parser failure, or metrics resolution failure (never converted to INCONCLUSIVE)

**Verification Flag Updated:**
- `real_confirmation_verified = true` (only on PASS)

**Estimated Runtime Risk:** Low (1-2 minutes for single pair, 1-month timerange)

**Cleanup Rules:**
- Delete temporary backtest results: `Remove-Item -Recurse -Force user_data/backtest_results/backtest-result-*`
- Do not delete frozen Champion artifacts
- Do not modify strategy or parameter files

---

### Stage 3: Real Final Unseen Smoke

**Exact Inputs:**
- Frozen Champion: Same frozen Champion from Stage 2 (must have PASS decision)
- Timerange: `20240301-20240331` (third 1-month window, completely unseen)
- Pairs: `BTC/USDT` only
- Timeframe: `5m`
- Config: `user_data/config.json` (dry_run: true enforced)
- Zone: `FINAL_UNSEEN` (access guard check required)
- Preflight: Strategy file exists, parameter file exists, config exists, Freqtrade binary available

**Exact Command/Test Target:**
```powershell
L:\M4tie\Documents\AeRoing4\4t\Scripts\python.exe -m pytest backend/tests/aeroing4/research/test_real_freqtrade_smoke.py::test_real_final_unseen_smoke -v
```
(Note: This test does not yet exist and must be created as part of implementation)

**Expected Artifact:**
- `user_data/backtest_results/backtest-result-*.zip` containing final unseen backtest
- `parsed_summary.json` with valid `CanonicalMetricsSnapshot`
- `FinalUnseenResult` with real `execution_id`, real metrics, decision (PASS/FAIL/INCONCLUSIVE), and `delivery_eligible` flag
- One-shot execution only (no reruns allowed)

**Pass/Fail/Skip/Block Criteria:**
- **PASS:** Preflight passes, `FINAL_UNSEEN` access granted, one-shot execution succeeds, `FinalUnseenPolicy` returns PASS, `FinalUnseenResult` persisted with `delivery_eligible=true`
- **FAIL:** Preflight passes, execution succeeds, `FinalUnseenPolicy` returns FAIL (PF below threshold, etc.)
- **INCONCLUSIVE:** Execution succeeds but insufficient trades (< 30) or critical metric unavailable
- **SKIP:** Freqtrade unavailable → `BLOCKED: REAL_FREQTRADE_UNAVAILABLE` (not SKIP, run does not enter stage)
- **BLOCKED:** Preflight fails, Confirmation did not PASS, protocol gate false, Champion hash mismatch, or `FINAL_UNSEEN` access denied
- **SYSTEM_FAILURE:** Freqtrade process failure, parser failure, or metrics resolution failure after execution started (never converted to INCONCLUSIVE)

**Verification Flag Updated:**
- `real_final_unseen_verified = true` (only on PASS)

**Estimated Runtime Risk:** Low (1-2 minutes for single pair, 1-month timerange)

**Cleanup Rules:**
- Delete temporary backtest results: `Remove-Item -Recurse -Force user_data/backtest_results/backtest-result-*`
- Do not delete frozen Champion artifacts
- Do not modify strategy or parameter files
- No rerun allowed (one-shot execution only)

---

### Stage 4: Real Delivery Package from Real Passed Final Unseen

**Exact Inputs:**
- Passed `FinalUnseenResult` from Stage 3 (must have `decision = PASS` and `delivery_eligible = true`)
- Frozen Champion artifacts (strategy + parameters)
- Export profile: `run_local` (default, under `runs_root/{run_id}/delivery/`)
- Versioning: Auto-generated unique filename with timestamp

**Exact Command/Test Target:**
```powershell
L:\M4tie\Documents\AeRoing4\4t\Scripts\python.exe -m pytest backend/tests/aeroing4/research/test_real_freqtrade_smoke.py::test_real_delivery_package -v
```
(Note: This test does not yet exist and must be created as part of implementation)

**Expected Artifact:**
- Package directory: `runs_root/{run_id}/delivery/{timestamp}/`
- Contents:
  - `AIStrategy.py` (frozen strategy)
  - `AIStrategy.json` (frozen parameters)
  - `delivery_manifest.json` (with verification_flags reflecting real verifications)
  - `warnings.json` (warnings for any `real_* = false`)
  - `audit_provenance.json` (execution history)
- Hash verification: All artifact hashes match in manifest

**Pass/Fail/Skip/Block Criteria:**
- **DELIVERED:** Real passed `FinalUnseenResult` exists, eligibility passes, package built atomically, hashes verified, manifest written
- **REUSED:** Same delivery identity already exists; metadata reused, no rewrite
- **EXPORT_FAILED:** Partial write (disk failure during package build), package not marked DELIVERED
- **BLOCKED:** Final Unseen missing, decision != PASS, `delivery_eligible=false`, Champion hash mismatch, paused state, or reconciliation required

**Verification Flag Updated:**
- `real_delivery_verified = true` (only on DELIVERED)

**Estimated Runtime Risk:** Very Low (file copy and hash computation, < 10 seconds)

**Cleanup Rules:**
- Keep delivery package for inspection
- Do not delete original strategy files
- Do not overwrite existing delivery packages without explicit approval
- Clean up only if test fails and user requests cleanup

---

### Stage 5: Optional Final Guarded Full E2E Test

**Exact Inputs:**
- Complete run from Baseline through Delivery
- All stages must use real Freqtrade (no fake runners)
- Same run identity throughout
- Short timeranges and single pair set for speed

**Exact Command/Test Target:**
```powershell
L:\M4tie\Documents\AeRoing4\4t\Scripts\python.exe -m pytest backend/tests/aeroing4/research/test_real_freqtrade_smoke.py::test_real_full_e2e -v
```
(Note: This test does not yet exist and must be created as part of implementation)

**Expected Artifact:**
- Complete `ResearchProtocolState` with all stages completed
- Valid `DeliveryPackage` from real passed Final Unseen
- All `real_*` flags set to `true` in manifest
- No fake runner invocations

**Pass/Fail/Skip/Block Criteria:**
- **PASS:** All five real stages (Baseline, Hyperopt, Confirmation, Final Unseen, Delivery) succeed in sequence on the same run, producing a real delivered package
- **FAIL:** Any real stage fails or produces non-PASS decision
- **SKIP:** Freqtrade unavailable → `SKIPPED: REAL_FREQTRADE_UNAVAILABLE`
- **BLOCKED:** Any stage blocked by access guard, protocol gate, or preflight failure

**Verification Flag Updated:**
- `full_e2e_verified = true` (only on PASS)

**Estimated Runtime Risk:** Medium (5-10 minutes for complete pipeline with short timeranges)

**Cleanup Rules:**
- Delete entire run directory: `Remove-Item -Recurse -Force user_data/aeroing4/runs/{run_id}`
- Do not delete original strategy files
- Do not modify user_data structure

---

## Cross-Stage Rules

**No Production Trading:**
- All commands enforce `dry_run: true` in config
- No live orders, no real funds, no exchange state modification

**No Pipeline Rewrite:**
- Real verification is additive test layer only
- No changes to main pipeline logic (`focused_hyperopt.py`, `confirmation.py`, `final_unseen.py`, `delivery.py`)
- Fake unit tests remain intact

**No Mutation After Confirmation:**
- Champion frozen from Confirmation PASS
- No parameter changes, no AI, no Hyperopt, no sensitivity after Confirmation
- Final Unseen inherits exact frozen parameters

**No Rerun/Tuning on Final Unseen:**
- One-shot execution only
- No retry based on performance
- Reuse allowed only for exact same identity

**Short Timeranges and Small Pair Set:**
- All verification uses 1-month timeranges (20240101-20240131, 20240201-20240229, 20240301-20240331)
- Single pair (BTC/USDT) for speed
- 5m timeframe for balance between speed and realism

**Dedicated Working Freqtrade Environment:**
- Use 4t virtual environment at `L:\M4tie\Documents\AeRoing4\4t`
- Freqtrade binary: `L:\M4tie\Documents\AeRoing4\4t\Scripts\freqtrade.exe`
- Config: `L:\M4tie\Documents\AeRoing4\user_data\config.json`

**Keep All Tests Guarded:**
- Each test checks `shutil.which("freqtrade")` → skip if missing
- Each test validates config `dry_run: true` → block if false
- Each test validates required files exist → block if missing
- Access guard checks for zone-specific stages (Confirmation, Final Unseen)

**Keep Fake Unit Tests Intact:**
- Existing unit tests (`test_focused_hyperopt.py`, `test_confirmation.py`, etc.) use fake runners
- Real verification tests are separate and additive
- No modification to existing fake test infrastructure

**Do Not Mark Real Flag True Unless Real Stage Ran:**
- `real_hyperopt_verified = true` only if real Focused Hyperopt executed and produced result
- `real_confirmation_verified = true` only if real Confirmation executed and produced PASS
- `real_final_unseen_verified = true` only if real Final Unseen executed and produced PASS
- `real_delivery_verified = true` only if real Delivery produced package from real Final Unseen
- `full_e2e_verified = true` only if all real stages passed in sequence on same run

---

## Implementation Notes

**Test File Location:**
- New tests added to `backend/tests/aeroing4/research/test_real_freqtrade_smoke.py`
- Each test follows the pattern: guard → execute → verify → update flag

**Test Dependencies:**
- Stage 2 (Confirmation) depends on Stage 1 (Hyperopt) for frozen Champion, or uses baseline if Stage 1 skipped
- Stage 3 (Final Unseen) depends on Stage 2 (Confirmation) PASS
- Stage 4 (Delivery) depends on Stage 3 (Final Unseen) PASS
- Stage 5 (Full E2E) depends on all previous stages

**Sequential Execution:**
- Tests can be run individually for isolated stage verification
- Full E2E test runs complete sequence
- Failed stage stops sequence (no cascade to next stage)

**Cleanup Automation:**
- Each test cleans up its own temporary artifacts on completion
- Failed tests may leave artifacts for inspection
- Manual cleanup command provided in each stage section

---

*Plan only. No code changes. No implementation until explicitly approved.*

### 1.1 Detect Freqtrade Binary
On Windows, verify the `freqtrade` executable is on PATH or provide an absolute path.

```powershell
# Check version
freqtrade --version

# If not on PATH, provide full path explicitly to the verification harness:
# e.g. C:\Users\M4tie\AppData\Local\Programs\Python\Python311\Scripts\freqtrade.exe
```

**Detection rule (inside verification harness):**
- `shutil.which("freqtrade")` returns a valid executable path → `REAL_FREQTRADE_AVAILABLE = True`
- Otherwise → `REAL_FREQTRADE_AVAILABLE = False`, all REAL tests skip with `SKIPPED: REAL_FREQTRADE_UNAVAILABLE`

### 1.2 Required Config Path
A valid Freqtrade config JSON file is required. Minimum fields:
- `dry_run: true` (enforced — never allow `dry_run: false`)
- `initial_wallet` or equivalent dry-run wallet setting
- `max_open_trades`
- `stake_currency`
- `stake_amount`
- `timeframe`
- `user_data` directory paths (strategies, data, etc.)

**Default path:** `L:\M4tie\Documents\fortiesr\user_data\config.json` (or a dedicated AeRoing4 config under `aeroing4/configs/`).

**Config validation rule:**
- `dry_run` MUST be `true`. If `false`, verification aborts with `BLOCKED: config_dry_run_false`.
- No exchange API keys are required for dry-run. If keys are present, they must not be used in dry-run mode.
- If config is missing, verification aborts with `BLOCKED: config_missing`.

### 1.3 Required user_data Path
Standard Freqtrade layout under `user_data/`:
```
user_data/
  strategies/
    <strategy files>
  data/
    <exchange>/
      <timeframe>/
        <pair>.json   (candle data)
  backup/
  logs/
```

**Rule:** `user_data/data/` must contain valid candle data for the target pairs/timeframes used in verification.

### 1.4 Required Candle Data
For each verification run, the following pairs/timeframes must have downloaded candle data:
- Pairs: `BTC/USDT`, `ETH/USDT`, `BNB/USDT` (configurable)
- Timeframes: `5m` (primary), optionally `1h` for cross-check
- Exchange: `binance` (spot) for dry-run

**Command to download data (one-time setup):**
```powershell
freqtrade download-data --exchange binance --days 365 -t 5m --userdir L:\M4tie\Documents\fortiesr\user_data
```

**Verification check:**
```powershell
Test-Path L:\M4tie\Documents\fortiesr\user_data\data\binance\5m\BTC_USDT-5m.json
Test-Path L:\M4tie\Documents\fortiesr\user_data\data\binance\5m\ETH_USDT-5m.json
Test-Path L:\M4tie\Documents\fortiesr\user_data\data\binance\5m\BNB_USDT-5m.json
```

### 1.5 Dry-Run / Paper-Only Safety
- **Hard rule:** `dry_run: true` is enforced in all real verification commands.
- **No live trading:** All `freqtrade` invocations use `--dry-run` flag or config with `dry_run: true`.
- **No exchange keys required unless strictly dry-run-safe:** For pure dry-run, Freqtrade does not require real exchange API keys. If keys are present, they must be for dry-run only (no withdrawal, no order placement). The verification plan does not require live keys.
- **Paper trading only:** No real funds. No real orders. No real exchange connections that could modify state.

### 1.6 Verification Harness Location
The verification commands and guarded tests run from:
```
L:\M4tie\Documents\AeRoing4\backend\
```
with the AeRoing4 virtual environment activated:
```powershell
cd L:\M4tie\Documents\AeRoing4\backend
.\.venv\Scripts\Activate.ps1
```

---

## 2. Minimal Real Verification Sequence

The sequence follows the exact pipeline order. Each stage must PASS before the next is attempted. If any stage fails, the sequence stops and the failure is reported.

### 2.1 Real Smoke Backtest for Existing Champion
**Goal:** Verify that `BacktestRunner.run_candidate_backtest` produces a valid `parsed_summary.json` that `MetricsSnapshot` can parse.

**Command:**
```powershell
freqtrade backtesting --config L:\path\to\dry_run_config.json --strategy AIStrategy --timerange 20240101-20240630 --pairs BTC/USDT,ETH/USDT,BNB/USDT --userdir L:\M4tie\Documents\fortiesr\user_data
```

**Verification check:**
- Exit code 0.
- `user_data/backtest_results/` contains a result directory.
- `parsed_summary.json` exists and contains valid `CanonicalMetricsSnapshot` fields.
- `MetricsSnapshot.model_validate_json` succeeds.

**Output:** `real_hyperopt_verified = true` if parsing succeeds.

### 2.2 Real Focused Hyperopt Smoke
**Goal:** Verify that `FocusedHyperoptService` can invoke `BacktestRunner.run_candidate_backtest` with `params_override` and resolve metrics from the real output.

**Method:** Use the AeRoing4 `FocusedHyperoptService.run()` with a `BacktestRunner` that delegates to the real `freqtrade backtesting` CLI (or reuse the existing `BacktestRunner` if it already shells out).

**Command (guarded in pytest):**
```powershell
pytest tests/aeroing4/research/test_focused_hyperopt.py::test_real_hyperopt_smoke -v
```
(Such a test does not yet exist; it would be added as part of this verification plan only.)

**Pass criteria:**
- `BacktestRunner` returns a valid `execution_id`.
- `parsed_summary.json` is produced and parsed.
- `CanonicalMetricsSnapshot` is resolved without fallback.
- `FocusedHyperoptService` returns a valid result.

### 2.3 Real Confirmation Smoke
**Goal:** Verify that `ConfirmationService` runs the exact frozen Champion on the CONFIRMATION timerange and produces a valid `ConfirmationResult`.

**Command:**
```powershell
freqtrade backtesting --config L:\path\to\dry_run_config.json --timerange 20240701-20240731 --pairs BTC/USDT,ETH/USDT,BNB/USDT --userdir L:\M4tie\Documents\fortiesr\user_data --strategy AIStrategy
```

**Pass criteria:**
- Frozen Champion strategy file and sidecar are copied without modification.
- `BacktestRunner` produces valid metrics on CONFIRMATION zone.
- `ConfirmationPolicy.evaluate` returns PASS/FAIL/INCONCLUSIVE based on real metrics.
- `ConfirmationResult` is persisted with real `execution_id` and real metrics.

### 2.4 Real Final Unseen Smoke
**Goal:** Verify that `FinalUnseenService` preflight passes, `request_access(FINAL_UNSEEN)` is granted, and the one-shot execution produces a terminal `FinalUnseenResult`.

**Preflight checks (must all pass):**
```powershell
freqtrade --version
Test-Path L:\path\to\config.json
Test-Path L:\path\to\champions\AIStrategy.py
Test-Path L:\path\to\champions\AIStrategy.json
```

**Pass criteria:**
- Preflight returns `(True, "ok")`.
- `request_access(FINAL_UNSEEN)` is allowed.
- One execution only (`runner._counter == 1` or equivalent).
- `FinalUnseenPolicy` evaluates real metrics.
- Result is persisted and reusable by identity.

### 2.5 Real Delivery Package from Real Passed Final Unseen
**Goal:** Verify that `DeliveryService` produces a valid run-local package from a real passed `FinalUnseenResult`.

**Command:**
```powershell
pytest tests/aeroing4/research/test_delivery.py::test_real_delivery_package -v
```

**Pass criteria:**
- Package directory contains `.py` + `.json` + `delivery_manifest.json` + `warnings.json` + `audit_provenance.json`.
- Manifest `verification_flags` reflect the real verifications that actually ran.
- `real_delivery_verified = true` only after real Final Unseen result is packaged.
- Warnings are present for any `real_* = false`.

---

## 3. Verification Flags

Flags are set to `true` **only after the corresponding real stage executes and produces a real result**. They default to `false` in all fake/test environments.

| Flag | Becomes true when |
|---|---|
| `real_hyperopt_verified` | `FocusedHyperoptService` successfully runs a real Freqtrade backtest with real params_override and parses real `parsed_summary.json`. |
| `real_confirmation_verified` | `ConfirmationService` successfully executes a real frozen Champion on the CONFIRMATION zone and produces a real `ConfirmationResult` with `decision = PASS`. |
| `real_final_unseen_verified` | `FinalUnseenService` preflight passes, `request_access(FINAL_UNSEEN)` succeeds, one real execution produces a terminal `FinalUnseenResult` with `decision = PASS`. |
| `real_delivery_verified` | `DeliveryService` produces a real `DeliveryPackage` from a real passed `FinalUnseenResult`. |
| `real_freqtrade_verified` | A real `freqtrade` process (backtest) executes successfully end-to-end with the verified config and data. |
| `full_e2e_verified` | All five real stages above succeed in sequence on the same real run, producing a real delivered package. |

**Transition rules:**
- Flags are **monotonic**: once `true`, they stay `true` for that run.
- Flags are **per-run**, not global.
- Flags are **recorded in the `DeliveryPackage.manifest`** and **not modified by Delivery itself**.
- If a real stage is skipped due to `REAL_FREQTRADE_UNAVAILABLE`, the corresponding flag stays `false` and a warning is recorded.

---

## 4. Safety Rules

1. **No live trading** — All real invocations use `--dry-run` or config with `dry_run: true`.
2. **No production overwrite** — Delivery defaults to run-local. Freqtrade export requires explicit profile + versioned filenames or `force_overwrite=True`.
3. **No rerun of Final Unseen unless same-identity reuse** — After `request_access(FINAL_UNSEEN)` + execution, any result is terminal. Re-execution is forbidden. Reuse is allowed only for the exact same identity.
4. **No tuning on Confirmation or Final Unseen** — No AI, no mutation, no Hyperopt, no sensitivity, no parameter changes, no repair, no retry-based-on-performance.
5. **No changing params after Final Unseen** — Champion is frozen from the moment Confirmation PASSes. Final Unseen inherits exact frozen params.
6. **Delivery remains packaging-only** — No validation, no backtest, no mutation, no promotion/demotion of Champion.

---

## 5. Commands (Windows PowerShell)

### 5.1 Check Freqtrade Binary
```powershell
freqtrade --version
```
Expected output: `freqtrade 2024.x` or similar.  
If not found:
```powershell
Get-Command freqtrade -ErrorAction SilentlyContinue
```
If nothing returned, add to PATH or use absolute path in verification harness.

### 5.2 Check Config Exists
```powershell
Test-Path L:\M4tie\Documents\fortiesr\user_data\config.json
```
Must return `True`.  
Validate dry-run flag:
```powershell
(Get-Content L:\M4tie\Documents\fortiesr\user_data\config.json | ConvertFrom-Json).dry_run
```
Must return `True`.

### 5.3 Check Data Exists
```powershell
Test-Path L:\M4tie\Documents\fortiesr\user_data\data\binance\5m\BTC_USDT-5m.json
Test-Path L:\M4tie\Documents\fortiesr\user_data\data\binance\5m\ETH_USDT-5m.json
Test-Path L:\M4tie\Documents\fortiesr\user_data\data\binance\5m\BNB_USDT-5m.json
```

### 5.4 Download Data (if missing)
```powershell
freqtrade download-data --exchange binance --days 365 -t 5m --userdir L:\M4tie\Documents\fortiesr\user_data
```

### 5.5 Dry-Run Backtest Command
```powershell
cd L:\M4tie\Documents\AeRoing4\backend
.\.venv\Scripts\Activate.ps1
freqtrade backtesting --config L:\M4tie\Documents\fortiesr\user_data\config.json `
  --strategy AIStrategy `
  --timerange 20240101-20240630 `
  --pairs BTC/USDT,ETH/USDT,BNB/USDT `
  --userdir L:\M4tie\Documents\fortiesr\user_data `
  --dry-run
```

### 5.6 Guarded Real Tests Command
```powershell
cd L:\M4tie\Documents\AeRoing4\backend
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = ""
python -m pytest tests/aeroing4/research/test_real_freqtrade_smoke.py -v -p no:cacheprovider
```
(If `freqtrade` is not on PATH, pytest auto-skips with `SKIPPED: REAL_FREQTRADE_UNAVAILABLE`.)

---

## 6. Pass / Fail / Skip / Blocked / System Failure Criteria

### 6.1 Focused Hyperopt
| Outcome | Criteria |
|---|---|
| **PASS** | Real backtest executes, `parsed_summary.json` produced, metrics parsed, `FocusedHyperoptService` returns result with real `execution_id`. |
| **FAIL** | Backtest runs but metrics indicate Champion is not profitable (PF < threshold, or no trades). |
| **SKIP** | `freqtrade` binary not on PATH → `SKIPPED: REAL_FREQTRADE_UNAVAILABLE`. |
| **BLOCKED** | Config missing, config `dry_run=false`, or strategy file missing. |
| **SYSTEM_FAILURE** | Freqtrade process crashes, parser fails, or `parsed_summary.json` is malformed/absent. |

### 6.2 Confirmation
| Outcome | Criteria |
|---|---|
| **PASS** | Frozen Champion executes on CONFIRMATION timerange, metrics parsed, `ConfirmationPolicy` returns PASS, `ConfirmationResult` persisted, `ResearchProtocolState.confirmation_passed = true`. |
| **FAIL** | Frozen Champion executes, metrics parsed, `ConfirmationPolicy` returns FAIL (PF below threshold or expectancy negative). |
| **SKIP** | Freqtrade unavailable or preflight fails (for Final Unseen preflight, not Confirmation — Confirmation does not have a preflight gate in current design). |
| **BLOCKED** | `CONFIRMATION` zone access denied by `DataZoneGuard`, or protocol `confirmation_passed` was already false. |
| **SYSTEM_FAILURE** | Freqtrade process failure, parser failure, or `MetricsSnapshot` resolution failure. **Never converted to INCONCLUSIVE.** |

### 6.3 Final Unseen
| Outcome | Criteria |
|---|---|
| **PASS** | Preflight passes, `FINAL_UNSEEN` access granted, one-shot execution succeeds, `FinalUnseenPolicy` returns PASS, `FinalUnseenResult` persisted with `delivery_eligible=true`. |
| **FAIL** | Preflight passes, execution succeeds, `FinalUnseenPolicy` returns FAIL (PF below threshold, etc.). |
| **INCONCLUSIVE** | Execution succeeds but insufficient trades or critical metric unavailable. |
| **SKIP** | Freqtrade unavailable (preflight fails) → `BLOCKED: REAL_FREQTRADE_UNAVAILABLE` (not SKIP; the run does not enter the stage). |
| **BLOCKED** | Preflight fails, `Confirmation` did not PASS, protocol gate false, Champion hash mismatch, or `FINAL_UNSEEN` access denied. |
| **SYSTEM_FAILURE** | Freqtrade process failure, parser failure, or metrics resolution failure **after execution started**. **Never converted to INCONCLUSIVE.** |

### 6.4 Delivery
| Outcome | Criteria |
|---|---|
| **DELIVERED** | Real passed `FinalUnseenResult` exists, eligibility passes, package built atomically, hashes verified, manifest written. |
| **REUSED** | Same delivery identity already exists; metadata reused, no rewrite. |
| **EXPORT_FAILED** | Partial write (e.g., disk failure during package build). Package is **not** marked DELIVERED. |
| **BLOCKED** | Final Unseen missing, decision != PASS, `delivery_eligible=false`, Champion hash mismatch, paused state, or reconciliation required. |

---

## 7. Rollback / Cleanup

### 7.1 Remove Temporary Run Artifacts
AeRoing4 stores run artifacts under:
```
L:\M4tie\Documents\AeRoing4\backend\user_data\aeroing4\runs\{run_id}\
```

To clean a single failed real verification run:
```powershell
Remove-Item -Recurse -Force L:\M4tie\Documents\AeRoing4\backend\user_data\aeroing4\runs\{run_id}
```

To clean all test runs (use with caution):
```powershell
Remove-Item -Recurse -Force L:\M4tie\Documents\AeRoing4\backend\user_data\aeroing4\runs\test-*
```

### 7.2 Avoid Deleting Real User Strategies
**Hard rule:** Never delete files under `L:\M4tie\Documents\fortiesr\user_data\strategies\`.  
The verification plan only **copies** strategy files to run-local delivery directories. It never modifies or deletes the originals.

### 7.3 Avoid Overwriting Existing Freqtrade Files
- Delivery defaults to `run_local` export profile (under `runs_root/{run_id}/delivery/`).
- Export to `user_data/strategies/` requires explicit `export_profile="freqtrade_user_data"` + versioned filenames or `force_overwrite=True`.
- Never silently overwrite an existing `.py` or `.json` in `user_data/strategies/`.
- If a test or real run attempts overwrite without approval, it returns `BLOCKED` and aborts.

### 7.4 Rollback Summary
| Action | Command / Rule |
|---|---|
| Remove run artifacts | `Remove-Item -Recurse -Force user_data\aeroing4\runs\{run_id}` |
| Keep user strategies | Never touch `user_data\strategies\` |
| No overwrite | `export_profile="run_local"` default; freqtrade export requires explicit approval |
| Clean temp delivery packages | `Remove-Item -Recurse -Force user_data\aeroing4\runs\{run_id}\delivery` |

---

## 8. Final Report Format

After running the real verification sequence, the report must clearly state:

```
=== REAL FREQTRADE VERIFICATION REPORT ===
Date: <ISO timestamp>
Environment: <Windows hostname, Python version, Freqtrade version>
Config: <config path>
Data: <user_data path>
Dry-run: <True>

--- What ran with real Freqtrade ---
[ ] Focused Hyperopt smoke
[ ] Confirmation smoke
[ ] Final Unseen smoke
[ ] Delivery package from real Final Unseen

--- What passed ---
<list of stages that passed with real Freqtrade execution>

--- What failed ---
<list of stages that failed, with error summary>

--- What was skipped ---
<list of stages skipped due to REAL_FREQTRADE_UNAVAILABLE or other skip condition>

--- What remains unverified ---
REAL HYPEROPT VERIFIED: <true/false>
REAL CONFIRMATION VERIFIED: <true/false>
REAL FINAL_UNSEEN VERIFIED: <true/false>
REAL DELIVERY VERIFIED: <true/false>
REAL FREQTRADE VERIFIED: <true/false>
FULL E2E VERIFIED: <true/false>

--- Can Full E2E be claimed? ---
<Yes only if all five real stages passed in sequence on the same run. No otherwise.>

--- Warnings ---
<Any incomplete verifications, config gaps, or partial data>

=== END REPORT ===
```

**Honesty rule:** The report must not claim any `real_* = true` unless the corresponding real stage actually executed and produced a real result. `SKIPPED` or `BLOCKED` stages must be listed explicitly. `Full E2E` can be claimed **only** when all five real stages pass in sequence on the same run.

---

## 9. Implementation Guard (for future use)

When this plan is approved for implementation:

1. Add a `tests/aeroing4/research/test_real_freqtrade_smoke.py` file with guarded real tests.
2. Each real test:
   - Checks `shutil.which("freqtrade")` → skip if missing.
   - Validates config `dry_run: true` → block if false.
   - Invokes real `freqtrade backtesting` via `subprocess` or `BacktestRunner`.
   - Parses real `parsed_summary.json` via `CanonicalMetricsSnapshot.model_validate_json`.
   - Flips the corresponding `real_*` flag to `true` only on success.
3. No code in the main pipeline (`focused_hyperopt.py`, `confirmation.py`, `final_unseen.py`, `delivery.py`) is modified. Real verification is an **additive test layer** only.
4. Default behavior of the pipeline remains unchanged: without real Freqtrade, it uses fake runners and skips real tests.

---

*Plan only. No code changes. No implementation until explicitly approved.*
