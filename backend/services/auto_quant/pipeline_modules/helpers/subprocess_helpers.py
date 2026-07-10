"""Subprocess execution and error classification helpers."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from ..logging import _rlog, get_queues, logger
from ..state import PipelineState, _Cancelled, _cancelled

# Regex to parse freqtrade hyperopt epoch lines, e.g.:
#   42/100:    100 trades. ... Total profit  0.279 USDT ( 0.28%). ... Objective: -0.283.
_HYPEROPT_EPOCH_RE = re.compile(
    r"^\s*(\d+)/(\d+):\s+(\d+)\s+trades.*?Objective:\s*([-\d.]+)",
    re.IGNORECASE,
)
_HYPEROPT_PROFIT_RE = re.compile(
    r"Total profit\s+([-\d.]+)",
    re.IGNORECASE,
)
_HYPEROPT_AVG_PROFIT_RE = re.compile(
    r"Avg profit\s+([-\d.]+)%",
    re.IGNORECASE,
)
_HYPEROPT_DRAWDOWN_RE = re.compile(
    r"Max drawdown\s+([-\d.]+)%",
    re.IGNORECASE,
)
_HYPEROPT_WIN_RATE_RE = re.compile(
    r"Win rate\s+([-\d.]+)%",
    re.IGNORECASE,
)


async def _run_subprocess(
    run_id: str,
    cmd: list[str],
    *,
    stage: int,
    stream: bool = False,
    timeout: int | None = None,
) -> tuple[int, str, str]:
    """Run a subprocess, optionally streaming stdout to the WS queue.

    Every spawn and exit is logged at DEBUG level.  Lines that match
    ``_should_forward`` (errors, warnings, key metrics) are also emitted to
    the WebSocket queue even in non-stream mode.

    Args:
        timeout: Optional timeout in seconds. If provided, the subprocess will
                 be killed if it doesn't complete within the timeout.
    """
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    _rlog(run_id, stage, logging.DEBUG,
          f"[subprocess] SPAWN pid=pending  cmd={cmd[0]} {' '.join(cmd[1:4])}{'…' if len(cmd) > 4 else ''}")

    # Set JOBLIB_IDLE_WORKER_TIMEOUT for Stage 2 (hyperopt) to prevent worker timeout warnings
    env = None
    if stage == 2:
        import os
        from pathlib import Path
        env = os.environ.copy()
        env["JOBLIB_IDLE_WORKER_TIMEOUT"] = "1800"  # 30 minutes instead of default 5 minutes
        # Set temp folder to prevent conflicts and potential memory issues
        temp_dir = Path(os.environ.get("USERPROFILE", os.environ.get("HOME", "/tmp"))) / ".freqtrade_joblib_temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        env["JOBLIB_TEMP_FOLDER"] = str(temp_dir)
        # Additional joblib settings to prevent worker issues
        env["JOBLIB_START_METHOD"] = "loky"
        # Suppress the specific joblib/loky worker timeout warning in the subprocess
        env["PYTHONWARNINGS"] = "ignore::UserWarning"

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge stderr into stdout
            env=env,
        )
    except Exception as exc:
        _rlog(run_id, stage, logging.ERROR,
              f"[subprocess] FAILED to spawn: {exc}", exc_info=True)
        raise

    _rlog(run_id, stage, logging.DEBUG, f"[subprocess] pid={proc.pid}  running…")

    assert proc.stdout is not None
    while True:
        if _cancelled(run_id):
            _rlog(run_id, stage, logging.WARNING,
                  f"[subprocess] pid={proc.pid} — cancellation requested, sending SIGKILL")
            proc.kill()
            await proc.wait()
            raise _Cancelled()

        try:
            line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=2.0)
        except asyncio.TimeoutError:
            if proc.returncode is not None:
                break
            continue

        if not line_bytes:
            break

        line = line_bytes.decode(errors="replace").rstrip()
        # Filter out joblib/loky worker timeout warnings - comprehensive filtering
        if "worker stopped while some jobs were given to the executor" in line:
            continue
        if "warnings.warn(" in line and "process_executor.py:782" in line:
            continue
        if "process_executor.py:782" in line:
            continue
        if "joblib/externals/loky/process_executor.py" in line:
            continue
        if ".venv/lib/python3.12/site-packages/joblib/externals/loky" in line:
            continue
        if "site-packages/joblib/externals/loky" in line:
            continue
        # Filter any line containing joblib/externals/loky
        if "joblib/externals/loky" in line:
            continue
        # Filter any line containing loky/process_executor
        if "loky/process_executor" in line:
            continue
        stdout_lines.append(line)
        if stream or _should_forward(line):
            from .validation_helpers import _emit
            _emit(run_id, stage, "running", line, -1)
            _rlog(run_id, stage, logging.DEBUG, f"[subprocess][pid={proc.pid}] {line}")

        # ── Hyperopt epoch telemetry (Stage 2 only) ────────────────────────
        if stage == 2:
            m = _HYPEROPT_EPOCH_RE.match(line)
            if m:
                epoch_num = int(m.group(1))
                total_epochs = int(m.group(2))
                trade_count = int(m.group(3))
                objective = float(m.group(4))
                profit_m = _HYPEROPT_PROFIT_RE.search(line)
                profit_usdt = float(profit_m.group(1)) if profit_m else 0.0
                avg_profit_m = _HYPEROPT_AVG_PROFIT_RE.search(line)
                avg_profit_pct = float(avg_profit_m.group(1)) if avg_profit_m else 0.0
                # Extract additional metrics if available
                drawdown_m = _HYPEROPT_DRAWDOWN_RE.search(line)
                drawdown_pct = float(drawdown_m.group(1)) if drawdown_m else None
                win_rate_m = _HYPEROPT_WIN_RATE_RE.search(line)
                win_rate_pct = float(win_rate_m.group(1)) if win_rate_m else None
                from .validation_helpers import _emit
                point = {
                    "epoch": epoch_num,
                    "total_epochs": total_epochs,
                    "trades": trade_count,
                    "profit_usdt": profit_usdt,
                    "avg_profit_pct": avg_profit_pct,
                    "objective": objective,
                    "drawdown_pct": drawdown_pct,
                    "win_rate_pct": win_rate_pct,
                }
                _emit(
                    run_id, stage, "running",
                    f"Epoch {epoch_num}/{total_epochs}: {trade_count} trades, "
                    f"profit {profit_usdt:.4f} USDT, objective {objective:.4f}",
                    -1,
                    point,
                    msg_type="hyperopt_epoch",
                )
                # Frontend live fitness curve / progress badge listen for these
                # specific message shapes — keep in sync with
                # useAutoQuantPipeline.js's handleWsMessage.
                _emit(
                    run_id, stage, "running", "", -1,
                    msg_type="fitness_point",
                    extra={"point": point},
                )
                _emit(
                    run_id, stage, "running", "", -1,
                    msg_type="hyperopt_progress",
                    extra={"progress": {"current": epoch_num, "total": total_epochs}},
                )

    # Wait for process to complete, with optional timeout
    if timeout is not None:
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            _rlog(run_id, stage, logging.WARNING,
                  f"[subprocess] pid={proc.pid} — timeout after {timeout}s, killing process")
            proc.kill()
            await proc.wait()
            raise
    else:
        await proc.wait()

    rc = proc.returncode or 0
    _rlog(run_id, stage, logging.INFO if rc == 0 else logging.ERROR,
          f"[subprocess] pid={proc.pid} exited rc={rc}  lines_captured={len(stdout_lines)}")
    return rc, "\n".join(stdout_lines), "\n".join(stderr_lines)


def _should_forward(line: str) -> bool:
    """Forward important lines even when not in stream mode."""
    keywords = ("ERROR", "WARNING", "error", "warning", "Epoch", "epoch",
                 "best", "loss", "profit", "trade", "Trade", "Backtesting")
    return any(k in line for k in keywords)


def _classify_subprocess_error(rc: int, stdout: str, stage_label: str) -> str:
    """Return an actionable error message by inspecting subprocess output.

    Freqtrade exits with rc=2 in several distinct situations that all look the
    same to the caller.  This function pattern-matches the captured stdout to
    surface the *real* root cause instead of the generic "may not compile"
    message.
    """
    text = stdout.lower()

    # ── Missing / not-downloaded data ─────────────────────────────────────
    if "no data found" in text or "no history for" in text:
        # Count how many pairs are missing so the message is precise
        missing = [
            line for line in stdout.splitlines()
            if "no history for" in line.lower() or "no data found" in line.lower()
        ]
        pairs_hint = ""
        if missing:
            # Extract the first few pair names from lines like
            # "No history for BTC/USDT, spot, 5m found."
            found_pairs = re.findall(r"No history for ([A-Z]+/[A-Z]+)", stdout)
            if found_pairs:
                sample = ", ".join(found_pairs[:5])
                suffix = f" (+{len(found_pairs)-5} more)" if len(found_pairs) > 5 else ""
                pairs_hint = f" Missing pairs: {sample}{suffix}."
        return (
            f"{stage_label} failed — no market data found for the configured "
            f"timeframe/timerange.{pairs_hint} "
            f"Run `freqtrade download-data --config <config> --timerange <range> "
            f"--timeframe <tf>` to download OHLCV data before running the pipeline."
        )

    # ── Strategy import / class-not-found errors ──────────────────────────
    if "importerror" in text or "modulenotfounderror" in text or "no module named" in text:
        return (
            f"{stage_label} failed (exit {rc}) — strategy file has an import error. "
            f"Check that all strategy dependencies are installed."
        )

    # ── Strategy compilation errors ───────────────────────────────────────
    if "syntaxerror" in text or "indentationerror" in text:
        return (
            f"{stage_label} failed (exit {rc}) — strategy file has a syntax error. "
            f"Check the strategy file for typos or indentation issues."
        )

    # ── Strategy class not found ─────────────────────────────────────────
    if "strategy not found" in text or "no strategy" in text:
        return (
            f"{stage_label} failed (exit {rc}) — strategy class not found. "
            f"Ensure the strategy file contains a class that inherits from IStrategy."
        )

    # ── Config file errors ───────────────────────────────────────────────
    if "config" in text and "error" in text:
        return (
            f"{stage_label} failed (exit {rc}) — configuration file error. "
            f"Check the freqtrade config file for syntax errors or missing required fields."
        )

    # ── Permission errors ─────────────────────────────────────────────────
    if "permission" in text:
        return (
            f"{stage_label} failed (exit {rc}) — permission denied. "
            f"Check file permissions for the strategy file and data directories."
        )

    # ── Generic fallback ─────────────────────────────────────────────────
    return (
        f"{stage_label} failed (exit {rc}). "
        f"Check the logs for details."
    )
