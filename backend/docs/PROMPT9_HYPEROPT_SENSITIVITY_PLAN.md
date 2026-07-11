# PROMPT 9 — Focused Hyperopt + Sensitivity Analysis (Revised Plan)

**Scope (explicit):** Implements exactly TWO stages, slotted into the user's
sequence after PROMPT 8's KEEP champion:

```
Controlled Research Loop          (PROMPT 8 — DONE)
        ↓  Champion after KEEP
Focused Hyperopt                  (THIS PROMPT — §1–§6, §10)
        ↓  HYPEROPT champion (DecisionPolicy-gated KEEP)
Sensitivity Analysis              (THIS PROMPT — §7–§9)
        ↓  SENSITIVITY_PASS
Confirmation / Final Unseen / Delivery   (LATER PROMPTS — NOT here)
```

**Carried constraints:** DEVELOP zone ONLY via DataZoneGuard + AccessLedger;
reuse don't rewrite; DecisionPolicy is the final deterministic promotion gate
(KEEP only); AI suggests scope/loss hint, backend validates, Freqtrade tests,
metrics measure; REAL FREQTRADE remains NOT VERIFIED (item 14). No Confirmation/
Final Unseen/Delivery/Frontend/Monte Carlo/GA/RL/multi-agent/arbitrary AI code.

---

## §1. Reuse existing execution infrastructure (CORRECTION #1)

**Finding (verified against repo):**
- `services/execution/backtest_runner.py::BacktestRunner` is the real execution
  layer. `CandidateExecutor` already calls `backtest_runner.run_candidate_backtest(
  strategy, version_id, request, params_override=)` and resolves metrics via the
  existing adapter. **This is the infrastructure Focused Hyperopt reuses.**
- `services/optimizer/enhanced_trial_execution.py::EnhancedTrialExecutionService`
  is a higher-level trial runner over the same `BacktestRunner`.
- `services/quant/quant_service.py::QuantService.run_hyperopt` and
  `api/routers/quant.py` are **MOCK stubs** (return `best_profit: 1450.75`). They
  are NOT reused — they would inject fake results and violate the "Freqtrade
  tests, metrics measure" contract.

**Architecture (no new subprocess/parser/result-store/job system):**
```
FocusedHyperoptService
  → BacktestRunner (EXISTING execution layer, injected like CandidateExecutor)
  → AeRoing4 research policy wrapper (scope + objective + budget + DecisionPolicy)
```
- `FocusedHyperoptService` is a thin adapter: it builds scoped `ParamsSchema`
  overrides from the trusted allowed targets (like `CandidateExecutor`), calls
  `BacktestRunner.run_candidate_backtest` per candidate point, resolves
  `CanonicalMetricsSnapshot` via the SAME metrics adapter, and lets
  `DecisionPolicy` decide. No new subprocess, parser, or result store.
- The existing execution service CAN support everything required:
  current Champion artifact (via `params_override` + candidate `.py` copy),
  scoped parameters (trusted targets only), bounded epochs (loop count), frozen
  pairs/timeframe/DEVELOP timerange/exchange/trading mode/wallet/stake/
  max_open_trades/config identity/protocol+metrics version (all frozen in the
  `RunRequest`/artifact copy, exactly as `CandidateExecutor` does).
- Therefore **no new runner is created**. If a future need arises that
  `BacktestRunner` cannot satisfy, that gap would be documented here; none exists
  for the focused, bounded search defined in §2–§4.

## §2. Focused Hyperopt search-space construction (CORRECTION #2)

Search space = intersection of THREE trusted sets (never broader):

```
AllowedMutationTarget (trusted, discovered)          -- from allowed_targets
∩ Declared Hyperopt-capable Parameters               -- type/flag filtered
∩ Diagnosis-specific parameter scope                 -- from §3 mapping
```

New: `is_hyperopt_capable(target) -> bool` (continuous/int/decimal numeric with
finite min/max; categorical/boolean EXCLUDED from v1 search unless a trusted
policy enables them — symmetry with §7).

Outcomes (typed):
- `FOCUSED_SCOPE_READY` — non-empty intersection.
- `NO_SAFE_TARGET` — no trusted allowed mutation target at all.
- `NO_HYPEROPT_CAPABLE_TARGET` — allowed targets exist but none hyperopt-capable.
- `NO_ACTIONABLE_HYPEROPT_SCOPE` — intersection empty after diagnosis narrowing.
- **No silent broadening**: an empty intersection NEVER falls back to all
  strategy parameters. AI may NOT choose Hyperopt search parameters.

## §3. Diagnosis-aware Hyperopt objective profiles (CORRECTION #3)

Versioned policy `FOCUSED_HYPEROPT_POLICY_VERSION` in `research/hyperopt_policy.py`:

