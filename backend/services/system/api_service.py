"""System health API helper services."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


def check_freqtrade(executable: str) -> dict[str, Any]:
    """Run `freqtrade --version` and report the result."""
    resolved = shutil.which(executable) or executable
    entry: dict[str, Any] = {
        "check": "freqtrade_cli",
        "label": "Freqtrade CLI",
        "executable": resolved,
        "ok": False,
        "detail": "",
    }
    if not (shutil.which(executable) or Path(executable).is_file()):
        entry["detail"] = f"Executable not found: '{executable}'"
        return entry
    try:
        proc = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode == 0:
            version_line = (proc.stdout + proc.stderr).strip().splitlines()[0]
            entry["ok"] = True
            entry["detail"] = version_line
        else:
            entry["detail"] = (
                f"Exit code {proc.returncode}: "
                + (proc.stderr or proc.stdout).strip()[:200]
            )
    except FileNotFoundError:
        entry["detail"] = f"Executable not found at path '{executable}'"
    except subprocess.TimeoutExpired:
        entry["detail"] = "Timed out after 15 s"
    except Exception as exc:
        entry["detail"] = f"Unexpected error: {exc}"
    return entry


def check_directory(label: str, path: Path) -> dict[str, Any]:
    """Verify a directory exists and is writable."""
    entry: dict[str, Any] = {
        "check": "directory",
        "label": label,
        "path": str(path),
        "ok": False,
        "detail": "",
    }
    if not path.exists():
        entry["detail"] = "Does not exist"
        return entry
    if not path.is_dir():
        entry["detail"] = "Path exists but is not a directory"
        return entry
    try:
        with tempfile.NamedTemporaryFile(dir=path, delete=True):
            pass
        entry["ok"] = True
        entry["detail"] = "Exists and writable"
    except OSError as exc:
        entry["detail"] = f"Not writable: {exc}"
    return entry


def build_log(results: list[dict[str, Any]], elapsed_ms: int) -> str:
    """Render a terminal-style log string from check results."""
    lines = [
        "── Strategy Lab System Health Check ──────────────────────────────────",
        "",
    ]
    for result in results:
        icon = "✓" if result["ok"] else "✗"
        label = result["label"]
        detail = result.get("detail", "")
        path_or_exe = result.get("path") or result.get("executable") or ""
        if path_or_exe:
            lines.append(f"  {icon}  {label}  [{path_or_exe}]")
        else:
            lines.append(f"  {icon}  {label}")
        if detail:
            lines.append(f"       {detail}")
        lines.append("")
    overall = all(result["ok"] for result in results)
    status_word = "PASS" if overall else "FAIL"
    lines += [
        "──────────────────────────────────────────────────────────────────────",
        f"  Overall: {status_word}  (completed in {elapsed_ms} ms)",
        "──────────────────────────────────────────────────────────────────────",
    ]
    return "\n".join(lines)


async def collect_health(settings, root_dir: Path) -> dict[str, Any]:
    t_start = time.monotonic()
    checks: list[dict[str, Any]] = []

    checks.append(
        await asyncio.to_thread(check_freqtrade, settings.freqtrade_executable_path)
    )

    dir_checks = [
        ("data/", root_dir / "data"),
        ("data/backups/", root_dir / "data" / "backups"),
        ("user_data/strategies/", Path(settings.strategies_directory_path)),
        ("user_data/", Path(settings.user_data_directory_path)),
    ]
    for label, path in dir_checks:
        checks.append(await asyncio.to_thread(check_directory, label, path))

    elapsed_ms = round((time.monotonic() - t_start) * 1000)
    overall_ok = all(check["ok"] for check in checks)
    return {
        "ok": overall_ok,
        "elapsed_ms": elapsed_ms,
        "checks": checks,
        "log": build_log(checks, elapsed_ms),
    }
