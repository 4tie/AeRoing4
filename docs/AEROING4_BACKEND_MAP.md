# AeRoing4 Backend Mapping Document

## Executive Summary

This document maps the AeRoing4 workflow to existing backend services, identifying reusable components, legacy code to avoid, and missing functionality to implement. AeRoing4 can reuse most lower-level services but requires a new orchestration layer.

## 1. Current Backend Architecture Summary

### 1.1 Service Layer Architecture

The backend follows a layered architecture:

```
API Layer (FastAPI Routers)
    ↓
Service Layer (Business Logic)
    ↓
Core Layer (Data Models, Error Handling)
    ↓
Execution Layer (Freqtrade subprocess management)
```

### 1.2 Key Service Groups

**Strategy Services** (`backend/services/strategy/`)
- `StrategyRegistry` - Strategy discovery and indexing
- `StrategySourceParser` - Parse strategy files and extract parameters
- `VersionManager` - Strategy versioning and accepted version management
- `StrategyOptimizerService` - Parameter optimization orchestration
- `StrategyGitService` - Git integration for strategies
- `SnapshotService` - Strategy file snapshots

**Execution Services** (`backend/services/execution/`)
- `BacktestRunner` - Freqtrade backtest execution with progress tracking
- `DataDownloadRunner` - Market data download orchestration
- `PairSweepRunner` - Pair sweep stress testing
- `RunProgressService` - Backtest progress estimation and phase tracking

**Storage Services** (`backend/services/storage/`)
- `RunRepository` - Backtest result persistence and retrieval
- `ResultParser` - Parse Freqtrade backtest results into structured data
- `OptimizerStore` - Optimizer session persistence
- `ExportedTrialStore` - Exported optimizer trials

**AI Services** (`backend/services/ai/`)
- `AIService` - AI integration for strategy assistance
- `WorkflowToolExecutor` - AI tool execution for workflows
- `OllamaClient` - Local LLM integration

**Stress Testing Services** (`backend/services/stress/`)
- `TemporalStressService` - Time split, Monte Carlo, crash gauntlet testing

**AutoQuant Pipeline** (`backend/services/auto_quant/`)
- Complex 6-stage pipeline with heavy state management
- Tightly coupled to `PipelineState` and legacy workflow assumptions
- **DO NOT REUSE DIRECTLY** for AeRoing4

### 1.3 Session and Job Management

**SessionStore** (`backend/api/session_store.py`)
- Disk-backed session registry for background operations
- Survives server restarts via JSON persistence
- Universal polling endpoint `/api/session/status/{session_id}`

**Workflow Jobs** (`backend/services/workflow_jobs/`)
- Reusable job start functions extracted from routers
- `start_backtest_job` - Backtest execution
- `start_optimizer_job` - Optimizer execution
- `start_pair_explorer_job` - Pair discovery
- `start_pair_stress_job` - Pair stress testing (placeholder)
- `start_temporal_stress_job` - Temporal stress testing (placeholder)

## 2. AeRoing4 Workflow Step Analysis

### Step 1: Strategy Selection

**Reusable Service**: `StrategyRegistry`
- **File**: `backend/services/strategy/strategy_registry.py`
- **Function**: `list_strategies()`, `get_strategy(strategy_name)`
- **API Endpoint**: `GET /api/strategies`
- **Reusability**: ✅ **SAFE TO REUSE DIRECTLY**
- **Dependencies**: Strategy directory, version management
- **State Persistence**: None (in-memory index)

**Wrapper Needed**: No
- StrategyRegistry is independent and clean

### Step 2: Strict Strategy Validation

**Reusable Service**: `StrategyValidationService`
- **File**: `backend/services/strategy/strategy_validation_service.py`
- **Function**: `run_py_validate()`, `extract_class_name()`
- **API Endpoint**: `POST /api/strategies/validate`
- **Reusability**: ✅ **SAFE TO REUSE DIRECTLY**
- **Dependencies**: Freqtrade executable, temp file handling
- **State Persistence**: None

**Hidden Risk**: ⚠️ **Validation timeout handling**
- Freqtrade test-strategy can timeout (60s) - reported as warning, not error
- May report success when Freqtrade validation was skipped
- **Mitigation**: Add strict timeout and exit code checking in AeRoing4 wrapper

### Step 3: Smoke Data Preparation

**Reusable Service**: `DataDownloadRunner`
- **File**: `backend/services/execution/data_download_runner.py`
- **Function**: `run_download(DownloadDataRequest)`
- **API Endpoint**: `POST /api/data/download`
- **Reusability**: ✅ **SAFE TO REUSE DIRECTLY**
- **Dependencies**: Freqtrade executable, user_data_dir
- **State Persistence**: Download logs in `data_downloads_root`

**Hidden Risk**: ⚠️ **Busy state conflict**
- Global busy flag - only one download at a time
- **Mitigation**: AeRoing4 should manage own download scheduling

