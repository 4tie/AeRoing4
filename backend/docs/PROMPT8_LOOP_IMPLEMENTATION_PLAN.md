# PROMPT 8 — Controlled Research Loop: Remaining Implementation Plan

**Status accepted:** Prompt 8 NOT COMPLETE · focused primitive verification PASSING · Controlled Research Loop NOT IMPLEMENTED · real Freqtrade E2E NOT VERIFIED.

**Scope of this plan:** ONLY the remaining work. The following already exist and are verified (47 passed focused tests; AeRoing4-scoped suite 526 passed / 2 pre-existing failures / 10 skipped / 0 collection errors):

- Diagnosis engine integrity-before-cache-reuse (Q1) — `diagnosis/engine.py`
- DiagnosisStore writer safety + delete lock (Q2) — `diagnosis/persistence.py`
- Allowed mutation targets — `research/allowed_targets.py`
- Proposal Generator — `research/proposal_generator.py`
- Mutation Policy — `research/mutation_policy.py`
- ExperimentStore reservation / duplicate / budget — `research/experiments.py`
- DataZoneGuard / access_guard — `research/access_guard.py`
- Restart/recovery — `research/experiments.py::reconcile_interrupted_experiments`

Everything below is additive. No existing module is rewritten unless explicitly called out.

All code references are grounded in the current source (paths under `backend/services/aeroing4/`).

---

## 1. Fix ExperimentStore Windows concurrency defect (DO FIRST)

**File:** `backend/services/aeroing4/research/experiments.py` → `ExperimentStore._save_locked` (lines 603–628).

### Current temp-file naming
```python
tmp = f.with_suffix(".tmp")          # always "<run>/experiments.tmp" — SHARED name
...
with open(tmp, "w", ...) as fh:       # written once, before the retry loop
    json.dump(payload, fh); fh.flush(); os.fsync(fh.fileno())
for attempt in range(10):
    try:
        tmp.replace(f)               # atomic swap
        break
    except (PermissionError, FileNotFoundError):
        if attempt == 9: raise
        tmp = f.with_suffix(".tmp")  # re-points at SAME path, content already gone
        time.sleep(0.05 * (attempt + 1))
```
Outer `except Exception: tmp.unlink(missing_ok=True); raise`.

### How simultaneous writers can interact
`ExperimentStore.reserve()` holds `get_lock_for_path(experiments.json)` for the whole call, so **same-run** concurrent `reserve()` serialises. But the temp file name `experiments.tmp` is shared across every writer for that run and across processes. Two failure modes:

