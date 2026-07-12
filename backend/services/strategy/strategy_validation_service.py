"""Strategy validation service module for business logic extracted from routers."""

from __future__ import annotations

import py_compile
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import ValidateRequest


def extract_class_name(content: str) -> str | None:
    """Extract the first Python class name from strategy source."""
    match = re.search(r"^class\s+(\w+)\s*[\(:]", content, re.MULTILINE)
    return match.group(1) if match else None


def _workspace_root_from_services(services: Any, strategies_dir: Path) -> Path:
    root = getattr(services, "root_dir", None)
    if root:
        return Path(root).resolve()
    return strategies_dir.parent.parent.resolve()


def _resolve_freqtrade_command(freqtrade_exe: str, workspace_root: Path) -> list[str]:
    configured = (freqtrade_exe or "").strip()
    if configured == "py -m freqtrade":
        for candidate in (
            workspace_root / "4t" / "Scripts" / "freqtrade.exe",
            workspace_root / ".venv" / "Scripts" / "freqtrade.exe",
        ):
            if candidate.is_file():
                return [str(candidate)]
        freqtrade = shutil.which("freqtrade")
        if freqtrade:
            return [freqtrade]
        if shutil.which("python"):
            return ["python", "-m", "freqtrade"]
        if shutil.which("py"):
            return ["py", "-m", "freqtrade"]
        return ["py", "-m", "freqtrade"]

    exe_path = Path(configured)
    if not exe_path.is_absolute():
        rooted = workspace_root / exe_path
        if rooted.is_file():
            return [str(rooted)]
    return [configured]


def _strategy_line_failed(line: str, strategy_name: str) -> bool:
    if strategy_name not in line:
        return False
    upper = line.upper()
    return "LOAD FAILED" in upper or "ERROR" in upper


def run_py_validate(body: ValidateRequest, services: Any) -> dict:
    """Validate strategy syntax and run a Freqtrade structural import check."""
    errors: list[str] = []
    warnings: list[str] = []
    output_lines: list[str] = []

    settings = services.settings_store.load()
    strategies_dir = Path(settings.strategies_directory_path).resolve()
    freqtrade_exe = settings.freqtrade_executable_path
    user_data_dir = settings.user_data_directory_path
    workspace_root = _workspace_root_from_services(services, strategies_dir)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", encoding="utf-8", delete=False
    ) as temp_file:
        temp_file.write(body.content)
        tmp_path = Path(temp_file.name)

    try:
        py_compile.compile(str(tmp_path), doraise=True)
        output_lines.append("Python syntax OK")
    except py_compile.PyCompileError as exc:
        message = str(exc).replace(str(tmp_path), body.filename)
        errors.append(message)
        output_lines.append(f"Syntax error: {message}")
    finally:
        tmp_path.unlink(missing_ok=True)

    if errors:
        return {
            "valid": False,
            "errors": errors,
            "warnings": warnings,
            "output": "\n".join(output_lines),
        }

    class_name = extract_class_name(body.content)
    if not class_name:
        warnings.append("Could not detect strategy class name - skipping Freqtrade check.")
        return {
            "valid": True,
            "errors": errors,
            "warnings": warnings,
            "output": "\n".join(output_lines),
        }

    temp_strat_name = f"_stratlab_validate_{class_name}"
    temp_strat_file = strategies_dir / f"{temp_strat_name}.py"
    patched = re.sub(
        r"(^class\s+)" + re.escape(class_name) + r"(\s*[\(:])",
        rf"\g<1>{temp_strat_name}\2",
        body.content,
        count=1,
        flags=re.MULTILINE,
    )

    try:
        temp_strat_file.write_text(patched, encoding="utf-8")
        command = [
            *_resolve_freqtrade_command(freqtrade_exe, workspace_root),
            "list-strategies",
            "--user-data-dir",
            str(user_data_dir),
            "--strategy-path",
            str(strategies_dir),
        ]
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(workspace_root),
        )
        combined = (proc.stdout + proc.stderr).strip()
        lines = combined.splitlines()
        output_lines += [
            "",
            "Freqtrade list-strategies",
            f"Command: {subprocess.list2cmdline(command)}",
            *(lines or ["(no output)"]),
        ]

        if proc.returncode != 0:
            for line in lines:
                if any(token in line.lower() for token in ("error", "exception", "traceback")):
                    errors.append(line.replace(temp_strat_name, class_name))
            if not errors:
                errors.append(
                    f"Freqtrade structural validation failed with exit code {proc.returncode}."
                )
        elif not any(temp_strat_name in line for line in lines):
            errors.append("Freqtrade structural validation did not list the strategy.")
        elif any(_strategy_line_failed(line, temp_strat_name) for line in lines):
            errors.append("Freqtrade structural validation failed to load the strategy.")
        else:
            output_lines += ["", "Freqtrade structural validation passed"]
    except subprocess.TimeoutExpired:
        warnings.append("Freqtrade list-strategies timed out after 60 s.")
        output_lines.append("timed out.")
    except FileNotFoundError:
        warnings.append(f"freqtrade not found at '{freqtrade_exe}'.")
        output_lines.append("freqtrade not found - skipping structural check.")
    except Exception as exc:
        warnings.append(f"Freqtrade check failed: {exc}")
        output_lines.append(str(exc))
    finally:
        temp_strat_file.unlink(missing_ok=True)
        import sys as _sys

        pyc_ver = f"cpython-{_sys.version_info.major}{_sys.version_info.minor}"
        pyc = strategies_dir / "__pycache__" / f"{temp_strat_name}.{pyc_ver}.pyc"
        pyc.unlink(missing_ok=True)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "output": "\n".join(output_lines),
    }
