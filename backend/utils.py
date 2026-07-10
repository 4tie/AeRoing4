"""utils.py contains backend logic for utils.

This file is intentionally documented in plain English so readers can follow
what each section does even without deep Python experience.
"""

from __future__ import annotations
import ast
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


def ast_node_name(expr: ast.AST) -> str:
    """Return the simple name string from an AST Name or Attribute node."""
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return ""


def utc_now() -> datetime:
    """utc_now implements function-level backend logic."""
    return datetime.now(tz=UTC)


def to_snake_case(value: str) -> str:
    """to_snake_case implements function-level backend logic."""
    interim = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", interim).replace("-", "_").lower()


def ensure_directory(path: Path) -> Path:
    """ensure_directory implements function-level backend logic."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_text(path: Path, content: str) -> None:
    """atomic_write_text implements function-level backend logic."""
    ensure_directory(path.parent)
    encoded = content.encode("utf-8")
    with NamedTemporaryFile("wb", delete=False, dir=path.parent) as handle:
        handle.write(encoded)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def atomic_write_json(path: Path, payload: Any) -> None:
    """atomic_write_json implements function-level backend logic."""
    atomic_write_text(path, json.dumps(payload, indent=2, default=_json_default))


def read_json(path: Path, default: Any = None) -> Any:
    """read_json implements function-level backend logic."""
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_text_file(path: Path) -> str:
    """read_text_file implements function-level backend logic."""
    return path.read_text(encoding="utf-8")


def append_text(path: Path, content: str) -> None:
    """append_text implements function-level backend logic."""
    ensure_directory(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(content)


def unique_existing_counter(existing_names: list[str], prefix: str, width: int = 3) -> int:
    """unique_existing_counter implements function-level backend logic."""
    counters = []
    for name in existing_names:
        match = re.search(rf"{re.escape(prefix)}(\d{{{width}}})$", name)
        if match:
            counters.append(int(match.group(1)))
    return (max(counters) if counters else 0) + 1


def build_version_id(next_counter: int) -> str:
    """build_version_id implements function-level backend logic."""
    return f"v{next_counter:03d}"


def build_run_id(timestamp: datetime, strategy_name: str, version_id: str, counter: int) -> str:
    """build_run_id implements function-level backend logic."""
    return f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}_{strategy_name}_{version_id}_bt{counter:03d}"


def relative_or_absolute(path: Path) -> str:
    """relative_or_absolute implements function-level backend logic."""
    try:
        return str(path.resolve())
    except FileNotFoundError:
        return str(path)


def _json_default(value: Any) -> Any:
    """_json_default implements function-level backend logic."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def get_data_file_path(user_data_dir: str, pair: str, timeframe: str, exchange: str = "binance", data_format: str = "json") -> Path:
    """Get the path to a pair's data file.

    Args:
        user_data_dir: Path to user_data directory
        pair: Trading pair (e.g., "BTC/USDT")
        timeframe: Candle timeframe (e.g., "5m")
        exchange: Exchange name (default: "binance")
        data_format: Data file format (default: "json", also supports "feather")

    Returns:
        Path to the data file (e.g., user_data/data/binance/BTC_USDT-5m.json)
    """
    data_dir = Path(user_data_dir) / "data" / exchange
    pair_filename = pair.replace("/", "_").replace(":", "_")
    return data_dir / f"{pair_filename}-{timeframe}.{data_format}"


def detect_data_file_format(user_data_dir: str, pair: str, timeframe: str, exchange: str = "binance") -> str:
    """Detect the format of an existing data file.

    Args:
        user_data_dir: Path to user_data directory
        pair: Trading pair (e.g., "BTC/USDT")
        timeframe: Candle timeframe (e.g., "5m")
        exchange: Exchange name (default: "binance")

    Returns:
        Detected format ("json", "feather", or "json" as default)
    """
    data_dir = Path(user_data_dir) / "data" / exchange
    pair_filename = pair.replace("/", "_").replace(":", "_")
    
    # Check for feather format first (preferred for newer data)
    feather_path = data_dir / f"{pair_filename}-{timeframe}.feather"
    if feather_path.exists():
        return "feather"
    
    # Fall back to JSON format
    json_path = data_dir / f"{pair_filename}-{timeframe}.json"
    if json_path.exists():
        return "json"
    
    # Default to JSON if no file exists
    return "json"
