"""Backtest runner — synchronous execution with optional async wrapper.

Long-running subprocess execution is handled via threading internally.
Log streaming is done via a simple callback (set_log_callback).

The main run_backtest method is synchronous and blocks until the backtest completes.
An async queue_strategy_backtest wrapper is provided for optimizer use.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import threading
import zipfile
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from ...core.errors import BackendError
from ...models import (
    DownloadDataRequest,
    ParamsSchema,
    RunMetadata,
    RunProgressUpdateSource,
    RunPhase,
    RunRequest,
    RunStatus,
    RunType,
    StrategyRecord,
    VersionBacktestRequest,
)
from ...services.interfaces import IBacktestRunner
from ...settings_store import SettingsStore
from ...utils import append_text, atomic_write_json, atomic_write_text, build_run_id, get_data_file_path, detect_data_file_format, utc_now
from .data_download_runner import DataDownloadRunner
from ..storage.result_parser import ResultParser
from .run_progress import RunProgressService
from ..storage.run_repository import RunRepository
from ..strategy.strategy_git import StrategyGitService
from ..strategy.version_manager import VersionManager


class BacktestRunner(IBacktestRunner):
    """BacktestRunner contains class-level backend logic."""
    def __init__(
        self,
        settings_store: SettingsStore,
        run_repository: RunRepository,
        progress_service: RunProgressService,
        version_manager: VersionManager,
        result_parser: ResultParser,
        strategy_git_service: StrategyGitService,
        data_download_runner: DataDownloadRunner,
    ) -> None:
        self.settings_store = settings_store
        self.run_repository = run_repository
        self.progress_service = progress_service
        self.version_manager = version_manager
        self.result_parser = result_parser
        self.strategy_git_service = strategy_git_service
        self.data_download_runner = data_download_runner
        self.active_run_id: str | None = None
        self.active_process: subprocess.Popen | None = None
        self._current_run_id: str | None = None
        self._running = False
        self._cancel_requested = False
        self._busy_lock = threading.Lock()
        self.log_write_lock = threading.Lock()
        self.log_callback: Callable[[str], None] | None = None

    def is_busy(self) -> bool:
        with self._busy_lock:
            return self._running

    def get_current_run_id(self) -> str | None:
        return self._current_run_id

    def set_log_callback(self, callback: Callable[[str], None] | None) -> None:
        self.log_callback = callback

    def _check_data_exists(
        self,
        pairs: list[str],
        timeframe: str,
        user_data_dir: str,
        exchange: str = "binance",
    ) -> bool:
        data_dir = Path(user_data_dir) / "data" / exchange
        if not data_dir.exists():
            return False
        for pair in pairs:
            data_format = detect_data_file_format(user_data_dir, pair, timeframe, exchange)
            data_file = get_data_file_path(user_data_dir, pair, timeframe, exchange, data_format)
            if not data_file.exists():
                return False
        return True

    def _check_data_covers_timerange(
        self,
        pairs: list[str],
        timeframe: str,
        user_data_dir: str,
        timerange: str,
        exchange: str = "binance",
    ) -> bool:
        """Return True only if every pair's data file covers the full requested timerange.

        Parses the end date from the timerange string (format ``YYYYMMDD-YYYYMMDD``
        or ``YYYYMMDD-``).  When the end portion is absent or unparseable the check
        is skipped (returns True so the caller does not trigger a spurious download).
        """
        import json as _json
        from datetime import datetime, timezone

        parts = timerange.split("-")
        end_str = parts[-1] if len(parts) >= 2 else ""
        if len(end_str) != 8:
            return True
        try:
            required_end = datetime.strptime(end_str, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return True

        data_dir = Path(user_data_dir) / "data" / exchange
        for pair in pairs:
            data_format = detect_data_file_format(user_data_dir, pair, timeframe, exchange)
            data_file = get_data_file_path(user_data_dir, pair, timeframe, exchange, data_format)
            if not data_file.exists():
                return False
            try:
                if data_format == "feather":
                    # Read feather file using pandas
                    import pandas as pd
                    df = pd.read_feather(data_file)
                    if df.empty:
                        return False
                    # Convert date column to timestamp
                    if pd.api.types.is_integer_dtype(df["date"]):
                        last_ts_ms = df["date"].iloc[-1]
                    else:
                        # Convert datetime to timestamp
                        last_ts_ms = int(df["date"].iloc[-1].timestamp() * 1000)
                else:
                    # Read JSON file
                    raw = _json.loads(data_file.read_text(encoding="utf-8"))
                    if not raw:
                        return False
                    last_ts_ms = raw[-1][0]
                
                last_date = datetime.fromtimestamp(last_ts_ms / 1000, tz=timezone.utc)
                if last_date < required_end:
                    return False
            except Exception:
                return True  # unreadable file — let freqtrade handle it
        return True

    def run_backtest(
        self,
        strategy: StrategyRecord,
        version_id: str,
        request: RunRequest,
        phase_callback: Callable[[str], None] | None = None,
        params_override: ParamsSchema | None = None,
    ) -> str:
        """Run a backtest synchronously using the run_id for the full backtest session.

        This method blocks the calling thread until the entire backtest completes.
        Wrap in asyncio.to_thread or a worker thread when calling from async or UI code.

        ``params_override`` is an INTERNAL execution-layer override (Research
        Layer only): when provided, it replaces the params normally resolved
        from VersionManager. It is NOT part of the public ``RunRequest`` contract.
        When ``None`` behavior is identical to today.
        """
        return self._execute_run(
            strategy_name=strategy.strategy_name,
            version_id=version_id,
            config_file=request.config_file,
            timerange=request.timerange,
            timeframe=request.timeframe or strategy.timeframe or "5m",
            pairs=request.pairs or [],
            max_open_trades=request.max_open_trades,
            dry_run_wallet=request.dry_run_wallet,
            strategy_path=strategy.file_path,
            baseline_run_id=None,
            phase_callback=phase_callback,
            params_override=params_override,
        )

    def run_candidate_backtest(
        self,
        strategy: StrategyRecord,
        version_id: str,
        request: RunRequest,
        *,
        params_override: ParamsSchema,
        phase_callback: Callable[[str], None] | None = None,
    ) -> str:
        """Research-Layer entry point for candidate executions.

        Forwards to ``run_backtest`` with an internal ``params_override`` so a
        candidate's approved sidecar params run WITHOUT mutating the champion's
        accepted version. The candidate .py copy is supplied via ``strategy_path``
        (already accepted by ``run_backtest``).
        """
        return self.run_backtest(
            strategy,
            version_id,
            request,
            phase_callback=phase_callback,
            params_override=params_override,
        )

    async def queue_strategy_backtest(
        self,
        strategy: StrategyRecord,
        version_id: str,
        request: RunRequest,
    ) -> str:
        """Run a backtest asynchronously using asyncio.to_thread.

        This method wraps run_backtest to allow non-blocking execution
        from async contexts like the optimizer.
        """
        return await asyncio.to_thread(self.run_backtest, strategy, version_id, request)

    def cancel(self, run_id: str) -> RunMetadata:
        metadata = self.run_repository.load_metadata(run_id)
        if metadata.run_status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return metadata
        self._cancel_requested = True
        if self.active_process and self.active_run_id == run_id:
            # Strict kill sequence to prevent zombie processes
            if self.active_process.poll() is None:  # Process is still alive
                self.active_process.kill()  # Force close (SIGKILL)
                try:
                    self.active_process.wait(timeout=1.0)
                except Exception:
                    pass  # Ignore timeout errors
            self.active_process = None
        updated = metadata.model_copy(
            update={"run_status": RunStatus.CANCELLED, "completed_at": utc_now()}
        )
        self.run_repository.save_metadata(run_id, updated)
        run_dir = self.run_repository.find_run_dir(run_id)
        self.progress_service.mark_terminal(run_dir, updated, RunPhase.CANCELLED)
        return updated

    def _materialize_strategy_source_for_run(
        self,
        *,
        strategy_name: str,
        resolved_version_id: str,
        params: ParamsSchema,
        strategy_path: str | None = None,
    ) -> str:
        current_pointer = self.version_manager.get_current_pointer(strategy_name)
        if (
            current_pointer is not None
            and current_pointer.accepted_version_id == resolved_version_id
            and strategy_path
        ):
            live_path = Path(strategy_path)
            if live_path.exists():
                live_source = live_path.read_text(encoding="utf-8")
                return self.version_manager.materialize_strategy_source(
                    strategy_name,
                    resolved_version_id,
                    source=live_source,
                    params=params,
                )
        return self.version_manager.materialize_strategy_source(
            strategy_name,
            resolved_version_id,
            params=params,
        )

    def _execute_run(
        self,
        *,
        strategy_name: str,
        version_id: str,
        config_file: str,
        timerange: str,
        timeframe: str,
        pairs: list[str],
        max_open_trades: int,
        dry_run_wallet: float,
        strategy_path: str | None = None,
        baseline_run_id: str | None,
        phase_callback: Callable[[str], None] | None = None,
        params_override: ParamsSchema | None = None,
    ) -> str:
        with self._busy_lock:
            if self._running:
                raise BackendError("Backtest runner is busy.", status_code=409)
            self._running = True
        if not strategy_name:
            raise BackendError("Strategy name is required.", status_code=400)
        if not config_file:
            raise BackendError("Backtest config file is required.", status_code=400)
        if not Path(config_file).exists():
            raise BackendError("Backtest config file was not found.", status_code=400)

        version = self.version_manager.resolve_version(strategy_name, version_id)
        resolved_version_id = version.version_id
        # Internal Research-Layer override: use approved candidate params instead
        # of the champion's accepted version params. None => today's behavior.
        params = params_override or self.version_manager.load_params(
            strategy_name, resolved_version_id
        )
        strategy_source = self._materialize_strategy_source_for_run(
            strategy_name=strategy_name,
            resolved_version_id=resolved_version_id,
            params=params,
            strategy_path=strategy_path,
        )

        settings = self.settings_store.load()
        config_payload = self._load_config_payload(config_file)
        effective_pairs = list(dict.fromkeys(pairs or params.pair_list or []))
        
        # Fallback to config file whitelist if no pairs specified
        if not effective_pairs:
            config_whitelist = config_payload.get("exchange", {}).get("pair_whitelist", [])
            if config_whitelist:
                effective_pairs = list(dict.fromkeys(config_whitelist))
        
        # Raise clear error if still no pairs
        if not effective_pairs:
            raise BackendError(
                "No trading pairs specified. Provide pairs in the backtest request, "
                "strategy parameters, or configure pair_whitelist in the Freqtrade config file.",
                status_code=400
            )
        effective_pairs = self._normalize_pairs_for_config(effective_pairs, config_payload)
        
        now = utc_now()
        run_id = self._next_run_id(strategy_name, resolved_version_id, now)
        run_dir = self.run_repository.run_dir(strategy_name, run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        run_type = self._determine_run_type(str(version.change_type), baseline_run_id)
        metadata = RunMetadata(
            run_id=run_id,
            strategy_name=strategy_name,
            strategy_version_id=resolved_version_id,
            parent_version_id=version.parent_version_id,
            baseline_run_id=baseline_run_id,
            run_type=run_type,
            run_status=RunStatus.QUEUED,
            created_at=now,
            completed_at=None,
            freqtrade_exit_code=None,
            config_file=config_file,
            timerange=timerange,
            timeframe=timeframe,
            pairs=effective_pairs,
            max_open_trades=max_open_trades,
            dry_run_wallet=dry_run_wallet,
        )
        market_server = None
        market_thread = None
        local_market_base_url = None
        execution_config_payload = self._build_execution_config_payload(
            config_payload=config_payload,
            pairs=effective_pairs,
            timeframe=timeframe,
            max_open_trades=max_open_trades,
            dry_run_wallet=dry_run_wallet,
        )
        if self._should_use_local_binance_markets(config_payload, effective_pairs):
            market_server, market_thread, local_market_base_url = (
                self._start_local_binance_exchange_info_server(effective_pairs)
            )
            execution_config_payload = self._build_execution_config_payload(
                config_payload=config_payload,
                pairs=effective_pairs,
                timeframe=timeframe,
                max_open_trades=max_open_trades,
                dry_run_wallet=dry_run_wallet,
                market_base_url=local_market_base_url,
            )
        command_config_file = str(run_dir / "freqtrade_execution_config.json")
        atomic_write_json(Path(command_config_file), execution_config_payload)
        config_snapshot = self._build_run_config_snapshot(
            config_file, command_config_file, effective_pairs, max_open_trades,
            timeframe, timerange, dry_run_wallet, config_payload,
            execution_config_payload, local_market_base_url,
        )
        command = self._build_command(
            settings.freqtrade_executable_path,
            settings.user_data_directory_path,
            command_config_file, strategy_name, run_dir, timerange, timeframe,
            effective_pairs, max_open_trades, dry_run_wallet
        )
        cmd_str = subprocess.list2cmdline(command)
        atomic_write_json(run_dir / "run_config.json", config_snapshot)
        atomic_write_text(run_dir / "freqtrade_command.txt", cmd_str)
        atomic_write_text(run_dir / "strategy_snapshot.py", strategy_source)
        atomic_write_json(run_dir / "params.json", params.model_dump(mode="json"))
        atomic_write_json(run_dir / f"{strategy_name}.json",
                          self._build_strategy_sidecar_json(strategy_name, params))

        debug_info = f"Command: {cmd_str}\n"
        debug_info += f"Pairs: {pairs}\n"
        debug_info += f"Strategy: {strategy_name}\n"
        debug_info += f"Version ID: {version_id}\n"
        atomic_write_text(run_dir / "debug_info.txt", debug_info)

        sha = self.strategy_git_service.commit(strategy_name, strategy_source, run_id)
        metadata = metadata.model_copy(update={"git_commit_sha": sha})
        atomic_write_json(run_dir / "metadata.json", metadata.model_dump(mode="json"))
        atomic_write_json(run_dir / "strategy_params.json", params.model_dump(mode="json"))
        atomic_write_text(run_dir / "strategy.py", strategy_source)
        atomic_write_text(run_dir / "logs.txt", "")
        append_text(run_dir / "logs.txt", f"[COMMAND]: {cmd_str}\n")
        if self.log_callback is not None:
            try:
                self.log_callback(f"[COMMAND]: {cmd_str}")
            except Exception:
                pass
        self.progress_service.initialize_progress(run_dir, now)

        self.active_run_id = run_id
        self._current_run_id = run_id

        if phase_callback is not None:
            try:
                phase_callback("running", {"command": cmd_str})
            except Exception:
                pass

        # Synchronous execution
        try:
            self._execute_sync(run_id, command, version_id, phase_callback=phase_callback)
        finally:
            self._stop_local_market_server(market_server, market_thread)
            self._running = False
            self.active_process = None
            self.active_run_id = None

        return run_id

    def _execute_sync(self, run_id: str, command: list[str], version_id: str, phase_callback: Callable[[str], None] | None = None) -> None:
        metadata = self.run_repository.load_metadata(run_id)
        if self._cancel_requested:
            cancelled = metadata.model_copy(
                update={"run_status": RunStatus.CANCELLED, "completed_at": utc_now()}
            )
            self.run_repository.save_metadata(run_id, cancelled)
            self.progress_service.mark_terminal(
                self.run_repository.find_run_dir(run_id), cancelled, RunPhase.CANCELLED,
            )
            self._cancel_requested = False
            return

        run_dir = self.run_repository.find_run_dir(run_id)

        # Auto-download data if needed
        self._run_auto_download_sync(run_id, metadata, run_dir, phase_callback=phase_callback)

        if self._cancel_requested:
            cancelled = metadata.model_copy(
                update={"run_status": RunStatus.CANCELLED, "completed_at": utc_now()}
            )
            self.run_repository.save_metadata(run_id, cancelled)
            self.progress_service.mark_terminal(run_dir, cancelled, RunPhase.CANCELLED)
            self._cancel_requested = False
            return

        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.active_process = process  # assign immediately so cancel() can reach it
        except Exception as exc:
            detail = str(exc) or exc.__class__.__name__
            append_text(run_dir / "logs.txt", f"stderr: failed to launch freqtrade process: {detail}\n")
            failed = metadata.model_copy(
                update={"run_status": RunStatus.FAILED, "completed_at": utc_now(), "freqtrade_exit_code": None}
            )
            self.run_repository.save_metadata(run_id, failed)
            self.progress_service.mark_terminal(run_dir, failed, RunPhase.FAILED)
            return

        running = metadata.model_copy(update={"run_status": RunStatus.RUNNING})
        self.run_repository.save_metadata(run_id, running)
        self.progress_service.update_phase(
            run_dir, running, RunPhase.INITIALIZING,
            source=RunProgressUpdateSource.LOG_MARKER,
        )
        return_code = self._capture_process_output(process, run_dir / "logs.txt", run_id)

        updated = self.run_repository.load_metadata(run_id)
        if self._cancel_requested:
            cancelled = updated.model_copy(
                update={"run_status": RunStatus.CANCELLED, "completed_at": utc_now(), "freqtrade_exit_code": return_code}
            )
            self.run_repository.save_metadata(run_id, cancelled)
            self.progress_service.mark_terminal(run_dir, cancelled, RunPhase.CANCELLED)
            self._cancel_requested = False
            return

        raw_result_path = run_dir / "raw_result.json"
        if return_code == 0 and not raw_result_path.exists():
            self._collect_latest_freqtrade_result(run_dir)
        if return_code == 0 and raw_result_path.exists():
            try:
                self.result_parser.parse_run_artifacts(
                    run_dir, updated,
                    warning_logger=lambda message: append_text(run_dir / "logs.txt", message + "\n"),
                )
            except Exception as exc:
                append_text(run_dir / "logs.txt", f"stderr: Failed to parse backtest results: {exc}\n")
                failed = updated.model_copy(
                    update={"run_status": RunStatus.FAILED, "completed_at": utc_now(), "freqtrade_exit_code": return_code}
                )
                self.run_repository.save_metadata(run_id, failed)
                self.progress_service.mark_terminal(run_dir, failed, RunPhase.FAILED)
                self._cancel_requested = False
                return
            completed = updated.model_copy(
                update={"run_status": RunStatus.COMPLETED, "completed_at": utc_now(), "freqtrade_exit_code": return_code}
            )
            self.run_repository.save_metadata(run_id, completed)
            self.progress_service.mark_terminal(run_dir, completed, RunPhase.COMPLETED)
            if completed.run_type != RunType.BASELINE:
                self.version_manager.update_result_summary(
                    completed.strategy_name, version_id, completed.run_id,
                )
        else:
            if return_code == 0 and not raw_result_path.exists():
                append_text(
                    run_dir / "logs.txt",
                    "stderr: raw_result.json was not produced by Freqtrade.\n",
                )
            failed = updated.model_copy(
                update={"run_status": RunStatus.FAILED, "completed_at": utc_now(), "freqtrade_exit_code": return_code}
            )
            self.run_repository.save_metadata(run_id, failed)
            self.progress_service.mark_terminal(run_dir, failed, RunPhase.FAILED)
        self._cancel_requested = False

    def _run_auto_download_sync(
        self,
        run_id: str,
        metadata: RunMetadata,
        run_dir: Path,
        phase_callback: Callable[[str], None] | None = None,
    ) -> None:
        log_path = run_dir / "logs.txt"
        settings = self.settings_store.load()

        pairs = metadata.pairs or []
        data_exists = self._check_data_exists(
            pairs, metadata.timeframe, settings.user_data_directory_path,
        )
        data_covers = data_exists and self._check_data_covers_timerange(
            pairs, metadata.timeframe, settings.user_data_directory_path, metadata.timerange,
        )

        if data_covers:
            append_text(log_path,
                        "stdout: [auto-download] Data already exists and covers the requested timerange. Skipping download.\n")
            return

        reason = "file missing" if not data_exists else "timerange not fully covered by existing data"
        append_text(log_path, f"stdout: [auto-download] Downloading data ({reason})...\n")

        # Signal the session that we are in the data-download phase
        if phase_callback is not None:
            try:
                phase_callback("downloading")
            except Exception:
                pass

        download_request = DownloadDataRequest(
            config_file=metadata.config_file,
            timerange=metadata.timerange,
            timeframes=[metadata.timeframe],
            pairs=pairs,
            prepend=False,
        )
        try:
            self.data_download_runner.run_download(download_request)
        except Exception as exc:
            append_text(log_path, f"stderr: [auto-download] Could not start download: {exc}\n")
            updated = metadata.model_copy(
                update={"run_status": RunStatus.FAILED, "completed_at": utc_now()}
            )
            self.run_repository.save_metadata(run_id, updated)
            self.progress_service.mark_terminal(run_dir, updated, RunPhase.FAILED)
            raise BackendError(f"Data download failed: {exc}", status_code=500)

        status = self.data_download_runner.current_status()
        if status.get("status") == "completed":
            append_text(log_path, "stdout: [auto-download] Data download completed. Proceeding to backtest.\n")
            # Signal transition back to running before handing off to the backtest subprocess
            if phase_callback is not None:
                try:
                    phase_callback("running")
                except Exception:
                    pass
        else:
            error = status.get("error") or "unknown error"
            append_text(log_path, f"stderr: [auto-download] Data download finished with status '{status.get('status')}': {error}\n")
            updated = metadata.model_copy(
                update={"run_status": RunStatus.FAILED, "completed_at": utc_now()}
            )
            self.run_repository.save_metadata(run_id, updated)
            self.progress_service.mark_terminal(run_dir, updated, RunPhase.FAILED)
            raise BackendError(f"Data download failed: {error}", status_code=500)

    def _capture_process_output(self, process: subprocess.Popen, log_path: Path, run_id: str) -> int:
        threads: list[threading.Thread] = []
        for stream, channel in ((process.stdout, "stdout"), (process.stderr, "stderr")):
            if stream is None:
                continue
            thread = threading.Thread(
                target=self._pipe_logs_sync,
                args=(stream, log_path, channel, run_id),
                daemon=True,
            )
            thread.start()
            threads.append(thread)
        return_code = process.wait()
        for thread in threads:
            thread.join(timeout=5)
        return return_code

    def _pipe_logs_sync(self, stream, log_path: Path, channel: str, run_id: str) -> None:
        if stream is None:
            return
        run_dir = log_path.parent
        while True:
            chunk = stream.readline()
            if not chunk:
                break
            text = chunk.decode(errors="replace")
            with self.log_write_lock:
                append_text(log_path, f"{channel}: {text}")
                metadata = self.run_repository.load_metadata(run_id)
                self.progress_service.record_log_line(run_dir, metadata, text)
            if self.log_callback is not None:
                try:
                    self.log_callback(f"{channel}: {text}")
                except Exception:
                    pass

    def _collect_latest_freqtrade_result(self, run_dir: Path) -> None:
        raw_result_path = run_dir / "raw_result.json"
        if raw_result_path.exists():
            return

        for zip_candidate in sorted(
            run_dir.glob("*.zip"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        ):
            if self._extract_freqtrade_zip_result(zip_candidate, run_dir):
                return

        ignored = {
            "freqtrade_execution_config.json",
            "metadata.json",
            "params.json",
            "parsed_summary.json",
            "pair_results.json",
            "progress.json",
            "run_config.json",
            "strategy_params.json",
            "trades.json",
            "trades_by_pair.json",
            "advanced_metrics.json",
            "charts.json",
        }
        json_candidates = sorted(
            [
                path for path in run_dir.glob("*.json")
                if (
                    path.name not in ignored
                    and not path.name.startswith(".")
                    and not path.name.endswith("_config.json")
                    and not path.name.endswith(".meta.json")
                )
            ],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for candidate in json_candidates:
            try:
                raw_result_path.write_bytes(candidate.read_bytes())
                return
            except Exception:
                continue

        root = self.run_repository.backtest_results_root
        last_result_path = root / ".last_result.json"
        if not last_result_path.exists():
            return
        try:
            payload = json.loads(last_result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        latest_name = payload.get("latest_backtest")
        if not latest_name:
            return
        latest_zip = root / latest_name
        if not latest_zip.exists():
            return
        self._extract_freqtrade_zip_result(latest_zip, run_dir)

    def _extract_freqtrade_zip_result(self, zip_path: Path, run_dir: Path) -> bool:
        raw_result_path = run_dir / "raw_result.json"
        native_zip_path = run_dir / "freqtrade_native_result.zip"
        native_meta_path = run_dir / "freqtrade_native_result.meta.json"
        try:
            if zip_path.resolve() != native_zip_path.resolve():
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
                    return False
                preferred = next((name for name in json_members if "_result" not in name), json_members[0])
                with archive.open(preferred) as handle:
                    raw_result_path.write_bytes(handle.read())
            return raw_result_path.exists()
        except Exception:
            return False

    def _next_run_id(self, strategy_name: str, version_id: str, timestamp) -> str:
        strategy_root = self.run_repository.strategy_root(strategy_name)
        strategy_root.mkdir(parents=True, exist_ok=True)
        counters = []
        for run_dir in strategy_root.iterdir():
            if run_dir.is_dir() and run_dir.name.startswith(timestamp.strftime("%Y%m%d")):
                suffix = run_dir.name.rsplit("_bt", maxsplit=1)
                if len(suffix) == 2 and suffix[1].isdigit():
                    counters.append(int(suffix[1]))
        counter = max(counters, default=0) + 1
        return build_run_id(timestamp, strategy_name, version_id, counter)

    def _determine_run_type(self, change_type: str, baseline_run_id: str | None) -> RunType:
        if baseline_run_id is None:
            if change_type in {"parameter", "optimization"}:
                return RunType.CANDIDATE_PARAMETER
            return RunType.BASELINE
        if change_type in {"parameter", "optimization"}:
            return RunType.CANDIDATE_PARAMETER
        return RunType.CANDIDATE_CODE

    def _build_run_config_snapshot(
        self, source_config_file: str, command_config_file: str, pairs: list[str],
        max_open_trades: int, timeframe: str, timerange: str, dry_run_wallet: float,
        source_config: dict, execution_config: dict, local_market_base_url: str | None,
    ) -> dict:
        return {
            "config_file": command_config_file,
            "source_config_file": source_config_file,
            "timerange": timerange, "timeframe": timeframe,
            "pairs": pairs, "max_open_trades": max_open_trades,
            "dry_run_wallet": dry_run_wallet, "config": execution_config,
            "source_config": source_config,
            "local_market_metadata": {
                "enabled": local_market_base_url is not None,
                "base_url": local_market_base_url,
            },
        }

    def _load_config_payload(self, config_file: str) -> dict:
        config_path = Path(config_file)
        if not config_path.exists():
            return {}
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _normalize_pairs_for_config(self, pairs: list[str], config: dict) -> list[str]:
        if config.get("trading_mode") != "futures":
            return pairs

        normalized: list[str] = []
        for pair in pairs:
            text = str(pair or "").strip()
            if not text:
                continue
            if ":" in text:
                normalized.append(text)
                continue
            base_quote = text.split("/", maxsplit=1)
            if len(base_quote) == 2 and base_quote[1]:
                normalized.append(f"{text}:{base_quote[1]}")
            else:
                normalized.append(text)
        return list(dict.fromkeys(normalized))

    def _build_execution_config_payload(
        self,
        *,
        config_payload: dict,
        pairs: list[str],
        timeframe: str,
        max_open_trades: int,
        dry_run_wallet: float,
        market_base_url: str | None = None,
    ) -> dict:
        payload = deepcopy(config_payload) if isinstance(config_payload, dict) else {}
        payload["timeframe"] = timeframe
        payload["dry_run"] = True
        payload["max_open_trades"] = max_open_trades
        payload["dry_run_wallet"] = dry_run_wallet
        payload.setdefault("pairlists", [{"method": "StaticPairList"}])
        payload["pairlists"] = [{"method": "StaticPairList"}]

        exchange = payload.setdefault("exchange", {})
        exchange["pair_whitelist"] = pairs
        exchange.setdefault("key", "")
        exchange.setdefault("secret", "")
        exchange["skip_pair_validation"] = True
        exchange["skip_open_order_update"] = True

        if market_base_url:
            payload["trading_mode"] = "spot"
            payload["margin_mode"] = ""
            ccxt_config = exchange.setdefault("ccxt_config", {})
            options = ccxt_config.setdefault("options", {})
            options["defaultType"] = "spot"
            options["fetchMarkets"] = {"types": ["spot"]}
            options["fetchCurrencies"] = False
            ccxt_config["urls"] = {
                "api": {
                    "public": f"{market_base_url}/api/v3",
                    "private": f"{market_base_url}/api/v3",
                    "sapi": f"{market_base_url}/sapi/v1",
                    "sapiV2": f"{market_base_url}/sapi/v2",
                    "sapiV3": f"{market_base_url}/sapi/v3",
                    "sapiV4": f"{market_base_url}/sapi/v4",
                    "fapiPublic": f"{market_base_url}/fapi/v1",
                    "fapiPrivate": f"{market_base_url}/fapi/v1",
                    "dapiPublic": f"{market_base_url}/dapi/v1",
                    "dapiPrivate": f"{market_base_url}/dapi/v1",
                    "eapiPublic": f"{market_base_url}/eapi/v1",
                    "eapiPrivate": f"{market_base_url}/eapi/v1",
                    "papi": f"{market_base_url}/papi/v1",
                }
            }
            async_config = exchange.setdefault("ccxt_async_config", {})
            async_config["aiohttp_trust_env"] = False
            async_config["enableRateLimit"] = False
            async_config["use_asyncio_dns"] = False

        return payload

    def _should_use_local_binance_markets(self, config_payload: dict, pairs: list[str]) -> bool:
        if not pairs:
            return False
        exchange = config_payload.get("exchange", {}) if isinstance(config_payload, dict) else {}
        trading_mode = str(config_payload.get("trading_mode", "spot")).lower()
        return str(exchange.get("name", "")).lower() == "binance" and trading_mode != "futures"

    def _start_local_binance_exchange_info_server(
        self, pairs: list[str]
    ) -> tuple[ThreadingHTTPServer, threading.Thread, str]:
        payload = json.dumps(self._exchange_info_payload(pairs)).encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.split("?", 1)[0] != "/api/v3/exchangeInfo":
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        return server, thread, base_url

    def _stop_local_market_server(self, server, thread) -> None:
        if server is None:
            return
        try:
            server.shutdown()
            server.server_close()
        finally:
            if thread is not None:
                thread.join(timeout=5)

    def _exchange_info_payload(self, pairs: list[str]) -> dict:
        symbols = []
        for pair in pairs:
            spot_pair = pair.split(":", maxsplit=1)[0]
            if "/" not in spot_pair:
                continue
            base, quote = spot_pair.split("/", maxsplit=1)
            symbols.append({
                "symbol": f"{base}{quote}",
                "status": "TRADING",
                "baseAsset": base,
                "baseAssetPrecision": 8,
                "quoteAsset": quote,
                "quotePrecision": 8,
                "baseCommissionPrecision": 8,
                "quoteCommissionPrecision": 8,
                "orderTypes": ["LIMIT", "LIMIT_MAKER", "MARKET"],
                "icebergAllowed": True,
                "ocoAllowed": True,
                "quoteOrderQtyMarketAllowed": True,
                "isSpotTradingAllowed": True,
                "isMarginTradingAllowed": False,
                "permissions": ["SPOT"],
                "filters": [
                    {
                        "filterType": "PRICE_FILTER",
                        "minPrice": "0.00000001",
                        "maxPrice": "1000000.00000000",
                        "tickSize": "0.00000001",
                    },
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.00000100",
                        "maxQty": "1000000.00000000",
                        "stepSize": "0.00000100",
                    },
                    {
                        "filterType": "MIN_NOTIONAL",
                        "minNotional": "0.00010000",
                        "applyToMarket": True,
                        "avgPriceMins": 5,
                    },
                    {
                        "filterType": "MARKET_LOT_SIZE",
                        "minQty": "0.00000000",
                        "maxQty": "1000000.00000000",
                        "stepSize": "0.00000000",
                    },
                ],
            })
        return {
            "timezone": "UTC",
            "serverTime": 1704067200000,
            "rateLimits": [],
            "exchangeFilters": [],
            "symbols": symbols,
        }

    def _build_strategy_sidecar_json(self, strategy_name: str, params) -> dict:
        payload: dict = {
            "strategy_name": strategy_name,
            "params": {
                "buy": params.buy_params, "sell": params.sell_params,
                "protection": params.protection_params, "roi": params.roi_table,
                "stoploss": {"stoploss": params.stoploss},
                "trailing": {
                    "trailing_stop": params.trailing_stop,
                    "trailing_stop_positive": params.trailing_stop_positive,
                    "trailing_stop_positive_offset": params.trailing_stop_positive_offset,
                    "trailing_only_offset_is_reached": params.trailing_only_offset_is_reached,
                },
            },
        }
        if params.custom_params:
            payload["params"].update(params.custom_params)
        return payload

    def _build_command(self, executable, user_data_dir, config_file, strategy_name,
                       run_dir, timerange, timeframe, pairs, max_open_trades,
                       dry_run_wallet) -> list[str]:
        command = [
            *self._resolve_freqtrade_command(executable),
            "backtesting", "--user-data-dir", user_data_dir,
            "--config", config_file, "--strategy-path", str(run_dir),
            "--strategy", strategy_name, "--timerange", timerange,
            "--timeframe", timeframe,
            "--dry-run-wallet", str(dry_run_wallet),
            "--max-open-trades", str(max_open_trades),
            "--export", "trades", "--backtest-directory", str(run_dir),
        ]
        if pairs:
            # Deduplicate pairs to prevent Freqtrade configuration error
            unique_pairs = list(dict.fromkeys(pairs))  # Preserves order while removing duplicates
            command.extend(["--pairs", *unique_pairs])
        return command

    def _resolve_freqtrade_command(self, executable: str) -> list[str]:
        configured = str(executable or "").strip()
        root_dir = Path(getattr(self.settings_store, "root_dir", Path.cwd())).resolve()

        if configured == "py -m freqtrade":
            for candidate in (
                root_dir / "4t" / "Scripts" / "freqtrade.exe",
                root_dir / ".venv" / "Scripts" / "freqtrade.exe",
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
            rooted = root_dir / exe_path
            if rooted.is_file():
                return [str(rooted)]
        return [configured]
