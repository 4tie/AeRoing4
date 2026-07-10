# AeRoing4 Research Memory — Typed Research State, Hypothesis Registry, Experiment Memory, and Champion Lineage

## Overview

AeRoing4 Research Memory provides persistent, restart-safe research infrastructure for tracking hypotheses, experiments, budgets, and champion lineage. This document explains the architecture, lifecycle, and integration of the Research Memory system.

## State Ownership Model

AeRoing4 maintains three distinct but coordinated state systems:

### Workflow State (`AeRoing4Run` and `AeRoing4StateStore`)
- **Purpose:** Execution location and stage status
- **Owner:** `AeRoing4StateStore` at `user_data/aeroing4/runs/{run_id}/state.json`
- **Responsibilities:**
  - Track which workflow step is currently executing
  - Manage run lifecycle (PENDING → RUNNING → COMPLETED/FAILED)
  - Store step results and errors
  - Enforce single-active-run constraint

### Protocol State (`ResearchProtocolState` and AccessLedger)
- **Purpose:** Data access rules and research boundaries
- **Owner:** `AeRoing4StateStore` (boundaries) and `AccessLedger` (audit trail)
- **Files:** `state.json` (protocol section) and `access_ledger.json`
- **Responsibilities:**
  - Define DEVELOP/CONFIRMATION/FINAL_UNSEEN data zones
  - Enforce stage-based access control
  - Audit every data access attempt (allowed and denied)
  - Freeze boundaries after first DEVELOP access

### Research State (`ResearchState`, `HypothesisStore`, `ExperimentStore`, `ChampionStore`)
- **Purpose:** Research knowledge, budgets, active hypothesis, experiment memory, champion lineage
- **Owner:** Separate Research Memory stores
- **Files:** `research_state.json`, `hypotheses.json`, `experiments.json`, `champions.json`
- **Responsibilities:**
  - Track research budget counters
  - Maintain hypothesis registry with validated transitions
  - Store complete experiment records with identity deduplication
  - Manage champion lineage with provenance tracking
  - Provide restart-safe experiment recovery

**Key Principle:** These three state systems are siblings under the same run directory. They do not compete for ownership—each has a clear, scoped responsibility.

## Research State

### Model Structure

```python
class ResearchState(BaseModel):
    run_id: str
    
    # Champion tracking (null until Portfolio Baseline milestone)
    current_champion_id: Optional[str] = None
    current_champion_strategy_hash: Optional[str] = None
    current_champion_parameter_hash: Optional[str] = None
    
    # Active work pointers
    current_hypothesis_id: Optional[str] = None
    active_experiment_id: Optional[str] = None
    
    # Budget counters
    total_experiments_reserved: int = 0
    total_experiments_completed: int = 0
    max_total_experiments: int = 5  # default budget
    
    hypotheses_created: int = 0
    hypotheses_completed: int = 0
    
    # Summary of accessed data zones
    accessed_data_zones: list[str] = []
    
    # Overall research status
    research_status: ResearchStatus = ResearchStatus.NOT_STARTED
    
    created_at: datetime
    updated_at: datetime
```

### Research Status Lifecycle

```python
class ResearchStatus(str, Enum):
    NOT_STARTED = "not_started"
    READY = "ready"
    ACTIVE = "active"
    PAUSED = "paused"
    EXHAUSTED = "exhausted"
    COMPLETED = "completed"
    FAILED = "failed"
```

**Valid Transitions:**
- NOT_STARTED → READY, ACTIVE
- READY → ACTIVE, FAILED
- ACTIVE → PAUSED, EXHAUSTED, COMPLETED, FAILED
- PAUSED → ACTIVE, FAILED
- EXHAUSTED → COMPLETED
- COMPLETED → (terminal)
- FAILED → (terminal)

### Initial Champion Behavior

ResearchState safely allows `current_champion_id = null` until a future Portfolio Baseline milestone creates the actual baseline champion. No fake initial champion is created.

## Research Budget Policy

### Versioned Budget Constants

```python
RESEARCH_BUDGET_POLICY_VERSION = "1.0.0"
DEFAULT_MAX_TOTAL_EXPERIMENTS = 5
DEFAULT_MAX_EXPERIMENTS_PER_HYPOTHESIS = 3
```

### Budget Decision Model

Budget checks return typed decisions, never bare booleans:

