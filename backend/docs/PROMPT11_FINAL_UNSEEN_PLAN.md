# PROMPT 11 — Final Unseen Evaluation (Implementation Plan, planning only)

**Stage:** FINAL UNSEEN — final independent test, NOT optimization. Terminal evidence.

```
Confirmation PASS
→ ResearchProtocolState.confirmation_passed = true
→ current Champion frozen
→ FINAL_UNSEEN zone only → exact frozen strategy + exact frozen params
→ one honest final evaluation
→ PASS / FAIL / INCONCLUSIVE / SYSTEM_FAILURE
→ delivery eligibility ONLY if PASS
```

**Cardinal rule:** No AI · no mutation · no Hyperopt · no repair · no sensitivity · no
parameter changes · no retry-on-performance · no tuning after seeing the result.
This stage must NOT become a hidden tuning loop.

---

## Reuse inventory (all already exist — no rewrite)

* `BacktestRunner.run_candidate_backtest(params_override=...)` — execution.
* `DataZoneGuard` + `AccessLedger` — `ResearchZone.FINAL_UNSEEN` access + audit.
  Note: `AccessLedger.AccessDecisionCode.FINAL_UNSEEN_ALREADY_CONSUMED` enforces
  one-time consumption; idempotent same-identity reuse is still allowed.
* `ResearchProtocolState.confirmation_passed` / `confirmation_passed_at` +
  `DataZoneGuard.set_confirmation_passed(run, True)` — gate (set by PROMPT 10).
* `get_min_trades(timeframe)` (`policies.py`) — shared timeframe-aware trade sufficiency.
* `compute_boundary_hash(...)` (`data_zones.py`) — `boundary_hash`.
* `ChampionReference.strategy_artifact.artifact_hash` / `parameter_artifact.artifact_hash`.
* `ConfirmationResult` (PROMPT 10) — `parent_confirmation_result_id` link.
* `CanonicalMetricsSnapshot` (Metrics SSOT) + resolver pattern.
* `ConfirmationService` pattern — FinalUnseenService mirrors it (frozen eval + identity).

---

## 1. Typed persistent FinalUnseenResult (not status-only)

`research/final_unseen.py`:

```python
class FinalUnseenResult(BaseModel):
    result_id: str
    run_id: str
    champion_id: str
    parent_confirmation_result_id: str | None
    strategy_hash: str
    parameter_hash: str
    boundary_hash: str
    final_unseen_timerange: str
    configuration_hash: str
    protocol_version: str
    metrics_version: str
    final_unseen_policy_version: str
    access_ledger_entry_id: str | None
    underlying_execution_id: str | None
    canonical_metrics_snapshot: dict | None
    metrics_snapshot_hash: str | None
    execution_status: FinalUnseenExecutionStatus
    decision: FinalUnseenDecision | None
    reason_codes: list[str]
    evaluated_at: datetime
    delivery_eligible: bool
    final_unseen_identity: str
```

`ResearchState` holds ONLY summary: `final_unseen_status`, `latest_final_unseen_result_id`,
`delivery_eligible`. No conflicting ownership with `ResearchProtocolState`.

`FinalUnseenStore` (JSON, atomic, lock-guarded — same pattern as `ConfirmationStore`):
`save`, `load`, `find_by_identity`, `latest_for_run`.

---

## 2. Deterministic identity + anti-contamination (no hidden tuning loop)

`final_unseen_identity_hash = sha256(canonical)` over:

* Champion ID
* strategy hash
* parameter hash
* Final Unseen boundary hash
* frozen execution configuration identity
* timeframe
* selected pair set (sorted)
* protocol version
* metrics version
* final unseen policy version

Before execution:
* same identity exists → **reuse existing result, no second execution**
* different frozen config for same Champion/FINAL_UNSEEN → **reject / typed identity conflict**, no silent rerun

---

## 3. Eligibility gate (strict, typed BLOCKED/SKIPPED on any failure)

Final Unseen starts ONLY if ALL hold:

* `ConfirmationResult` exists for run
* `ConfirmationResult.decision == PASS`
* `ResearchProtocolState.confirmation_passed == true`
* current Champion exists
* Champion `strategy_hash` == confirmed Champion strategy_hash
* Champion `parameter_hash` == confirmed Champion parameter_hash
* no active experiment requires reconciliation
* no unresolved PAUSED state
* Sensitivity was PASS (`eligible_for_confirmation` was true)
* `DataZoneGuard.request_access(FINAL_UNSEEN)` allowed
* no prior FINAL_UNSEEN result for same identity except the reusable same-identity result