**Wrapper Needed**: No, but add data quality checks

**Missing Functionality**: ❌ **Data quality validation**
- Need to verify downloaded data covers requested timerange
- Need to check for gaps or corrupted data files
- Existing: `DataDownloadRunner` only checks process exit code

### Step 4: Smoke Backtest

**Reusable Service**: `BacktestRunner`
- **File**: `backend/services/execution/backtest_runner.py`
- **Function**: `run_backtest(strategy, version_id, request)`
- **API Endpoint**: `POST /api/backtest/run`
- **Reusability**: ✅ **SAFE TO REUSE DIRECTLY**
- **Dependencies**: Freqtrade executable, strategy files, data files
- **State Persistence**: RunRepository

**Workflow Job**: `start_backtest_job`
- **File**: `backend/services/workflow_jobs/backtest_job.py`
- **Reusability**: ✅ **SAFE TO REUSE DIRECTLY**
- **Provides**: Session management, preflight validation, error handling

**Hidden Risk**: ⚠️ **Busy state conflict**
- Global busy flag - only one backtest at a time
- **Mitigation**: AeRoing4 should queue backtests or use different runner instances

**Data Existence Check**: ✅ **Built-in**
- `BacktestRunner._check_data_exists()` - verifies data files exist
- `BacktestRunner._check_data_covers_timerange()` - verifies data coverage

### Step 5: Pair Discovery

**Reusable Service**: `PairExplorerService`
- **File**: `backend/services/pairs/pair_explorer_service.py`
- **Function**: Parallel multi-pair backtesting with ranking
- **API Endpoint**: `POST /api/strategy/pair-explorer`
- **Reusability**: ⚠️ **NEEDS THIN WRAPPER**
- **Dependencies**: BacktestRunner, DataDownloadRunner
- **State Persistence**: Session JSON files

**Workflow Job**: `start_pair_explorer_job`
- **File**: `backend/services/workflow_jobs/pair_explorer_job.py`
- **Reusability**: ✅ **SAFE TO REUSE DIRECTLY**

**Wrapper Needed**: Yes
- Current implementation optimized for large-scale discovery
- AeRoing4 needs focused discovery with specific constraints
- Add filtering for AeRoing4-specific criteria

**Missing Functionality**: ❌ **Candidate pair confirmation**
- Need service to confirm discovered pairs meet AeRoing4 requirements
- Need per-pair backtest result ranking and filtering

### Step 6: Candidate Pair Confirmation

**Reusable Service**: None
- **Status**: ❌ **MISSING FUNCTIONALITY**
- **Need**: Service to validate candidate pairs against strict criteria
- **Implementation**: Create new `PairConfirmationService`

**Reusable Components**:
- `ResultParser` - Parse per-pair backtest results
- `PairSelectorService` - Manage pair selection state
- Existing pair filtering logic in AutoQuant (tightly coupled, do not reuse)

### Step 7: Portfolio Baseline

**Reusable Service**: `BacktestRunner`
- **File**: `backend/services/execution/backtest_runner.py`
- **Function**: `run_backtest()` with portfolio configuration
- **Reusability**: ✅ **SAFE TO REUSE DIRECTLY**
- **Configuration**: Set `max_open_trades` and multiple pairs

**AutoQuant Reference**: ⚠️ **DO NOT REUSE**
- `stage2_portfolio.py` has portfolio baseline logic
- Tightly coupled to PipelineState and AutoQuant workflow
- Implement fresh in AeRoing4 using BacktestRunner directly

**Missing Functionality**: ❌ **Portfolio weight calculation**
- Need service to calculate optimal portfolio weights
- Need baseline metrics for capital constraints

### Step 8: Strategy Diagnosis

**Reusable Service**: None
- **Status**: ❌ **MISSING FUNCTIONALITY**
- **Need**: AI-powered strategy diagnosis service
- **Implementation**: Create new `StrategyDiagnosisService`

**Reusable Components**:
- `AIService` - AI integration infrastructure
- `OllamaClient` - Local LLM client
- Existing AI suggestion logic in AutoQuant (tightly coupled, do not reuse)

**Diagnosis Requirements**:
- Analyze strategy code structure
- Identify parameter sensitivity
- Detect overfitting patterns
- Suggest improvements

### Step 9: Focused Optimization

**Reusable Service**: `StrategyOptimizerService`
- **File**: `backend/services/strategy/strategy_optimizer.py`
- **Function**: Multi-trial parameter optimization
- **API Endpoint**: `POST /api/optimizer/run`
- **Reusability**: ✅ **SAFE TO REUSE DIRECTLY**
- **Dependencies**: BacktestRunner, OptimizerStore, VectorBT screener

**Workflow Job**: `start_optimizer_job`
- **File**: `backend/services/workflow_jobs/optimizer_job.py`
- **Reusability**: ✅ **SAFE TO REUSE DIRECTLY**

