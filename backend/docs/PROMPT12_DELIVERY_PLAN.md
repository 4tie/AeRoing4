# PROMPT 12 — Delivery / Export Package (Implementation Plan, planning only)

**Stage:** DELIVERY — packaging, NOT validation. Terminal safe export of a verified Champion.

```
FinalUnseenResult exists + decision=PASS + delivery_eligible=true
→ ResearchState.delivery_eligible=true
→ current Champion matches FinalUnseenResult (id + hashes)
→ no PAUSED · no active experiment requiring reconciliation
→ package to a RUN-LOCAL delivery directory (safe by default)
→ typed DeliveryStatus (not PASS/FAIL)
```

**Cardinal rule:** No AI · no mutation · no Hyperopt · no repair · no backtest · no
sensitivity · no confirmation/final-unseen rerun · no parameter changes. Delivery only
answers: "Can this verified champion be packaged safely?"

---

## Reuse inventory (all already exist — no rewrite)

* `FinalUnseenResult` (PROMPT 11) — delivery gate source of truth.
* `ConfirmationResult` (PROMPT 10) — confirmation result reference.
* `ChampionReference` + `ChampionStore` (`champions.py`) — artifacts + lineage
  (strategy_artifact / parameter_artifact with `artifact_hash`, `original_source_path`).
* `ResearchState.delivery_eligible` (PROMPT 11) — summary flag.
* `CanonicalMetricsSnapshot` (Metrics SSOT) — metrics summary.
* `AccessLedger` (optional audit/provenance entry for the export action).

---

## 1. Typed Delivery (manifest, not a status-only field)

`research/delivery_policy.py`:

```python
class DeliveryStatus(str, Enum):
    BLOCKED / READY / DELIVERED / REUSED / EXPORT_FAILED

class DeliveryPolicy:
    policy_version: str = "1.0.0"
    default_export_profile: str = "run_local"   # safe: never overwrite production
    force_overwrite_default: bool = False
```

`research/delivery.py`:

```python
class DeliveryPackage(BaseModel):   # the manifest
    delivery_id: str
    run_id: str
    champion_id: str
    strategy_name: str
    strategy_hash: str
    parameter_hash: str
    final_unseen_result_id: str
    confirmation_result_id: str | None
    source_champion_type: str | None
    parent_champion_id: str | None
    source_experiment_id: str | None
    source_hyperopt_result_id: str | None
    metrics_version: str
    protocol_version: str
    confirmation_policy_version: str
    final_unseen_policy_version: str
    delivery_policy_version: str
    created_at: datetime
    delivery_status: DeliveryStatus
    artifact_hashes: dict[str, str]
    export_paths: dict[str, str]
    verification_flags: dict[str, bool]   # logic/service/real_* as required
    warnings: list[str]
    delivery_identity: str
```

`ResearchState` holds ONLY summary: `delivery_status`. No conflicting ownership.

`DeliveryStore` (JSON, atomic, lock-guarded — same pattern as Confirmation/FinalUnseen):
`save`, `load`, `find_by_identity`, `latest_for_run`.

---

## 2. Deterministic delivery identity + idempotency (no silent overwrite)

`delivery_identity = sha256(canonical)` over:

* run_id
* champion_id
* strategy_hash
* parameter_hash
* final_unseen_result_id
* final_unseen_identity
* delivery_policy_version
* target export profile

Before export:
* same identity exists → **reuse existing delivery metadata**, do NOT rewrite artifacts
  unless explicitly forced by a safe versioned export mode.
* Never silently overwrite existing production files.

---

## 3. Eligibility gate (strict, typed BLOCKED on any failure)

Delivery runs ONLY if ALL hold:

* `FinalUnseenResult` exists for run
* `FinalUnseenResult.decision == PASS`
* `FinalUnseenResult.delivery_eligible == true`
* `ResearchState.delivery_eligible == true`
* current Champion id matches `FinalUnseenResult.champion_id`
* Champion `strategy_hash` == `FinalUnseenResult.strategy_hash`
* Champion `parameter_hash` == `FinalUnseenResult.parameter_hash`
* no unresolved PAUSED state
* no active experiment requiring reconciliation

