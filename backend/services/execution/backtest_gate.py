"""Backtest gate — validates strategy viability through controlled backtest."""

from __future__ import annotations

import json
import subprocess
import zipfile
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from ...models.base import RunType, RunStatus
from ...models.runs import RunMetadata
from ...utils import utc_now
from .data_quality_gate import check_data_quality
from ..storage.result_parser import ResultParser

GATE_THRESHOLDS: dict[str, Any] = {
    "min_trades": 10,
    "min_win_rate_pct": 40.0,
    "min_profit_factor": 1.05,
    "max_drawdown_pct": 30.0,
    "positive_expectancy": True,
    "min_sharpe_ratio": 0.5,
}


@dataclass
class BacktestGateResult:
    gate_status: Literal["passed", "failed", "data_quality_failed", "backtest_failed"]
    run_id: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict | None = None


def _build_gate_command(
    executable: str,
    user_data_dir: str,
    config_file: str,
    strategy_name: str,
    run_dir: Path,
    timerange: str,
    timeframe: str,
    pairs: list[str],
    max_open_trades: int,
    dry_run_wallet: float,
) -> list[str]:
    # Handle "py -m freqtrade" command by splitting it
    if executable == "py -m freqtrade":
        command = [
            "py", "-m", "freqtrade", "backtesting", "--user-data-dir", user_data_dir,
            "--config", config_file, "--strategy-path", str(run_dir),
            "--strategy", strategy_name, "--timerange", timerange,
            "--timeframe", timeframe,
            "--dry-run-wallet", str(dry_run_wallet),
            "--max-open-trades", str(max_open_trades),
            "--export", "trades", "--backtest-directory", str(run_dir),
        ]
    else:
        command = [
            executable, "backtesting", "--user-data-dir", user_data_dir,
            "--config", config_file, "--strategy-path", str(run_dir),
            "--strategy", strategy_name, "--timerange", timerange,
            "--timeframe", timeframe,
            "--dry-run-wallet", str(dry_run_wallet),
            "--max-open-trades", str(max_open_trades),
            "--export", "trades", "--backtest-directory", str(run_dir),
        ]
    if pairs:
        unique_pairs = list(dict.fromkeys(pairs))
        command.extend(["--pairs", *unique_pairs])
    return command


def _resolve_config_file(config_file: str, user_data_dir: str) -> str:
    """Resolve candidate config paths relative to the configured user_data dir."""
    config_path = Path(config_file)
    if config_path.is_absolute() or config_path.exists():
        return str(config_path)

    user_data_config = Path(user_data_dir) / config_path
    if user_data_config.exists():
        return str(user_data_config)

    return str(config_path)


def _load_config_payload(config_file: str) -> dict[str, Any]:
    config_path = Path(config_file)
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_pairs_for_config(pairs: list[str], config: dict[str, Any]) -> list[str]:
    cleaned = [str(pair or "").strip() for pair in pairs if str(pair or "").strip()]
    if config.get("trading_mode") != "futures":
        return list(dict.fromkeys(cleaned))

    normalized: list[str] = []
    for pair in cleaned:
        if ":" in pair:
            normalized.append(pair)
            continue
        base_quote = pair.split("/", maxsplit=1)
        if len(base_quote) == 2 and base_quote[1]:
            normalized.append(f"{pair}:{base_quote[1]}")
        else:
            normalized.append(pair)
    return list(dict.fromkeys(normalized))


def _write_pair_config_snapshot(
    *,
    run_dir: Path,
    config_payload: dict[str, Any],
    effective_pairs: list[str],
) -> str | None:
    """Write a gate-local config when the source whitelist differs from the run pairs."""
    if not config_payload:
        return None

    source_whitelist = config_payload.get("exchange", {}).get("pair_whitelist")
    if source_whitelist == effective_pairs:
        return None

    snapshot = deepcopy(config_payload)
    snapshot.setdefault("exchange", {})["pair_whitelist"] = effective_pairs
    snapshot_path = run_dir / "candidate_config.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return str(snapshot_path)


def _tail_lines(text: str, limit: int = 20) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-limit:]


def _summarize_process_error(stderr_text: str, stdout_text: str) -> str | None:
    stderr_tail = _tail_lines(stderr_text, limit=50)
    for line in reversed(stderr_tail):
        if " - ERROR - " in line:
            return line.split(" - ERROR - ", 1)[1].strip()
    for line in reversed(stderr_tail):
        return line
    for line in reversed(_tail_lines(stdout_text, limit=50)):
        return line
    return None


