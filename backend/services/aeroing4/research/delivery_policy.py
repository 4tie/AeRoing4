"""Versioned Delivery policy for the AeRoing4 pipeline (PROMPT 12 §1–§7).

Delivery is PACKAGING, not validation. It never promotes/demotes a Champion, never
mutates strategy/params, never reruns tests, and never marks real verification as true.

Default export profile is RUN-LOCAL only (constraint #1). Export into a live Freqtrade
strategies folder is explicit and never silently overwrites (constraint #2).
"""

from __future__ import annotations

from enum import Enum


class DeliveryStatus(str, Enum):
    """Delivery answers 'can this verified champion be packaged safely?'
    It is NOT a PASS/FAIL — that belongs to Final Unseen."""

    BLOCKED = "blocked"
    READY = "ready"
    DELIVERED = "delivered"
    REUSED = "reused"
    EXPORT_FAILED = "export_failed"


DELIVERY_POLICY_VERSION = "1.0.0"


class DeliveryPolicy:
    """Versioned, safe-by-default delivery policy."""

    policy_version: str = DELIVERY_POLICY_VERSION
    # Default export target is run-local only — never the live Freqtrade folder.
    default_export_profile: str = "run_local"
    # When exporting to freqtrade_user_data, require either versioned filenames
    # or explicit overwrite approval. Silent overwrite is forbidden.
    force_overwrite_default: bool = False
    allowed_profiles: tuple[str, ...] = ("run_local", "freqtrade_user_data")
