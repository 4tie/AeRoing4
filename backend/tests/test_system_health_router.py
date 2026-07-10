"""Regression tests for system health router contracts."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from backend.api.routers import system_health


def _services(tmp_path, settings):
    return SimpleNamespace(
        root_dir=tmp_path,
        settings_store=SimpleNamespace(load=lambda: settings),
    )


def _settings(tmp_path):
    return SimpleNamespace(
        freqtrade_executable_path="freqtrade",
        strategies_directory_path=str(tmp_path / "user_data" / "strategies"),
        user_data_directory_path=str(tmp_path / "user_data"),
    )


def _response_body(response):
    return json.loads(response.body.decode("utf-8"))


def test_system_health_returns_200_when_all_checks_pass(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    (tmp_path / "data" / "backups").mkdir(parents=True)
    (tmp_path / "user_data" / "strategies").mkdir(parents=True)

    async def fake_collect_health(_settings, _root_dir):
        return {
            "ok": True,
            "elapsed_ms": 3,
            "checks": [{"label": "Freqtrade CLI", "ok": True}],
            "log": "Overall: PASS",
        }

    monkeypatch.setattr(system_health, "_collect_health", fake_collect_health)

    response = asyncio.run(system_health.system_health(_services(tmp_path, settings)))
    body = _response_body(response)

    assert response.status_code == 200
    assert body["ok"] is True
    assert body["log"] == "Overall: PASS"


def test_system_health_returns_207_when_any_check_fails(tmp_path, monkeypatch):
    settings = _settings(tmp_path)

    async def fake_collect_health(_settings, _root_dir):
        return {
            "ok": False,
            "elapsed_ms": 5,
            "checks": [{"label": "Freqtrade CLI", "ok": False}],
            "log": "Overall: FAIL",
        }

    monkeypatch.setattr(system_health, "_collect_health", fake_collect_health)

    response = asyncio.run(system_health.system_health(_services(tmp_path, settings)))
    body = _response_body(response)

    assert response.status_code == 207
    assert body["ok"] is False
    assert body["checks"][0]["ok"] is False


def test_build_log_keeps_pass_fail_summary():
    log = system_health._build_log(
        [{"label": "Data", "ok": False, "detail": "Does not exist"}],
        12,
    )

    assert "Data" in log
    assert "Does not exist" in log
    assert "Overall: FAIL" in log