**Hidden Risk**: ⚠️ **Busy state conflict**
- Global busy flag - only one optimizer at a time
- **Mitigation**: AeRoing4 should manage optimizer scheduling

**Wrapper Needed**: Yes
- Current optimizer is general-purpose
- AeRoing4 needs focused optimization with specific constraints
- Add parameter space narrowing based on diagnosis

**AutoQuant Reference**: ⚠️ **DO NOT REUSE**
- AutoQuant optimization stages (hyperopt, genetic, RL) are tightly coupled
- Use StrategyOptimizerService directly instead

### Step 10: Parameter Sensitivity

**Reusable Service**: `SensitivityService` (AutoQuant)
- **File**: `backend/services/auto_quant/sensitivity.py`
- **Function**: `run_sensitivity_check()`
- **Reusability**: ⚠️ **NEEDS THIN WRAPPER**
- **Dependencies**: Freqtrade, variant management

**Hidden Risk**: ⚠️ **AutoQuant coupling**
- Uses AutoQuant variant management and state
- Depends on AutoQuant-specific file structure
- **Mitigation**: Extract core sensitivity logic into standalone service

**Missing Functionality**: ❌ **Standalone sensitivity service**
- Need service independent of AutoQuant pipeline
- Should work with any strategy and parameter set

### Step 11: OOS Validation

**Reusable Service**: `OOSAndWalkForwardEngine`
- **File**: `backend/engine/oos_walkforward_engine.py`
- **Function**: `test_oos_performance()`, `test_walk_forward()`
- **Reusability**: ✅ **SAFE TO REUSE DIRECTLY**
- **Dependencies**: Strategy metrics, trade data

**AutoQuant Reference**: ⚠️ **DO NOT REUSE**
- `stage3_oos_validation.py` has OOS logic
- Tightly coupled to PipelineState and timerange management
- Use OOSAndWalkForwardEngine directly instead

**Missing Functionality**: ❌ **OOS data preparation**
- Need service to split data into IS/OOS periods
- Need to ensure OOS data is never contaminated
- Need timerange management for OOS testing

### Step 12: Unseen-Pair Generalization

**Reusable Service**: `BacktestRunner`
- **Function**: Run backtest on unseen pairs
- **Reusability**: ✅ **SAFE TO REUSE DIRECTLY**

**Missing Functionality**: ❌ **Unseen pair management**
- Need service to track which pairs are "seen" vs "unseen"
- Need to prevent data leakage between seen/unseen pairs
- Need generalization scoring logic

### Step 13: Realistic Execution Stress Test

**Reusable Service**: `TemporalStressService`
- **File**: `backend/services/stress/temporal_stress_service.py`
- **Function**: Time split, Monte Carlo, crash gauntlet testing
- **API Endpoint**: `POST /api/temporal-stress-lab/run`
- **Reusability**: ✅ **SAFE TO REUSE DIRECTLY**

**Workflow Job**: `start_temporal_stress_job`
- **File**: `backend/services/workflow_jobs/stress_job.py`
- **Reusability**: ⚠️ **NEEDS IMPLEMENTATION**
- **Status**: Currently placeholder

**Missing Functionality**: ❌ **Slippage and execution simulation**
- Need realistic execution simulation beyond temporal stress
- Need slippage modeling
- Need order book impact simulation

### Step 14: Monte Carlo Analysis

**Reusable Service**: `MonteCarloService` (AutoQuant)
- **File**: `backend/services/auto_quant/monte_carlo.py`
- **Function**: `run_monte_carlo()`
- **Reusability**: ✅ **SAFE TO REUSE DIRECTLY**
- **Dependencies**: NumPy, trade data

**Status**: ✅ **Standalone and clean**
- Pure function, no external dependencies
- Can be reused directly

### Step 15: Final Decision

**Reusable Service**: None
- **Status**: ❌ **MISSING FUNCTIONALITY**
- **Need**: Decision aggregation and scoring service
- **Implementation**: Create new `AeRoing4DecisionService`

**Reusable Components**:
- All step results from previous steps
- Scoring logic from existing engines (use as reference)

## 3. Reusable Service Inventory

### 3.1 Services Safe to Reuse Directly

| Service | File | Purpose | API Endpoint |
|---------|------|---------|-------------|
| StrategyRegistry | `backend/services/strategy/strategy_registry.py` | Strategy discovery | `GET /api/strategies` |
| StrategyValidationService | `backend/services/strategy/strategy_validation_service.py` | Strategy validation | `POST /api/strategies/validate` |
| BacktestRunner | `backend/services/execution/backtest_runner.py` | Backtest execution | `POST /api/backtest/run` |
| DataDownloadRunner | `backend/services/execution/data_download_runner.py` | Data download | `POST /api/data/download` |
| ResultParser | `backend/services/storage/result_parser.py` | Result parsing | N/A |
| RunRepository | `backend/services/storage/run_repository.py` | Result persistence | N/A |
| StrategyOptimizerService | `backend/services/strategy/strategy_optimizer.py` | Optimization | `POST /api/optimizer/run` |
| OOSAndWalkForwardEngine | `backend/engine/oos_walkforward_engine.py` | OOS testing | N/A |
| TemporalStressService | `backend/services/stress/temporal_stress_service.py` | Temporal stress | `POST /api/temporal-stress-lab/run` |
| MonteCarloService | `backend/services/auto_quant/monte_carlo.py` | Monte Carlo | N/A |
| SessionStore | `backend/api/session_store.py` | Session management | `GET /api/session/status/{id}` |
| PairSelectorService | `backend/services/pairs/pair_selector.py` | Pair selection | `GET /api/pairs` |

