"""Regression tests for pair selector router contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api.routers import pairs as pairs_router
from backend.models import PairListResponse, PairSelectorState


class FakePairSelector:
    def __init__(self) -> None:
        self.state = PairSelectorState(
            available_pairs=["BTC/USDT", "ETH/USDT", "SOL/USDT"],
            selected_pairs=["BTC/USDT"],
            favorite_pairs={"ETH/USDT"},
            locked_pairs={"BTC/USDT"},
            max_open_trades=2,
        )
        self.calls: list[tuple[str, object]] = []

    def get_state(self) -> PairSelectorState:
        return self.state

    def search_pairs(self, request) -> PairListResponse:
        self.calls.append(("search_pairs", request))
        return PairListResponse(
            favorites=["ETH/USDT"],
            other_pairs=["BTC/USDT"],
            total_count=2,
        )

    def toggle_favorite(self, request) -> PairSelectorState:
        self.calls.append(("toggle_favorite", request))
        return self.state

    def toggle_lock(self, request) -> PairSelectorState:
        self.calls.append(("toggle_lock", request))
        return self.state

    def select_pair(self, request) -> PairSelectorState:
        self.calls.append(("select_pair", request))
        return self.state

    def randomize_pairs(self, request) -> PairSelectorState:
        self.calls.append(("randomize_pairs", request))
        return self.state

    def update_max_trades(self, request) -> PairSelectorState:
        self.calls.append(("update_max_trades", request))
        return self.state

    def clear_selection(self) -> PairSelectorState:
        self.calls.append(("clear_selection", None))
        return self.state

    def set_selected(self, selected_pairs: list[str]) -> PairSelectorState:
        self.calls.append(("set_selected", selected_pairs))
        self.state.selected_pairs = selected_pairs
        return self.state


def _services(selector: FakePairSelector | None = None) -> SimpleNamespace:
    return SimpleNamespace(pair_selector=selector or FakePairSelector())


def test_get_pairs_returns_frontend_state_shape():
    body = asyncio.run(pairs_router.get_pairs(_services()))

    assert body == {
        "available_pairs": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        "selected_pairs": ["BTC/USDT"],
        "max_open_trades": 2,
        "favorite_pairs": ["ETH/USDT"],
        "locked_pairs": ["BTC/USDT"],
    }


def test_search_pairs_preserves_match_buckets():
    selector = FakePairSelector()
    body = asyncio.run(pairs_router.search_pairs("usdt", _services(selector)))

    assert body == {
        "matches": ["ETH/USDT", "BTC/USDT"],
        "favorites": ["ETH/USDT"],
        "other_pairs": ["BTC/USDT"],
        "total_count": 2,
    }
    assert selector.calls[0][0] == "search_pairs"
    assert selector.calls[0][1].search_term == "usdt"


@pytest.mark.parametrize(
    ("handler", "body", "call_name"),
    [
        (pairs_router.toggle_favorite, {"pair": "ETH/USDT"}, "toggle_favorite"),
        (pairs_router.toggle_lock, {"pair": "ETH/USDT"}, "toggle_lock"),
        (pairs_router.toggle_select, {"pair": "ETH/USDT", "selected": True}, "select_pair"),
        (pairs_router.update_max_trades, {"max_open_trades": 2}, "update_max_trades"),
    ],
)
def test_mutation_routes_return_updated_state(handler, body, call_name):
    selector = FakePairSelector()
    response = asyncio.run(handler(body, _services(selector)))

    assert response["selected_pairs"] == ["BTC/USDT"]
    assert selector.calls[0][0] == call_name


def test_randomize_accepts_empty_body_for_existing_clients():
    selector = FakePairSelector()
    response = asyncio.run(pairs_router.randomize_pairs(None, _services(selector)))

    assert response["available_pairs"] == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    assert selector.calls[0][0] == "randomize_pairs"
    assert selector.calls[0][1].preserve_locked is True


def test_set_selected_rejects_non_list_payload():
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(pairs_router.set_selected({"pairs": "BTC/USDT"}, _services()))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "pairs must be a list"


def test_value_errors_are_mapped_to_bad_request():
    selector = FakePairSelector()
    selector.toggle_favorite = lambda _request: (_ for _ in ()).throw(ValueError("bad pair"))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(pairs_router.toggle_favorite({"pair": "NOPE/USDT"}, _services(selector)))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "bad pair"
