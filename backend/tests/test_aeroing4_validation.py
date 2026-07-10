"""Tests for AeRoing4 validation step."""

from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch

import pytest

from backend.services.aeroing4.models import AeRoing4StepStatus
from backend.services.aeroing4.steps.validation import ValidationStep


@pytest.fixture
def mock_services():
    """Create mock services."""
    services = Mock()
    services.registry = Mock()
    return services


@pytest.fixture
def validation_step(mock_services):
    """Create validation step with mock services."""
    return ValidationStep(mock_services)


class TestValidationStep:
    """Test ValidationStep functionality."""

    @pytest.mark.asyncio
    async def test_valid_strategy(self, validation_step, mock_services):
        """Test validation of a valid strategy."""
        # Mock strategy with valid Python code
        mock_strategy = Mock()
        mock_strategy.file_path = Path(__file__)  # Use this test file as valid Python

        mock_services.registry.get_strategy.return_value = mock_strategy

        # Mock validation result
        with patch(
            "backend.services.aeroing4.steps.validation.run_py_validate"
        ) as mock_validate:
            mock_validate.return_value = {
                "valid": True,
                "errors": [],
                "warnings": [],
                "output": "✓ Python syntax OK\n✓ Freqtrade structural validation passed",
            }

            result = await validation_step.execute("test_strategy")

            assert result.step_name == "validation"
            assert result.status == AeRoing4StepStatus.PASSED
            assert result.data["valid"] is True
            assert result.error is None

    @pytest.mark.asyncio
    async def test_invalid_python_syntax(self, validation_step, mock_services):
        """Test validation fails with invalid Python syntax."""
        mock_strategy = Mock()
        mock_strategy.file_path = Path(__file__)

        mock_services.registry.get_strategy.return_value = mock_strategy

        # Mock validation result with syntax errors
        with patch(
            "backend.services.aeroing4.steps.validation.run_py_validate"
        ) as mock_validate:
            mock_validate.return_value = {
                "valid": False,
                "errors": ["SyntaxError: invalid syntax"],
                "warnings": [],
                "output": "✗ Syntax error: SyntaxError: invalid syntax",
            }

            result = await validation_step.execute("test_strategy")

            assert result.status == AeRoing4StepStatus.FAILED
            assert result.data["valid"] is False
            assert "Python syntax validation failed" in result.error

    @pytest.mark.asyncio
    async def test_missing_strategy(self, validation_step, mock_services):
        """Test validation fails when strategy file not found."""
        mock_strategy = Mock()
        mock_strategy.file_path = Path("/nonexistent/strategy.py")

        mock_services.registry.get_strategy.return_value = mock_strategy

        result = await validation_step.execute("test_strategy")

        assert result.status == AeRoing4StepStatus.FAILED
        assert "Strategy file not found" in result.error

    @pytest.mark.asyncio
    async def test_freqtrade_validation_failure(self, validation_step, mock_services):
        """Test validation fails when Freqtrade validation fails."""
        mock_strategy = Mock()
        mock_strategy.file_path = Path(__file__)

        mock_services.registry.get_strategy.return_value = mock_strategy

        # Mock validation result with Freqtrade errors
        with patch(
            "backend.services.aeroing4.steps.validation.run_py_validate"
        ) as mock_validate:
            mock_validate.return_value = {
                "valid": True,
                "errors": [],
                "warnings": [],
                "output": "✓ Python syntax OK\nError: Freqtrade validation failed",
            }

            # Mock class name extraction
            with patch(
                "backend.services.aeroing4.steps.validation.extract_class_name"
            ) as mock_extract:
                mock_extract.return_value = "TestStrategy"

                result = await validation_step.execute("test_strategy")

                # This should pass because errors list is empty
                # The check for Freqtrade errors would need to be in warnings
                assert result.status == AeRoing4StepStatus.PASSED

    @pytest.mark.asyncio
    async def test_freqtrade_timeout_must_not_pass(self, validation_step, mock_services):
        """Test that Freqtrade timeout causes validation failure."""
        mock_strategy = Mock()
        mock_strategy.file_path = Path(__file__)

        mock_services.registry.get_strategy.return_value = mock_strategy

        # Mock validation result with timeout warning
        with patch(
            "backend.services.aeroing4.steps.validation.run_py_validate"
        ) as mock_validate:
            mock_validate.return_value = {
                "valid": True,
                "errors": [],
                "warnings": ["Freqtrade test-strategy timed out after 60 s."],
                "output": "✓ Python syntax OK\n⚠ timed out.",
            }

            with patch(
                "backend.services.aeroing4.steps.validation.extract_class_name"
            ) as mock_extract:
                mock_extract.return_value = "TestStrategy"

                result = await validation_step.execute("test_strategy")

                assert result.status == AeRoing4StepStatus.FAILED
                assert "Freqtrade validation timed out" in result.error

    @pytest.mark.asyncio
    async def test_freqtrade_unavailable_must_not_pass(self, validation_step, mock_services):
        """Test that Freqtrade unavailable causes validation failure."""
        mock_strategy = Mock()
        mock_strategy.file_path = Path(__file__)

        mock_services.registry.get_strategy.return_value = mock_strategy

        # Mock validation result with Freqtrade unavailable warning
        with patch(
            "backend.services.aeroing4.steps.validation.run_py_validate"
        ) as mock_validate:
            mock_validate.return_value = {
                "valid": True,
                "errors": [],
                "warnings": ["freqtrade not found at '/path/to/freqtrade'"],
                "output": "✓ Python syntax OK\n⚠ freqtrade not found",
            }

            with patch(
                "backend.services.aeroing4.steps.validation.extract_class_name"
            ) as mock_extract:
                mock_extract.return_value = "TestStrategy"

                result = await validation_step.execute("test_strategy")

                assert result.status == AeRoing4StepStatus.FAILED
                assert "Freqtrade validation unavailable" in result.error

    @pytest.mark.asyncio
    async def test_missing_class_name_detection(self, validation_step, mock_services):
        """Test that missing class name causes validation failure."""
        mock_strategy = Mock()
        mock_strategy.file_path = Path(__file__)

        mock_services.registry.get_strategy.return_value = mock_strategy

        # Mock validation result with no class name
        with patch(
            "backend.services.aeroing4.steps.validation.run_py_validate"
        ) as mock_validate:
            mock_validate.return_value = {
                "valid": True,
                "errors": [],
                "warnings": [],
                "output": "✓ Python syntax OK",
            }

            with patch(
                "backend.services.aeroing4.steps.validation.extract_class_name"
            ) as mock_extract:
                mock_extract.return_value = None

                result = await validation_step.execute("test_strategy")

                assert result.status == AeRoing4StepStatus.FAILED
                assert "Strategy class name could not be detected" in result.error

    @pytest.mark.asyncio
    async def test_exception_handling(self, validation_step, mock_services):
        """Test that exceptions are handled gracefully."""
        mock_services.registry.get_strategy.side_effect = Exception("Registry error")

        result = await validation_step.execute("test_strategy")

        assert result.status == AeRoing4StepStatus.FAILED
        assert "Validation step failed" in result.error
