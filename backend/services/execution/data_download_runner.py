"""Synchronous data download runner — NO async/await, NO asyncio.

Downloads market data by spawning a freqtrade subprocess and capturing
its stdout/stderr. Threading is used internally for log piping.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Callable

from ...core.errors import BackendError
from ...models import DownloadDataRequest
from ...settings_store import SettingsStore
from ...utils import append_text, atomic_write_json, atomic_write_text, utc_now


class DataDownloadRunner:
    """DataDownloadRunner contains class-level backend logic."""
    def __init__(self, settings_store: SettingsStore, downloads_root: Path) -> None:
        self.settings_store = settings_store
        self.downloads_root = downloads_root
        self.active_download_id: str | None = None
        self.active_process: subprocess.Popen | None = None
        self._running = False
        self.last_command: str = ""
        self.last_status: dict[str, str | bool | None] = {
            "download_id": None,
            "status": "idle",
            "prepend": False,
            "log_path": None,
            "error": None,
        }
        self.log_callback: Callable[[str], None] | None = None

    def is_busy(self) -> bool:
        return self._running

    def current_status(self) -> dict[str, str | bool | None]:
        return dict(self.last_status)

    def set_log_callback(self, callback: Callable[[str], None] | None) -> None:
        self.log_callback = callback

    def run_download(self, request: DownloadDataRequest) -> str:
        """Download data synchronously.

        Args:
            request: DownloadDataRequest with config, timerange, timeframes, pairs.

        Returns:
            The download_id.
        """
        if self.is_busy():
            raise BackendError("Data download runner is busy.", status_code=409)

        settings = self.settings_store.load()
        now = utc_now()
        download_id = f"download_{now:%Y%m%d_%H%M%S}"
        log_path = self.downloads_root / f"{download_id}.log"
        self.downloads_root.mkdir(parents=True, exist_ok=True)

        status: dict[str, str | bool | None] = {
            "download_id": download_id,
            "status": "running",
            "prepend": request.prepend,
            "log_path": str(log_path),
            "error": None,
        }
        self.last_status = status
        self.active_download_id = download_id
        self._running = True

        try:
            # Build and run the freqtrade download-data command
            # Handle "py -m freqtrade" command by splitting it
            if settings.freqtrade_executable_path == "py -m freqtrade":
                command = [
                    "py", "-m", "freqtrade",
                    "download-data",
                    "--user-data-dir",
                    settings.user_data_directory_path,
                    "--config",
                    request.config_file,
                ]
            else:
                command = [
                    settings.freqtrade_executable_path,
                    "download-data",
                    "--user-data-dir",
                    settings.user_data_directory_path,
                    "--config",
                    request.config_file,
                ]
            if request.timerange:
                command.extend(["--timerange", request.timerange])
            if request.timeframes:
                command.extend(["--timeframes", *request.timeframes])
            if request.pairs:
                command.extend(["--pairs", *request.pairs])
            if request.prepend:
                command.append("--prepend")

            self.last_command = subprocess.list2cmdline(command)
            append_text(log_path, f"[COMMAND]: {self.last_command}\n")
            if self.log_callback is not None:
                try:
                    self.log_callback(f"[COMMAND]: {self.last_command}")
                except Exception:
                    pass

            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.active_process = process

            # Pipe logs to file and callback
            threads: list[threading.Thread] = []
            for stream, channel in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                if stream is None:
                    continue
                thread = threading.Thread(
                    target=self._pipe_logs_sync,
                    args=(stream, log_path, channel),
                    daemon=True,
                )
                thread.start()
                threads.append(thread)

            return_code = process.wait()
            for thread in threads:
                thread.join(timeout=5)

            if return_code != 0:
                error_msg = f"Download process exited with code {return_code}"
                append_text(log_path, f"stderr: {error_msg}\n")
                status["status"] = "failed"
                status["error"] = error_msg
                self.last_status = status
                raise BackendError(error_msg, status_code=500)

            append_text(log_path, "stdout: Data download completed successfully.\n")
            status["status"] = "completed"
            self.last_status = status
            return download_id

        except BackendError:
            raise
        except Exception as exc:
            error_msg = str(exc)
            append_text(log_path, f"stderr: {error_msg}\n")
            status["status"] = "failed"
            status["error"] = error_msg
            self.last_status = status
            raise BackendError(f"Data download failed: {error_msg}", status_code=500)

        finally:
            self._running = False
            self.active_process = None

    def cancel(self) -> None:
        """Cancel the active download."""
        if self.active_process is not None:
            # Strict kill sequence to prevent zombie processes
            if self.active_process.poll() is None:  # Process is still alive
                self.active_process.kill()  # Force close (SIGKILL)
                try:
                    self.active_process.wait(timeout=1.0)
                except Exception:
                    pass  # Ignore timeout errors
            self.active_process = None
        self._running = False
        self.last_status["status"] = "cancelled"
        if self.log_callback:
            try:
                self.log_callback("stdout: Data download cancelled.\n")
            except Exception:
                pass

    def _pipe_logs_sync(self, stream, log_path: Path, channel: str) -> None:
        if stream is None:
            return
        while True:
            chunk = stream.readline()
            if not chunk:
                break
            text = chunk.decode(errors="replace")
            append_text(log_path, f"{channel}: {text}")
            if self.log_callback is not None:
                try:
                    self.log_callback(f"{channel}: {text}")
                except Exception:
                    pass