### 3.2 Workflow Jobs (Reusable)

| Job | File | Purpose |
|-----|------|---------|
| start_backtest_job | `backend/services/workflow_jobs/backtest_job.py` | Backtest execution with session management |
| start_optimizer_job | `backend/services/workflow_jobs/optimizer_job.py` | Optimizer execution with session management |
| start_pair_explorer_job | `backend/services/workflow_jobs/pair_explorer_job.py` | Pair discovery with session management |

### 3.3 Services Needing Thin Wrappers

| Service | File | Wrapper Reason |
|---------|------|----------------|
| PairExplorerService | `backend/services/pairs/pair_explorer_service.py` | Need AeRoing4-specific filtering and ranking |
| SensitivityService | `backend/services/auto_quant/sensitivity.py` | Remove AutoQuant variant coupling |
| PairSweepRunner | `backend/services/execution/pair_sweep_runner.py` | Need AeRoing4-specific stress criteria |

### 3.4 Legacy AutoQuant Code to Avoid

**DO NOT CALL DIRECTLY:**

- `backend/services/auto_quant/pipeline.py` - Main pipeline orchestrator
- `backend/services/auto_quant/pipeline_modules/orchestrator.py` - Pipeline orchestration
- `backend/services/auto_quant/pipeline_modules/state.py` - PipelineState management
- `backend/services/auto_quant/pipeline_modules/stages/*.py` - All stage implementations
- `backend/services/auto_quant/pipeline_modules/helpers.py` - Pipeline-specific helpers
- `backend/services/auto_quant/variants.py` - Variant management (AutoQuant-specific)
- `backend/services/auto_quant/generator/*.py` - Strategy generation
- `backend/services/auto_quant/genetic/*.py` - Genetic algorithms
- `backend/services/auto_quant/rl/*.py` - Reinforcement learning
- `backend/services/auto_quant/regime_*.py` - Regime detection

**Reasons to Avoid:**
- Heavy dependency on `PipelineState` object
- Stage numbering and approval checkpoints
- Retry loops and self-healing logic
- Legacy workflow assumptions
- State persistence tied to AutoQuant directory structure
- User approval checkpoints and pause/resume logic

## 4. Missing Functionality

### 4.1 AeRoing4 Orchestration Layer

**Status**: ❌ **MISSING**
**Priority**: 🔴 **CRITICAL**
**Description**: New orchestration service to coordinate AeRoing4 workflow steps
**Implementation**: Create `backend/services/aeroing4/orchestrator.py`
**Requirements**:
- Step-by-step workflow execution
- State management independent of AutoQuant
- Progress tracking and cancellation
- Error handling and recovery
- Result aggregation and decision making

### 4.2 Strategy Diagnosis Service

**Status**: ❌ **MISSING**
**Priority**: 🔴 **CRITICAL**
**Description**: AI-powered strategy analysis and diagnosis
**Implementation**: Create `backend/services/aeroing4/strategy_diagnosis.py`
**Requirements**:
- Strategy code analysis
- Parameter sensitivity detection
- Overfitting pattern detection
- Improvement suggestions
- Integration with existing AIService

### 4.3 Pair Confirmation Service

**Status**: ❌ **MISSING**
**Priority**: 🟡 **HIGH**
**Description**: Validate candidate pairs against strict AeRoing4 criteria
**Implementation**: Create `backend/services/aeroing4/pair_confirmation.py`
**Requirements**:
- Per-pair backtest result analysis
- Strict filtering criteria
- Ranking and selection
- Integration with PairSelectorService

### 4.4 Portfolio Weight Calculation

**Status**: ❌ **MISSING**
**Priority**: 🟡 **HIGH**
**Description**: Calculate optimal portfolio weights for baseline
**Implementation**: Create `backend/services/aeroing4/portfolio_weights.py`
**Requirements**:
- Weight calculation algorithms
- Capital constraint handling
- Risk-adjusted optimization
- Integration with BacktestRunner

### 4.5 OOS Data Preparation

**Status**: ❌ **MISSING**
**Priority**: 🟡 **HIGH**
**Description**: Split data into IS/OOS periods with contamination prevention
**Implementation**: Create `backend/services/aeroing4/oos_data_prep.py`
**Requirements**:
- Timerange splitting
- OOS contamination prevention
- Data validation
- Integration with DataDownloadRunner

