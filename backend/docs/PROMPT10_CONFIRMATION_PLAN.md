# PROMPT 10 — Confirmation Zone Evaluation (Revised Plan, corrections applied)

**Scope:** ONE stage — **Confirmation** — entered ONLY after PROMPT 9 Sensitivity
PASS (`eligible_for_confirmation == true`):

```
HYPEROPT Champion → Sensitivity PASS → eligible_for_confirmation = true
→ Confirmation Zone only → frozen strategy + frozen params
→ no AI · no Hyperopt · no repair · no adaptive retry
→ one honest absolute OOS evaluation → PASS / FAIL / INCONCLUSIVE
```

**Cardinal rule:** Confirmation is a TEST, not an optimization stage. No mutation,
no promotion, no repair. On FAIL/INCONCLUSIVE the Champion is left unchanged and
the decision returns to the workflow.

---

## Reuse inventory (already exist — no rewrite)

* `BacktestRunner.run_candidate_backtest(params_override=...)` — execution layer.
* `DataZoneGuard` + `AccessLedger` — `ResearchZone.CONFIRMATION` access + audit.
* `ResearchProtocolState.confirmation_passed` / `confirmation_passed_at` +
  `DataZoneGuard.set_confirmation_passed(run, passed)` — protocol gate.
* `get_min_trades(timeframe)` in `policies.py` — shared timeframe-aware trade
  sufficiency (used by ConfirmationPolicy, NOT duplicated).
* `compute_boundary_hash(...)` in `data_zones.py` — `boundary_hash`.
* `ChampionReference.strategy_artifact.artifact_hash` / `parameter_artifact.artifact_hash`.
* `CanonicalMetricsSnapshot` (Metrics SSOT) + resolver pattern from PROMPT 9.

---

## 1. Typed persistent ConfirmationResult (not ResearchState-only)

`research/confirmation.py`:

```python
class ConfirmationResult(BaseModel):
    result_id: str
    run_id: str
    champion_id: str
    strategy_hash: str
    parameter_hash: str
    boundary_hash: str
    confirmation_timerange: str
    configuration_hash: str
    protocol_version: str
    metrics_version: str
    confirmation_policy_version: str
    access_ledger_entry_id: str | None
    underlying_execution_id: str | None
    canonical_metrics_snapshot: CanonicalMetricsSnapshot | None
    metrics_snapshot_hash: str | None
    execution_status: ConfirmationExecutionStatus
    decision: ConfirmationDecision | None
    reason_codes: list[str]
    evaluated_at: datetime
    confirmation_identity: str   # deterministic id (§2)
```

`ResearchState` holds ONLY summary: `confirmation_status: Optional[str]` +
`latest_confirmation_result_id: Optional[str]`. No conflicting ownership with
`ResearchProtocolState` (which keeps `confirmation_passed` gate only).

`ConfirmationStore` (JSON, atomic, lock-guarded — same pattern as state_store):
`save(result)`, `load(result_id)`, `find_by_identity(confirmation_identity)`,
`latest_for_run(run_id)`.

---

## 2. Deterministic identity + idempotency (correction #2)

`confirmation_identity = sha256(canonical_string)` over:

* champion_id
* strategy_hash
* parameter_hash
* boundary_hash
* configuration_hash (frozen execution config identity)
* timeframe
* sorted pair set
* protocol_version
* metrics_version
* confirmation_policy_version

Before execution: if `find_by_identity(confirmation_identity)` exists →
**reuse existing result, do NOT execute again** (no hidden tuning loop, no
Confirmation-as-optimization-surface). Any change to a frozen-context field
produces a DIFFERENT identity → triggers integrity check / typed conflict, not a
silent rerun.

Tests: A (same identity → reused, no 2nd execution), B (same champion + altered
frozen context → rejected/conflict, no silent rerun), C (restart after completed →
reused).

---

## 3. Existing protocol confirmation gate (correction #3)

On PASS only:
1. persist `ConfirmationResult`
2. update `ResearchState` summary (`confirmation_status`, `latest_confirmation_result_id`)
3. call `zone_guard.set_confirmation_passed(run, True)` → sets
   `ResearchProtocolState.confirmation_passed = true` + `confirmation_passed_at`
4. (FINAL_UNSEEN eligibility later uses this gate)

On FAIL / INCONCLUSIVE / PROTOCOL_DENIED / EXECUTION_SYSTEM_FAILURE: do NOT set the
protocol gate. No second conflicting Final-Unseen flag created here.

---

## 4. Shared timeframe-aware trade sufficiency (correction #4)