```python
class BudgetDecision(BaseModel):
    allowed: bool
    code: BudgetDecisionCode
    reason: str
    total_reserved: int = 0
    total_max: int = 0
    remaining_total: int = 0
    hypothesis_experiment_count: int = 0
    hypothesis_max: int = 0
    remaining_hypothesis: int = 0
    policy_version: str = RESEARCH_BUDGET_POLICY_VERSION
```

### Decision Codes

```python
class BudgetDecisionCode(str, Enum):
    ALLOWED = "allowed"
    TOTAL_BUDGET_EXHAUSTED = "total_budget_exhausted"
    HYPOTHESIS_BUDGET_EXHAUSTED = "hypothesis_budget_exhausted"
    DUPLICATE_EXPERIMENT = "duplicate_experiment"
    RUN_NOT_FOUND = "run_not_found"
    HYPOTHESIS_NOT_FOUND = "hypothesis_not_found"
```

### Atomic Budget Reservation

Experiment reservation follows a strict atomic sequence to prevent race conditions:

1. Load current ResearchState and HypothesisRecord
2. Validate total run budget
3. Validate per-hypothesis budget
4. Check for duplicate experiment identity
5. Reserve the experiment slot (increment counters)
6. Persist the reservation

All steps execute under the ExperimentStore lock, preventing concurrent experiment creation from exceeding budget limits.

## Hypothesis Registry

### Hypothesis Model

```python
class HypothesisRecord(BaseModel):
    hypothesis_id: str
    run_id: str
    
    diagnosis_code: Optional[str] = None
    hypothesis_text: str
    evidence_refs: list[HypothesisEvidenceRef] = []
    evidence_values: dict[str, object] = {}
    
    proposed_change_type: Optional[str] = None
    target_scope: Optional[str] = None
    expected_effect: Optional[str] = None
    success_criteria: Optional[str] = None
    risks: Optional[str] = None
    confidence: Optional[float] = None  # 0.0 – 1.0
    
    source: HypothesisSource = HypothesisSource.USER
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    
    created_at: datetime
    updated_at: datetime
    experiment_ids: list[str] = []
```

### Hypothesis Sources

```python
class HypothesisSource(str, Enum):
    DETERMINISTIC_DIAGNOSIS = "deterministic_diagnosis"
    AI_PROPOSAL = "ai_proposal"
    USER = "user"
```

### Hypothesis Lifecycle

```python
class HypothesisStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    ACTIVE = "active"
    SUPPORTED = "supported"
    REJECTED = "rejected"
    EXHAUSTED = "exhausted"
```

**Valid Transitions:**
- PROPOSED → APPROVED, REJECTED
- APPROVED → ACTIVE, REJECTED
- ACTIVE → SUPPORTED, REJECTED, EXHAUSTED
- SUPPORTED → (terminal)
- REJECTED → (terminal)
- EXHAUSTED → (terminal)

**Key Rule:** REJECTED → ACTIVE requires a new HypothesisRecord, never history rewrite. Invalid transitions raise `HypothesisTransitionError`.

### Evidence References

Hypotheses reference real evidence through typed evidence refs:

```python
class HypothesisEvidenceRef(BaseModel):
    ref_path: str          # e.g. "baseline.metrics.profit_factor"
    source_result_id: Optional[str] = None   # backtest run ID
    description: Optional[str] = None
```

**Evidence Immutability:** Once a hypothesis becomes ACTIVE, its evidence cannot be silently mutated. This prevents post-hoc rationalization of hypothesis decisions.

## Experiment Memory

### Experiment Model

```python
class ExperimentRecord(BaseModel):
    experiment_id: str
    run_id: str
    hypothesis_id: str
    parent_champion_id: Optional[str] = None
    candidate_id: Optional[str] = None
    
    # Strategy provenance
    original_strategy_provenance: OriginalStrategyProvenance
    original_strategy_path_hash: Optional[str] = None
    
    strategy_version_before: Optional[str] = None
    strategy_version_after: Optional[str] = None
    strategy_hash_before: Optional[str] = None
    strategy_hash_after: Optional[str] = None
    
    parameter_hash_before: Optional[str] = None
    parameter_hash_after: Optional[str] = None
    
    exact_change: Optional[ExactChange] = None
    
    # Data zone and execution context
    dataset_zone: str = "develop"
    concrete_timerange: Optional[str] = None
    pair_set: list[str] = []
    pair_set_hash: Optional[str] = None
    configuration_hash: Optional[str] = None
    input_hash: Optional[str] = None
    
    # Canonical identity
    experiment_identity_hash: str
    
    # Metrics (CanonicalMetricsSnapshot or None)
    metrics_before: Optional[CanonicalMetricsSnapshot] = None
    metrics_after: Optional[CanonicalMetricsSnapshot] = None
    metrics_version: str = METRICS_VERSION
    protocol_version: str = RESEARCH_PROTOCOL_VERSION
    
    # Execution references
    access_ledger_entry_id: Optional[str] = None
    underlying_execution_id: Optional[str] = None
    
    # Lifecycle
    status: ExperimentStatus = ExperimentStatus.PLANNED
    result: Optional[str] = None
    decision: ExperimentDecision = ExperimentDecision.PENDING
    
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: datetime
    artifacts: dict[str, str] = {}
```

