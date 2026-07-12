"""Unit tests for strategy validation service module."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
from pydantic import BaseModel, Field

from backend.services.strategy.strategy_validation_service import extract_class_name, run_py_validate


# Mock ValidateRequest since it's defined in the router, not models
class ValidateRequest(BaseModel):
    filename: str = Field(..., description="Strategy filename (e.g. MultiMa_v3.py)")
    content: str = Field(..., description="Current editor content to validate")


def _workspace_tempdir():
    repo_root = Path(__file__).resolve().parents[2]
    return tempfile.TemporaryDirectory(dir=repo_root)


def test_extract_class_name_valid():
    """Test extract_class_name with valid class definition."""
    code = """
class MyStrategy:
    def __init__(self):
        pass
"""
    result = extract_class_name(code)
    assert result == "MyStrategy"


def test_extract_class_name_with_inheritance():
    """Test extract_class_name with class inheritance."""
    code = """
class MyStrategy(IStrategy):
    def __init__(self):
        pass
"""
    result = extract_class_name(code)
    assert result == "MyStrategy"


def test_extract_class_name_no_class():
    """Test extract_class_name with no class definition."""
    code = """
def some_function():
    pass
"""
    result = extract_class_name(code)
    assert result is None


def test_extract_class_name_multiple_classes():
    """Test extract_class_name returns first class."""
    code = """
class FirstClass:
    pass

class SecondClass:
    pass
"""
    result = extract_class_name(code)
    assert result == "FirstClass"




def test_run_py_validate_syntax_error():
    """Test run_py_validate with Python syntax error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        class MockSettingsStore:
            def load(self):
                class Settings:
                    strategies_directory_path = tmpdir
                    freqtrade_executable_path = "freqtrade"
                    user_data_directory_path = tmpdir
                return Settings()
        
        class MockServices:
            settings_store = MockSettingsStore()
        
        body = ValidateRequest(filename="TestStrategy.py", content="def broken(\n")
        result = run_py_validate(body, MockServices())
        
        assert result["valid"] is False
        assert len(result["errors"]) == 1
        assert "Syntax error" in result["output"]


def test_run_py_validate_valid_python_no_class():
    """Test run_py_validate with valid Python but no class."""
    with tempfile.TemporaryDirectory() as tmpdir:
        class MockSettingsStore:
            def load(self):
                class Settings:
                    strategies_directory_path = tmpdir
                    freqtrade_executable_path = "freqtrade"
                    user_data_directory_path = tmpdir
                return Settings()
        
        class MockServices:
            settings_store = MockSettingsStore()
        
        body = ValidateRequest(filename="TestStrategy.py", content="def some_function():\n    pass\n")
        result = run_py_validate(body, MockServices())
        
        assert result["valid"] is True
        assert len(result["warnings"]) == 1
        assert "Could not detect strategy class name" in result["warnings"][0]


def test_run_py_validate_valid_python_with_class():
    """Test run_py_validate with valid Python and class."""
    with tempfile.TemporaryDirectory() as tmpdir:
        class MockSettingsStore:
            def load(self):
                class Settings:
                    strategies_directory_path = tmpdir
                    freqtrade_executable_path = "missing-freqtrade-for-test"
                    user_data_directory_path = tmpdir
                return Settings()
        
        class MockServices:
            settings_store = MockSettingsStore()
        
        body = ValidateRequest(
            filename="TestStrategy.py",
            content="class TestStrategy:\n    pass\n"
        )
        result = run_py_validate(body, MockServices())
        
        # Should pass syntax check but skip freqtrade check if freqtrade not available
        assert result["valid"] is True
        assert "Python syntax OK" in result["output"]


def test_run_py_validate_py_m_freqtrade_uses_local_executable():
    """Default py -m freqtrade should fall back to the local workspace executable."""
    with _workspace_tempdir() as tmpdir:
        workspace = Path(tmpdir)
        strategies_dir = workspace / "user_data" / "strategies"
        user_data_dir = workspace / "user_data"
        freqtrade_exe = workspace / "4t" / "Scripts" / "freqtrade.exe"
        strategies_dir.mkdir(parents=True)
        freqtrade_exe.parent.mkdir(parents=True)
        freqtrade_exe.write_text("", encoding="utf-8")

        class MockSettingsStore:
            def load(self):
                class Settings:
                    strategies_directory_path = str(strategies_dir)
                    freqtrade_executable_path = "py -m freqtrade"
                    user_data_directory_path = str(user_data_dir)

                return Settings()

        class MockServices:
            root_dir = workspace
            settings_store = MockSettingsStore()

        body = ValidateRequest(
            filename="TestStrategy.py",
            content="class TestStrategy:\n    pass\n",
        )

        listed = "| _stratlab_validate_TestStrategy | _stratlab_validate_TestStrategy.py | OK |"
        with (
            patch(
                "backend.services.strategy.strategy_validation_service.subprocess.run"
            ) as run,
            patch(
                "backend.services.strategy.strategy_validation_service.shutil.which",
                side_effect=lambda name: "C:\\Windows\\py.exe" if name == "py" else None,
            ),
        ):
            run.return_value = SimpleNamespace(returncode=0, stdout=listed, stderr="")
            result = run_py_validate(body, MockServices())

        command = run.call_args.args[0]
        assert result["valid"] is True
        assert command[0] == str(freqtrade_exe)
        assert command[1] == "list-strategies"
        assert "test-strategy" not in command
        assert "--user-data-dir" in command
