"""Strategy resolver for the AI copilot.

Resolves any of:
  - aistrategy.py
  - AIStrategy.py
  - aistrategy
  - AIStrategy

… to the real strategy file on disk and its Freqtrade class name.

Rules:
- Scans ONLY the configured strategies directory (allowlisted safe path).
- Case-insensitive stem matching.
- Strips .py extension before comparison.
- Prefers exact-case stem match when multiple case-insensitive hits exist.
- Reads the first ``class <Name>`` declaration from the file to extract the
  Freqtrade class name (which may differ from the file stem).
- Raises AmbiguousStrategyError when multiple files match.
- Raises StrategyNotFoundError when no file matches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


# ── Custom exceptions ─────────────────────────────────────────────────────────


class StrategyNotFoundError(ValueError):
    """Raised when no strategy file matches the given name."""

    def __init__(self, name: str, strategies_dir: str | Path) -> None:
        self.name = name
        self.strategies_dir = str(strategies_dir)
        super().__init__(
            f"Strategy '{name}' not found in {self.strategies_dir}. "
            "Try list_strategies to see what is available."
        )


class AmbiguousStrategyError(ValueError):
    """Raised when multiple strategy files match the given name."""

    def __init__(self, name: str, candidates: list[str]) -> None:
        self.name = name
        self.candidates = candidates
        super().__init__(
            f"Strategy name '{name}' is ambiguous — multiple files match: "
            + ", ".join(candidates)
            + ". Please be more specific."
        )


# ── Resolution result ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StrategyResolution:
    """Result of a successful strategy resolution."""

    stem: str
    """File stem without extension, e.g. 'AIStrategy'."""

    py_path: Path
    """Absolute path to the .py file."""

    class_name: str
    """Freqtrade strategy class name extracted from the file."""

    json_path: Path | None
    """Absolute path to the companion .json file, or None if absent."""

    @property
    def has_json(self) -> bool:
        return self.json_path is not None and self.json_path.exists()


# ── Class-name extractor ──────────────────────────────────────────────────────

_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_]\w*)\s*[\(:]", re.MULTILINE)


def _extract_class_name(py_path: Path) -> str:
    """Return the first ``class Foo`` name found in the file.

    Falls back to the file stem if no class declaration is found.
    """
    try:
        text = py_path.read_text(encoding="utf-8", errors="replace")
        match = _CLASS_RE.search(text)
        if match:
            return match.group(1)
    except OSError:
        pass
    return py_path.stem


# ── Main resolver ─────────────────────────────────────────────────────────────


def resolve_strategy(name: str, strategies_dir: str | Path) -> StrategyResolution:
    """Resolve *name* to a strategy file inside *strategies_dir*.

    Args:
        name: Strategy name in any form:
              ``AIStrategy``, ``aistrategy``, ``AIStrategy.py``, ``aistrategy.py``
        strategies_dir: Absolute path to the strategies directory.
                        Only files inside this directory are considered.

    Returns:
        StrategyResolution with stem, py_path, class_name, json_path.

    Raises:
        StrategyNotFoundError: No .py file matches *name*.
        AmbiguousStrategyError: Multiple .py files match *name*.
    """
    strategies_dir = Path(strategies_dir).resolve()

    # Strip optional .py extension and normalise case for comparison
    bare = name.strip()
    if bare.lower().endswith(".py"):
        bare = bare[:-3]
    bare_lower = bare.lower()

    # Collect all .py files in the directory (non-recursive)
    py_files = [p for p in strategies_dir.glob("*.py") if p.is_file()]

    # Build candidate list: (stem, path)
    # 1. Exact case-insensitive stem match
    ci_matches = [p for p in py_files if p.stem.lower() == bare_lower]

    if not ci_matches:
        raise StrategyNotFoundError(name, strategies_dir)

    if len(ci_matches) == 1:
        py_path = ci_matches[0]
    else:
        # Multiple case-insensitive matches — prefer exact case
        exact = [p for p in ci_matches if p.stem == bare]
        if len(exact) == 1:
            py_path = exact[0]
        else:
            raise AmbiguousStrategyError(name, [p.name for p in ci_matches])

    # Validate the resolved path is still inside strategies_dir (allowlist check)
    try:
        py_path.resolve().relative_to(strategies_dir)
    except ValueError as exc:
        raise StrategyNotFoundError(name, strategies_dir) from exc

    stem = py_path.stem
    class_name = _extract_class_name(py_path)
    json_path = py_path.with_suffix(".json")

    return StrategyResolution(
        stem=stem,
        py_path=py_path,
        class_name=class_name,
        json_path=json_path if json_path.exists() else None,
    )