### Original Strategy Provenance

Prevents conflating different source strategies that happen to have identical parameter states:

```python
class OriginalStrategyProvenance(BaseModel):
    logical_name: str
    path_reference: Optional[str] = None
    path_hash: Optional[str] = None
    source_hash: Optional[str] = None
    version_id: Optional[str] = None
```

### Experiment Status Lifecycle

```python
class ExperimentStatus(str, Enum):
    PLANNED = "planned"
    RESERVED = "reserved"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED_SYSTEM = "failed_system"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    INVALIDATED = "invalidated"
```

**Valid Transitions:**
- PLANNED → RESERVED, CANCELLED, INVALIDATED
- RESERVED → READY, CANCELLED, INVALIDATED
- READY → RUNNING, CANCELLED, INVALIDATED
- RUNNING → COMPLETED, FAILED_SYSTEM, CANCELLED, INTERRUPTED, INVALIDATED
- COMPLETED → (terminal)
- FAILED_SYSTEM → (terminal)
- CANCELLED → (terminal)
- INTERRUPTED → (terminal)
- INVALIDATED → (terminal)

### Research Decision (Separate from Execution Status)

```python
class ExperimentDecision(str, Enum):
    PENDING = "pending"
    KEEP = "keep"
    DROP = "drop"
    INCONCLUSIVE = "inconclusive"
```

**Key Principle:** Execution status (COMPLETED, FAILED_SYSTEM) is separate from research decision (KEEP, DROP). The actual KEEP/DROP policy will be implemented in a future milestone.

## Experiment Identity and Deduplication

### Identity Components

The experiment identity hash includes:

- Original strategy provenance hash (prevents conflating different source strategies)
- Strategy code hash before the experiment
- Parameter hash before the experiment
- Normalized proposed change (JSON-serialized, sort_keys=True)
- Dataset zone
- Concrete timerange
- Pair set hash (order-independent)
- Relevant execution configuration hash
- Timeframe
- Trading mode
- Exchange (where relevant)
- Protocol version
- Metrics version

**What is NOT part of identity:**
- experiment_id (assigned after identity is computed)
- hypothesis_id (multiple hypotheses can share the same experiment identity)
- created_at / timestamps
- status / result / decision
- metrics_before / metrics_after (outcomes, not inputs)
- access_ledger_entry_id / underlying_execution_id (assigned at execution time)

### Canonical Serialization

Identity computation uses JSON serialization with `sort_keys=True` to ensure dictionary key ordering does not affect the hash:

```python
def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)
```

### Duplicate Detection

Before reservation, ExperimentStore checks for an existing experiment with the same identity hash:

```python
class DuplicateExperimentDecision(BaseModel):
    is_duplicate: bool
    existing_experiment_id: Optional[str] = None
    existing_status: Optional[ExperimentStatus] = None
    existing_result: Optional[str] = None
    reason: str
```

**Policy:** If a duplicate is found, the existing experiment ID, status, and result are returned. Automatic rerun is not allowed—forced rerun requires an explicit future policy mechanism.

## Restart and Resume Behavior

### In-Flight Experiment Recovery

On application reload, experiments in non-terminal states are classified:

- **PLANNED/RESERVED/READY:** Remain in place, block duplicate creation
- **RUNNING:** Automatically transition to INTERRUPTED (explicit, auditable)
- **INTERRUPTED:** Marked as requiring reconciliation before new experiments

### Resume Safety Report

The system provides a typed report before allowing new experiments:

```python
class ResumeSafetyReport(BaseModel):
    has_active_experiment: bool
    active_experiment_id: Optional[str] = None
    active_experiment_status: Optional[ExperimentStatus] = None
    is_resumable: bool
    must_reconcile_first: bool
    new_experiment_allowed: bool
    reason: str
```

