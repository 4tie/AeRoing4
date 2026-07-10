"""Prove _extract_hyperopt_best works on the real newest .fthypt from the failed run."""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services.auto_quant.pipeline_modules.helpers import config_helpers as mod


def test_extract_real_newest_fthypt():
    real = next(
        p for p in Path("../user_data/hyperopt_results").glob("strategy_AIStrategy_*.fthypt")
        if p.name.endswith("12-51-56.fthypt")
    )
    tmp = Path(tempfile.mkdtemp())
    hr = tmp / "hyperopt_results"
    hr.mkdir()
    shutil.copy(real, hr / real.name)
    out = tmp / "out"
    out.mkdir()

    state = SimpleNamespace(user_data_dir=str(tmp), config_file="x", freqtrade_path="freqtrade")
    orig = mod.subprocess.run
    mod.subprocess.run = lambda *a, **k: SimpleNamespace(stdout="", stderr="blocked")
    try:
        res = asyncio.run(mod._extract_hyperopt_best(state, out))
    finally:
        mod.subprocess.run = orig

    assert res is not None
    assert res["loss"] != 100000, "would have injected penalty params"
    assert len(res["params_dict"]) >= 1
    assert (out / "hyperopt_best.json").exists()
