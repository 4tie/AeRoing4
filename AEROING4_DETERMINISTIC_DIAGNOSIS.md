# AeRoing4 Deterministic Diagnosis Engine

## Overview

The Deterministic Diagnosis Engine is a core component of AeRoing4 that analyzes the Initial Champion using measured evidence to identify weaknesses without using AI, executing new backtests, or mutating strategy code. The engine provides deterministic, evidence-based diagnosis with clear severity levels and actionable research guidance.

**Policy Version:** 1.0.0

## Design Principles

1. **Deterministic:** Same input always produces same output
2. **Evidence-Based:** Only uses available measured evidence
3. **No AI:** Does not use Ollama or any AI models
4. **No Strategy Mutation:** Does not modify strategy code
5. **No Automatic Experiments:** Does not create experiments automatically
6. **Typed Models:** Uses Pydantic for type safety
7. **Centralized Registry:** All rules registered in one place
8. **Evidence Quality Gate:** Primary diagnosis requires sufficient evidence quality
9. **Conservative Thresholds:** Uses moderate diagnostic thresholds for balanced sensitivity

## Architecture

### Package Structure

```
backend/services/aeroing4/diagnosis/
├── __init__.py              # Public API exports
├── models.py                # Typed models (DiagnosisInput, DiagnosisResult, etc.)
├── engine.py                # DiagnosisEngine (orchestrates evaluation)
├── registry.py              # RuleRegistry (centralized rule management)
├── resolver.py              # EvidenceResolver (typed evidence access)
├── thresholds.py           # ThresholdPolicy + EvidenceQuality
├── persistence.py           # DiagnosisStore (atomic save/load)
└── rules/
    ├── __init__.py
    ├── base.py              # BaseRule interface
    ├── sample_quality.py    # Sample quality rules
    ├── edge_quality.py      # Edge quality rules
    ├── risk.py              # Risk quality rules
    ├── pair_structure.py    # Pair structure rules
    ├── exit_behavior.py     # Exit behavior rules
    ├── entry_behavior.py    # Entry behavior rules
    └── parameter_research.py # Derived/routing findings
```

### Data Flow

```
PortfolioBaselineResult
    ↓
DiagnosisInput (typed)
    ↓
EvidenceResolver (typed access)
    ↓
RuleRegistry (all rules)
    ↓
Rule Evaluation (each rule)
    ↓
DiagnosisResult (findings + metadata)
    ↓
DiagnosisStore (atomic persistence)
```

## Evidence Sources

The Diagnosis Engine uses the following evidence sources:

1. **PortfolioBaselineResult**
   - `selected_pairs`: List of selected pairs
   - `per_pair_contribution`: Per-pair trade and profit data
   - `concentration_summary`: Concentration metrics
   - `exit_reason_distribution`: Exit reason statistics
   - `canonical_metrics`: CanonicalMetricsSnapshot

2. **CanonicalMetricsSnapshot**
   - Total trades, winning trades, losing trades
   - Profit factor, expectancy
   - Max drawdown, Calmar, Sortino, Sharpe
   - Win rate, average trade duration

3. **ChampionReference**
   - Champion ID, run ID
   - Strategy artifact hash
   - Parameter artifact hash
   - For integrity verification

## Diagnosis Categories

### Sample Quality
- `INSUFFICIENT_SAMPLE`: Total trades below timeframe minimum
- `UNBALANCED_PAIR_SAMPLE`: Uneven trade distribution across pairs

### Edge Quality
- `NEGATIVE_EXPECTANCY`: Negative per-trade profit
- `WEAK_EDGE`: Profit factor in weak range (1.00-1.10)
- `LOW_PROFIT_FACTOR`: Profit factor below 1.0
- `NO_EDGE`: Conservative definition (PF < 1.0 + Expectancy < 0)

### Risk Quality
- `EXCESSIVE_DRAWDOWN`: Max drawdown exceeds thresholds
- `POOR_RETURN_TO_DRAWDOWN`: Low Calmar ratio
- `DOWNSIDE_RISK_DOMINANCE`: Low Sortino ratio

### Pair Structure
- `PAIR_CONCENTRATION`: Top pair dominates portfolio
- `SINGLE_PAIR_DEPENDENCE`: Only one contributing pair
- `MULTIPLE_NEGATIVE_CONTRIBUTORS`: Multiple pairs with negative contribution

### Exit Behavior
- `STOPLOSS_DOMINANCE`: Stop loss exits dominate
- `EXIT_LOSS_CONCENTRATION`: Losses concentrated in specific exit reasons

### Entry Behavior
- `ENTRY_TOO_RESTRICTIVE`: Very low trade count relative to minimum

### Parameter Research (Derived/Routing Only)
- `PARAMETER_RESEARCH_NEEDED`: General parameter research suggestion
- `EXIT_PARAMETER_RESEARCH_NEEDED`: Exit parameter research suggestion
- `RISK_PARAMETER_RESEARCH_NEEDED`: Risk parameter research suggestion
- `ENTRY_PARAMETER_RESEARCH_NEEDED`: Entry parameter research suggestion

**Note:** Parameter research findings are derived/routing only and must NOT become primary diagnoses.

## Thresholds

### Profit Factor
- **Negative:** PF < 1.00
- **Weak:** 1.00 ≤ PF < 1.10
- **Marginal:** 1.10 ≤ PF < 1.30
- **Strong:** PF ≥ 1.30

