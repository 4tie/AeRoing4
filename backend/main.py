"""Direct backend entrypoint.

The project no longer starts a local server from `backend.main`.  This file is
kept as a small command-line friendly entrypoint so old direct module invocations
fail less abruptly while the desktop app moves to `backend.runtime.create_services`.
"""

from __future__ import annotations

from .runtime import create_services


def main() -> int:
    """Create the backend service graph and print a small readiness summary."""

    services = create_services()
    strategy_count = len(services.registry.list_strategies())
    run_count = len(services.list_runs())
    print(f"Backend services ready: {strategy_count} strategies, {run_count} runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