Any failure → typed `BLOCKED`, no export.

---

## 4. Required output (run-local delivery directory by default)

`{runs_root}/{run_id}/delivery/`:

1. final strategy `.py` (copy of champion strategy artifact — **original preserved**)
2. final params sidecar `.json` (copy of champion parameter artifact)
3. `delivery_manifest.json` (the `DeliveryPackage`)
4. frozen execution config snapshot (json)
5. metrics summary (from `FinalUnseenResult.canonical_metrics_snapshot`)
6. confirmation result reference (id)
7. final unseen result reference (id)
8. champion lineage summary (json)
9. audit/provenance report (ledger-derived)
10. `warnings.json` if anything is service-boundary-only or real Freqtrade unverified

---

## 5. Export safety (default = safe)

* Write to run-local delivery dir FIRST.
* Never overwrite user production strategy path by default.
* Export to Freqtrade `user_data/strategies` only with versioned filenames or explicit
  overwrite approval (`force_overwrite=True`, versioned name).
* Always export `.py` + `.json` together.
* Verify both files exist after export.
* Verify hashes after write match `artifact_hashes`.
* Verify sidecar matches delivered `parameter_hash`.
* Preserve original champion artifacts unchanged (copy-only).
* Partial write failure → `EXPORT_FAILED`, package NOT marked `DELIVERED`.

---

## 6. Verification flags (honest)

Manifest `verification_flags` includes:
`logic_verified`, `service_boundary_verified`, `real_ollama_verified`,
`real_hyperopt_verified`, `real_confirmation_verified`, `real_final_unseen_verified`,
`real_freqtrade_verified`, `full_e2e_verified`.

Without real Freqtrade execution: `real_*` = false; `warnings` records the gap.
Do NOT claim production readiness if real Final Unseen was skipped because Freqtrade
was unavailable.

---

## 7. Tests required (A–O)

A blocked if FinalUnseenResult missing
B blocked if FinalUnseen decision != PASS
C blocked if delivery_eligible=false
D blocked if current Champion differs from FinalUnseen champion
E blocked if strategy hash changed
F blocked if parameter hash changed
G blocked if active experiment requires reconciliation
H successful run-local delivery creates .py + .json + manifest
I same identity rerun reuses delivery metadata
J existing target file not overwritten by default
K explicit versioned export creates unique filename
L manifest contains all required provenance fields
M artifact hashes match written files
N missing sidecar prevents delivery
O partial write failure → EXPORT_FAILED, not DELIVERED

---

## Implementation order (when approved)

1. `research/delivery_policy.py` — `DeliveryStatus` + `DeliveryPolicy`.
2. `research/delivery.py` — `DeliveryPackage` + `DeliveryStore` + `DeliveryService`
   (eligibility, identity/idempotency, safe run-local export, hash verification,
   EXPORT_FAILED on partial failure, manifest with verification_flags + warnings).
3. `research/state_store.py` (`ResearchState`) — add `delivery_status`.
4. `research/factory.py` — `build_delivery_service`.
5. `orchestrator.py` — run after Final Unseen PASS (within the `enable_focused_hyperopt`
   block), gated by `delivery_eligible == true`.
6. `api/routers/aeroing4.py` — surface `delivery_status`.
7. `tests/aeroing4/research/test_delivery.py` — A–O.

## Verification reporting (post-implementation)

```
LOGIC VERIFIED
SERVICE-BOUNDARY VERIFIED
REAL DELIVERY VERIFIED
REAL FREQTRADE VERIFIED
FULL E2E VERIFIED
```

Do NOT claim REAL DELIVERY or FULL E2E unless a real passed Final Unseen result
exists and the package is exported from that real result.

## Out of scope
Hyperopt, Confirmation/Final Unseen reruns, any mutation/repair, frontend, Monte Carlo/
GA/RL/multi-agent, real Freqtrade execution (guarded only; manifest records real_*=false).