### 4.6 Unseen Pair Management

**Status**: ❌ **MISSING**
**Priority**: 🟡 **HIGH**
**Description**: Track and manage seen vs unseen pairs for generalization testing
**Implementation**: Create `backend/services/aeroing4/unseen_pairs.py`
**Requirements**:
- Seen/unseen pair tracking
- Data leakage prevention
- Generalization scoring
- Integration with BacktestRunner

### 4.7 Realistic Execution Simulation

**Status**: ❌ **MISSING**
**Priority**: 🟢 **MEDIUM**
**Description**: Simulate realistic execution with slippage and order book impact
**Implementation**: Create `backend/services/aeroing4/execution_sim.py`
**Requirements**:
- Slippage modeling
- Order book impact simulation
- Fee calculation
- Integration with backtest results

### 4.8 Decision Aggregation Service

**Status**: ❌ **MISSING**
**Priority**: 🟡 **HIGH**
**Description**: Aggregate results from all steps and make final decision
**Implementation**: Create `backend/services/aeroing4/decision_service.py`
**Requirements**:
- Multi-criteria decision scoring
- Weight-based aggregation
- Pass/fail determination
- Explanation generation

### 4.9 Standalone Sensitivity Service

**Status**: ❌ **MISSING**
**Priority**: 🟢 **MEDIUM**
**Description**: Extract sensitivity logic from AutoQuant into standalone service
**Implementation**: Create `backend/services/aeroing4/sensitivity.py`
**Requirements**:
- Extract core logic from `backend/services/auto_quant/sensitivity.py`
- Remove AutoQuant variant coupling
- Work with any strategy and parameter set

## 5. Proposed AeRoing4 Backend Architecture

### 5.1 Directory Structure

```
backend/services/aeroing4/
├── __init__.py
├── orchestrator.py              # Main workflow orchestration
├── state.py                     # AeRoing4 state management
├── strategy_diagnosis.py        # AI-powered strategy diagnosis
├── pair_confirmation.py         # Candidate pair validation
├── portfolio_weights.py         # Portfolio weight calculation
├── oos_data_prep.py             # OOS data preparation
├── unseen_pairs.py              # Unseen pair management
├── execution_sim.py             # Realistic execution simulation
├── decision_service.py          # Final decision aggregation
├── sensitivity.py               # Parameter sensitivity (extracted)
├── models.py                    # AeRoing4-specific data models
└── config.py                    # AeRoing4 configuration

backend/api/routers/aeroing4/
├── __init__.py
├── workflow.py                  # AeRoing4 workflow endpoints
├── diagnosis.py                 # Strategy diagnosis endpoints
└── results.py                   # AeRoing4 results endpoints
```

### 5.2 Service Dependencies

```
AeRoing4Orchestrator
├── StrategyRegistry (reuse)
├── StrategyValidationService (reuse)
├── DataDownloadRunner (reuse)
├── BacktestRunner (reuse)
├── PairExplorerService (wrap)
├── PairConfirmationService (new)
├── StrategyDiagnosisService (new)
├── StrategyOptimizerService (reuse)
├── SensitivityService (extract)
├── OOSAndWalkForwardEngine (reuse)
├── OOSDataPrepService (new)
├── UnseenPairsService (new)
├── TemporalStressService (reuse)
├── MonteCarloService (reuse)
├── ExecutionSimService (new)
├── DecisionService (new)
└── SessionStore (reuse)
```

### 5.3 State Management

**AeRoing4 State** (independent of AutoQuant PipelineState):
```python
@dataclass
class AeRoing4State:
    run_id: str
    strategy_name: str
    current_step: int
    step_status: dict[int, StepStatus]
    step_results: dict[int, StepResult]
    final_decision: Decision | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancelled: bool = False
```

**Persistence**: JSON-based, similar to SessionStore
**Location**: `user_data_dir/aeroing4/runs/{run_id}/state.json`

## 6. Files to Create

### 6.1 Core AeRoing4 Services

1. `backend/services/aeroing4/__init__.py` - Package initialization
2. `backend/services/aeroing4/orchestrator.py` - Main orchestration logic
3. `backend/services/aeroing4/state.py` - State management and persistence
4. `backend/services/aeroing4/models.py` - AeRoing4-specific data models
5. `backend/services/aeroing4/config.py` - Configuration management

### 6.2 Step-Specific Services

6. `backend/services/aeroing4/strategy_diagnosis.py` - Strategy diagnosis
7. `backend/services/aeroing4/pair_confirmation.py` - Pair validation
8. `backend/services/aeroing4/portfolio_weights.py` - Portfolio weights
9. `backend/services/aeroing4/oos_data_prep.py` - OOS data preparation
10. `backend/services/aeroing4/unseen_pairs.py` - Unseen pair management
11. `backend/services/aeroing4/execution_sim.py` - Execution simulation
12. `backend/services/aeroing4/decision_service.py` - Decision aggregation
13. `backend/services/aeroing4/sensitivity.py` - Sensitivity analysis

