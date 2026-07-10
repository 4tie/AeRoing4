"""Router: POST /api/data/download

Triggers an asynchronous Freqtrade market-data download.
The endpoint returns immediately with a session_id; callers poll
GET /api/session/status/{session_id} to track progress.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from ...core.errors import BackendError
from ...models import DownloadDataRequest
from ..dependencies import get_services, get_session_store
from ..models import AsyncJobResponse, DataDownloadApiRequest
from ..session_store import SessionStore

router = APIRouter(prefix="/api/data", tags=["Data"])


@router.post(
    "/download",
    response_model=AsyncJobResponse,
    status_code=202,
    summary="Download market data",
    description=(
        "Queues a Freqtrade download-data job for the requested pairs and timeframes. "
        "Returns a session_id immediately; poll /api/session/status/{session_id} for progress."
    ),
)
async def download_data(
    body: DataDownloadApiRequest,
    background_tasks: BackgroundTasks,
    services=Depends(get_services),
    store: SessionStore = Depends(get_session_store),
) -> AsyncJobResponse:
    if services.data_download_runner.is_busy():
        raise HTTPException(
            status_code=409,
            detail="A data download is already running. Wait for it to finish or check its status.",
        )

    record = store.create("data_download")
    background_tasks.add_task(
        _run_download_task, services, store, record.session_id, body
    )
    return AsyncJobResponse(
        session_id=record.session_id,
        status="queued",
        message=(
            f"Data download queued. "
            f"Poll /api/session/status/{record.session_id} for progress."
        ),
    )


async def _run_download_task(
    services,
    store: SessionStore,
    session_id: str,
    body: DataDownloadApiRequest,
) -> None:
    store.update(session_id, status="running", started_at=datetime.now(tz=UTC))
    try:
        settings = services.settings_store.load()
        config_file = body.config_file or settings.default_config_file_path

        internal_request = DownloadDataRequest(
            config_file=config_file,
            timerange=body.timerange,
            timeframes=body.timeframes,
            pairs=body.pairs,
            prepend=body.prepend,
        )

        download_id: str = await asyncio.to_thread(
            services.data_download_runner.run_download, internal_request
        )

        store.update(
            session_id,
            status="completed",
            completed_at=datetime.now(tz=UTC),
            result={
                "download_id": download_id,
                "command": services.data_download_runner.last_command,
                "pairs": body.pairs,
                "timeframes": body.timeframes,
                "timerange": body.timerange,
            },
        )
    except BackendError as exc:
        store.update(
            session_id,
            status="failed",
            completed_at=datetime.now(tz=UTC),
            error=exc.message,
        )
    except Exception as exc:
        store.update(
            session_id,
            status="failed",
            completed_at=datetime.now(tz=UTC),
            error=str(exc),
        )
