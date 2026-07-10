"""Run-local strategy variant management for AutoQuant.

The original user strategy is treated as immutable after a run starts. Freqtrade
is pointed at a run-local strategy directory via --strategy-path, and all
mutations/validation variants are written there.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any


def variant_dir(state: Any) -> Path:
    if getattr(state, "strategy_runtime_dir", None):
        return Path(state.strategy_runtime_dir)
    return Path(state.user_data_dir) / "auto_quant" / state.run_id / "strategies"


def strategy_source_path(state: Any, strategy_name: str | None = None) -> Path:
    return variant_dir(state) / f"{strategy_name or state.strategy}.py"


def active_strategy_path(state: Any, strategy_name: str | None = None) -> Path:
    """Return the run-local strategy path when present, else the legacy path."""
    run_local = strategy_source_path(state, strategy_name)
    if run_local.exists():
        return run_local
    return Path(state.user_data_dir) / "strategies" / f"{strategy_name or state.strategy}.py"


def strategy_path_args(state: Any) -> list[str]:
    """Freqtrade CLI args that point at run-local strategy variants."""
    runtime_dir = getattr(state, "strategy_runtime_dir", None)
    return ["--strategy-path", runtime_dir] if runtime_dir else []


def read_strategy_source(state: Any, strategy_name: str | None = None) -> str:
    return active_strategy_path(state, strategy_name).read_text(encoding="utf-8")


def ensure_working_copy(state: Any, out_dir: Path) -> Path:
    """Copy the immutable source strategy into the run-local strategy dir."""
    runtime_dir = out_dir / "strategies"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    state.strategy_runtime_dir = str(runtime_dir)

    original_strategy = getattr(state, "original_strategy", None) or state.strategy
    state.original_strategy = original_strategy

    source_path = Path(state.user_data_dir) / "strategies" / f"{original_strategy}.py"
    if not source_path.exists():
        raise FileNotFoundError(f"Strategy file not found: {source_path}")

    source_bytes = source_path.read_bytes()
    state.original_strategy_hash = hashlib.sha256(source_bytes).hexdigest()

    working_path = runtime_dir / f"{original_strategy}.py"
    if not working_path.exists():
        working_path.write_bytes(source_bytes)

    versioned_working = runtime_dir / f"{original_strategy}_working_v1.py"
    if not versioned_working.exists():
        versioned_working.write_bytes(source_bytes)

    _record_variant(
        state,
        role="working",
        strategy_name=original_strategy,
        path=working_path,
        source=str(source_path),
    )
    _write_manifest(state)
    return working_path


def create_variant(
    state: Any,
    *,
    role: str,
    strategy_name: str,
    source: str,
    versioned: bool = True,
) -> Path:
    runtime_dir = variant_dir(state)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    path = runtime_dir / f"{strategy_name}.py"
    path.write_text(source, encoding="utf-8")

    if versioned:
        version = _next_role_version(runtime_dir, strategy_name, role)
        versioned_path = runtime_dir / f"{strategy_name}_{role}_v{version}.py"
        versioned_path.write_text(source, encoding="utf-8")
        _record_variant(state, role=role, strategy_name=strategy_name, path=versioned_path)

    _record_variant(state, role=role, strategy_name=strategy_name, path=path)
    _write_manifest(state)
    return path


def clone_with_class_name(source: str, new_class_name: str) -> str:
    return re.sub(
        r"class\s+\w+\s*\(",
        f"class {new_class_name}(",
        source,
        count=1,
    )


def copy_to_output(path: Path, out_dir: Path, filename: str | None = None) -> Path:
    out_path = out_dir / (filename or path.name)
    shutil.copy2(path, out_path)
    return out_path


def _next_role_version(runtime_dir: Path, strategy_name: str, role: str) -> int:
    existing = sorted(runtime_dir.glob(f"{strategy_name}_{role}_v*.py"))
    return len(existing) + 1


def _record_variant(
    state: Any,
    *,
    role: str,
    strategy_name: str,
    path: Path,
    source: str | None = None,
) -> None:
    manifest = list(getattr(state, "strategy_variants", []) or [])
    record = {
        "role": role,
        "strategy_name": strategy_name,
        "path": str(path),
    }
    if source:
        record["source"] = source
    if record not in manifest:
        manifest.append(record)
    state.strategy_variants = manifest


def _write_manifest(state: Any) -> None:
    runtime_dir = variant_dir(state)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = runtime_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "original_strategy": getattr(state, "original_strategy", state.strategy),
                "original_strategy_hash": getattr(state, "original_strategy_hash", None),
                "variants": getattr(state, "strategy_variants", []),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


__all__ = [
    "ensure_working_copy",
    "variant_dir",
    "strategy_source_path",
    "active_strategy_path",
    "strategy_path_args",
    "read_strategy_source",
    "create_variant",
    "clone_with_class_name",
    "copy_to_output",
]
