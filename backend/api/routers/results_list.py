"""Router: GET /api/results

Lists all completed backtest runs with lightweight summary info,
suitable for a results table view.
"""

from __future__ import annotations

import time as _time

from fastapi import APIRouter, Depends

from ...app_services import AppServices
from ...services.results import api_service as results_api
from ..dependencies import get_services
from ..models import ResultListItem, ResultListResponse

router = APIRouter(prefix="/api", tags=["Results"])

# ── In-memory TTL cache to avoid O(n) directory scans on every layout switch ──
_CACHE_TTL_SECS = 30.0
_results_cache: dict = {"data": None, "ts": 0.0}


def invalidate_results_cache() -> None:
    """Call this after a new backtest completes to force a fresh scan."""
    _results_cache["data"] = None
    _results_cache["ts"] = 0.0


_result_item_payload = results_api.result_item_payload


@router.get(
    "/results",
    response_model=ResultListResponse,
    summary="List all backtest results",
    description="Returns a lightweight list of completed backtest runs with parsed summaries.",
)
async def list_results(
    services: AppServices = Depends(get_services),
) -> ResultListResponse:
    now = _time.monotonic()
    if _results_cache["data"] is not None and (now - _results_cache["ts"]) < _CACHE_TTL_SECS:
        return _results_cache["data"]

    repo = services.run_repository

    runs = repo.list_runs()
    items: list[ResultListItem] = []

    for metadata in runs:
        # Skip runs that haven't completed
        if metadata.run_status != "completed":
            continue

        run_dir = repo.find_run_dir(metadata.run_id)
        items.append(ResultListItem.model_validate(_result_item_payload(metadata, run_dir)))

    result = ResultListResponse(results=items)
    _results_cache["data"] = result
    _results_cache["ts"] = now
    return result
