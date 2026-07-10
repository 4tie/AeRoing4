"""Process-wide shared lock registry for Research Memory stores.

Provides process-wide locking keyed by canonical resolved file path to ensure
that multiple store instances targeting the same file cannot corrupt data
through concurrent writes. This is necessary because stores are designed to
be instantiated directly with a runs_root path, and each instance previously
had its own threading.Lock() which did not protect against multi-instance
concurrent access.

The registry uses a module-level dict of threading.Lock instances keyed by
the canonical resolved file path. All store instances in the same process
that target the same file will share the same lock.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict

# Module-level lock registry: canonical_path -> threading.Lock
_lock_registry: Dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()


def get_lock_for_path(file_path: Path) -> threading.Lock:
    """Get or create a shared lock for the canonical resolved file path.

    Args:
        file_path: The file path to lock (will be resolved to canonical form)

    Returns:
        A threading.Lock that is shared across all store instances targeting
        the same canonical file path within this process.
    """
    # Resolve to canonical absolute path to ensure different Path objects
    # referring to the same file share the same lock
    canonical_path = str(file_path.resolve())

    with _registry_lock:
        if canonical_path not in _lock_registry:
            _lock_registry[canonical_path] = threading.Lock()
        return _lock_registry[canonical_path]


def clear_registry() -> None:
    """Clear the lock registry.

    This is primarily useful for tests to ensure isolation between test cases.
    Production code should not need to call this.
    """
    with _registry_lock:
        _lock_registry.clear()
