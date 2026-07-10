"""Top-level ASGI entry point for the Strategy Lab backend API.

Development
-----------
    .venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload

Production (direct)
-------------------
    python server.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
VENV_DIR = ROOT_DIR / ".venv"
VENV_BIN_DIR = VENV_DIR / ("Scripts" if os.name == "nt" else "bin")
VENV_PYTHON = VENV_BIN_DIR / ("python.exe" if os.name == "nt" else "python")


def _running_from_project_venv() -> bool:
    try:
        return Path(sys.prefix).resolve() == VENV_DIR.resolve()
    except OSError:
        return False


def _started_by_uvicorn() -> bool:
    argv0 = str(Path(sys.argv[0])).lower()
    return "uvicorn" in argv0


def _bootstrap_project_venv() -> None:
    if os.environ.get("STRATEGY_LAB_SKIP_VENV_BOOTSTRAP") == "1":
        return
    if _running_from_project_venv() or not VENV_PYTHON.exists():
        return
    if __name__ != "__main__" and not _started_by_uvicorn():
        return

    os.environ["VIRTUAL_ENV"] = str(VENV_DIR)
    os.environ["PATH"] = f"{VENV_BIN_DIR}{os.pathsep}{os.environ.get('PATH', '')}"

    if _started_by_uvicorn():
        os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), "-m", "uvicorn", *sys.argv[1:]])
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])


_bootstrap_project_venv()

from dotenv import load_dotenv
import asyncio
import uvicorn

from backend.api.app import create_app

load_dotenv()

# Windows requires ProactorEventLoop for subprocess support
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host=os.getenv("BACKEND_HOST", "0.0.0.0"),
        port=int(os.getenv("BACKEND_PORT", "8000")),
        reload=False,
    )