1. **Cross-process / antivirus hold on `f`** → `tmp.replace(f)` raises `PermissionError`. Current retry sleeps and retries the same temp file — this case is recoverable *as long as the temp file still exists*.
2. **Temp file disappears before replace** (deleted by another writer's outer `except` cleanup, temp-dir scavenger, or a prior failed attempt) → `tmp.replace(f)` raises `FileNotFoundError`.

### Why retrying `replace()` on a deleted temp file is unsafe
On the `FileNotFoundError` branch the code does `tmp = f.with_suffix(".tmp")` — reassigning the *path string* — but it **never re-opens or re-writes** the temp file. The file content was already flushed once before the loop and is now gone. Every subsequent `tmp.replace(f)` therefore raises `FileNotFoundError` again, and after 10 attempts the outer `except` does `tmp.unlink(missing_ok=True)` (no-op) and re-raises. **The save is lost and the caller gets an unhandled error**, even though the data was valid. This is exactly the background-thread `FileNotFoundError` warning observed in `test_duplicate_concurrent_creates_one_experiment`.

### Minimal safe fix (preferred: unique temp file per write)
Use a **unique temp filename per write** under the same shared path lock. This removes the shared-`experiments.tmp` contention entirely and makes a missing temp file impossible (each attempt opens a fresh, uniquely-named file).

```python
import uuid
def _save_locked(self, run_id, records):
    f = self._experiment_file(run_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    payload = [json.loads(r.model_dump_json()) for r in records]
    max_retries = 10
    for attempt in range(max_retries):
        tmp = f.with_name(f"{f.stem}.{uuid.uuid4().hex}.tmp")   # unique per attempt
        try:
            with open(tmp, "w", encoding="utf-8") as fh:        # content written EVERY attempt
                json.dump(payload, fh, indent=2); fh.flush(); os.fsync(fh.fileno())
            tmp.replace(f)                                      # atomic swap
            return
        except PermissionError:
            if attempt == max_retries - 1:
                raise
            time.sleep(0.05 * (attempt + 1))                    # backoff, then rewrite+retry
        except FileNotFoundError:
            # Should not happen with unique names, but if it does, retry rewrites fresh.
            if attempt == max_retries - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    # unreachable; loop always returns or raises
```

Atomic persistence is preserved: `tmp.replace(f)` is still the only point that mutates the real file. The shared path lock is unchanged. No weakening.

**Same latent pattern** exists in `hypotheses.py:278` and `research_state.py:190` (they catch only `PermissionError`, not `FileNotFoundError`, and also share one fixed `.tmp` name). Back-port the same unique-temp fix there for consistency — secondary, not blocking.

### Regression test (add to `tests/aeroing4/research/test_experiments_windows_race.py`)
- `test_concurrent_saves_preserve_all_records`: spawn N threads, each calls `store.reserve()` with distinct `ExperimentRecord`s for the **same run_id**; join; reload; assert `len(records) == N` and no exception escaped.
- `test_save_locked_recovers_from_missing_temp`: monkeypatch `Path.replace` to first raise `FileNotFoundError` once (simulating vanished temp), then succeed; assert save completes and file content is correct.
- Run on Windows (CI or local) — this is the real failure surface.

---

## 2. Candidate Artifact Service

**New file:** `backend/services/aeroing4/research/candidate_artifacts.py`.

### Responsibilities
- Input: current `ChampionReference`, one policy-approved `ExactChange`, `strategy_name`, `runs_root`, champion run-local artifact paths (from `ChampionReference.strategy_artifact` / `parameter_artifact`).
- Create a **run-local candidate artifact** under `runs_root/{run_id}/candidates/{candidate_id}/`:
  - Copy champion strategy `.py` → candidate copy. **Never** write to `original_source_path`. **Never** mutate the champion artifact in place (champion artifacts live under `champions/` and are read-only references).
  - Copy champion parameter sidecar → candidate sidecar.
- Apply exactly the one approved change:
  - **Parameter-only, sidecar-owned target** (target found in `_safe_sidecar_targets`, i.e. `source == SIDECAR_METADATA`): mutate the **copied sidecar JSON** value only. **Prefer sidecar mutation** — do not rewrite Python for parameter targets.
  - If a target required Python rewrite, v1 scope does **not** support it (our allowed targets are parameters); such a change is rejected upstream by Mutation Policy, so the service only ever receives sidecar-owned parameter changes in v1.
- Compute `before`/`after` hashes:
  - `strategy_hash_before/after` = sha256 of the champion strategy artifact vs candidate strategy copy (proves strategy file unchanged by param mutation).
  - `parameter_hash_before/after` = sha256 of champion sidecar JSON vs candidate sidecar JSON.
- Return typed `CandidateArtifactResult`:
  ```python
  class CandidateArtifactResult(BaseModel):
      candidate_id: str
      candidate_dir: str
      strategy_artifact: ArtifactReference      # copied .py
      parameter_artifact: ArtifactReference     # copied + mutated sidecar
      strategy_hash_before: str
      strategy_hash_after: str
      parameter_hash_before: str
      parameter_hash_after: str
  ```

### SSOT rule
`ExperimentRecord` remains the **sole persistent source of truth** for candidate metadata. The Loop Coordinator copies `CandidateArtifactResult` fields into the existing `ExperimentRecord` fields (`candidate_id`, `strategy_hash_before/after`, `parameter_hash_before/after`, `artifacts`). **No `CandidateArtifactStore` is created.**

### Sidecar mutation detail
Reuse `allowed_targets._safe_sidecar_targets` to locate the editable param block in `runs_root/strategies/{strategy_name}.json`. Patch the single key named by `exact_change.target` with `exact_change.after_value`; rewrite only the candidate copy. Keep `original_source_path`/`original_source_hash` pointing at the user's file for audit; the candidate's own `artifact_hash` is the new sidecar hash.

---

## 3. Candidate Executor

**New file:** `backend/services/aeroing4/research/candidate_executor.py`.

### Reuse, do not rebuild
Use the existing `BacktestRunner` (`services/execution/backtest_runner.py:44`, interface `IBacktestRunner`). Call `run_backtest(strategy, version_id, request)` (sync, wrap in `asyncio.to_thread` from the coordinator) — **not** a new engine.

### Freeze Parent Champion research context
All of the following are read from the champion's `ResearchState` / `ResearchProtocolState` / `PortfolioBaselineResult` and passed unchanged into the `RunRequest` (only the approved mutation differs):
- `pairs` — champion's selected pair set (from baseline selection or `ResearchState` evidence).
- `timeframe` — from run.
- `timerange` — `run.research_protocol.boundaries.develop_timerange` (**DEVELOP only**; never CONFIRMATION/FINAL_UNSEEN).
- `exchange`, `trading_mode`, `dry_run_wallet` (wallet/stake config), `max_open_trades`, `config_file` (config identity), `protocol_version`, `metrics_version`.

### Supplying candidate artifacts to BacktestRunner — INTERNAL override only (user decision 2026-07-11)
`RunRequest` is a **public** backtest contract (run settings); it must NOT gain an internal research-override field. `BacktestRunner` already resolves params from `VersionManager` and uses them at materialization.

**Decision: keep the override internal to the execution layer.**
- Add `params_override: ParamsSchema | None = None` as an **internal** parameter of `BacktestRunner._execute_run` (and `run_backtest`), NOT a field on `RunRequest`.
- When `params_override` is provided, `_execute_run` uses it instead of `version_manager.load_params(...)`; when `None`, behavior is identical to today.
- Provide a Research-Layer entry point `BacktestRunner.run_candidate_backtest(strategy, version_id, request, params_override, phase_callback=None)` that calls `run_backtest(..., params_override=params_override)`. The candidate `.py` copy is supplied via `strategy_path` (already accepted by `run_backtest`).

This keeps the public `RunRequest` contract unchanged and minimizes blast radius across the app.

Normal Backtest → VersionManager params. Research Candidate → Candidate sidecar / approved params override (internal).

### Return
Typed `CandidateExecutionResult`:
```python
class CandidateExecutionStatus(str, Enum):
    SUCCESS = "success"
    EXECUTION_FAILURE = "execution_failure"   # freqtrade non-zero / no raw_result
    PARSE_FAILURE = "parse_failure"
    NO_TRADES = "no_trades"
    SYSTEM_FAILURE = "system_failure"

class CandidateExecutionResult(BaseModel):
    underlying_execution_id: str | None       # freqtrade run_id from BacktestRunner
    status: CandidateExecutionStatus
    candidate_dir: str
    artifacts: dict[str, str]
    metrics: CanonicalMetricsSnapshot | None   # resolved via existing adapter, NOT computed here
    failure_classification: str | None
```
**Do not calculate metrics locally.** Resolve `CanonicalMetricsSnapshot` from the backtest result using the existing metrics adapter (`metrics/adapters.py` — `from_parsed_summary` / equivalent already used by `research` tests). If parsing fails → `PARSE_FAILURE`.

---

## 4. Diagnosis-aware Deterministic Decision Policy

**New file:** `backend/services/aeroing4/research/decision_policy.py`.

### Contract
```python
RESEARCH_DECISION_POLICY_VERSION = "1.0.0"

class DecisionOutcome(str, Enum):
    KEEP = "keep"
    DROP = "drop"
    INCONCLUSIVE = "inconclusive"
    UNSUPPORTED_OBJECTIVE = "unsupported_objective"

class DecisionResult(BaseModel):
    outcome: DecisionOutcome
    diagnosis_code: str
    objective: str
    reason: str
    metrics_compared: dict[str, Any]
    guardrails_passed: list[str]
    policy_version: str = RESEARCH_DECISION_POLICY_VERSION
```

### Method
`decide(*, diagnosis_code, champion_metrics: CanonicalMetricsSnapshot, candidate_metrics: CanonicalMetricsSnapshot, evidence_quality, materiality_overrides=None) -> DecisionResult`.

Flow per code:
1. Look up `DiagnosisCode → ObjectiveSpec` (objective metric, target evidence fields, materiality threshold, guardrails).
2. If code has **no reliable comparison path** under parameter-only mutation → `UNSUPPORTED_OBJECTIVE` (coordinator maps to INCONCLUSIVE, never KEEP).
3. Compare candidate vs champion on the objective metric(s).
4. Apply **global guardrails** (must pass for any KEEP):
   - `candidate.total_trades >= MIN_TRADE_COUNT` (default 20) — no trade-count starvation.
   - `evidence_quality != INSUFFICIENT`.
   - Candidate does not breach a hard risk cap (e.g., `max_drawdown_pct` within +X pp of champion; configurable constant).
   - Zone is DEVELOP (enforced by executor, asserted here).
5. Materiality: improvement must exceed the threshold **and** the candidate must still be a valid edge (`profit_factor > 1.0`, `expectancy > 0` where those are the objective).
6. Emit KEEP / DROP / INCONCLUSIVE.

### Initial supported objectives (only codes with real available evidence)
CanonicalMetricsSnapshot fields available: `total_trades, profit_factor, expectancy, max_drawdown_abs/pct, sharpe, sortino, calmar, win_rate, net_profit_abs/pct, bootstrap_sharpe_p5, per_pair_contribution, concentration_summary, exit_reason_distribution`.

| DiagnosisCode | Objective (candidate vs champion) | Materiality | Reliable under param-only? |
|---|---|---|---|
| `NO_EDGE` | `profit_factor>1.0` and `expectancy>0` | PF +0.1, exp +0.0005 | Yes |
| `NEGATIVE_EXPECTANCY` | `expectancy>0` (baseline <0) | exp +0.0005 | Yes |
| `LOW_PROFIT_FACTOR` | `profit_factor > baseline + mat` and `>1.0` | +0.1 | Yes |
| `STOPLOSS_DOMINANCE` | reduce `exit_reason_distribution[stoploss].share` below threshold | −5pp | Yes (exit-reason distribution present) |
| `EXIT_LOSS_CONCENTRATION` | reduce negative-contribution exit share | −5pp | Yes |
| `PAIR_CONCENTRATION` | reduce `concentration_summary.top_pair_profit_contribution_share` | −5pp | **Caution** — pair set fixed by champion; param mutation rarely moves concentration → prefer INCONCLUSIVE |
| `SINGLE_PAIR_DEPENDENCE` | increase contributing-pair count / reduce top share | −5pp | **Caution** — same caveat → prefer INCONCLUSIVE |
| `MULTIPLE_NEGATIVE_CONTRIBUTORS` | reduce count of negative-contribution pairs | −1 pair | **Caution** — same caveat → prefer INCONCLUSIVE |
| `EXCESSIVE_DRAWDOWN` | `max_drawdown_pct < baseline` and `< cap` | −2pp | Yes |
| `POOR_RETURN_TO_DRAWDOWN` | `(net_profit/max_drawdown) > baseline + mat` | +0.05 | Yes |
| `ENTRY_TOO_RESTRICTIVE` | `total_trades` (activity) `> baseline + mat` | +10% trades | Yes |

**Honesty rule:** For `PAIR_CONCENTRATION`, `SINGLE_PAIR_DEPENDENCE`, `MULTIPLE_NEGATIVE_CONTRIBUTORS` — parameter-only mutation cannot reliably change the **pair set**, so the objective is marked `UNSUPPORTED_OBJECTIVE` and the coordinator records INCONCLUSIVE (champion unchanged, history preserved). Do **not** fabricate target evidence the candidate execution does not produce.

All thresholds are named module constants (e.g. `MIN_TRADE_COUNT`, `PF_MATERIALITY`, `DRAWDOWN_MATERIALITY_PP`, `TRADE_COUNT_MATERIALITY`, `STOPLOSS_SHARE_THRESHOLD`) so they are explicit and testable. No universal metric ordering — each code has its own objective.

---

## 5. Controlled Research Loop Coordinator

**New file:** `backend/services/aeroing4/research/loop_coordinator.py`.

Orchestration logic only. **No new `LoopStateStore`** — reuse `ResearchState` as the persistent research truth.

### Constructor dependencies
`ResearchLoopCoordinator(state_store, experiment_store, champion_store, hypothesis_store, data_zone_guard, diagnosis_engine, diagnosis_store, proposal_generator, candidate_artifact_service, candidate_executor, decision_policy, allowed_targets_discoverer, mutation_policy, services)`.

### Method
`async def run_loop(self, run_id: str, *, max_iterations: int, enable_research_loop: bool = True) -> ResearchLoopSummary`

### Exact iteration order (per the spec)
1. Load `ResearchState`.
2. Verify current Champion (via `ChampionStore`).
3. Load or run valid Diagnosis (`diagnosis_engine.diagnose` + idempotent store; reuse `DiagnosisEngine` already implemented).
4. Select actionable diagnosis (`primary_diagnosis` if outcome `DIAGNOSIS_COMPLETE` and evidence not insufficient).
5. Reuse compatible active Hypothesis or create new (see §6).
6. Discover trusted Allowed Mutation Targets (`allowed_targets.discover_allowed_mutation_targets`).
7. Build bounded Proposal context (limits, no shell/code/path).
8. Call `ProposalGenerator.propose`.
9. Strict schema validation (generator already enforces; coordinator rejects non-`ACCEPTED`).
10. Validate evidence references (non-empty, exist in diagnosis).
11. Validate target exists in allowed targets.
12. `MutationPolicy.evaluate`.
13. Build deterministic Experiment identity (`experiment_identity_hash` from parent champion + exact_change + DEVELOP context + config identity — already partially in `ExperimentRecord`).
14. Call `ExperimentStore.reserve()` **exactly once**.
15. If duplicate → return existing experiment reference, consume **no** new budget (reserve already returns duplicate without reserving).
16. Request DEVELOP access via `DataZoneGuard.request_access(stage=RESEARCH, zone=DEVELOP, …)`.
17. Mark experiment READY (`transition_status(READY)`).
18. Create candidate artifact (`candidate_artifact_service`).
19. Apply exactly one approved change (sidecar mutation).
20. Execute candidate (`candidate_executor.execute`).
21. Produce/resolve `CanonicalMetricsSnapshot` (via adapter).
22. Run `DecisionPolicy.decide`.
23. Persist `ExperimentDecision` (`experiment_store.record_decision`).
24. Update Hypothesis lifecycle (`hypothesis_store.transition_status` to SUPPORTED/REJECTED/EXHAUSTED as appropriate).
25. **KEEP:** `champion_store.promote(...)` preserving `parent_champion_id`, set `source_experiment_id`; update `ResearchState.current_champion_id`; re-run/reuse Diagnosis for the new champion.
26. **DROP:** Champion unchanged.
27. **INCONCLUSIVE:** Champion unchanged.
28. Continue only while budget remains and actionable research exists.

**Hard guarantees:**
- No candidate artifact creation before `reserve()` succeeds (steps 14 → 18 ordering).
- No AI final decision — AI only proposes (step 8); decision is deterministic (step 22).
- No direct CONFIRMATION or FINAL_UNSEEN access (executor uses DEVELOP only).

---

## 6. Hypothesis reuse (deterministic selector)

**Add to:** `research/hypotheses.py` (no new store, no rebuild of `HypothesisStore`).

```python
def select_compatible_hypothesis(
    self, run_id, *, diagnosis_code, target_scope=None, evidence_refs=None
) -> HypothesisRecord | None:
    candidates = [h for h in self.list_for_run(run_id)
                  if h.status in (PROPOSED, APPROVED, ACTIVE)        # exclude REJECTED/EXHAUSTED/SUPPORTED
                  and h.diagnosis_code == diagnosis_code
                  and (target_scope is None or h.target_scope == target_scope)]
    if evidence_refs:
        candidates = [h for h in candidates
                      if set(evidence_refs) & {r.ref_path for r in h.evidence_refs}]
    candidates.sort(key=lambda h: h.created_at)
    return candidates[0] if candidates else None
```
No semantic/AI similarity. Deterministic compatibility only.

---

## 7. ResearchState minimal extension

**File:** `research/research_state.py` → `ResearchState` (lines 65–94).

Existing fields already cover `current_champion_id`, `current_champion_strategy_hash`, `current_champion_parameter_hash`, `current_hypothesis_id`, `active_experiment_id`, budget counters, `research_status`. **Do not duplicate these.**

Add only the proven-necessary additive fields:
```python
current_iteration: int = 0
stop_reason: Optional[str] = None
pause_reason: Optional[str] = None
last_decision_id: Optional[str] = None
```
No new store; `ResearchStateStore` is reused as-is.

---

## 8. Proposal Generator integration (verify, do not rebuild)

**File:** `research/proposal_generator.py` (already read). Verified against the required contract:
- ✅ Strict JSON schema (`_validate_proposal_payload`, known/expected keys only).
- ✅ Exactly one repair attempt (`for attempt in range(2)`).
- ✅ AI unavailable typed result (`ProposalOutcome.AI_UNAVAILABLE`, `OllamaProposalAdapter.generate` catches all exceptions).
- ✅ Malformed proposal → `AI_PROPOSAL_SKIPPED` (no reservation).
- ✅ `force_skip` context limit → `AI_PROPOSAL_SKIPPED`.
- ✅ Proposal-only role (no execution); **no** `cmd/shell/exec/code/path/file_path` etc. (forbidden-keys block).
- ✅ Allowed target list supplied from backend (`ProposalRequest.allowed_targets`, built by coordinator from `allowed_targets.discover_*`).

**Conclusion:** Proposal Generator needs **no rebuild**. The missing pieces are **coordinator responsibilities**, not generator changes:
- If `outcome != ACCEPTED` → coordinator must NOT call `reserve()`.
- If `outcome == AI_UNAVAILABLE` → coordinator sets `ResearchState.research_status = PAUSED` + `pause_reason`, consumes **no** budget, creates **no** candidate artifact, **no** ExperimentRecord.

---

## 9. Integration wiring (minimal, opt-in)

### `orchestrator.py`
- Add `enable_research_loop: bool = False` to `create_run` (line 47) and thread into `state_store.create_run`.
- After the Diagnosis step (line ~468), add:
  ```python
  if getattr(run, "enable_research_loop", False):
      from .research.loop_coordinator import ResearchLoopCoordinator
      from .research.factory import build_research_loop_coordinator
      coordinator = build_research_loop_coordinator(self.services, self.state_store.runs_root)
      await coordinator.run_loop(run_id, max_iterations=run.max_total_experiments)
  ```
- Existing runs with `enable_research_loop=False` are **byte-for-byte unchanged**.

### Run / request models
- Add `enable_research_loop: bool = False` to `AeRoing4Run` (in `services/aeroing4/models.py`) and its creation payload. Default `False`.

### `AppServices` / service wiring
- Add `services/aeroing4/research/factory.py::build_research_loop_coordinator(services, runs_root)` that assembles all stores + `BacktestRunner` (`services.backtest_runner`), `strategy_registry`, `version_manager`, `result_parser`, diagnosis engine/store, proposal generator, candidate services, decision policy, mutation policy, data zone guard.

### Executor → BacktestRunner wiring (internal override, NO `RunRequest` change)
- Add internal `params_override: ParamsSchema | None = None` to `BacktestRunner.run_backtest` and `_execute_run` only (NOT `RunRequest`). When set, `_execute_run` uses it instead of `version_manager.load_params(...)`; when `None`, identical to today.
- Add `BacktestRunner.run_candidate_backtest(...)` as the Research-Layer entry point that forwards `params_override`.
- No change to `models/contracts.py` `RunRequest`.

### AeRoing4 API router
- Add optional `enable_research_loop` to the run-creation request schema.
- Expose research-loop status in `GET /api/aeroing4/runs/{id}` summary: `research_status`, `current_iteration`, `pause_reason`, `stop_reason`, `last_decision_id`, current champion id. No forced enable.

### Behavior matrix
- **Start:** only when `enable_research_loop=True` (opt-in).
- **Pause:** coordinator sets `ResearchState.PAUSED` + `pause_reason` (e.g., AI unavailable, budget exhausted, no actionable diagnosis); loop returns.
- **Resume:** re-invoke `run_loop` when status is `PAUSED` and caller requests; continues from `current_iteration`.
- **Cancellation:** existing `cancel_run` stops the workflow task; coordinator checks `ResearchState.research_status` each iteration and stops if not `ACTIVE`.
- **API summary:** read-only research state exposure as above.

---

## 10. Required integration scenarios (tests)

All under `tests/aeroing4/research/` (and `tests/test_aeroing4_research_loop.py`). Use real stores over a `tempfile.mkdtemp()` runs_root for unit/service-boundary; use a **fake BacktestRunner** (implements `run_backtest` returning a deterministic `RunMetadata` + pre-written `raw_result.json`/`metrics`) so scenarios A–F run without Freqtrade. Real `BacktestRunner` is used only in §11 items 13–14.

- **A. DROP path** — `test_loop_drop_path`: Champion A → Diagnosis A → Hypothesis → Proposal(ACCEPTED) → MutationPolicy ALLOWED → reserve → DEVELOP access → candidate artifact → fake execute → metrics → DecisionPolicy DROP → assert current champion still A, experiment decision DROP persisted, history preserved.
- **B. KEEP path** — `test_loop_keep_path`: same setup, DecisionPolicy KEEP → assert new Champion B created, `parent_champion_id == A`, `source_experiment_id` set, `ResearchState.current_champion_id == B`, Diagnosis B runs/reuses, next proposal uses Diagnosis B.
- **C. AI unavailable** — `test_loop_ai_unavailable_pauses`: ProposalGenerator returns `AI_UNAVAILABLE` → assert `ResearchState.research_status == PAUSED`, **no** ExperimentRecord, **no** budget consumed (`total_experiments_reserved == 0`), **no** candidate artifact.
- **D. Duplicate** — `test_loop_duplicate_returns_existing`: same parent + same `ExactChange` + same DEVELOP context + same config identity → second iteration returns existing experiment, no new budget slot, no candidate execution (assert executor call count == 1).
- **E. Restart** — `test_loop_restart_reconciles`: seed an experiment in `RUNNING`, call `reconcile_interrupted_experiments`, assert → `INTERRUPTED`, `resume_safety_report.new_experiment_allowed == False`, no duplicate execution scheduled.
- **F. INCONCLUSIVE** — `test_loop_inconclusive`: candidate executes, comparison evidence insufficient (e.g. `PAIR_CONCENTRATION` under param-only) → DecisionPolicy INCONCLUSIVE → Champion unchanged, experiment decision INCONCLUSIVE persisted.

---

## 11. Verification strategy (ordered)

1. ExperimentStore Windows race regression test (§1).
2. Candidate Artifact tests (sidecar mutation, hashes, no original mutation).
3. Candidate Executor tests (fake BacktestRunner; `params_override` path; status/failure classification; metrics resolved via adapter, not local).
4. Decision Policy tests (each supported code; materiality; guardrails; UNSUPPORTED_OBJECTIVE → INCONCLUSIVE for pair-structure codes).
5. Loop Coordinator tests (orchestration order; reservation-before-artifact invariant).
6. Scenario A (DROP). 7. Scenario B (KEEP). 8. Scenario C (AI unavailable). 9. Scenario D (Duplicate). 10. Scenario E (Restart). 11. Scenario F (INCONCLUSIVE).
12. AeRoing4-scoped regression suite (the 526/2/10 command from prior turn).
13. Real Ollama proposal test (port 11434 is OPEN — exercise `OllamaProposalAdapter` against live Ollama with a guarded timeout; assert `ACCEPTED` or `AI_UNAVAILABLE`, never crash).
14. Real Freqtrade candidate execution test **when Freqtrade is available** (currently NOT on PATH — this item stays BLOCKED until a Freqtrade executable is configured; assert a real candidate strategy runs end-to-end and produces a `CanonicalMetricsSnapshot`).

### Reporting categories (separate)
- **UNIT VERIFIED** — items 1–11 pass with fakes/temp stores.
- **SERVICE-BOUNDARY VERIFIED** — Executor + Decision Policy + Coordinator exercise real stores and real `BacktestRunner` interface with a fake subprocess.
- **REAL OLLAMA VERIFIED** — item 13 passes against live Ollama.
- **REAL FREQTRADE VERIFIED** — item 14 passes against a real Freqtrade binary.
- **FULL E2E VERIFIED** — only after item 14: a real candidate strategy executed through real Freqtrade inside the loop, KEEP/DROP recorded. **Do NOT claim Full E2E until then.**

---

## 12. Scope protection (explicitly NOT implemented)

- Focused Hyperopt
- Sensitivity Analysis
- Confirmation execution
- Final Unseen execution
- Delivery
- Frontend
- Monte Carlo
- Genetic Algorithms (GA)
- Reinforcement Learning (RL)
- Multi-agent / swarm systems
- Arbitrary AI Python strategy rewriting

---

## Implementation order (mandated)
1. §1 ExperimentStore race fix (+ regression test) — **blocks everything else that writes heavily**.
2. §2 Candidate Artifact Service (+ tests).
3. §3 Candidate Executor (+ `RunRequest.params_override` dependency) (+ tests).
4. §4 Decision Policy (+ tests).
5. §5 Loop Coordinator (+ tests).
6. §6 Hypothesis selector.
7. §7 ResearchState fields.
8. §8 (no generator change; coordinator wiring only).
9. §9 Integration wiring (opt-in `enable_research_loop`).
10. §10 Scenarios A–F.
11. §11 Verification (units → scoped suite → real Ollama → real Freqtrade when available).

**Do not begin Focused Hyperopt or Sensitivity.**