**Scenario Examples:**

**Scenario A:** RESERVED experiment survives reload → new duplicate creation blocked

**Scenario B:** RUNNING experiment becomes INTERRUPTED on reconcile → new experiment blocked until reconciliation

**Scenario C:** active_experiment_id persists → state still references correct experiment

**Scenario D:** hypothesis budget partly consumed → remaining budget correct after reload

### No Silent Duplicate Execution

The system explicitly answers:
- Is there an active experiment?
- Is there an unfinished reservation?
- Is it resumable?
- Must it be reconciled first?
- Is a new experiment allowed?

Resume → forget active experiment → create duplicate replacement is **strictly prohibited**.

## Champion Lineage

### Champion Model

```python
class ChampionReference(BaseModel):
    champion_id: str
    run_id: str
    parent_champion_id: Optional[str] = None
    
    source_type: ChampionSourceType
    source_experiment_id: Optional[str] = None
    
    strategy_artifact: Optional[ArtifactReference] = None
    parameter_artifact: Optional[ArtifactReference] = None
    
    metrics: Optional[CanonicalMetricsSnapshot] = None
    
    created_at: datetime
```

### Champion Source Types

```python
class ChampionSourceType(str, Enum):
    BASELINE = "baseline"
    RESEARCH_EXPERIMENT = "research_experiment"
    HYPEROPT = "hyperopt"
```

### Artifact References

Champions reference run-local artifact copies, never the user's original strategy file:

```python
class ArtifactReference(BaseModel):
    artifact_path: str            # relative path within run directory
    artifact_hash: str            # SHA-256 of artifact content
    original_source_path: str     # user's original file path (audit only)
    original_source_hash: str     # hash of original at capture time (immutable)
```

### Promotion Contract

Champion promotion requires:
- Candidate exists
- Experiment is terminal and successfully evaluated
- Candidate artifact hashes exist
- Parameter hashes exist
- Canonical metrics snapshot present when required
- Parent relationship valid

**Arbitrary champion replacement without lineage is strictly prohibited.**

### Initial Champion Behavior

Before Portfolio Baseline milestone:
- ResearchState.current_champion_id = null
- No fake initial champion created
- ResearchState works correctly before champion initialization
- Baseline champion can be registered later

## Original Strategy Protection

Research experiments never overwrite the user's original strategy. The system uses:

- Existing versioning infrastructure
- Snapshot services
- Run-local candidate artifacts
- Artifact-copy infrastructure

Before any future experiment execution, the research model references run-local candidate artifacts or immutable version references.

**Key Guarantees:**
- Original strategy file hash remains unchanged
- Experiment candidate has independent artifact identity
- Promotion changes ResearchState reference, not original source file

## Research Protocol Integration

### Experiment Planning (No Data Access)

Planning a hypothesis does not require protected data access. Hypothesis creation and experiment identity computation can occur without touching Research Protocol data zones.

### Execution Readiness (DEVELOP Access)

Before an experiment transitions to READY or RUNNING state:
1. Request DEVELOP access through DataZoneGuard
2. Store the resulting ledger access reference
3. Persist concrete timerange
4. Persist protocol version

### Access Ledger Ordering

The atomic sequence for experiment start:
1. Experiment identity persisted
2. Budget slot reserved
3. Protocol access requested and ledgered
4. Experiment marked READY
5. (Future) execution starts
6. Execution reference attached
7. Status RUNNING

This prevents states like:
- Experiment RUNNING but no protocol access record exists
- Execution started but no experiment identity persisted

### Zone Restrictions

Research experiments:
- ✅ Can use DEVELOP zone
- ❌ Cannot use CONFIRMATION zone
- ❌ Cannot use FINAL_UNSEEN zone

CONFIRMATION and FINAL_UNSEEN are reserved for future validation stages.

## Persistence Layout

### Run Directory Structure

```
user_data/aeroing4/runs/{run_id}/
├── state.json                    # Workflow state (AeRoing4StateStore)
├── access_ledger.json            # Protocol access audit trail
├── research_state.json           # Research state (ResearchStateStore)
├── hypotheses.json               # Hypothesis registry (HypothesisStore)
├── experiments.json              # Experiment memory (ExperimentStore)
└── champions.json               # Champion lineage (ChampionStore)
```

### Atomic Persistence

