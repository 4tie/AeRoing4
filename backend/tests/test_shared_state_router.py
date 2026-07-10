"""Regression tests for shared frontend state router contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.api.routers import shared_state


def _services(root_dir):
    return SimpleNamespace(root_dir=root_dir)


def test_get_shared_state_returns_empty_object_when_file_is_missing(tmp_path):
    body = asyncio.run(shared_state.get_shared_state(_services(tmp_path)))

    assert body == {}
    assert (tmp_path / "user_data").exists()


def test_update_shared_state_merges_existing_values_and_normalizes_pairs(tmp_path):
    services = _services(tmp_path)

    first = asyncio.run(
        shared_state.update_shared_state(
            shared_state.SharedStatePayload(
                strategy_name="DemoStrategy",
                pairs="btc/usdt, eth/usdt",
                max_open_trades=2,
            ),
            services,
        )
    )
    second = asyncio.run(
        shared_state.update_shared_state(
            shared_state.SharedStatePayload(timeframe="1h"),
            services,
        )
    )

    assert first["pairs"] == ["BTC/USDT", "ETH/USDT"]
    assert second == {
        "strategy_name": "DemoStrategy",
        "pairs": ["BTC/USDT", "ETH/USDT"],
        "max_open_trades": 2,
        "timeframe": "1h",
    }


def test_shared_state_rejects_invalid_pairs_payload():
    with pytest.raises(ValidationError):
        shared_state.SharedStatePayload(pairs=123)
