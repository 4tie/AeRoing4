# AutoQuant Skills Configuration

This folder contains the **static skill system design** for AutoQuant.

Right now this is **docs and schema only**. No runtime loading, no service changes, no pipeline changes.

## What is a skill?

A skill is a small, named behavior that can be turned **on or off** for an AutoQuant run.

Skills do **not** replace backend validation or Freqtrade.
They only decide **when** and **how** to use existing AutoQuant modules such as:
- Monte Carlo
- Regime adapter
- Auto-fix engine
- Sensitivity checks
- Strategy variants

## File layout

```
backend/config/skills/auto_quant/
  README.md       <- this file
  schema.json     <- JSON Schema for skill definitions
```

Current static skill docs:
- `strategy_validation/`
- `pair_data_discovery/`
- `baseline_backtest/`

Later, when runtime loading is enabled, this folder may also contain:
- `catalog/` - bundled default skill JSON files
- `examples/` - reference skills

## Core rules

1. **Opt-in only.** A skill is ignored unless `enabled` is `true`.
2. **Stage-scoped.** Each skill declares which AutoQuant stages it may run in.
3. **Run-scoped config.** Every run carries the exact skill config it used.
4. **No secrets.** Skills must not read credentials or environment variables directly.
5. **Backend validates.** The backend never trusts a skill result blindly.

## Schema overview

See `schema.json` for the exact contract.

Required root fields:
- `id` - unique slug, lowercase, numbers, dashes, underscores only
- `name` - human-readable label
- `version` - semver string
- `description` - one or two sentences explaining what the skill does
- `enabled` - boolean master switch
- `applies_to` - which stages and optional gates this skill can fire in
- `config` - JSON Schema object fragment describing required runtime parameters

Optional root fields:
- `tags` - list of simple category strings
- `author` - display only
- `dependencies` - list of other skill ids that must be enabled first
- `preconditions` - list of boolean expressions checked before activation
- `rollback` - retry and fallback rules
- `timeout_seconds` - max execution time for this skill
- `permissions` - what the skill is allowed to read or write
- `docs` - path to markdown documentation for this skill

## Example

```json
{
  "id": "monte_carlo_v1",
  "name": "Monte Carlo stability check",
  "version": "1.0.0",
  "description": "Runs simulations on OOS trades to confirm the strategy is not a sharp-peak artifact. Fails stage4 if worst 5% drawdown exceeds threshold.",
  "enabled": true,
  "applies_to": {
    "stages": ["stage4_stress"],
    "gates": ["post_optimization"]
  },
  "config": {
    "type": "object",
    "required": ["simulations", "confidence"],
    "properties": {
      "simulations": { "type": "integer", "minimum": 500, "maximum": 5000 },
      "confidence":  { "type": "number",  "minimum": 0.90, "maximum": 0.99 },
      "block_on_fail": { "type": "boolean", "default": true }
    }
  },
  "tags": ["robustness", "drawdown"],
  "author": "AutoQuant",
  "dependencies": [],
  "preconditions": [
    "baseline_profit_factor >= 1.0",
    "oos_trade_count >= 10"
  ],
  "rollback": { "enabled": true, "max_attempts": 1 },
  "timeout_seconds": 900,
  "permissions": {
    "read_results": true,
    "write_artifacts": true,
    "modify_strategy": false
  },
  "docs": "skills/auto_quant/monte_carlo_v1.md"
}
```

## Migration path

1. **This phase:** README + schema only.
2. **Next phase:** Add schema validation tests under `backend/tests/auto_quant/skills/`.
3. **Later phase:** Introduce a static registry and optional per-run skill inclusion.
4. **Final phase:** Enable runtime discovery only after stage names and precondition parser are stable.

## Safety notes

- Skills must never bypass existing gates such as OOS isolation, data quality checks, or Monte Carlo thresholds.
- If a skill fails, the run should fail unless `rollback.enabled` explicitly allows recovery.
- All skill activity must be logged and visible in the run state.
