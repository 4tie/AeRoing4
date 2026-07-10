"""Router: GET /api/shared-state  &  POST /api/shared-state

Simple JSON-backed shared state used by the frontend to persist the
Backtesting Tab form values between sessions.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from ...app_services import AppServices
from ...services.shared_state import api_service as shared_state_api
from ..dependencies import get_services

router = APIRouter(prefix="/api/shared-state", tags=["Shared State"])

# ── Pydantic models ────────────────────────────────────────────────────────────


class SharedStatePayload(BaseModel):
    strategy_name: str | None = Field(default=None)
    timeframe: str | None = Field(default=None)
    timerange: str | None = Field(default=None)
    start_date: str | None = Field(default=None)
    end_date: str | None = Field(default=None)
    pairs: list[str] | None = Field(default=None)
    max_open_trades: int | None = Field(default=None)
    dry_run_wallet: float | None = Field(default=None)

    @field_validator("pairs", mode="before")
    @classmethod
    def validate_pairs(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, str):
            items = v.split(",")
        elif isinstance(v, list):
            items = v
        else:
            raise ValueError("pairs must be a list or comma-separated string.")
        cleaned = [str(item).strip().upper() for item in items if str(item).strip()]
        return cleaned or None


_state_file_path = shared_state_api.state_file_path
_load_state = shared_state_api.load_state
_update_state = shared_state_api.update_state


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.get(
    "",
    summary="Get shared state",
    description="Returns the current persisted shared state for the Backtesting Tab.",
)
async def get_shared_state(
    services: AppServices = Depends(get_services),
) -> dict[str, Any]:
    path = _state_file_path(services.root_dir)
    return _load_state(path)


@router.post(
    "",
    summary="Update shared state",
    description=(
        "Partially or fully replaces the persisted shared state. "
        "Any fields you supply overwrite existing values; omitted fields stay unchanged."
    ),
)
async def update_shared_state(
    body: SharedStatePayload,
    services: AppServices = Depends(get_services),
) -> dict[str, Any]:
    path = _state_file_path(services.root_dir)
    payload = body.model_dump(mode="json", exclude_none=True)
    return _update_state(path, payload)
