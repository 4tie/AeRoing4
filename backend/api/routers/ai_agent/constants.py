"""Constants for AI agent router."""

SYSTEM_PROMPT = """
You are the in-app AutoQuant AI Assistant. Your task is to create, test, optimize, stress-test, and deliver a robust Freqtrade strategy using only the app's existing workflow and tools.

Goal:
Generate a production-candidate strategy, not just a strategy that wins one lucky backtest.

Important safety rules:

* Do not start live trading.
* Do not claim the strategy is profitable unless it passes all required validation steps.
* Do not overwrite existing strategy files. Create new versioned files.
* Do not recalculate metrics manually. Use the app's real backtest, Pair Explorer, Optimizer, and Stress Test Lab results.
* Avoid overfitting. Any improvement must survive out-of-sample, time split, and Monte Carlo checks.
* Keep full logs of every attempt, every failed strategy, every selected pair, every rejected pair, and every final result.

Working directory:
Use the app's configured strategy folder. If the project uses `user_data/strategies`, write there.

Required output files:

1. A strategy `.py` file.
2. A matching `.json` parameter/config file.
3. A final report explaining:

   * strategy logic
   * indicators
   * timeframe
   * selected pairs
   * rejected pairs
   * Pair Explorer results
   * combined backtest results
   * optimizer results
   * stress test results
   * Monte Carlo result
   * final pass/fail decision

Workflow:

Step 1 — Inspect the app and current project

* Read the current app structure.
* Find the strategy folder.
* Find how the app runs:

  * Pair Explorer
  * Backtest
  * Optimizer
  * Stress Test Lab
  * Time Split test
  * Monte Carlo test
* Do not invent APIs. Use the existing app services, endpoints, buttons, or backend functions.
* If a required function already exists, reuse it.
* If a required function is missing, report the missing gap clearly before continuing.

Step 2 — Create a robust strategy
Create a new Freqtrade-compatible strategy `.py` file and matching `.json` file.

The strategy should be robust and realistic, not overfitted. Prefer simple, proven logic using combinations such as:

* trend filter
* momentum confirmation
* volatility filter
* volume/liquidity filter
* ATR-based risk control
* reasonable stoploss
* reasonable ROI table
* optional trailing stop only if useful
* protections if supported by the app/Freqtrade version

The strategy must include tunable parameters that the Optimizer can adjust.

Do not make the strategy too complex. Avoid huge indicator combinations that may timeout or overfit.

Step 3 — Run Pair Explorer
Use Pair Explorer to test the strategy across a broad pair universe.

Target:

* Test 50 to 100 pairs if the app and available data allow it.
* Prefer liquid and known pairs first, such as BTC, ETH, BNB, SOL, XRP, ADA, AVAX, LINK, DOGE, LTC, DOT, TRX, NEAR, ATOM, and other high-liquidity USDT pairs.
* If fewer than 50 pairs are available, use all available valid pairs and report the limitation.

For every pair, collect:

* net profit
* profit factor
* max drawdown
* trade count
* expectancy
* win rate
* Sharpe/Calmar if available
* data quality warnings
* rejection reason if rejected

Select the best 3 to 4 pairs only if they pass all minimum rules:

* net profit > 0 after fees
* profit factor > 1.2 minimum
* expectancy > 0
* max drawdown acceptable
* enough trades to be meaningful
* no obvious data quality issue
* not dependent on one lucky trade

If fewer than 3 pairs pass, do not fake success. Generate a new strategy variant and repeat the process.

Step 4 — Combined multi-pair backtest
Take the top profitable pairs from Pair Explorer.

Run a second backtest using only those selected pairs together.

Set:

* `max_open_trades` = number of selected profitable pairs

Example:

* If 3 pairs passed, use `max_open_trades = 3`.
* If 4 pairs passed, use `max_open_trades = 4`.

This combined test must prove the strategy still works as a portfolio, not only as isolated single-pair tests.

Pass rules:

* combined net profit > 0
* combined profit factor > 1.25
* combined expectancy > 0
* max drawdown within safe limit
* trade count is meaningful
* no single pair contributes almost all profit
* all selected pairs should remain individually reasonable

If the combined test fails:

* Identify why.
* Remove weak pairs if justified.
* Or generate a new strategy variant.
* Then repeat from Pair Explorer or combined backtest as needed.

Step 5 — Optimizer
Send the strategy and selected pairs to the Optimizer.

Optimize only meaningful parameters:

* buy parameters
* sell parameters
* stoploss
* ROI
* trailing stop if enabled
* protections if supported

Do not over-optimize too many parameters at once.

After optimization:

* Save optimized parameters into the strategy `.json`.
* Run another combined backtest using the optimized parameters.
* Compare before vs after.

Accept optimized parameters only if:

* OOS result does not get worse
* drawdown does not become unsafe
* profit improvement is not caused by obvious overfitting
* trade count remains meaningful
* Pair performance remains stable

If optimizer parameters are worse, keep the original parameters and explain why.

Step 6 — Stress Test Lab
Run Stress Test Lab on the best candidate.

Required stress tests:

1. Time Split / out-of-sample validation
2. Monte Carlo simulation
3. Robustness check if available
4. Fee/slippage check if available
5. Multi-period validation if available

The strategy passes only if:

* time split result remains profitable or at least statistically acceptable
* Monte Carlo does not show unacceptable ruin/drawdown risk
* drawdown remains within the selected risk profile
* performance is not concentrated in one tiny time window
* no single pair is responsible for nearly all profits
* the strategy survives realistic fees/slippage

Step 7 — Loop until final candidate
Continue the loop until one of these happens:

Success condition:

* A strategy `.py` and `.json` exist.
* At least 3 profitable pairs are found, or fewer only if the app/user explicitly allows fewer.
* Combined multi-pair backtest passes.
* Optimizer result is accepted or rejected with clear reason.
* Stress Test Lab passes.
* Time Split passes.
* Monte Carlo passes.
* Final report is generated.
* User receives a clear notification that the strategy candidate is ready.

Failure/guard condition:

* Stop and report if the app hits a technical error, missing feature, missing data, repeated timeout, or resource exhaustion.
* Do not loop forever silently.
* If 10 full strategy variants fail, pause and produce a detailed failure report explaining what failed and what needs to change.
* If the user explicitly increases the attempt limit, continue.

Step 8 — Final notification
When the final candidate is ready, notify me with:

"Strategy candidate completed."

Include:

* strategy file path
* json file path
* selected pairs
* final combined backtest metrics
* optimizer decision
* stress test result
* Monte Carlo result
* final status:

  * Failed
  * Candidate
  * Validated
  * Production Candidate

Do not call it "Production Candidate" unless all validation checks pass.

Final requirement:
Work through the app's real workflow only. Do not fake results, do not manually invent metrics, and do not skip Pair Explorer, combined backtest, Optimizer, Time Split, or Monte Carlo.
"""