### Drawdown
- **Acceptable:** < 20%
- **Elevated:** 20% - 30%
- **High:** 30% - 40%
- **Critical:** > 40%

### Expectancy
- **Negative:** Expectancy < 0

### Concentration
- **Top Pair Threshold:** 50% profit share
- **Single Pair Dependence:** 1 contributing pair

### Exit Reasons
- **Stoploss Dominance:** > 60% stop loss exits

## Evidence Quality Classification

Evidence quality is classified based on:
- Sufficient trade count (vs. timeframe minimum)
- Number of selected pairs
- Canonical metric availability
- Per-pair evidence availability
- Exit reason availability
- Sample duration

**Quality Levels:**
- **HIGH:** 4-5 quality factors met
- **MEDIUM:** 2-3 quality factors met
- **LOW:** 1 quality factor met
- **INSUFFICIENT:** 0 quality factors met

## Primary Diagnosis Selection

Primary diagnosis is selected using deterministic order:

1. **Evidence Quality Gate:** Only HIGH/MEDIUM evidence findings can be primary
   - With LOW evidence: only CRITICAL findings with confidence ≥ 0.85
   - With INSUFFICIENT evidence: no primary diagnosis

2. **Severity:** CRITICAL > HIGH > MEDIUM > LOW > INFO

3. **Confidence:** Higher confidence wins

4. **Rule Priority:** Fixed priority per rule (higher = more important)

5. **Tie-Break:** Diagnosis code (alphabetical, stable)

**Exclusion:** Parameter research findings are excluded from primary diagnosis consideration.

## Champion Integrity Checks

Before diagnosis, the engine verifies:
- Champion reference is provided
- Champion ID matches between input and reference
- Strategy hash matches between input and reference
- Parameter hash matches between input and reference

Any mismatch results in `INTEGRITY_ERROR` outcome.

## Persistence

Diagnosis results are persisted atomically in:
```
user_data/aeroing4/runs/{run_id}/diagnoses.json
```

**Persistence Features:**
- Atomic save (write to temp file, then rename)
- History support (multiple diagnoses per run/champion)
- Idempotency (input hash for duplicate detection)
- Query by run ID, champion ID, or diagnosis ID
- Latest diagnosis retrieval

## API Endpoints

### Existing Run Endpoint (Enhanced)
```
GET /api/aeroing4/runs/{run_id}
```

Response now includes `diagnosis` field with summary:
- `status`: Diagnosis outcome
- `primary_code`: Primary diagnosis code
- `severity`: Primary diagnosis severity
- `confidence`: Primary diagnosis confidence
- `evidence_quality`: Evidence quality classification

### New Diagnosis History Endpoint
```
GET /api/aeroing4/runs/{run_id}/diagnoses
```

Returns full diagnosis history for a run:
- All diagnosis results
- Complete findings (primary, secondary, informational)
- Evidence quality and rule evaluation metadata
- Timing and error information

## Integration with Orchestrator

The Diagnosis Step is added after Initial Champion Step in the workflow:

```
Validation → Data Preparation → Smoke Backtest → Bias Check
→ Pair Discovery → Pair Selection → Portfolio Baseline
→ Initial Champion → Diagnosis → Complete
```

**Diagnosis Step Behavior:**
- Non-fatal: Step failure does not stop the run
- Informational: Provides diagnosis guidance
- Skipped if Initial Champion fails

## Shared Policy Module

The Diagnosis Engine reuses the existing timeframe-aware minimum trade policy from Pair Discovery:

**Location:** `backend/services/aeroing4/policies.py`

**Exports:**
- `TIMEFRAME_MIN_TRADES`: Dictionary mapping timeframes to minimum trades
- `get_min_trades(timeframe: str) -> int`: Get minimum trades for timeframe

This ensures consistency across Pair Discovery and Diagnosis without heuristic invention.

## Testing

Comprehensive tests are provided in `backend/tests/aeroing4/diagnosis/`:

- `test_models.py`: Model validation and enums
- `test_thresholds.py`: Threshold constants and evidence quality
- `test_resolver.py`: Evidence resolver and exit reason mapping
- `test_rules.py`: Individual rule evaluation
- `test_engine.py`: Engine orchestration and primary diagnosis selection
- `test_persistence.py`: Persistence operations

Run tests:
```bash
pytest backend/tests/aeroing4/diagnosis/
```

## Limitations

1. **No Trade-Level Evidence:** Does not use MFE, MAE, or trade-path data
2. **No Indicator-Level Evidence:** Does not use indicator-specific data
3. **Conservative Thresholds:** Thresholds are moderate, not aggressive
4. **Evidence-Dependent:** Diagnosis quality depends on evidence availability
5. **No AI:** Does not use AI for pattern recognition or anomaly detection

## Future Enhancements (Not Implemented)

The following are explicitly NOT implemented as per requirements:
- AI Proposal Generator
- Research Loop integration
- Automatic experiment creation
- Strategy code mutation
- New backtest execution

## Version History

**1.0.0** (Initial Release)
- Deterministic diagnosis engine
- 7 diagnosis categories with 16 diagnosis codes
- Evidence quality classification
- Primary diagnosis selection with quality gate
- Atomic persistence with history support
- API integration (summary + history endpoints)
- Orchestrator integration
- Comprehensive test coverage