def _json_result_candidates(run_dir: Path) -> list[Path]:
    ignored = {
        "candidate_config.json",
        "parsed_summary.json",
        "pair_results.json",
        "trades.json",
        "trades_by_pair.json",
        "advanced_metrics.json",
        "charts.json",
    }
    return sorted(
        [
            path for path in run_dir.glob("*.json")
            if path.name not in ignored and not path.name.endswith("_config.json")
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _extract_result_zip(zip_path: Path, run_dir: Path) -> str | None:
    raw_result_path = run_dir / "raw_result.json"
    native_zip_path = run_dir / "freqtrade_native_result.zip"
    native_meta_path = run_dir / "freqtrade_native_result.meta.json"

    try:
        native_zip_path.write_bytes(zip_path.read_bytes())
        meta_path = zip_path.with_suffix(".meta.json")
        if meta_path.exists():
            native_meta_path.write_text(meta_path.read_text(encoding="utf-8"), encoding="utf-8")
        with zipfile.ZipFile(zip_path) as archive:
            json_members = [
                name for name in archive.namelist()
                if name.endswith(".json") and not name.endswith("_config.json")
            ]
            if not json_members:
                return None
            preferred = next((name for name in json_members if "_result" not in name), json_members[0])
            with archive.open(preferred) as handle:
                raw_result_path.write_bytes(handle.read())
        return str(zip_path)
    except Exception:
        return None


def _collect_freqtrade_result(
    run_dir: Path,
    user_data_dir: str,
    *,
    not_before: datetime | None = None,
) -> str | None:
    """Collect Freqtrade's native output into run_dir/raw_result.json."""
    raw_result_path = run_dir / "raw_result.json"
    if raw_result_path.exists():
        return str(raw_result_path)

    for candidate in _json_result_candidates(run_dir):
        try:
            raw_result_path.write_bytes(candidate.read_bytes())
            return str(candidate)
        except Exception:
            continue

    for zip_candidate in sorted(
        run_dir.glob("*.zip"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ):
        source = _extract_result_zip(zip_candidate, run_dir)
        if source and raw_result_path.exists():
            return source

    results_root = Path(user_data_dir) / "backtest_results"
    last_result_path = results_root / ".last_result.json"
    if not last_result_path.exists():
        return None
    try:
        payload = json.loads(last_result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    latest_name = payload.get("latest_backtest")
    if not latest_name:
        return None
    latest_zip = results_root / latest_name
    if not latest_zip.exists():
        return None
    if not_before is not None and latest_zip.stat().st_mtime < not_before.timestamp() - 5:
        return None
    source = _extract_result_zip(latest_zip, run_dir)
    if source and raw_result_path.exists():
        return source
    return None


def _apply_gate_rules(metrics: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    t = GATE_THRESHOLDS

    if metrics.get("total_trades") is not None and metrics["total_trades"] < t["min_trades"]:
        failures.append("MIN_TRADES")
    if metrics.get("win_rate_pct") is not None and metrics["win_rate_pct"] < t["min_win_rate_pct"]:
        failures.append("MIN_WIN_RATE")
    if metrics.get("profit_factor") is not None and metrics["profit_factor"] < t["min_profit_factor"]:
        failures.append("MIN_PROFIT_FACTOR")
    if metrics.get("max_drawdown_pct") is not None and metrics["max_drawdown_pct"] > t["max_drawdown_pct"]:
        failures.append("MAX_DRAWDOWN")
    if metrics.get("expectancy") is not None and not (metrics["expectancy"] > 0):
        failures.append("POSITIVE_EXPECTANCY")
    if metrics.get("sharpe_ratio") is not None and metrics["sharpe_ratio"] < t["min_sharpe_ratio"]:
        failures.append("MIN_SHARPE")

    return failures


def run_backtest_gate(
    *,
    strategy_path: str,
    strategy_name: str,
    config_file: str,
    timerange: str,
    timeframe: str,
    pairs: list[str],
    max_open_trades: int = 1,
    dry_run_wallet: float = 1000.0,
    user_data_dir: str,
    exchange: str = "binance",
    freqtrade_executable_path: str = "freqtrade",
) -> BacktestGateResult:
    resolved_config_file = _resolve_config_file(config_file, user_data_dir)
    config_payload = _load_config_payload(resolved_config_file)
    effective_pairs = _normalize_pairs_for_config(pairs, config_payload)

    if not effective_pairs:
        return BacktestGateResult(
            gate_status="backtest_failed",
            errors=["No trading pairs specified for backtest gate"],
        )

    dq_result = check_data_quality(
        pairs=effective_pairs,
        timeframe=timeframe,
        timerange=timerange,
        user_data_dir=user_data_dir,
        exchange=exchange,
    )
    if not dq_result["passed"]:
        return BacktestGateResult(
            gate_status="data_quality_failed",
            errors=list(dq_result.get("errors", [])),
            warnings=list(dq_result.get("warnings", [])),
            details=dq_result.get("details"),
        )

    strategy_file = Path(strategy_path)
    if not strategy_file.exists():
        return BacktestGateResult(
            gate_status="backtest_failed",
            errors=[f"Strategy file not found: {strategy_path}"],
        )

    strategy_source = strategy_file.read_text(encoding="utf-8")
    now = utc_now()
    run_id = f"gate_{now.strftime('%Y%m%d_%H%M%S')}_{strategy_name}"
    run_dir = Path(user_data_dir) / "backtest_gate" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "strategy_snapshot.py").write_text(strategy_source, encoding="utf-8")
    command_config_file = _write_pair_config_snapshot(
        run_dir=run_dir,
        config_payload=config_payload,
        effective_pairs=effective_pairs,
    ) or resolved_config_file

    command = _build_gate_command(
        executable=freqtrade_executable_path,
        user_data_dir=user_data_dir,
        config_file=command_config_file,
        strategy_name=strategy_name,
        run_dir=run_dir,
        timerange=timerange,
        timeframe=timeframe,
        pairs=effective_pairs,
        max_open_trades=max_open_trades,
        dry_run_wallet=dry_run_wallet,
    )

    stdout_text = ""
    stderr_text = ""
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        return_code = process.returncode
        if stdout:
            stdout_text = stdout.decode(errors="replace")
            (run_dir / "stdout.log").write_text(stdout_text, encoding="utf-8")
        if stderr:
            stderr_text = stderr.decode(errors="replace")
            (run_dir / "stderr.log").write_text(stderr_text, encoding="utf-8")
    except Exception as e:
        return BacktestGateResult(
            gate_status="backtest_failed",
            errors=[f"Subprocess execution failed: {e}"],
            details={
                "run_dir": str(run_dir),
                "config_file": command_config_file,
                "original_config_file": config_file,
                "pairs": effective_pairs,
                "original_pairs": pairs,
            },
        )

    if return_code != 0:
        errors = [f"Freqtrade exited with code {return_code}"]
        error_summary = _summarize_process_error(stderr_text, stdout_text)
        if error_summary and error_summary not in errors:
            errors.append(error_summary)
        return BacktestGateResult(
            gate_status="backtest_failed",
            errors=errors,
            details={
                "run_dir": str(run_dir),
                "config_file": command_config_file,
                "original_config_file": config_file,
                "pairs": effective_pairs,
                "original_pairs": pairs,
                "stderr_tail": _tail_lines(stderr_text),
                "stdout_tail": _tail_lines(stdout_text),
            },
        )

    raw_result_path = run_dir / "raw_result.json"
    result_source = _collect_freqtrade_result(run_dir, user_data_dir, not_before=now)
    if not raw_result_path.exists():
        return BacktestGateResult(
            gate_status="backtest_failed",
            errors=[
                "raw_result.json not produced by Freqtrade and no native result archive could be collected",
            ],
            details={
                "run_dir": str(run_dir),
                "config_file": command_config_file,
                "original_config_file": config_file,
                "pairs": effective_pairs,
                "original_pairs": pairs,
                "stderr_tail": _tail_lines(stderr_text),
                "stdout_tail": _tail_lines(stdout_text),
                "expected_result": str(raw_result_path),
                "last_result_pointer": str(Path(user_data_dir) / "backtest_results" / ".last_result.json"),
            },
        )

    metadata = RunMetadata(
        run_id=run_id,
        strategy_name=strategy_name,
        strategy_version_id="gate",
        parent_version_id=None,
        baseline_run_id=None,
        run_type=RunType.BASELINE,
        run_status=RunStatus.COMPLETED,
        created_at=now,
        completed_at=utc_now(),
        freqtrade_exit_code=return_code,
        config_file=config_file,
        timerange=timerange,
        timeframe=timeframe,
        pairs=effective_pairs,
        max_open_trades=max_open_trades,
        dry_run_wallet=dry_run_wallet,
    )

    parser = ResultParser()
    try:
        summary, _ = parser.parse_run_artifacts(run_dir, metadata)
    except Exception as e:
        return BacktestGateResult(
            gate_status="backtest_failed",
            errors=[f"Failed to parse backtest results: {e}"],
            details={
                "run_dir": str(run_dir),
                "result_source": result_source,
                "raw_result_path": str(raw_result_path),
            },
        )

    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    for key in ["total_trades", "win_rate_pct", "profit_factor", "max_drawdown_pct", "expectancy", "sharpe_ratio"]:
        value = getattr(summary, key, None)
        metrics[key] = value
        if value is None:
            warnings.append(f"Metric '{key}' not available from backtest result")

    failures = _apply_gate_rules(metrics)
    gate_status = "passed" if not failures else "failed"

    return BacktestGateResult(
        gate_status=gate_status,
        run_id=run_id,
        metrics=metrics,
        failures=failures,
        warnings=warnings,
        details={
            **(dq_result.get("details") or {}),
            "result_source": result_source,
            "raw_result_path": str(raw_result_path),
        },
    )
