"""Bias check step for AeRoing4."""

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

from ....core.errors import BackendError
from ..models import (
    StepResult,
    BiasCheckResult,
    BiasCheckOutcome,
    BiasCheckItemResult,
    AeRoing4StepStatus,
)
from ...execution.bias_check_runner import BiasCheckCommandConfig
from ...storage.bias_parser import BiasParser

if TYPE_CHECKING:
    from ...app_services import AppServices


class BiasCheckStep:
    """Bias check step.

    Runs lookahead and recursive analysis checks against the strategy.
    Classifies outcome based on policy version.
    """

    def __init__(self, services: "AppServices"):
        """Initialize bias check step with services."""
        self.services = services

    async def execute(
        self,
        strategy_name: str,
        pairs: list[str],
        timeframe: str,
        timerange: str,
        policy_version: str = "1.0.0"
    ) -> StepResult:
        """Execute the bias check.

        Args:
            strategy_name: Name of the strategy
            pairs: List of pairs to test
            timeframe: Timeframe to test
            timerange: Timerange to test
            policy_version: Version of the bias check policy

        Returns:
            StepResult containing BiasCheckResult
        """
        started_at = datetime.now(UTC)
        
        # Identity hash preparation could be more robust, simple concat for now
        input_identity = f"{strategy_name}_{timeframe}_{timerange}_{','.join(sorted(pairs))}_{policy_version}"

        result_model = BiasCheckResult(
            outcome=BiasCheckOutcome.EXECUTION_FAILURE,
            started_at=started_at,
            policy_version=policy_version,
            input_identity=input_identity,
            timerange=timerange,
            pairs=pairs,
            checks_requested=["lookahead", "recursive"]
        )

        try:
            # We must use asyncio.to_thread because the runner is synchronous
            runner = self.services.execution_services.bias_check_runner
            
            # --- 1. Lookahead Analysis ---
            lookahead_config = BiasCheckCommandConfig(
                strategy_name=strategy_name,
                timeframe=timeframe,
                pairs=pairs,
                timerange=timerange,
                export_filename=None # If we want to use stdout parser primarily, or specify a temp csv
            )
            
            # Execute Lookahead
            lookahead_raw = await asyncio.to_thread(
                runner.run_lookahead_analysis, lookahead_config
            )
            result_model.checks_executed.append("lookahead")
            result_model.command_records.append(lookahead_raw.command)
            
            lookahead_item = BiasCheckItemResult(
                check_type="lookahead",
                execution_status="success" if lookahead_raw.success else "failure",
                analytical_status="",
                decision_code="",
                command=lookahead_raw.command,
                exit_code=lookahead_raw.exit_code,
                duration_seconds=lookahead_raw.duration_seconds
            )

            if lookahead_raw.success:
                parsed_lookahead = BiasParser.parse_lookahead_stdout(lookahead_raw.stdout)
                if parsed_lookahead["status"] == "success":
                    if parsed_lookahead["has_bias"]:
                        lookahead_item.analytical_status = "bias_detected"
                        lookahead_item.decision_code = "FAIL_LOOKAHEAD"
                        lookahead_item.failures.append(parsed_lookahead["message"])
                    else:
                        lookahead_item.analytical_status = "clean"
                        lookahead_item.decision_code = "PASS"
                else:
                    lookahead_item.analytical_status = "parse_failure"
                    lookahead_item.decision_code = "EXECUTION_FAILURE"
                    lookahead_item.failures.append(parsed_lookahead["message"])
            else:
                lookahead_item.analytical_status = "execution_failure"
                lookahead_item.decision_code = "EXECUTION_FAILURE"
                lookahead_item.failures.append(lookahead_raw.stderr)
                if lookahead_raw.timeout:
                    lookahead_item.warnings.append("Lookahead analysis timed out")

            result_model.lookahead_result = lookahead_item
            
            # --- 2. Recursive Analysis ---
            recursive_config = BiasCheckCommandConfig(
                strategy_name=strategy_name,
                timeframe=timeframe,
                pairs=pairs,
                timerange=timerange
            )
            
            # Execute Recursive
            recursive_raw = await asyncio.to_thread(
                runner.run_recursive_analysis, recursive_config
            )
            result_model.checks_executed.append("recursive")
            result_model.command_records.append(recursive_raw.command)

            recursive_item = BiasCheckItemResult(
                check_type="recursive",
                execution_status="success" if recursive_raw.success else "failure",
                analytical_status="",
                decision_code="",
                command=recursive_raw.command,
                exit_code=recursive_raw.exit_code,
                duration_seconds=recursive_raw.duration_seconds
            )

            if recursive_raw.success:
                parsed_recursive = BiasParser.parse_recursive_stdout(recursive_raw.stdout)
                if parsed_recursive["status"] == "success":
                    if parsed_recursive["has_bias"]:
                        recursive_item.analytical_status = "bias_detected"
                        recursive_item.decision_code = "FAIL_RECURSIVE_BIAS"
                        recursive_item.failures.append(parsed_recursive["message"])
                    else:
                        recursive_item.analytical_status = "clean"
                        recursive_item.decision_code = "PASS"
                else:
                    recursive_item.analytical_status = "parse_failure"
                    recursive_item.decision_code = "EXECUTION_FAILURE"
                    recursive_item.failures.append(parsed_recursive["message"])
            else:
                recursive_item.analytical_status = "execution_failure"
                recursive_item.decision_code = "EXECUTION_FAILURE"
                recursive_item.failures.append(recursive_raw.stderr)
                if recursive_raw.timeout:
                    recursive_item.warnings.append("Recursive analysis timed out")

            result_model.recursive_result = recursive_item
            
            # --- Combine Results & Policy Enforcement ---
            
            # Fatal bias
            if lookahead_item.decision_code == "FAIL_LOOKAHEAD":
                result_model.outcome = BiasCheckOutcome.FAIL_LOOKAHEAD
                result_model.failures.extend(lookahead_item.failures)
            elif recursive_item.decision_code == "FAIL_RECURSIVE_BIAS":
                result_model.outcome = BiasCheckOutcome.FAIL_RECURSIVE_BIAS
                result_model.failures.extend(recursive_item.failures)
            # Execution failure
            elif lookahead_item.decision_code == "EXECUTION_FAILURE" or recursive_item.decision_code == "EXECUTION_FAILURE":
                result_model.outcome = BiasCheckOutcome.EXECUTION_FAILURE
                if lookahead_item.decision_code == "EXECUTION_FAILURE":
                    result_model.execution_errors.extend(lookahead_item.failures)
                if recursive_item.decision_code == "EXECUTION_FAILURE":
                    result_model.execution_errors.extend(recursive_item.failures)
            # Pass
            else:
                if lookahead_item.warnings or recursive_item.warnings:
                    result_model.outcome = BiasCheckOutcome.PASS_WITH_WARNING
                    result_model.warnings.extend(lookahead_item.warnings)
                    result_model.warnings.extend(recursive_item.warnings)
                else:
                    result_model.outcome = BiasCheckOutcome.PASS
                    
            result_model.completed_at = datetime.now(UTC)
            result_model.duration_seconds = (result_model.completed_at - result_model.started_at).total_seconds()

            status = AeRoing4StepStatus.FAILED
            if result_model.outcome in [BiasCheckOutcome.PASS, BiasCheckOutcome.PASS_WITH_WARNING]:
                status = AeRoing4StepStatus.PASSED

            return StepResult(
                step_name="bias_check",
                status=status,
                started_at=started_at,
                completed_at=result_model.completed_at,
                data=result_model.model_dump(mode="json"),
                error="Bias execution failure" if result_model.outcome == BiasCheckOutcome.EXECUTION_FAILURE else None
            )

        except Exception as e:
            result_model.outcome = BiasCheckOutcome.EXECUTION_FAILURE
            result_model.execution_errors.append(str(e))
            result_model.completed_at = datetime.now(UTC)
            result_model.duration_seconds = (result_model.completed_at - result_model.started_at).total_seconds()
            
            return StepResult(
                step_name="bias_check",
                status=AeRoing4StepStatus.FAILED,
                started_at=started_at,
                completed_at=result_model.completed_at,
                data=result_model.model_dump(mode="json"),
                error=f"Bias check step failed: {str(e)}"
            )