`ConfirmationPolicy` (versioned) reuses `get_min_trades(timeframe)` for the
minimum-trade requirement. It does NOT hardcode a duplicate threshold.

```python
class ConfirmationPolicy:
    policy_version: str = "1.0.0"
    min_profit_factor: float          # centralized, tested (correction #5)
    require_positive_expectancy: bool
    max_drawdown_pct: float
    # availability rules: which metrics MUST be AVAILABLE
```

`evaluate(metrics, timeframe)` → PASS/FAIL/INCONCLUSIVE using ABSOLUTE thresholds
+ `get_min_trades(timeframe)`. No trade-per-day heuristics.

---

## 5. PF threshold is policy, not scattered literal (correction #5)

`min_profit_factor` lives ONLY in `ConfirmationPolicy` (default e.g. 1.10, explicit
and tested — NOT `1.0` scattered). Confirmation is an absolute OOS gate; it never
compares profit % across DEVELOP vs CONFIRMATION.

---

## 6. Execution status vs research decision (correction #6)

```python
class ConfirmationExecutionStatus(str, Enum):
    SKIPPED / BLOCKED / PROTOCOL_DENIED / EXECUTION_SYSTEM_FAILURE / COMPLETED

class ConfirmationDecision(str, Enum):
    PASS / FAIL / INCONCLUSIVE
```

* backtest OK + thresholds met → COMPLETED / PASS
* backtest OK + PF/expectancy gate failed → COMPLETED / FAIL
* backtest OK + insufficient sample / critical metric UNAVAILABLE → COMPLETED / INCONCLUSIVE
* Freqtrade process failure / parse / metrics system failure → EXECUTION_SYSTEM_FAILURE, `decision = None`
* Never convert system failure → INCONCLUSIVE.

---

## 7. Frozen execution context (correction #7)

Confirmation inherits the EXACT current Champion context; only timerange differs
(DEVELOP → CONFIRMATION). `params_override` = Champion's exact parameter set. No
mutation of any kind.

---

## 8. Access ordering (correction #8)

Eligibility gate → verify frozen Champion hashes → compute identity →
reusable-result lookup → `zone_guard.request_access(CONFIRMATION)` → persist ledger
reference → execute exact frozen Champion → Metrics SSOT → `ConfirmationPolicy` →
persist `ConfirmationResult` → update `ResearchState` summary → on PASS only, set
protocol gate. Ordering test included. No execution before CONFIRMATION access.

---

## 9. Audit / contamination tests (A–R)

A same identity → reused, no 2nd exec
B same champion + altered frozen context → rejected/conflict
C restart after completed → reused
I same identity rerun → reused
J changed strategy hash after eligibility → integrity failure, no exec
K changed parameter hash after eligibility → integrity failure, no exec
L altered execution config → identity mismatch / frozen-context rejection
M access denied → no exec, no PASS, protocol gate false
N PASS → result persisted, protocol gate true
O FAIL → result persisted, Champion unchanged, gate false
P INCONCLUSIVE → result persisted, Champion unchanged, gate false
Q system/parse failure → EXECUTION_SYSTEM_FAILURE, not INCONCLUSIVE, gate false
R restart after completed → deterministic reuse, no repeated exposure

---

## 10. Real execution guard — minimal (correction #10)

Guarded smoke test only. No separate REAL milestone / no code expansion.

```
Freqtrade unavailable → SKIPPED: REAL_FREQTRADE_UNAVAILABLE
Freqtrade available   → one real Confirmation smoke on frozen Champion + CONFIRMATION zone
```

Do NOT claim REAL CONFIRMATION / FULL E2E verified until the real test executes.

---

## Implementation order

1. `research/confirmation_policy.py` — enums + `ConfirmationPolicy` (reuse `get_min_trades`).
2. `research/confirmation.py` — `ConfirmationResult` + `ConfirmationStore` + `ConfirmationService`
   (identity/idempotency, frozen eval, protocol gate, ordering).
3. `research/state_store.py` — add `confirmation_status` + `latest_confirmation_result_id` to `ResearchState`.
4. `research/factory.py` — `build_confirmation_service`.
5. `orchestrator.py` — run after Sensitivity PASS (gated by `eligible_for_confirmation`).
6. `api/routers/aeroing4.py` — surface `confirmation_status`.
7. `tests/aeroing4/research/test_confirmation.py` — A–R + guarded smoke skip.

## Out of scope
Final Unseen, Delivery, Frontend, Monte Carlo/GA/RL/multi-agent, any mutation/repair
inside Confirmation.