```
DiagnosisCode
  → allowed parameter category (entry/exit/risk/all)
  → optimization objective profile (edge / risk-adjusted / balanced)
  → final DecisionPolicy acceptance gate
```

Mapping:
- `NO_EDGE` / `NEGATIVE_EXPECTANCY` / `LOW_PROFIT_FACTOR`
  → trusted entry/exit scope → edge-improvement objective → DecisionPolicy.
- `STOPLOSS_DOMINANCE` / `EXCESSIVE_DRAWDOWN` / `POOR_RETURN_TO_DRAWDOWN`
  → trusted risk/exit scope → risk-adjusted objective → DecisionPolicy.
- `PARAMETER_RESEARCH_NEEDED` (+ the three `*_PARAMETER_RESEARCH_NEEDED`)
  → bounded trusted hyperopt-capable scope → balanced objective.
- All other DiagnosisCodes (sample-quality, pair-structure, entry-too-restrictive
  w/o a parameter-research routing, etc.) → `NO_ACTIONABLE_HYPEROPT_OBJECTIVE`;
  **no broad hyperopt merely because a diagnosis exists**.

The Hyperopt objective selects candidate points; **DecisionPolicy remains the
final deterministic promotion gate** (unchanged KEEP boundary).

## §4. Versioned, centralized Hyperopt budget policy (CORRECTION #4)

`research/hyperopt_policy.py::FocusedHyperoptBudgetPolicy`:
- `policy_version: str`
- `default_epochs: int = 50`  (current default; not hardcoded at call sites)
- `max_epochs: int`
- `max_search_targets: int`   (bounds the intersection size)
- `loss` default + Quick/Deep profile hooks (NOT implemented in UI now; struct
  left for future). The stage stays bounded.

## §5. Freeze Hyperopt execution context (CORRECTION #5)

`FocusedHyperoptService` inherits the current Champion's frozen research context
(strategy + parameter artifacts, pairs, timeframe, DEVELOP timerange, exchange,
trading mode, wallet, stake, max_open_trades, config identity, protocol version,
metrics version). ONLY the approved hyperopt parameter scope may change. All data
access is DEVELOP-only via DataZoneGuard + AccessLedger. NO CONFIRMATION /
FINAL_UNSEEN access.

## §6. Hyperopt result handling (CORRECTION #6)

Required path (Hyperopt does NOT promote directly):
```
Current Champion
 → Focused Hyperopt (scoped search on DEVELOP)
 → best parameter artifact (written as a run-local candidate copy)
 → deterministic candidate materialization
 → canonical DEVELOP evaluation (BacktestRunner)
 → Metrics SSOT (existing adapter)
 → DecisionPolicy.decide(...)
 → KEEP / DROP / INCONCLUSIVE
```
- KEEP → `ChampionStore.promote` with `source_type=HYPEROPT`,
  `parent_champion_id=current`, parameter artifact + metrics provenance preserved,
  `ResearchState.current_champion_id` updated.
- DROP / INCONCLUSIVE → no promotion; current Champion unchanged.
- SYSTEM / PARSE failure → explicit `EXECUTION_SYSTEM_FAILURE` (NOT INCONCLUSIVE);
  `metrics_availability_reason` typed (reuse PROMPT 8 §10 field).
- Protocol denial → `PROTOCOL_DENIED`; no execution; no promotion.

## §7. Type-aware Sensitivity (CORRECTION #7)

Local one-parameter-at-a-time (OAT), reusing `BacktestRunner` on DEVELOP:
- **Continuous numeric** → deterministic bounded local perturbation (±pct of
  allowed range, clamped to `min_allowed`/`max_allowed`).
- **Integer** → valid integer neighbor perturbations with clamping +
  deduplication (no float values).
- **Boolean** → `NOT_APPLICABLE` in v1 (unless a trusted policy enables).
- **Categorical** → `NOT_APPLICABLE` in v1 (unless trusted ordered alternatives).
- **Zero-valued numeric** → still receives a non-zero valid perturbation derived
  from the trusted allowed range (never a 0±0 dead point).
- Never mutate more than one parameter per Sensitivity evaluation.

## §8. Explicit Sensitivity classifications (CORRECTION #8)

Each tested parameter → typed result:
`STABLE` / `ONE_SIDED_FRAGILE` / `TWO_SIDED_FRAGILE` / `INCONCLUSIVE` /
`NOT_APPLICABLE`.
Uses canonical metrics only, same DEVELOP context, diagnosis-aware objective
evidence where supported, global guardrails, metric-availability semantics; no
fake-zero substitution. This is LOCAL PARAMETER SENSITIVITY only — NOT complete
robustness validation.

## §9. Sensitivity progression gate (CORRECTION #9)

