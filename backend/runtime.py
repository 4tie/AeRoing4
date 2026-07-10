"""Direct backend runtime composition for desktop callers.

Desktop code should call `create_services()` to receive an `AppServices`
object, then call service methods directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app_services import AppServices


def _resolve_root(root_dir: Path | None = None) -> Path:
    return root_dir or Path(__file__).resolve().parent.parent


def _build_services(root_dir: Path) -> "AppServices":
    from .app_services import AppServices
    return AppServices(root_dir)


def create_services(root_dir: Path | None = None) -> "AppServices":
    """Build and return the full backend service graph.

    Args:
        root_dir: Optional project root.  When omitted, the root is inferred as
            the parent directory of the `backend` package.

    Returns:
        A ready-to-use `AppServices` instance with settings, paths, runners,
        stores, and strategy services wired together.
    """
    return _build_services(_resolve_root(root_dir))