### 6.3 API Layer

14. `backend/api/routers/aeroing4/__init__.py` - Router package
15. `backend/api/routers/aeroing4/workflow.py` - Workflow endpoints
16. `backend/api/routers/aeroing4/diagnosis.py` - Diagnosis endpoints
17. `backend/api/routers/aeroing4/results.py` - Results endpoints

### 6.4 Documentation

18. `docs/AEROING4_BACKEND_MAP.md` - This document
19. `docs/AEROING4_API_REFERENCE.md` - API reference (future)
20. `docs/AEROING4_ARCHITECTURE.md` - Architecture documentation (future)

## 7. Existing Files Requiring Small Integration Changes

### 7.1 App Services Registration

**File**: `backend/app_services.py`
**Change**: Add AeRoing4 services to AppServices class
```python
# In AppServices.__init__ or reload()
self.aeroing4_orchestrator = AeRoing4Orchestrator(...)
self.aeroing4_state_store = AeRoing4StateStore(...)
```

### 7.2 FastAPI App Registration

**File**: `backend/api/app.py`
**Change**: Register AeRoing4 routers
```python
from .routers import aeroing4
app.include_router(aeroing4.workflow.router)
app.include_router(aeroing4.diagnosis.router)
app.include_router(aeroing4.results.router)
```

### 7.3 Workflow Jobs Extension

**File**: `backend/services/workflow_jobs/__init__.py`
**Change**: Add AeRoing4 workflow job
```python
from .aeroing4_job import start_aeroing4_job
__all__ = [..., "start_aeroing4_job"]
```

### 7.4 Settings Store Extension

**File**: `backend/settings_store.py` (if exists)
**Change**: Add AeRoing4-specific settings
```python
aeroing4_enabled: bool = True
aeroing4_runs_dir: str = "user_data/aeroing4/runs"
```

## 8. Recommended Implementation Order

### Phase 1: Foundation (Week 1-2)
1. Create AeRoing4 package structure
2. Implement state management (`state.py`)
3. Implement data models (`models.py`)
4. Implement configuration (`config.py`)
5. Create basic orchestrator skeleton

### Phase 2: Core Services (Week 3-4)
6. Implement pair confirmation service
7. Implement portfolio weight calculation
8. Implement OOS data preparation
9. Implement unseen pair management
10. Extract sensitivity service from AutoQuant

### Phase 3: Advanced Services (Week 5-6)
11. Implement strategy diagnosis service
12. Implement execution simulation
13. Implement decision aggregation service
14. Integrate with existing services (BacktestRunner, etc.)

### Phase 4: Orchestration (Week 7-8)
15. Complete orchestrator implementation
16. Implement step-by-step workflow execution
17. Add progress tracking and cancellation
18. Add error handling and recovery

### Phase 5: API Layer (Week 9)
19. Create API routers
20. Implement workflow endpoints
21. Implement diagnosis endpoints
22. Implement results endpoints
23. Register routers in FastAPI app

### Phase 6: Integration and Testing (Week 10)
24. Integrate with AppServices
25. Add workflow jobs integration
26. End-to-end testing
27. Documentation and refinement

## 9. Risks and Blockers

### 9.1 Critical Risks

**Risk 1: Busy State Conflicts**
- **Description**: BacktestRunner, DataDownloadRunner, and StrategyOptimizerService use global busy flags
- **Impact**: Only one operation of each type can run at a time
- **Mitigation**: 
  - AeRoing4 should implement its own job queue
  - Consider creating runner instances for AeRoing4
  - Coordinate with existing runners to avoid conflicts

**Risk 2: AutoQuant Coupling**
- **Description**: Many useful services are tightly coupled to AutoQuant PipelineState
- **Impact**: Cannot reuse optimization, validation, and stress testing logic directly
- **Mitigation**:
  - Extract core logic into standalone services
  - Implement AeRoing4-specific versions where extraction is complex
  - Use lower-level services (BacktestRunner) instead of higher-level AutoQuant functions

**Risk 3: State Persistence Complexity**
- **Description**: AeRoing4 needs its own state management separate from AutoQuant
- **Impact**: Complex state synchronization and recovery logic
- **Mitigation**:
  - Design simple state model from the start
  - Use JSON-based persistence (proven pattern from SessionStore)
  - Implement recovery logic early

### 9.2 Medium Risks

**Risk 4: Data Contamination**
- **Description**: OOS data can be contaminated by IS data if not carefully managed
- **Impact**: Invalid OOS validation results
- **Mitigation**:
  - Implement strict OOS guard similar to AutoQuant's oos_guard.py
  - Add validation checks before each OOS test
  - Document OOS data handling clearly

**Risk 5: AI Service Dependency**
- **Description**: Strategy diagnosis depends on AI service availability
- **Impact**: Diagnosis step may fail or be unavailable
- **Mitigation**:
  - Make diagnosis optional
  - Provide fallback to rule-based diagnosis
  - Add clear error handling for AI failures

