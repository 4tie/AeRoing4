"""Shared FastAPI dependencies for API routers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

from ..models import SettingsModel
from .log_broadcaster import LogBroadcaster
from .session_store import SessionStore

if TYPE_CHECKING:
    from ..app_services import AppServices


def get_services(request: Request) -> "AppServices":
    """Return the initialized backend service graph."""
    return request.app.state.services


def get_settings(request: Request) -> SettingsModel:
    """Return the currently persisted application settings."""
    return get_services(request).settings_store.load()


def get_session_store(request: Request) -> SessionStore:
    """Return the disk-backed background job store."""
    return request.app.state.session_store


def get_log_broadcaster(request: Request) -> LogBroadcaster:
    """Return the process-wide log broadcaster used by SSE clients."""
    return request.app.state.log_broadcaster
