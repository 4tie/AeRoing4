"""services/strategy/strategy_registry.py contains backend logic for strategy registry.

This file is intentionally documented in plain English so readers can follow
what each section does even without deep Python experience.
"""

from __future__ import annotations
from pathlib import Path

from ...core.errors import BackendError
from ...models import ManagedStatus, RegistryDiff, StrategyDetail, StrategyRecord
from ...services.interfaces import IStrategyRegistry
from .strategy_source import StrategySourceParser


class StrategyRegistry(IStrategyRegistry):
    """StrategyRegistry contains class-level backend logic."""
    def __init__(self, strategies_dir: Path, versions_root: Path) -> None:
        """__init__ implements function-level backend logic."""
        self.strategies_dir = strategies_dir
        self.versions_root = versions_root
        self.parser = StrategySourceParser(strategies_dir, versions_root)
        self._index: dict[str, StrategyRecord] = {}
        self._path_index: dict[str, float] = {}
        self._parse_errors: list[dict[str, str]] = []
        self._last_diff = RegistryDiff(added=[], removed=[], modified=[], parse_errors=[])

    def scan(self) -> RegistryDiff:
        """scan implements function-level backend logic."""
        new_index: dict[str, StrategyRecord] = {}
        new_paths: dict[str, float] = {}
        parse_errors: list[dict[str, str]] = []
        for file_path in sorted(self.strategies_dir.rglob("*.py")):
            if "versions" in file_path.parts:
                continue
            try:
                parsed = self.parser.parse(file_path)
                record = parsed.record
                record = record.model_copy(update={"managed_status": ManagedStatus.AVAILABLE})
                new_index[record.strategy_name] = record
                # Ensure a sidecar JSON exists next to every strategy file.
                # create_default_sidecar_json() is a no-op if the file already exists.
                self.parser.create_default_sidecar_json(file_path, parsed)
                json_path = file_path.with_suffix(".json")
                mtime = file_path.stat().st_mtime
                if json_path.exists():
                    mtime = max(mtime, json_path.stat().st_mtime)
                new_paths[str(file_path.resolve())] = mtime
            except Exception as exc:
                parse_errors.append({"file_path": str(file_path.resolve()), "error": str(exc)})

        added = sorted(set(new_index) - set(self._index))
        removed = sorted(set(self._index) - set(new_index))
        modified = sorted(
            record.strategy_name
            for record in new_index.values()
            if (
                record.strategy_name in self._index
                and new_paths.get(record.file_path) != self._path_index.get(record.file_path)
            )
        )

        self._index = new_index
        self._path_index = new_paths
        self._parse_errors = parse_errors
        self._last_diff = RegistryDiff(
            added=added, removed=removed, modified=modified, parse_errors=parse_errors
        )
        return self._last_diff

    def ensure_scanned(self) -> None:
        """ensure_scanned implements function-level backend logic."""
        if not self._index:
            self.scan()

    def list_strategies(self) -> list[StrategyRecord]:
        """list_strategies implements function-level backend logic."""
        self.ensure_scanned()
        return sorted(self._index.values(), key=lambda item: item.strategy_name.lower())

    def get_strategy(self, strategy_name: str) -> StrategyRecord:
        """get_strategy implements function-level backend logic."""
        self.ensure_scanned()
        try:
            return self._index[strategy_name]
        except KeyError as exc:
            raise BackendError(f"Strategy '{strategy_name}' was not found.", status_code=404) from exc

    def parse_strategy(self, strategy_name: str):
        """parse_strategy implements function-level backend logic."""
        record = self.get_strategy(strategy_name)
        return self.parser.parse(Path(record.file_path))

    @property
    def parse_errors(self) -> list[dict[str, str]]:
        """parse_errors implements function-level backend logic."""
        return list(self._parse_errors)

    @property
    def last_diff(self) -> RegistryDiff:
        """last_diff implements function-level backend logic."""
        return self._last_diff