**Risk 6: Performance Bottlenecks**
- **Description**: AeRoing4 workflow involves many sequential backtests
- **Impact**: Long execution times, poor user experience
- **Mitigation**:
  - Implement parallel execution where possible
  - Add progress tracking and cancellation
  - Optimize data preparation to avoid redundant downloads

### 9.3 Low Risks

**Risk 7: API Compatibility**
- **Description**: Existing API endpoints may not support all AeRoing4 requirements
- **Impact**: May need to extend existing APIs
- **Mitigation**:
  - Use workflow jobs layer for abstraction
  - Extend APIs incrementally as needed
  - Maintain backward compatibility

**Risk 8: Configuration Complexity**
- **Description**: AeRoing4 introduces many new configuration options
- **Impact**: Complex configuration management
- **Mitigation**:
  - Provide sensible defaults
  - Use configuration profiles (conservative, aggressive, etc.)
  - Document configuration clearly

### 9.4 Blockers

**Blocker 1: Missing Workflow Jobs**
- **Description**: `start_pair_stress_job` and `start_temporal_stress_job` are placeholders
- **Impact**: Cannot use stress testing from workflow jobs layer
- **Resolution**: Implement these job functions before AeRoing4 stress testing step

**Blocker 2: Strategy Diagnosis**
- **Description**: No existing strategy diagnosis service
- **Impact**: Cannot implement strategy diagnosis step
- **Resolution**: Implement strategy diagnosis service or make step optional

**Blocker 3: Execution Simulation**
- **Description**: No existing realistic execution simulation
- **Impact**: Cannot implement realistic execution stress test
- **Resolution**: Implement execution simulation or simplify stress testing requirements

## 10. Hidden Risks in Existing Code

### 10.1 Validation Reporting Success When Skipped

**Location**: `backend/services/strategy/strategy_validation_service.py`
**Risk**: Freqtrade test-strategy timeout is reported as warning, not error
**Code**: Lines 97-99
```python
except subprocess.TimeoutExpired:
    warnings.append("Freqtrade test-strategy timed out after 60 s.")
    output_lines.append("⚠ timed out.")
```
**Impact**: Validation may report success when Freqtrade validation was skipped
**Mitigation**: Add strict timeout handling in AeRoing4 wrapper

### 10.2 Hardcoded Exchange Assumptions

**Location**: `backend/services/execution/backtest_runner.py`
**Risk**: Default exchange hardcoded to "binance"
**Code**: Lines 87-88
```python
def _check_data_exists(
    self,
    pairs: list[str],
    timeframe: str,
    user_data_dir: str,
    exchange: str = "binance",  # Hardcoded default
```
**Impact**: Data checks may fail for non-binance exchanges
**Mitigation**: Always pass exchange parameter explicitly in AeRoing4

### 10.3 Strategy File Mutation

**Location**: `backend/services/auto_quant/variants.py`
**Risk**: AutoQuant mutates strategy files in run-local directories
**Code**: Lines 46-78
**Impact**: Original strategy files may be modified during AutoQuant runs
**Mitigation**: AeRoing4 should use version management (VersionManager) to prevent mutation

### 10.4 Shared Runner Busy State

**Location**: Multiple runner services
**Risk**: Global busy flags prevent concurrent operations
**Code**: Various `is_busy()` methods
**Impact**: AeRoing4 cannot run concurrent operations
**Mitigation**: Implement job queue or use runner instances

### 10.5 Temporary File Behavior

**Location**: `backend/services/strategy/strategy_validation_service.py`
**Risk**: Temporary strategy files may not be cleaned up on error
**Code**: Lines 107-111
```python
finally:
    temp_strat_file.unlink(missing_ok=True)
    import sys as _sys
    pyc_ver = f"cpython-{_sys.version_info.major}{_sys.version_info.minor}"
    pyc = strategies_dir / "__pycache__" / f"{temp_strat_name}.{pyc_ver}.pyc"
    pyc.unlink(missing_ok=True)
```
**Impact**: Temporary files may accumulate over time
**Mitigation**: Add robust cleanup in AeRoing4 wrappers

### 10.6 Background Job Survival

**Location**: `backend/api/session_store.py`
**Risk**: Sessions survive restarts but background tasks do not
**Code**: Session persistence vs task lifecycle
**Impact**: Orphaned sessions after server restart
**Mitigation**: Implement recovery logic in AeRoing4 orchestrator

### 10.7 Duplicated Result Parsing

**Location**: Multiple locations
**Risk**: Result parsing logic duplicated across services
**Code**: `ResultParser`, AutoQuant helpers, API routers
**Impact**: Inconsistent result parsing across contexts
**Mitigation**: Use ResultParser consistently in AeRoing4

### 10.8 Hidden Dependency on AutoQuant PipelineState