All Research Memory writes use safe persistence:
1. Write temporary file
2. Flush
3. fsync where appropriate
4. Atomic replace

**Fail-Closed Behavior:** If a memory file exists but is corrupted, the system raises a typed integrity error rather than silently returning empty history.

### Concurrency Protection

**AccessLedger:** Uses per-instance threading.Lock(). AppServices owns one canonical AeRoing4Orchestrator which owns one DataZoneGuard which owns one AccessLedger per runs_root. This single-instance ownership model makes the per-instance lock sufficient for in-process concurrent callers.

**Research Memory Stores:** Each store (ResearchStateStore, HypothesisStore, ExperimentStore, ChampionStore) uses its own threading.Lock() for atomic writes. Since AppServices creates one canonical instance per process, this is sufficient for single-process correctness.

**Multi-Instance Protection:** The system does not support multiple DataZoneGuard/AccessLedger instances writing the same ledger file concurrently from separate processes. AeRoing4 is designed as single-process, single-machine.

## Metrics SSOT Integration

Experiment records store canonical Metrics SSOT snapshots:

```python
metrics_before: Optional[CanonicalMetricsSnapshot] = None
metrics_after: Optional[CanonicalMetricsSnapshot] = None
metrics_version: str = METRICS_VERSION
```

**Key Principle:** Experiment Memory does not calculate Profit Factor, Expectancy, Sharpe, Drawdown, or other canonical metrics. It stores snapshots from the canonical Metrics SSOT source.

**Preservation:** The system preserves:
- metrics_version
- provenance
- availability states
- unavailable metrics

Unavailable metrics are never silently flattened to zero.

## Future Integration

### Diagnosis (Not Yet Implemented)

The Research Memory infrastructure is designed to support future Diagnosis stages by:
- Providing evidence reference structure for diagnosis findings
- Storing diagnosis codes in HypothesisRecord
- Supporting deterministic diagnosis as a hypothesis source
- Maintaining audit trail of what was diagnosed vs. what was proposed

### AI Proposal Generator (Not Yet Implemented)

The Research Memory infrastructure is designed to support future AI proposal generation by:
- Supporting AI_PROPOSAL as a hypothesis source
- Providing complete experiment history for AI context
- Maintaining evidence refs for AI to reason about
- Storing confidence scores and expected effects
- Enabling AI to review past hypothesis outcomes

### Research Loop Orchestration (Not Yet Implemented)

The Research Memory infrastructure provides the foundation for future Research Loop orchestration by:
- Managing active experiment state and resume safety
- Tracking budget exhaustion and research status
- Providing duplicate detection to prevent redundant experiments
- Maintaining champion lineage for promotion decisions
- Integrating with Research Protocol for data zone access control

## Complete Example

This example demonstrates the complete research memory flow (documentation only—Research Loop not yet implemented):

### Initial State
```
ResearchState:
  current_champion_id: null
  current_hypothesis_id: null
  active_experiment_id: null
  total_experiments_reserved: 0
  hypotheses_created: 0
  research_status: NOT_STARTED
```

### Step 1: Portfolio Baseline Creates Initial Champion
```
ChampionReference:
  champion_id: champ-001
  run_id: run-001
  parent_champion_id: null
  source_type: BASELINE
  strategy_artifact: ArtifactReference(...)
  parameter_artifact: ArtifactReference(...)
  metrics: CanonicalMetricsSnapshot(...)

ResearchState:
  current_champion_id: champ-001
  current_champion_strategy_hash: "abc123"
  current_champion_parameter_hash: "def456"
  research_status: READY
```

### Step 2: Diagnosis Creates Hypothesis
```
HypothesisRecord:
  hypothesis_id: hyp-001
  run_id: run-001
  diagnosis_code: "INSUFFICIENT_TRADES"
  hypothesis_text: "Increase trade frequency by lowering entry threshold"
  evidence_refs: [
    HypothesisEvidenceRef(ref_path="baseline.metrics.total_trades", ...)
  ]
  source: DETERMINISTIC_DIAGNOSIS
  status: PROPOSED

ResearchState:
  current_hypothesis_id: hyp-001
  hypotheses_created: 1
```

### Step 3: Hypothesis Approved and Activated
```
HypothesisRecord (hyp-001):
  status: APPROVED → ACTIVE
  evidence_locked: true

ResearchState:
  research_status: ACTIVE
```