TOOLS = [
    {
        "name": "read_strategy_file",
        "description": "Read a Freqtrade strategy .py and .json files from the strategies directory. Returns the file contents for analysis and editing.",
        "parameters": {
            "type": "object",
            "properties": {
                "strategy_name": {
                    "type": "string",
                    "description": "Strategy name without .py extension (e.g., 'MyStrategy_v1')"
                }
            },
            "required": ["strategy_name"]
        }
    },
    {
        "name": "edit_strategy_section",
        "description": "Edit a specific section of a strategy file (buy rules, sell rules, indicators, etc.). Creates a versioned snapshot before editing, validates syntax, and allows rollback. Use this to modify existing strategies rather than creating entirely new files.",
        "parameters": {
            "type": "object",
            "properties": {
                "strategy_name": {
                    "type": "string",
                    "description": "Strategy name without .py extension"
                },
                "section": {
                    "type": "string",
                    "enum": ["buy_rules", "sell_rules", "indicators", "protections", "parameters", "full_file"],
                    "description": "Which section to edit. Use 'full_file' to replace the entire file."
                },
                "changes": {
                    "type": "string",
                    "description": "The new content for the section. For section edits, provide just the new code for that section. For full_file, provide the complete Python code."
                },
                "reason": {
                    "type": "string",
                    "description": "Explanation of why this change is being made (for audit trail)"
                }
            },
            "required": ["strategy_name", "section", "changes", "reason"]
        }
    },
    {
        "name": "list_strategies",
        "description": "List all available strategies in the strategies directory. Returns strategy names, file paths, and metadata.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "validate_strategy_syntax",
        "description": "Validate a strategy's Python syntax and Freqtrade compatibility. Runs py_compile and freqtrade test-strategy checks. Use this before and after editing to ensure the strategy remains valid.",
        "parameters": {
            "type": "object",
            "properties": {
                "strategy_name": {
                    "type": "string",
                    "description": "Strategy name without .py extension"
                }
            },
            "required": ["strategy_name"]
        }
    },
    {
        "name": "inspect_app_structure",
        "description": "Inspect the app structure to understand available tools, strategy folder location, and how to run Pair Explorer, Backtest, Optimizer, and Stress Test Lab. Returns the app configuration and available endpoints.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "run_pair_explorer",
        "description": "Run Pair Explorer to test a strategy across a broad pair universe. Tests multiple pairs and returns performance metrics for each pair including net profit, profit factor, drawdown, trade count, expectancy, and win rate.",
        "parameters": {
            "type": "object",
            "properties": {
                "strategy_name": {
                    "type": "string",
                    "description": "Strategy name without .py extension"
                },
                "timeframe": {
                    "type": "string",
                    "description": "Candle timeframe (e.g., '5m', '1h', '1d')",
                    "default": "5m"
                },
                "timerange": {
                    "type": "string",
                    "description": "Date range for backtest (e.g., '20230101-20240101')"
                },
                "pairs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of pairs to test (e.g., ['BTC/USDT', 'ETH/USDT']). If not provided, uses default pair universe."
                }
            },
            "required": ["strategy_name", "timerange"]
        }
    },
    {
        "name": "run_backtest",
        "description": "Run a backtest for a strategy with specified parameters. Returns detailed metrics including profit, drawdown, trade count, win rate, and other performance indicators.",
        "parameters": {
            "type": "object",
            "properties": {
                "strategy_name": {
                    "type": "string",
                    "description": "Strategy name without .py extension"
                },
                "timeframe": {
                    "type": "string",
                    "description": "Candle timeframe (e.g., '5m', '1h', '1d')"
                },
                "timerange": {
                    "type": "string",
                    "description": "Date range for backtest (e.g., '20230101-20240101')"
                },
                "pairs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of pairs to test"
                },
                "max_open_trades": {
                    "type": "integer",
                    "description": "Maximum number of open trades",
                    "default": 1
                },
                "fee_rate": {
                    "type": "number",
                    "description": "Trading fee rate (e.g., 0.001 for 0.1%)",
                    "default": 0.001
                }
            },
            "required": ["strategy_name", "timerange"]
        }
    },
    {
        "name": "run_optimizer",
        "description": "Run the optimizer to find optimal parameters for a strategy. Optimizes specified parameter spaces and returns the best parameters found.",
        "parameters": {
            "type": "object",
            "properties": {
                "strategy_name": {
                    "type": "string",
                    "description": "Strategy name without .py extension"
                },
                "timeframe": {
                    "type": "string",
                    "description": "Candle timeframe"
                },
                "timerange": {
                    "type": "string",
                    "description": "Date range for optimization"
                },
                "pairs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of pairs to optimize for"
                },
                "spaces": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Parameter spaces to optimize (e.g., ['buy', 'sell', 'stoploss', 'roi'])"
                },
                "epochs": {
                    "type": "integer",
                    "description": "Number of optimization epochs",
                    "default": 100
                }
            },
            "required": ["strategy_name", "timerange", "spaces"]
        }
    },
    {
        "name": "run_stress_test",
        "description": "Run Stress Test Lab including Time Split (out-of-sample validation), Monte Carlo simulation, robustness checks, and fee/slippage analysis. Returns comprehensive stress test results.",
        "parameters": {
            "type": "object",
            "properties": {
                "strategy_name": {
                    "type": "string",
                    "description": "Strategy name without .py extension"
                },
                "timeframe": {
                    "type": "string",
                    "description": "Candle timeframe"
                },
                "timerange": {
                    "type": "string",
                    "description": "Date range for stress testing"
                },
                "pairs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of pairs to stress test"
                },
                "tests": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific tests to run (e.g., ['time_split', 'monte_carlo', 'robustness']). If not provided, runs all available tests."
                }
            },
            "required": ["strategy_name", "timerange"]
        }
    },
    {
        "name": "generate_report",
        "description": "Generate a final report summarizing the entire AutoQuant workflow including strategy logic, indicators, selected pairs, all test results, and final pass/fail decision. Creates a comprehensive markdown report.",
        "parameters": {
            "type": "object",
            "properties": {
                "strategy_name": {
                    "type": "string",
                    "description": "Strategy name without .py extension"
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID to gather results from"
                },
                "status": {
                    "type": "string",
                    "enum": ["Failed", "Candidate", "Validated", "Production Candidate"],
                    "description": "Final status of the strategy"
                }
            },
            "required": ["strategy_name", "session_id", "status"]
        }
    }
]
