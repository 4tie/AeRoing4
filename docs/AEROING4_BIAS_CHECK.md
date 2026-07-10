# AeRoing4 Bias Check Stage

## Overview
The Bias Check Stage is a critical quality gate inserted between the `SmokeBacktestStep` and the `PairDiscoveryStep` within the AeRoing4 orchestration workflow. It is responsible for identifying two types of subtle strategy flaws that can invalidate backtesting results:
1.  **Lookahead Bias:** The strategy accessing future data to make decisions in the present.
2.  **Recursive Formulae Issues:** The strategy using indicators that diverge uncontrollably over time or depend inconsistently on starting conditions.

This stage leverages Freqtrade's built-in `lookahead-analysis` and `recursive-analysis` commands to inspect strategies under test and evaluates their output.

## Architecture

*   **Models (`backend/services/aeroing4/models.py`):**
    *   `BiasCheckResult`: Aggregates the results of all individual bias checks into a single structured output.
    *   `BiasCheckItemResult`: Contains detailed information about a specific check (lookahead or recursive), including its execution status, analytical status, warnings, failures, and evidence.
    *   `BiasCheckOutcome`: An enum representing the final decision of the stage (e.g., `PASS`, `FAIL_LOOKAHEAD`, `EXECUTION_FAILURE`).
*   **Orchestration Step (`backend/services/aeroing4/steps/bias_check.py`):** The workflow step implementation. It utilizes dependency-injected services to trigger the subprocess executions and parse the results, ultimately mutating the run state.
*   **Runner (`backend/services/execution/bias_check_runner.py`):** Encapsulates the execution logic for running Freqtrade commands asynchronously via `subprocess.run()`. Returns a unified `BiasCheckCommandResult`.
*   **Parser (`backend/services/storage/bias_parser.py`):** Analyzes the raw `stdout` and `stderr` streams from the Freqtrade commands. It detects the presence of bias and extracts relevant summary information.

## Workflow Integration
If the `SmokeBacktestStep` yields a `PASS_ACTIVITY` outcome, the orchestrator triggers the `BiasCheckStep`.

The stage handles results as follows:
*   **Pass (`PASS` / `PASS_WITH_WARNING`):** The workflow proceeds to the `PairDiscoveryStep`.
*   **Fail (`FAIL_LOOKAHEAD` / `FAIL_RECURSIVE`):** The run is terminated immediately. A fatal flaw has been detected, preventing further (and potentially misleading) exploration.
*   **Error (`EXECUTION_FAILURE`):** The underlying Freqtrade command crashed or encountered an unexpected system error. The workflow run fails.

## Execution Pattern
Bias check tools execute via `freqtrade lookahead-analysis` and `freqtrade recursive-analysis`. Like other runner services, `BiasCheckRunner` delegates execution to a subprocess via `asyncio.to_thread` to avoid blocking the main event loop.