**Location**: Various AutoQuant services
**Risk**: Services appear independent but depend on PipelineState
**Code**: Implicit state passing through function arguments
**Impact**: May fail when called outside AutoQuant context
**Mitigation**: Test services independently before reuse in AeRoing4

## 11. Integration Points

### 11.1 Service Layer Integration

**AppServices Extension**:
```python
class AppServices:
    def __init__(self, root_dir: Path) -> None:
        # ... existing services ...
        
        # AeRoing4 services
        from backend.services.aeroing4.orchestrator import AeRoing4Orchestrator
        from backend.services.aeroing4.state import AeRoing4StateStore
        
        self.aeroing4_orchestrator = AeRoing4Orchestrator(
            self.backtest_runner,
            self.data_download_runner,
            self.strategy_optimizer,
            # ... other dependencies
        )
        self.aeroing4_state_store = AeRoing4StateStore(
            self.paths.user_data_dir / "aeroing4" / "runs"
        )
```

### 11.2 API Layer Integration

**Router Registration**:
```python
# In backend/api/app.py
from .routers import aeroing4

app.include_router(aeroing4.workflow.router)
app.include_router(aeroing4.diagnosis.router)
app.include_router(aeroing4.results.router)
```

### 11.3 Workflow Jobs Integration

**Job Function**:
```python
# In backend/services/workflow_jobs/aeroing4_job.py
async def start_aeroing4_job(
    services,
    store: SessionStore,
    strategy_name: str,
    config: AeRoing4Config,
) -> tuple[str, str]:
    """Start AeRoing4 workflow and return (session_id, status)."""
    # Implementation similar to start_backtest_job
```

## 12. Testing Strategy

### 12.1 Unit Testing

- Test each new service independently
- Mock external dependencies (Freqtrade, AI service)
- Test state persistence and recovery
- Test error handling and edge cases

### 12.2 Integration Testing

- Test service integration with existing services
- Test API endpoints with real service calls
- Test workflow execution end-to-end
- Test cancellation and recovery

### 12.3 Performance Testing

- Test workflow execution time
- Test concurrent operation handling
- Test memory usage and resource cleanup
- Test database/file I/O performance

## 13. Monitoring and Observability

### 13.1 Progress Tracking

- Use SessionStore for job tracking
- Emit progress events for each step
- Provide real-time status via WebSocket or SSE

### 13.2 Error Logging

- Log all errors with context
- Distinguish between retryable and fatal errors
- Log state snapshots on errors for debugging

### 13.3 Metrics Collection

- Track step execution times
- Track success/failure rates per step
- Track resource usage (memory, CPU, I/O)
- Track AI service latency and success rate

## 14. Documentation Requirements

### 14.1 API Documentation

- Document all AeRoing4 API endpoints
- Provide request/response examples
- Document error codes and recovery procedures

### 14.2 Service Documentation

- Document each AeRoing4 service
- Explain dependencies and integration points
- Provide usage examples

### 14.3 Architecture Documentation

- Document AeRoing4 architecture decisions
- Explain trade-offs and alternatives
- Provide diagrams for complex workflows

## 15. Success Criteria

### 15.1 Functional Requirements

- ✅ All 15 workflow steps implemented
- ✅ Integration with existing services verified
- ✅ State persistence and recovery working
- ✅ Cancellation and error handling working
- ✅ API endpoints functional and documented

### 15.2 Non-Functional Requirements

- ✅ No conflicts with existing AutoQuant workflow
- ✅ Performance acceptable (workflow completes in reasonable time)
- ✅ Resource usage acceptable (memory, CPU, I/O)
- ✅ Code quality meets project standards
- ✅ Comprehensive test coverage

### 15.3 Integration Requirements

- ✅ Registered in AppServices
- ✅ Routers registered in FastAPI app
- ✅ Workflow jobs integrated
- ✅ Settings configured
- ✅ Documentation complete

## 16. Conclusion

The backend has strong lower-level services that AeRoing4 can reuse directly, particularly:

- **BacktestRunner** - Core backtest execution
- **DataDownloadRunner** - Market data download
- **StrategyOptimizerService** - Parameter optimization
- **ResultParser** - Result parsing
- **OOSAndWalkForwardEngine** - OOS testing logic
- **TemporalStressService** - Temporal stress testing
- **MonteCarloService** - Monte Carlo analysis

The main work is to:

1. **Create AeRoing4 orchestration layer** - Independent of AutoQuant pipeline
2. **Implement missing services** - Diagnosis, pair confirmation, decision aggregation
3. **Extract sensitivity logic** - From AutoQuant into standalone service
4. **Implement state management** - Independent of PipelineState
5. **Create API layer** - Workflow, diagnosis, and results endpoints

**Critical Path**: Orchestration → State Management → Core Services → API Layer

**Estimated Effort**: 10 weeks for full implementation and testing

**Risk Level**: Medium - Low coupling to AutoQuant reduces risk, but new orchestration layer adds complexity