Sensitivity never promotes/demotes Champions directly, but its result controls
downstream eligibility:
- `SENSITIVITY_PASS` → `eligible_for_confirmation = true`
- `SENSITIVITY_FRAGILE` → `eligible_for_confirmation = false` + stop/block reason
- `SENSITIVITY_INCONCLUSIVE` → `eligible_for_confirmation = false` + reason
The HYPEROPT Champion may remain in history/current per lineage rules, but the
workflow must NOT auto-advance a fragile/inconclusive Champion into Confirmation.
(Confirmation itself is outside PROMPT 9.)

## §10. Entry-condition / eligibility gate for Focused Hyperopt (CORRECTION #10)

Hyperopt must NOT start while the research loop has unresolved active work. Gate
requires ALL:
- current Champion exists,
- no active Experiment requiring reconciliation (`resume_safety_report.must_reconcile_first is False`),
- ResearchState not PAUSED due to unresolved AI/system condition,
- Research Loop reached an allowed terminal/transition state,
- actionable Hyperopt scope exists (`FOCUSED_SCOPE_READY`),
- DEVELOP access allowed.
Otherwise return a typed skip/block outcome (`HYPEROPT_BLOCKED` + reason).
`enable_focused_hyperopt=true` alone is NOT sufficient to start.

## §11. Tests (CORRECTION #11) — keep A–H, add I–W

`tests/aeroing4/research/test_focused_hyperopt.py`:
A. scope narrows by diagnosis.  B. empty scope → `NO_SAFE_TARGET`, no run.
C. zone denial → `PROTOCOL_DENIED`, no run, champion unchanged.
D. KEEP → HYPEROPT champion promoted (lineage valid).
E. DROP/INCONCLUSIVE → no promotion.  F. system/parse → `EXECUTION_SYSTEM_FAILURE`.
G. entry gate: `HYPEROPT_BLOCKED` when must_reconcile_first / PAUSED.
H. budget policy enforced (epochs ≤ max_epochs, targets ≤ max_search_targets).
I. allowed target exists but NOT hyperopt-capable → no execution.
J. diagnosis has no actionable objective → `NO_ACTIONABLE_HYPEROPT_OBJECTIVE`, no execution.
K. empty focused intersection → no broad fallback.
L. execution-context drift attempt → rejected (frozen context).
M. Hyperopt KEEP → HYPEROPT Champion correct lineage (verifies §6).
N. Hyperopt DROP → current Champion unchanged.
O. Hyperopt system/parse failure → explicit system failure, not INCONCLUSIVE.

`tests/aeroing4/research/test_sensitivity.py`:
P. float param → bounded two-sided perturbation.  Q. int param → valid integer neighbors.
R. zero-valued numeric → non-zero perturbation.  S. categorical/boolean → NOT_APPLICABLE.
T. fragile result → `eligible_for_confirmation=false`.  U. inconclusive → `eligible_for_confirmation=false`.
V. pass → `eligible_for_confirmation=true`.  W. sensitivity never mutates >1 param / never promotes.

## §12. Verification reporting (CORRECTION #12)

Report Prompt 9 separately:
- LOGIC VERIFIED
- SERVICE-BOUNDARY VERIFIED
- REAL HYPEROPT VERIFIED  (guarded; NOT while Freqtrade unavailable)
- REAL FREQTRADE VERIFIED  (NOT — item 14)
- FULL E2E VERIFIED        (NOT)
Do NOT claim REAL HYPEROPT or FULL E2E while Freqtrade remains unavailable.

---

## Files touched (minimal, reuse-first)
- NEW `research/hyperopt_policy.py` — versioned budget + objective profiles.
- NEW `research/focused_hyperopt.py` — `FocusedHyperoptService` (adapter over
  `BacktestRunner`), scope intersection (§2), eligibility gate (§10), result path (§6).
- NEW `research/sensitivity.py` — type-aware OAT (§7), classifications (§8),
  progression gate (§9).
- EDIT `research/factory.py` — `build_focused_hyperopt_coordinator`,
  `build_sensitivity_coordinator` (reuse stores + injected `backtest_runner`).
- EDIT `models.py` / `state_store.py` / `orchestrator.py` / `api/routers/aeroing4.py`
  — opt-in `enable_focused_hyperopt: bool = False` (mirror `enable_research_loop`);
  `ResearchState` gains `eligible_for_confirmation` flag (set by Sensitivity gate).
- NEW `tests/aeroing4/research/test_focused_hyperopt.py` (A–O)
- NEW `tests/aeroing4/research/test_sensitivity.py` (P–W)
- NO changes to: Intent Router, Redesign Assistant, Backtest execution logic,
  PROMPT 8 KEEP-boundary contract, or the existing `BacktestRunner`/`CandidateExecutor`.
