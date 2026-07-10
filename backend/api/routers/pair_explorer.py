"""Router: /api/strategy/pair-explorer  &  /api/strategy/add-pair

POST /api/strategy/pair-explorer       — kick off a parallel multi-pair exploration
GET  /api/strategy/pair-explorer       — list all past exploration sessions
GET  /api/strategy/pair-explorer/{id}  — poll progress + results for a session
POST /api/strategy/add-pair            — append a pair to the strategy's config
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from ...services.execution.data_download_runner import DataDownloadRunner
from ...services.pairs import pair_explorer_service as pair_explorer_api
from ..dependencies import get_services

router = APIRouter(prefix="/api/strategy", tags=["Pair Explorer"])
logger = logging.getLogger(__name__)

# ── in-memory session store ────────────────────────────────────────────────────
_SESSIONS = pair_explorer_api.SESSIONS

# ── one download at a time across all concurrent pair tasks ───────────────────
_DOWNLOAD_LOCK = pair_explorer_api.DOWNLOAD_LOCK


# ── Pydantic models ─────────────────────────────────────────────────────────────

class PairExplorerRequest(BaseModel):
    strategy_name: str = Field(..., description="Strategy to backtest")
    pairs: list[str] = Field(..., min_length=1, description="Pairs to explore")
    timeframe: str = Field("1h")
    timerange: str = Field(..., description="Freqtrade timerange string e.g. 20230101-20240101")
    dry_run_wallet: float = Field(default=1000.0)
    max_open_trades: int = Field(default=1, ge=1, description="Group size: pairs run together in one backtest")


class AddPairRequest(BaseModel):
    strategy_name: str = Field(..., description="Strategy whose config to update")
    pair: str = Field(..., description="Pair to add to pair_whitelist")


# ── service helper aliases ─────────────────────────────────────────────────────

_sessions_dir = pair_explorer_api.sessions_dir
_save_session = pair_explorer_api.save_session
_load_all_sessions = pair_explorer_api.load_all_sessions
_data_file_exists = pair_explorer_api.data_file_exists
_ensure_data = pair_explorer_api.ensure_data
_snapshot_zips = pair_explorer_api.snapshot_zips
_find_new_zip = pair_explorer_api.find_new_zip
_parse_zip_result = pair_explorer_api.parse_zip_result
_strategy_block = pair_explorer_api.strategy_block
_extract_trade_rows = pair_explorer_api.extract_trade_rows
_extract_metrics = pair_explorer_api.extract_metrics
_group_key = pair_explorer_api.group_key
_safe_config_filename = pair_explorer_api.safe_config_filename
_TERMINAL_GROUP_STATUSES = pair_explorer_api.TERMINAL_GROUP_STATUSES
_session_results_list = pair_explorer_api.session_results_list
_coerce_results_dict = pair_explorer_api.coerce_results_dict
_record_group_result = pair_explorer_api.record_group_result
_fail_unfinished_group = pair_explorer_api.fail_unfinished_group
_reconcile_terminal_session = pair_explorer_api.reconcile_terminal_session


# ── helpers ────────────────────────────────────────────────────────────────────

def _load_settings(services):
    return services.settings_store.load()


# ── background tasks ───────────────────────────────────────────────────────────

async def _run_pair_group(
    semaphore: asyncio.Semaphore,
    session_id: str,
    chunk: list[str],
    strategy_name: str,
    timeframe: str,
    timerange: str,
    freqtrade_exe: str,
    config_file: str,
    strategies_dir: str,
    user_data_dir: str,
    exchange: str,
    data_download_runner: DataDownloadRunner,
    dry_run_wallet: float = 1000.0,
    max_open_trades: int = 1,
) -> None:
    """Auto-download data for each pair in the chunk, then run one backtest for the group."""
    gkey = _group_key(chunk)
    start_time = datetime.now(tz=UTC)
    # Create unique export filename for this group to avoid race conditions
    group_hash = hashlib.md5(f"{session_id}_{gkey}".encode()).hexdigest()[:8]
    export_filename = f"pe_{session_id[:8]}_{group_hash}"
    
    logger.info(
        "[Pair Explorer] Starting group %s (session=%s, pairs=%s, export=%s)",
        gkey, session_id[:8], chunk, export_filename
    )

    async with semaphore:
        session = pair_explorer_api.get_session(session_id)
        if session is None:
            logger.error("[Pair Explorer] Session %s not found", session_id)
            return

        # ── 1. Auto-download data for every pair in the group ─────────────────
        session["results"][gkey] = {"group": gkey, "pairs": chunk, "status": "downloading"}

        download_warnings: list[str] = []
        for pair in chunk:
            err = await _ensure_data(
                data_download_runner, pair, timeframe, timerange,
                config_file, user_data_dir, exchange,
            )
            if err:
                download_warnings.append(f"{pair}: {err}")

        # ── 2. Write a per-group temp config ──────────────────────────────────
        # Sets pair_whitelist to exactly this group so freqtrade accepts them all
        session["results"][gkey]["status"] = "running"

        try:
            base_cfg: dict = json.loads(Path(config_file).read_text(encoding="utf-8"))
        except Exception as exc:
            session["results"][gkey] = {
                "group": gkey, "pairs": chunk, "status": "failed",
                "error": f"Could not read config: {exc}",
            }
            session["completed"] += 1
            return

        group_cfg = base_cfg.copy()
        
        # Override strategy, timeframe, and max_open_trades with user selections
        group_cfg["strategy"] = strategy_name
        group_cfg["timeframe"] = timeframe
        group_cfg["max_open_trades"] = max_open_trades
        
        if "exchange" not in group_cfg:
            group_cfg["exchange"] = {}
        group_cfg["exchange"]["pair_whitelist"] = chunk
        
        # Create unique result directory for this group
        pe_results_dir = Path(user_data_dir) / "pair_explorer_results"
        pe_results_dir.mkdir(parents=True, exist_ok=True)
        group_result_dir = pe_results_dir / export_filename
        group_result_dir.mkdir(parents=True, exist_ok=True)
        
        # Set export directory in config to ensure freqtrade writes to the right place
        group_cfg["export"] = {
            "export_filename": str(group_result_dir / export_filename),
        }
        
        # Disable rate limiting to avoid exchange connectivity issues during backtesting
        if "ccxt_config" not in group_cfg["exchange"]:
            group_cfg["exchange"]["ccxt_config"] = {}
        group_cfg["exchange"]["ccxt_config"]["enableRateLimit"] = False
        
        # Ensure api_server has required config even if disabled
        if "api_server" not in group_cfg:
            group_cfg["api_server"] = {}
        if "listen_ip_address" not in group_cfg["api_server"]:
            group_cfg["api_server"]["listen_ip_address"] = "127.0.0.1"
        if "listen_port" not in group_cfg["api_server"]:
            group_cfg["api_server"]["listen_port"] = 8080
        
        # Try to use offline mode by setting exchange to not require API calls
        group_cfg["exchange"]["exchange"] = "binance"
        group_cfg["dry_run"] = True
        # Disable API key requirements for backtesting
        if "api_key" in group_cfg["exchange"]:
            del group_cfg["exchange"]["api_key"]
        if "api_secret" in group_cfg["exchange"]:
            del group_cfg["exchange"]["api_secret"]
        # Try to skip market loading by using sandbox mode
        group_cfg["exchange"]["sandbox"] = False
        
        logger.debug(
            "[Pair Explorer] Group %s: result dir=%s, pairs=%s",
            gkey, group_result_dir, chunk
        )

        # Write per-group config
        pe_config_dir = Path(user_data_dir) / "pair_explorer_configs"
        pe_config_dir.mkdir(parents=True, exist_ok=True)
        tmp_config = pe_config_dir / _safe_config_filename(session_id, gkey)
        config_json = json.dumps(group_cfg, indent=2)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            prefix=f".{tmp_config.stem}.",
            dir=pe_config_dir,
            encoding="utf-8",
            delete=False,
        ) as f:
            f.write(config_json)
            temp_path = f.name
        Path(temp_path).replace(tmp_config)

        # Handle "py -m freqtrade" command by splitting it
        if freqtrade_exe == "py -m freqtrade":
            cmd = [
                "py", "-m", "freqtrade",
                "backtesting",
                "--user-data-dir", user_data_dir,
                "--config", str(tmp_config),
                "--strategy-path", strategies_dir,
                "--strategy", strategy_name,
                "--timerange", timerange,
                "--timeframe", timeframe,
                "--export", "trades",
                "--backtest-directory", str(group_result_dir),
                "--cache", "none",
                "--pairs",
            ] + chunk + [
                "--dry-run-wallet", str(dry_run_wallet),
                "--max-open-trades", str(max_open_trades),
            ]
        else:
            cmd = [
                freqtrade_exe,
                "backtesting",
                "--user-data-dir", user_data_dir,
                "--config", str(tmp_config),
                "--strategy-path", strategies_dir,
                "--strategy", strategy_name,
                "--timerange", timerange,
                "--timeframe", timeframe,
                "--export", "trades",
                "--backtest-directory", str(group_result_dir),
                "--cache", "none",
                "--pairs",
            ] + chunk + [
                "--dry-run-wallet", str(dry_run_wallet),
                "--max-open-trades", str(max_open_trades),
            ]

        logger.debug("[Pair Explorer] Group %s: freqtrade cmd=%s", gkey, " ".join(cmd))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(Path(user_data_dir).parent),
            )
            logger.info("[Pair Explorer] Group %s: subprocess started PID=%d", gkey, proc.pid)
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=300
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                session["results"][gkey] = {
                    "group": gkey, "pairs": chunk, "status": "failed",
                    "error": "Timed out after 5 minutes",
                }
                session["completed"] += 1
                _save_session(session, user_data_dir)
                return

            exit_code = proc.returncode
            stderr_text = ""
            if stderr_bytes:
                raw = stderr_bytes.decode("utf-8", errors="replace").strip()
                logger.error(f"Freqtrade stderr: {raw}")
                lines = raw.splitlines()
                important = [
                    l for l in lines
                    if any(kw in l for kw in (
                        "ERROR", "No data", "No candle",
                        "not found", "KeyError", "Exception", "Traceback", "No pair",
                        "PermissionError", "FileNotFoundError", "RuntimeError",
                    ))
                    # Exclude INFO level logs that happen to contain keywords
                    and "- INFO -" not in l
                    and "- DEBUG -" not in l
                ]
                # Only use fallback if exit code indicates an error
                if important:
                    stderr_text = " | ".join(important[-3:])
                elif exit_code != 0:
                    stderr_text = lines[-1] if lines else raw[:300]

        except Exception as exc:
            session["results"][gkey] = {
                "group": gkey, "pairs": chunk, "status": "failed", "error": str(exc),
            }
            session["completed"] += 1
            _save_session(session, user_data_dir)
            return

        if exit_code != 0:
            session["results"][gkey] = {
                "group": gkey, "pairs": chunk, "status": "failed",
                "error": stderr_text or f"freqtrade exited with code {exit_code}",
            }
            session["completed"] += 1
            _save_session(session, user_data_dir)
            return

        # ── 3. Parse the result from the unique export path ─────────────────────
        finish_time = datetime.now(tz=UTC)
        duration = (finish_time - start_time).total_seconds()
        
        # Try to load result from the unique export path first
        result_json = group_result_dir / f"{export_filename}.json"
        result_zip = group_result_dir / f"{export_filename}.zip"
        
        metrics = {}
        artifact_used = None
        
        if result_json.exists():
            try:
                with open(result_json, encoding="utf-8") as f:
                    payload = json.load(f)
                metrics = _extract_metrics(payload, strategy_name)
                artifact_used = str(result_json)
                logger.info(
                    "[Pair Explorer] Group %s: loaded result from JSON %s",
                    gkey, result_json
                )
            except Exception as exc:
                logger.warning(
                    "[Pair Explorer] Group %s: failed to load JSON result %s: %s",
                    gkey, result_json, exc
                )
        
        if not metrics and result_zip.exists():
            metrics = _parse_zip_result(result_zip, strategy_name)
            artifact_used = str(result_zip)
            logger.info(
                "[Pair Explorer] Group %s: loaded result from ZIP %s",
                gkey, result_zip
            )
        
        # Fallback: look for freqtrade's default backtest-result-*.zip files
        if not metrics:
            try:
                for zip_file in sorted(group_result_dir.glob("backtest-result-*.zip")):
                    metrics = _parse_zip_result(zip_file, strategy_name)
                    if metrics:
                        artifact_used = str(zip_file)
                        logger.info(
                            "[Pair Explorer] Group %s: loaded result from fallback ZIP %s",
                            gkey, zip_file
                        )
                        break
            except Exception as exc:
                logger.warning(
                    "[Pair Explorer] Group %s: failed to load fallback ZIP results: %s",
                    gkey, exc
                )
        
        if not metrics:
            session["results"][gkey] = {
                "group": gkey, "pairs": chunk, "status": "failed",
                "error": stderr_text or "No result file produced by freqtrade",
            }
            session["completed"] += 1
            _save_session(session, user_data_dir)
            logger.error(
                "[Pair Explorer] Group %s: no result found at %s or %s",
                gkey, result_json, result_zip
            )
            return
        
        # ── 4. Validate pair integrity ───────────────────────────────────────────
        parsed_pairs = set(metrics.get("trades_by_pair", {}).keys())
        expected_pairs = set(chunk)
        unexpected_pairs = parsed_pairs - expected_pairs
        
        if unexpected_pairs:
            session["results"][gkey] = {
                "group": gkey, "pairs": chunk, "status": "failed",
                "error": (
                    f"Artifact mismatch: expected pairs {expected_pairs}, "
                    f"but found pairs {parsed_pairs} in result. "
                    f"Unexpected: {unexpected_pairs}. "
                    f"Artifact: {artifact_used}"
                ),
            }
            session["completed"] += 1
            _save_session(session, user_data_dir)
            logger.error(
                "[Pair Explorer] Group %s: PAIR INTEGRITY VIOLATION - "
                "expected=%s, parsed=%s, unexpected=%s, artifact=%s",
                gkey, expected_pairs, parsed_pairs, unexpected_pairs, artifact_used
            )
            return
        
        result = {"group": gkey, "pairs": chunk, "status": "completed", **metrics}
        if download_warnings:
            result["download_warning"] = "; ".join(download_warnings)
        session["results"][gkey] = result
        session["completed"] += 1
        
        # Persist session after each group completes for crash recovery
        _save_session(session, user_data_dir)
        
        logger.info(
            "[Pair Explorer] Group %s: completed in %.1fs, pairs=%s, "
            "trades=%d, profit=%.2f%%, artifact=%s",
            gkey, duration, chunk, metrics.get("total_trades", 0),
            metrics.get("total_profit_pct", 0), artifact_used
        )


async def _explore_task(
    session_id: str,
    chunks: list[list[str]],
    strategy_name: str,
    timeframe: str,
    timerange: str,
    freqtrade_exe: str,
    config_file: str,
    strategies_dir: str,
    user_data_dir: str,
    exchange: str,
    data_download_runner: DataDownloadRunner,
    dry_run_wallet: float = 1000.0,
    max_open_trades: int = 1,
) -> None:
    semaphore = asyncio.Semaphore(4)
    tasks = [
        _run_pair_group(
            semaphore, session_id, chunk,
            strategy_name, timeframe, timerange,
            freqtrade_exe, config_file, strategies_dir, user_data_dir,
            exchange, data_download_runner,
            dry_run_wallet=dry_run_wallet,
            max_open_trades=max_open_trades,
        )
        for chunk in chunks
    ]
    task_results = await asyncio.gather(*tasks, return_exceptions=True)

    session = pair_explorer_api.get_session(session_id)
    if session:
        for chunk, task_result in zip(chunks, task_results, strict=False):
            if isinstance(task_result, Exception):
                logger.error(
                    "Pair Explorer group task failed unexpectedly for %s",
                    _group_key(chunk),
                    exc_info=(type(task_result), task_result, task_result.__traceback__),
                )
                _fail_unfinished_group(
                    session,
                    user_data_dir,
                    chunk,
                    f"Pair group task failed unexpectedly: {task_result}",
                )

        for chunk in chunks:
            _fail_unfinished_group(
                session,
                user_data_dir,
                chunk,
                "Pair group ended without a terminal result.",
            )

        # Only mark as completed if all tasks actually finished
        if session["completed"] >= session["total"]:
            session["status"] = "completed"
            session["completed_at"] = datetime.now(tz=UTC).isoformat()
            _save_session(session, user_data_dir)


# ── routes ─────────────────────────────────────────────────────────────────────

@router.get("/pair-explorer", summary="List all past pair-explorer sessions")
async def list_pair_explorer_sessions(services=Depends(get_services)) -> dict:
    settings = _load_settings(services)
    if not _SESSIONS:
        _SESSIONS.update(_load_all_sessions(settings.user_data_directory_path))
    sessions = sorted(_SESSIONS.values(), key=lambda s: s.get("created_at", ""), reverse=True)
    for session in sessions:
        _reconcile_terminal_session(session, settings.user_data_directory_path)
    return {
        "sessions": [
            {
                "session_id": s["session_id"],
                "strategy_name": s.get("strategy_name", ""),
                "status": s.get("status", "unknown"),
                "total": s.get("total", 0),
                "completed": s.get("completed", 0),
                "created_at": s.get("created_at"),
                "completed_at": s.get("completed_at"),
                "timerange": s.get("timerange", ""),
                "timeframe": s.get("timeframe", ""),
                "max_open_trades": s.get("max_open_trades", 1),
            }
            for s in sessions
        ]
    }


@router.post("/pair-explorer", status_code=202, summary="Start a multi-pair exploration")
async def start_pair_explorer(
    body: PairExplorerRequest,
    background_tasks: BackgroundTasks,
    services=Depends(get_services),
) -> dict:
    settings = _load_settings(services)

    if not _SESSIONS:
        _SESSIONS.update(_load_all_sessions(settings.user_data_directory_path))

    pairs = [p.strip().upper() for p in body.pairs if p.strip()]
    if not pairs:
        raise HTTPException(status_code=422, detail="At least one pair must be selected.")

    # Exchange name for data-file existence checks
    try:
        exchange = json.loads(
            Path(settings.default_config_file_path).read_text(encoding="utf-8")
        ).get("exchange", {}).get("name", "binance")
    except Exception:
        exchange = "binance"

    # Chunk pairs into groups of max_open_trades
    n = body.max_open_trades
    chunks: list[list[str]] = [pairs[i:i + n] for i in range(0, len(pairs), n)]

    session_id = str(uuid.uuid4())
    _SESSIONS[session_id] = {
        "session_id": session_id,
        "status": "running",
        "total": len(chunks),
        "completed": 0,
        "results": {},
        "strategy_name": body.strategy_name,
        "timeframe": body.timeframe,
        "timerange": body.timerange,
        "dry_run_wallet": body.dry_run_wallet,
        "max_open_trades": body.max_open_trades,
        "pairs": pairs,
        "created_at": datetime.now(tz=UTC).isoformat(),
        "completed_at": None,
    }
    _save_session(_SESSIONS[session_id], settings.user_data_directory_path)

    logger.info(f"[Pair Explorer] Starting background task for session {session_id} with {len(chunks)} chunks")
    print(f"[DEBUG] Pair Explorer: Starting background task for session {session_id} with {len(chunks)} chunks")
    background_tasks.add_task(
        _explore_task,
        session_id, chunks,
        body.strategy_name, body.timeframe, body.timerange,
        settings.freqtrade_executable_path,
        settings.default_config_file_path,
        settings.strategies_directory_path,
        settings.user_data_directory_path,
        exchange,
        services.data_download_runner,
        dry_run_wallet=body.dry_run_wallet,
        max_open_trades=body.max_open_trades,
    )

    return {
        "session_id": session_id,
        "status": "running",
        "total": len(chunks),
        "groups": [_group_key(c) for c in chunks],
        "message": (
            f"Exploration started: {len(pairs)} pair(s) in {len(chunks)} "
            f"group(s) of up to {n}. Data will be auto-downloaded as needed."
        ),
    }


@router.get("/pair-explorer/{session_id}", summary="Poll pair-explorer progress")
async def get_pair_explorer_status(session_id: str, services=Depends(get_services)) -> dict:
    session = _SESSIONS.get(session_id)
    if session is None:
        settings = _load_settings(services)
        disk_path = _sessions_dir(settings.user_data_directory_path) / f"{session_id}.json"
        if disk_path.exists():
            try:
                session = json.loads(disk_path.read_text(encoding="utf-8"))
                _SESSIONS[session_id] = session
            except Exception:
                pass

    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    settings = _load_settings(services)
    _reconcile_terminal_session(session, settings.user_data_directory_path)

    return {
        "session_id": session["session_id"],
        "status": session["status"],
        "total": session["total"],
        "completed": session["completed"],
        "results": _session_results_list(session),
        "strategy_name": session.get("strategy_name", ""),
        "timeframe": session.get("timeframe", ""),
        "timerange": session.get("timerange", ""),
        "max_open_trades": session.get("max_open_trades", 1),
        "created_at": session.get("created_at"),
        "completed_at": session.get("completed_at"),
    }


@router.post("/add-pair", summary="Add a pair to the config pair_whitelist")
async def add_pair_to_config(body: AddPairRequest, services=Depends(get_services)) -> dict:
    settings = _load_settings(services)
    config_path = Path(settings.default_config_file_path)
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Config file not found.")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read config: {exc}")

    pair = body.pair.strip().upper()
    whitelist: list = config.get("exchange", {}).get("pair_whitelist", [])
    if pair in whitelist:
        return {"ok": True, "pair": pair, "already_present": True, "whitelist": whitelist}

    whitelist.append(pair)
    config.setdefault("exchange", {})["pair_whitelist"] = whitelist
    tmp = config_path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
        tmp.replace(config_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not write config: {exc}")

    return {"ok": True, "pair": pair, "already_present": False, "whitelist": whitelist}
