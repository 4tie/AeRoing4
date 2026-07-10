"""Strict strategy validation step for AeRoing4."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from pydantic import BaseModel

from backend.services.strategy.strategy_validation_service import (
    extract_class_name,
    run_py_validate,
)
from ..models import StepResult, ValidationResult, AeRoing4StepStatus

if TYPE_CHECKING:
    from ...app_services import AppServices


class ValidateRequest(BaseModel):
    """Request model for strategy validation."""
    filename: str
    content: str


class ValidationStep:
    """Strict strategy validation step.

    Reuses existing strategy validation logic but applies stricter
    decision rules. Only passes when:
    - Python syntax validation succeeds
    - Strategy class is detected
    - Freqtrade structural validation executes successfully
    - Freqtrade exits successfully
    """

    def __init__(self, services: "AppServices"):
        """Initialize validation step with services."""
        self.services = services

    async def execute(
        self,
        strategy_name: str,
    ) -> StepResult:
        """Execute strict validation step.

        Args:
            strategy_name: Name of the strategy to validate

        Returns:
            StepResult with validation outcome
        """
        started_at = datetime.now(UTC)

        try:
            # Get strategy file content
            strategy = self.services.registry.get_strategy(strategy_name)
            strategy_file = Path(strategy.file_path)

            if not strategy_file.exists():
                return StepResult(
                    step_name="validation",
                    status=AeRoing4StepStatus.FAILED,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    error=f"Strategy file not found: {strategy_file}",
                    data={"valid": False, "errors": ["Strategy file not found"]},
                )

            content = strategy_file.read_text(encoding="utf-8")

            # Create validation request
            validate_request = ValidateRequest(
                filename=strategy_file.name,
                content=content,
            )

            # Run validation (this is synchronous, wrap in thread)
            validation_result = await asyncio.to_thread(
                run_py_validate, validate_request, self.services
            )

            # Apply strict decision rules
            errors = validation_result.get("errors", [])
            warnings = validation_result.get("warnings", [])
            output = validation_result.get("output", "")

            # Check for strict failure conditions
            # 1. Python syntax errors
            if errors:
                return StepResult(
                    step_name="validation",
                    status=AeRoing4StepStatus.FAILED,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    error=f"Python syntax validation failed: {'; '.join(errors)}",
                    data={
                        "valid": False,
                        "errors": errors,
                        "warnings": warnings,
                        "output_summary": output,
                    },
                )

            # 2. Freqtrade unavailable or skipped
            freqtrade_warnings = [
                w for w in warnings
                if "freqtrade not found" in w.lower() or "skipping" in w.lower()
            ]
            if freqtrade_warnings:
                return StepResult(
                    step_name="validation",
                    status=AeRoing4StepStatus.FAILED,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    error=f"Freqtrade validation unavailable: {'; '.join(freqtrade_warnings)}",
                    data={
                        "valid": False,
                        "errors": ["Freqtrade validation unavailable"],
                        "warnings": warnings,
                        "output_summary": output,
                    },
                )

            # 3. Freqtrade timeout
            timeout_warnings = [w for w in warnings if "timed out" in w.lower()]
            if timeout_warnings:
                return StepResult(
                    step_name="validation",
                    status=AeRoing4StepStatus.FAILED,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    error=f"Freqtrade validation timed out: {'; '.join(timeout_warnings)}",
                    data={
                        "valid": False,
                        "errors": ["Freqtrade validation timed out"],
                        "warnings": warnings,
                        "output_summary": output,
                    },
                )

            # 4. Extract class name and verify detection
            class_name = extract_class_name(content)
            if not class_name:
                return StepResult(
                    step_name="validation",
                    status=AeRoing4StepStatus.FAILED,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    error="Strategy class name could not be detected",
                    data={
                        "valid": False,
                        "errors": ["Strategy class name not detected"],
                        "warnings": warnings,
                        "output_summary": output,
                    },
                )

            # All strict checks passed
            return StepResult(
                step_name="validation",
                status=AeRoing4StepStatus.PASSED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                data={
                    "valid": True,
                    "class_name": class_name,
                    "errors": [],
                    "warnings": warnings,
                    "output_summary": output,
                },
            )

        except Exception as exc:
            return StepResult(
                step_name="validation",
                status=AeRoing4StepStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error=f"Validation step failed: {str(exc)}",
                data={
                    "valid": False,
                    "errors": [str(exc)],
                    "warnings": [],
                    "output_summary": "",
                },
            )