Any failure → typed `BLOCKED` (or `SKIPPED` when simply not-yet-eligible) outcome, no execution.

---

## 4. Policy — versioned, absolute OOS gate

`research/final_unseen_policy.py`:

```python
class FinalUnseenExecutionStatus(str, Enum):
    SKIPPED / BLOCKED / PROTOCOL_DENIED / EXECUTION_SYSTEM_FAILURE / COMPLETED

class FinalUnseenDecision(str, Enum):
    PASS / FAIL / INCONCLUSIVE

class FinalUnseenPolicy:
    policy_version: str
    min_profit_factor: float          # centralized, tested (default 1.10)
    require_positive_expectancy: bool
    max_drawdown_pct: float
    required_metrics: tuple[str, ...] # which must be AVAILABLE
    # minimum trades sourced from shared get_min_trades(timeframe) — NOT duplicated
    def evaluate(self, metrics, timeframe): -> (decision|None, reason_codes)
```

Rules (correction — no cross-zone comparison, no zero-substitution):
* success + thresholds pass → COMPLETED / PASS / `delivery_eligible=true`
* success + threshold fail → COMPLETED / FAIL / `delivery_eligible=false`
* success + insufficient sample / unavailable critical metric → COMPLETED / INCONCLUSIVE / `delivery_eligible=false`
* Freqtrade/process/parser/metrics failure → EXECUTION_SYSTEM_FAILURE / `decision=None` / `delivery_eligible=false`
* Never convert system failure → INCONCLUSIVE.

---

## 5. Access ordering (no execution before access granted)

Eligibility gate → verify frozen Champion hashes → verify Confirmation PASS identity
→ compute Final Unseen identity → reusable result lookup →
`DataZoneGuard.request_access(FINAL_UNSEEN)` → persist ledger reference →
execute exact frozen Champion → Metrics SSOT → `FinalUnseenPolicy` →
persist `FinalUnseenResult` → update `ResearchState` summary →
on PASS set `delivery_eligible=true`.

Ordering test included (L).

---

## 6. Scope protection

* Do NOT implement Delivery in this prompt.
* Do NOT export strategy.
* Do NOT create frontend.
* Do NOT implement Monte Carlo / GA / RL / multi-agent / arbitrary AI.
* Do NOT mutate strategy or params.

---

## 7. Tests required (A–N)

A blocked if Confirmation did not PASS
B blocked if protocol confirmation_passed is false
C blocked if Champion hash differs from confirmed hash
D blocked if parameter hash differs from confirmed hash
E access denied → no execution
F same identity rerun → result reused, no second execution
G changed frozen execution config → identity conflict / rejected
H PASS → result persisted, delivery_eligible=true
I FAIL → result persisted, delivery_eligible=false
J INCONCLUSIVE → result persisted, delivery_eligible=false
K system/parse failure → EXECUTION_SYSTEM_FAILURE, not INCONCLUSIVE
L ordering test: access before execution
M restart after completed result → deterministic reuse
N guarded real Freqtrade smoke: skip when unavailable

---

## Implementation order (when approved)

1. `research/final_unseen_policy.py` — enums + `FinalUnseenPolicy` (reuse `get_min_trades`).
2. `research/final_unseen.py` — `FinalUnseenResult` + `FinalUnseenStore` + `FinalUnseenService`
   (eligibility incl. Confirmation PASS + protocol gate, identity/idempotency, frozen eval,
   delivery_eligible, ordering).
3. `research/state_store.py` (`ResearchState`) — add `final_unseen_status` +
   `latest_final_unseen_result_id` + `delivery_eligible`.
4. `research/factory.py` — `build_final_unseen_service`.
5. `orchestrator.py` — run after Confirmation PASS (within the `enable_focused_hyperopt`
   block), gated by `confirmation_status == "pass"`.
6. `api/routers/aeroing4.py` — surface `final_unseen_status` + `delivery_eligible`.
7. `tests/aeroing4/research/test_final_unseen.py` — A–N + guarded smoke.

## Verification reporting (post-implementation)

```
LOGIC VERIFIED
SERVICE-BOUNDARY VERIFIED
REAL FINAL_UNSEEN VERIFIED
REAL FREQTRADE VERIFIED
FULL E2E VERIFIED
```

Do NOT claim REAL FINAL_UNSEEN or FULL E2E while Freqtrade is unavailable.

## Out of scope
Delivery, Frontend, Monte Carlo/GA/RL/multi-agent, any mutation/repair.
