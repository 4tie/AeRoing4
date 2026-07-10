"""Strategy validation service module for business logic extracted from routers."""

from __future__ import annotations

import py_compile
import re
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import ValidateRequest


def extract_class_name(content: str) -> str | None:
    """Extract the class name from Python strategy code.
    
    Args:
        content: Python source code content
        
    Returns:
        Class name if found, None otherwise
    """
    m = re.search(r"^class\s+(\w+)\s*[\(:]", content, re.MULTILINE)
    return m.group(1) if m else None


def run_py_validate(body: ValidateRequest, services: Any) -> dict:
    """Validate strategy syntax and run freqtrade test-strategy.
    
    Args:
        body: Validation request with filename and content
        services: AppServices instance for accessing settings
        
    Returns:
        Dictionary with validation results including valid status, errors, warnings, and output
    """
    errors: list[str] = []
    warnings: list[str] = []
    output_lines: list[str] = []

    settings = services.settings_store.load()
    strategies_dir = Path(settings.strategies_directory_path).resolve()
    freqtrade_exe = settings.freqtrade_executable_path
    user_data_dir = settings.user_data_directory_path

    # Step 1: py_compile syntax check
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", encoding="utf-8", delete=False
    ) as tf:
        tf.write(body.content)
        tmp_path = Path(tf.name)

    try:
        py_compile.compile(str(tmp_path), doraise=True)
        output_lines.append("✓ Python syntax OK")
    except py_compile.PyCompileError as exc:
        msg = str(exc).replace(str(tmp_path), body.filename)
        errors.append(msg)
        output_lines.append(f"✗ Syntax error: {msg}")
    finally:
        tmp_path.unlink(missing_ok=True)

    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings, "output": "\n".join(output_lines)}

    # Step 2: freqtrade test-strategy
    class_name = extract_class_name(body.content)
    if not class_name:
        warnings.append("Could not detect strategy class name — skipping Freqtrade check.")
        return {"valid": True, "errors": errors, "warnings": warnings, "output": "\n".join(output_lines)}

    temp_strat_name = f"_stratlab_validate_{class_name}"
    temp_strat_file = strategies_dir / f"{temp_strat_name}.py"
    patched = re.sub(
        r"(^class\s+)" + re.escape(class_name) + r"(\s*[\(:])",
        rf"\g<1>{temp_strat_name}\2",
        body.content, count=1, flags=re.MULTILINE,
    )

    try:
        temp_strat_file.write_text(patched, encoding="utf-8")
        proc = subprocess.run(
            [freqtrade_exe, "test-strategy", "--userdir", str(user_data_dir), "--strategy", temp_strat_name],
            capture_output=True, text=True, timeout=60,
            cwd=str(strategies_dir.parent.parent),
        )
        combined = (proc.stdout + proc.stderr).strip()
        output_lines += ["", "── Freqtrade test-strategy ──"] + (combined.splitlines() or ["(no output)"])
        if proc.returncode != 0:
            for line in combined.splitlines():
                if any(k in line.lower() for k in ("error", "exception", "traceback")):
                    errors.append(line.replace(temp_strat_name, class_name))
        else:
            output_lines += ["", "✓ Freqtrade structural validation passed"]
    except subprocess.TimeoutExpired:
        warnings.append("Freqtrade test-strategy timed out after 60 s.")
        output_lines.append("⚠ timed out.")
    except FileNotFoundError:
        warnings.append(f"freqtrade not found at '{freqtrade_exe}'.")
        output_lines.append("⚠ freqtrade not found — skipping structural check.")
    except Exception as exc:
        warnings.append(f"Freqtrade check failed: {exc}")
        output_lines.append(f"⚠ {exc}")
    finally:
        temp_strat_file.unlink(missing_ok=True)
        import sys as _sys
        pyc_ver = f"cpython-{_sys.version_info.major}{_sys.version_info.minor}"
        pyc = strategies_dir / "__pycache__" / f"{temp_strat_name}.{pyc_ver}.pyc"
        pyc.unlink(missing_ok=True)

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings, "output": "\n".join(output_lines)}
