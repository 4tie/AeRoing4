"""Backtest service module for business logic extracted from routers."""

from __future__ import annotations

import py_compile
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import RunRequest


def preflight_strategy(strategies_dir: str, strategy_name: str) -> list[str]:
    """Return a list of error strings if the strategy files are missing or invalid.

    Checks performed:
    1. The .py file exists inside strategies_dir.
    2. The .py file passes py_compile (syntax check).
    3. If a companion .json file exists, it is valid JSON.
    
    Args:
        strategies_dir: Path to the strategies directory
        strategy_name: Name of the strategy (without .py extension)
        
    Returns:
        List of error strings, empty if no errors
    """
    errors: list[str] = []
    base = Path(strategies_dir)

    py_path = base / f"{strategy_name}.py"
    if not py_path.exists():
        errors.append(
            f"Strategy file not found: '{strategy_name}.py' in {strategies_dir}"
        )
        return errors  # cannot syntax-check a missing file

    try:
        py_source = py_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        errors.append(f"Could not read strategy file: {exc}")
        return errors

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", encoding="utf-8", delete=False
    ) as tf:
        tf.write(py_source)
        tmp_path = Path(tf.name)
    try:
        py_compile.compile(str(tmp_path), doraise=True)
    except py_compile.PyCompileError as exc:
        msg = str(exc).replace(str(tmp_path), f"{strategy_name}.py")
        errors.append(f"Syntax error in strategy: {msg}")
    finally:
        tmp_path.unlink(missing_ok=True)

    json_path = base / f"{strategy_name}.json"
    if json_path.exists():
        import json as _json
        try:
            _json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            errors.append(f"Invalid JSON in '{strategy_name}.json': {exc}")

    return errors


def extract_freqtrade_error(run_dir: Path) -> str | None:
    """Return the last freqtrade ERROR line from logs.txt, or None if not found.
    
    Args:
        run_dir: Path to the backtest run directory
        
    Returns:
        Error message string or None if no error found
    """
    log_path = run_dir / "logs.txt"
    if not log_path.exists():
        return None
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    error_lines = [
        line for line in text.splitlines()
        if " - ERROR - " in line or "ERROR - " in line
    ]
    if not error_lines:
        return None
    last = error_lines[-1]
    # Strip the timestamp/logger prefix, keep just the message
    if " - ERROR - " in last:
        last = last.split(" - ERROR - ", 1)[-1].strip()
    return last or None
