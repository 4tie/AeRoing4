"""Router: /api/pairs

Exposes the PairSelectorService — both read and write operations.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...app_services import AppServices
from ...models import (
    RandomizePairsRequest,
    SearchPairsRequest,
    SelectPairRequest,
    ToggleFavoriteRequest,
    ToggleLockRequest,
    UpdateMaxTradesRequest,
)
from ..dependencies import get_services

router = APIRouter(prefix="/api/pairs", tags=["Pairs"])


def _state_response(services) -> dict:
    state = services.pair_selector.get_state()
    return {
        "available_pairs": state.available_pairs,
        "selected_pairs": state.selected_pairs,
        "max_open_trades": state.max_open_trades,
        "favorite_pairs": sorted(state.favorite_pairs),
        "locked_pairs": sorted(state.locked_pairs),
    }


@router.get("", summary="Get full pair selector state")
async def get_pairs(services: AppServices = Depends(get_services)) -> dict:
    return _state_response(services)


@router.get("/search", summary="Search available pairs")
async def search_pairs(
    q: str,
    services: AppServices = Depends(get_services),
) -> dict:
    result = services.pair_selector.search_pairs(SearchPairsRequest(search_term=q))
    return {
        "matches": result.favorites + result.other_pairs,
        "favorites": result.favorites,
        "other_pairs": result.other_pairs,
        "total_count": result.total_count,
    }


@router.post("/toggle-favorite", summary="Toggle favorite status of a pair")
async def toggle_favorite(
    body: dict,
    services: AppServices = Depends(get_services),
) -> dict:
    try:
        services.pair_selector.toggle_favorite(ToggleFavoriteRequest(**body))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _state_response(services)


@router.post("/toggle-lock", summary="Toggle lock status of a pair")
async def toggle_lock(
    body: dict,
    services: AppServices = Depends(get_services),
) -> dict:
    try:
        services.pair_selector.toggle_lock(ToggleLockRequest(**body))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _state_response(services)


@router.post("/toggle-select", summary="Select or deselect a pair")
async def toggle_select(
    body: dict,
    services: AppServices = Depends(get_services),
) -> dict:
    try:
        services.pair_selector.select_pair(SelectPairRequest(**body))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _state_response(services)


@router.post("/randomize", summary="Randomize pair selection")
async def randomize_pairs(
    body: dict | None = None,
    services: AppServices = Depends(get_services),
) -> dict:
    try:
        req = RandomizePairsRequest(**(body or {}))
        services.pair_selector.randomize_pairs(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _state_response(services)


@router.post("/update-max-trades", summary="Update max open trades limit")
async def update_max_trades(
    body: dict,
    services: AppServices = Depends(get_services),
) -> dict:
    try:
        services.pair_selector.update_max_trades(UpdateMaxTradesRequest(**body))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _state_response(services)


@router.post("/clear", summary="Clear all non-locked selected pairs")
async def clear_selection(services: AppServices = Depends(get_services)) -> dict:
    services.pair_selector.clear_selection()
    return _state_response(services)


@router.post("/set-selected", summary="Set selected pairs to an explicit list")
async def set_selected(
    body: dict,
    services: AppServices = Depends(get_services),
) -> dict:
    pairs = body.get("pairs", [])
    if not isinstance(pairs, list):
        raise HTTPException(status_code=400, detail="pairs must be a list")
    services.pair_selector.set_selected(pairs)
    return _state_response(services)
