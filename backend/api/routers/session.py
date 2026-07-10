"""Router: GET /api/session/status/{session_id}  &  GET /api/session/list

Universal polling endpoint so any frontend can check whether a queued,
running, completed, or failed background job is done — without knowing
which specific runner it belongs to.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import get_session_store
from ..models import SessionListResponse, SessionStatusResponse
from ..session_store import SessionRecord, SessionStore

router = APIRouter(prefix="/api/session", tags=["Session"])


def _to_response(record: SessionRecord) -> SessionStatusResponse:
    return SessionStatusResponse(
        session_id=record.session_id,
        operation=record.operation,
        status=record.status,
        created_at=record.created_at.isoformat(),
        started_at=record.started_at.isoformat() if record.started_at else None,
        completed_at=record.completed_at.isoformat() if record.completed_at else None,
        result=record.result,
        error=record.error,
    )


@router.get(
    "/status/{session_id}",
    response_model=SessionStatusResponse,
    summary="Poll a background job",
    description=(
        "Returns the current state of any background job (download, backtest, "
        "optimizer, stress-lab) created in this server session. "
        "Possible statuses: queued | running | completed | failed | cancelled."
    ),
)
async def get_session_status(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> SessionStatusResponse:
    record = store.get(session_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found. It may belong to a previous server run.",
        )
    return _to_response(record)


@router.get(
    "/list",
    response_model=SessionListResponse,
    summary="List all background jobs",
    description="Returns every session created since the server started, newest first.",
)
async def list_sessions(
    store: SessionStore = Depends(get_session_store),
) -> SessionListResponse:
    records = sorted(store.list_all(), key=lambda r: r.created_at, reverse=True)
    return SessionListResponse(sessions=[_to_response(r) for r in records])