### Step 4: Experiment A Planned and Reserved
```
ExperimentRecord:
  experiment_id: exp-001
  run_id: run-001
  hypothesis_id: hyp-001
  parent_champion_id: champ-001
  original_strategy_provenance: OriginalStrategyProvenance(...)
  exact_change: ExactChange(change_type="parameter", target="entry_threshold", ...)
  experiment_identity_hash: "hash123"
  status: PLANNED → RESERVED
  dataset_zone: develop
  concrete_timerange: "20240101-20240331"

ResearchState:
  active_experiment_id: exp-001
  total_experiments_reserved: 1

HypothesisRecord (hyp-001):
  experiment_ids: ["exp-001"]
```

### Step 5: Experiment A Executed and Evaluated
```
ExperimentRecord (exp-001):
  status: READY → RUNNING → COMPLETED
  metrics_after: CanonicalMetricsSnapshot(...)
  decision: DROP  # Poor performance
  result: "Insufficient improvement"

ResearchState:
  total_experiments_completed: 1
  active_experiment_id: null
```

### Step 6: Experiment B Planned and Reserved
```
ExperimentRecord:
  experiment_id: exp-002
  run_id: run-001
  hypothesis_id: hyp-001
  parent_champion_id: champ-001  # Still original champion
  exact_change: ExactChange(change_type="parameter", target="stop_loss", ...)
  experiment_identity_hash: "hash456"  # Different from exp-001
  status: PLANNED → RESERVED

ResearchState:
  active_experiment_id: exp-002
  total_experiments_reserved: 2

HypothesisRecord (hyp-001):
  experiment_ids: ["exp-001", "exp-002"]
```

### Step 7: Experiment B Executed and Evaluated
```
ExperimentRecord (exp-002):
  status: READY → RUNNING → COMPLETED
  metrics_after: CanonicalMetricsSnapshot(...)
  decision: KEEP  # Strong improvement
  result: "Significant profit increase with acceptable risk"

ResearchState:
  total_experiments_completed: 2
  active_experiment_id: null
```

### Step 8: Hypothesis Supported
```
HypothesisRecord (hyp-001):
  status: ACTIVE → SUPPORTED

ResearchState:
  hypotheses_completed: 1
```

### Step 9: New Champion Promoted
```
ChampionReference:
  champion_id: champ-002
  run_id: run-001
  parent_champion_id: champ-001  # Lineage preserved
  source_type: RESEARCH_EXPERIMENT
  source_experiment_id: exp-002
  strategy_artifact: ArtifactReference(...)
  parameter_artifact: ArtifactReference(...)
  metrics: CanonicalMetricsSnapshot(...)

ResearchState:
  current_champion_id: champ-002
  current_champion_strategy_hash: "xyz789"
  current_champion_parameter_hash: "uvw012"
  research_status: ACTIVE
```

### Final State
```
Champion Lineage:
  champ-001 (BASELINE) → champ-002 (RESEARCH_EXPERIMENT from exp-002)

Hypothesis History:
  hyp-001: PROPOSED → APPROVED → ACTIVE → SUPPORTED
  experiments: exp-001 (DROP), exp-002 (KEEP)

Experiment Memory:
  exp-001: RESERVED → READY → RUNNING → COMPLETED (DROP)
  exp-002: RESERVED → READY → RUNNING → COMPLETED (KEEP)

Research State:
  current_champion_id: champ-002
  hypotheses_created: 1
  hypotheses_completed: 1
  total_experiments_reserved: 2
  total_experiments_completed: 2
  research_status: ACTIVE
```

## Summary

AeRoing4 Research Memory provides:

1. **Typed Research State:** Persistent research knowledge, budgets, and active work tracking
2. **Hypothesis Registry:** Validated hypothesis lifecycle with evidence immutability
3. **Experiment Memory:** Complete experiment records with identity deduplication
4. **Champion Lineage:** Audit trail of champion promotions with provenance tracking
5. **Budget Policy:** Versioned, atomic budget enforcement
6. **Restart Safety:** Explicit in-flight experiment recovery and resume guards
7. **Original Strategy Protection:** Artifact references prevent source file mutation
8. **Protocol Integration:** DEVEL zone access with ledger ordering guarantees
9. **Metrics SSOT Integration:** Canonical metric snapshots without recalculation
10. **Concurrency Safety:** Single-instance ownership with per-instance locks

The infrastructure is designed to support future Diagnosis, AI Proposal Generation, and Research Loop orchestration without requiring architectural changes.