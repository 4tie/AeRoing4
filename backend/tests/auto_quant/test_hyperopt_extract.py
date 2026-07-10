"""Tests for hyperopt result extraction (_parse_fthypt_file / _extract_hyperopt_best)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services.auto_quant.pipeline_modules.helpers.config_helpers import (
    _parse_fthypt_file,
)


def _write_fthypt(tmp_path: Path, epochs: list[dict]) -> Path:
    p = tmp_path / "strategy_Foo_2026-01-01_00-00-00.fthypt"
    p.write_text("\n".join(json.dumps(e) for e in epochs), encoding="utf-8")
    return p


def test_parse_picks_is_best_epoch(tmp_path: Path):
    good = {
        "loss": 1.23,
        "params_dict": {"buy_ma_count": 5, "stoploss": -0.1},
        "is_best": True,
    }
    bad = {"loss": 5.0, "params_dict": {"buy_ma_count": 1}, "is_best": False}
    path = _write_fthypt(tmp_path, [bad, good, bad])
    res = _parse_fthypt_file(path)
    assert res is not None
    assert res["loss"] == 1.23
    assert res["params_dict"]["buy_ma_count"] == 5


def test_parse_falls_back_to_lowest_loss_when_no_is_best(tmp_path: Path):
    best = {"loss": 0.5, "params_dict": {"a": 1}}
    others = [{"loss": 9.0, "params_dict": {"a": 2}}, {"loss": 3.0, "params_dict": {"a": 3}}]
    path = _write_fthypt(tmp_path, others + [best])
    res = _parse_fthypt_file(path)
    assert res["loss"] == 0.5


def test_parse_skips_malformed_lines(tmp_path: Path):
    path = _write_fthypt(tmp_path, [{"loss": 2.0, "params_dict": {"x": 1}}])
    # Append a corrupted line
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\nthis is not json\n")
    res = _parse_fthypt_file(path)
    assert res is not None
    assert res["params_dict"]["x"] == 1


def test_parse_single_object_with_results_array(tmp_path: Path):
    obj = {
        "results": [
            {"loss": 4.0, "params_dict": {"a": 9}},
            {"loss": 0.1, "params_dict": {"a": 1, "stoploss": -0.2}},
        ]
    }
    p = tmp_path / "strategy_Single.fthypt"
    p.write_text(json.dumps(obj), encoding="utf-8")
    res = _parse_fthypt_file(p)
    assert res is not None
    assert res["params_dict"]["a"] == 1


def test_parse_penalty_only_returns_best_penalty_epoch(tmp_path: Path):
    # All epochs are freqtrade penalty (loss=100000) — we still return the
    # (least-bad) epoch rather than None, so callers can detect the failure.
    path = _write_fthypt(
        tmp_path,
        [
            {"loss": 100000, "params_dict": {"a": 1}},
            {"loss": 100000, "params_dict": {"a": 2}},
        ],
    )
    res = _parse_fthypt_file(path)
    assert res is not None
    assert res["loss"] == 100000


def test_zero_trades_guard_ignores_absent_key(tmp_path: Path):
    # freqtrade 2026.6 .fthypt epochs omit top-level "total_trades" entirely
    # (trades live under results_metrics). Absence must NOT be read as 0 trades.
    path = _write_fthypt(
        tmp_path,
        [{"loss": 1.2, "params_dict": {"a": 1}, "is_best": True}],
    )
    res = _parse_fthypt_file(path)
    assert res is not None
    assert res["params_dict"]["a"] == 1


def test_zero_trades_guard_fires_when_present_and_zero(tmp_path: Path):
    path = _write_fthypt(
        tmp_path,
        [{"loss": 100000, "params_dict": {}, "total_trades": 0},
         {"loss": 100000, "params_dict": {}, "total_trades": 0}],
    )
    assert _parse_fthypt_file(path) is None


def test_extract_via_fthypt_file(tmp_path: Path):
    """End-to-end: _extract_hyperopt_best reads the real .fthypt file."""
    from backend.services.auto_quant.pipeline_modules.helpers.config_helpers import (
        _extract_hyperopt_best,
    )

    # Write a result file in a fake hyperopt_results dir
    hyper_dir = tmp_path / "hyperopt_results"
    hyper_dir.mkdir()
    (hyper_dir / "strategy_Foo.fthypt").write_text(
        json.dumps({"loss": 0.7, "params_dict": {"buy_ma_count": 4, "stoploss": -0.15}, "is_best": True}),
        encoding="utf-8",
    )

    state = SimpleNamespace(
        user_data_dir=str(tmp_path),
        config_file="ignored",
        freqtrade_path="freqtrade",
    )
    # out_dir must exist for hyperopt_best.json save
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    # Patch hyperopt-show away so Method 2 cannot interfere (it would fail to spawn).
    import backend.services.auto_quant.pipeline_modules.helpers.config_helpers as mod

    orig_run = mod.subprocess.run
    mod.subprocess.run = lambda *a, **k: SimpleNamespace(stdout="", stderr="cmd not found")
    try:
        res = asyncio.run(mod._extract_hyperopt_best(state, out_dir))
    finally:
        mod.subprocess.run = orig_run

    assert res is not None
    assert res["params_dict"]["buy_ma_count"] == 4
