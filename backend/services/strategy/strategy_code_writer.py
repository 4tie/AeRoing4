"""Template-based code writer for rendering StrategySpec into Freqtrade source."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import py_compile

from backend.models.strategy_spec import StrategySpec, validate_spec
from backend.utils import atomic_write_text
from backend.validators.strategy_validator import StrategyValidator
from backend.services.auto_quant.generator import (
    generate_strategy_source_momentum,
    generate_strategy_source_adaptive,
    generate_strategy_source_ensemble,
    generate_strategy_source_omni,
)


def render_strategy_from_spec(spec: StrategySpec) -> dict:
    """Render a validated StrategySpec into in-memory Freqtrade strategy source.

    Args:
        spec: StrategySpec to render

    Returns:
        dict with keys:
            - source: str | None - rendered source code or None if invalid
            - errors: list[str] - validation errors
            - warnings: list[str] - validation warnings
            - template: str | None - template name used or None if invalid
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Step 1: Validate spec before rendering
    spec_errors = validate_spec(spec)
    
    # Validate direction (MVP long-only)
    if spec.direction != "long":
        errors.append(f"Only long direction is supported, got: {spec.direction}")
        return {
            "source": None,
            "errors": errors,
            "warnings": warnings,
            "template": None,
        }
    
    if spec_errors:
        return {
            "source": None,
            "errors": spec_errors,
            "warnings": [],
            "template": None,
        }

    # Step 2: Select template based on trading_style
    template_map = {
        "momentum": "momentum",
        "adaptive": "adaptive",
        "ensemble": "ensemble",
        "trend_following": "omni",
        "mean_reversion": "omni",
        "breakout": "omni",
    }

    template_name = template_map.get(spec.trading_style)
    if not template_name:
        errors.append(f"Unsupported trading_style: {spec.trading_style}")
        return {
            "source": None,
            "errors": errors,
            "warnings": warnings,
            "template": None,
        }

    # Step 3: Generate source using selected template
    try:
        if template_name == "momentum":
            source = generate_strategy_source_momentum(spec.name)
        elif template_name == "adaptive":
            source = generate_strategy_source_adaptive(spec.name)
        elif template_name == "ensemble":
            source = generate_strategy_source_ensemble(spec.name)
        elif template_name == "omni":
            source = generate_strategy_source_omni(spec.name, timeframe=spec.timeframe)
        else:
            errors.append(f"Unknown template: {template_name}")
            return {
                "source": None,
                "errors": errors,
                "warnings": warnings,
                "template": None,
            }
    except Exception as e:
        errors.append(f"Template generation failed: {e}")
        return {
            "source": None,
            "errors": errors,
            "warnings": warnings,
            "template": None,
        }

    # Step 4: Apply timeframe for non-omni templates
    if template_name != "omni":
        # Try to replace exact timeframe line
        target_line = 'timeframe = "5m"'
        replacement_line = f'timeframe = "{spec.timeframe}"'
        if target_line in source:
            source = source.replace(target_line, replacement_line)
        else:
            warnings.append(
                f"Could not apply timeframe '{spec.timeframe}' to {template_name} template: "
                f"exact line '{target_line}' not found"
            )

    # Step 5: Apply stoploss
    if spec.stoploss is not None:
        # Try to replace stoploss line
        stoploss_pattern = r'stoploss = -?\d+\.?\d*'
        import re
        if re.search(stoploss_pattern, source):
            source = re.sub(stoploss_pattern, f'stoploss = {spec.stoploss}', source)
        else:
            warnings.append(f"Could not apply stoploss {spec.stoploss} to template")

    # Step 6: Apply ROI settings
    if spec.roi and len(spec.roi) > 0:
        # Try to find and replace minimal_roi
        roi_pattern = r'minimal_roi = \{[^}]*\}'
        roi_str = "{"
        roi_str += ", ".join([f'"{int(mins)}": {pct}' for mins, pct in spec.roi])
        roi_str += "}"
        if re.search(roi_pattern, source):
            source = re.sub(roi_pattern, f'minimal_roi = {roi_str}', source)
        else:
            warnings.append("Could not apply ROI settings to template")

    # Step 7: Apply trailing stop settings
    if spec.trailing and spec.trailing.trailing_stop:
        # Try to replace trailing stop configuration
        trailing_pattern = r'trailing_stop = (True|False)'
        if re.search(trailing_pattern, source):
            source = re.sub(trailing_pattern, 'trailing_stop = True', source)
            if spec.trailing.trailing_stop_positive is not None:
                source = re.sub(
                    r'trailing_stop_positive = -?\d+\.?\d*',
                    f'trailing_stop_positive = {spec.trailing.trailing_stop_positive}',
                    source
                )
        else:
            warnings.append("Could not apply trailing stop settings to template")

    # Step 8: Apply max_open_trades if specified
    if spec.max_open_trades is not None:
        max_trades_pattern = r'max_open_trades = \d+'
        if re.search(max_trades_pattern, source):
            source = re.sub(max_trades_pattern, f'max_open_trades = {spec.max_open_trades}', source)

    # Step 9: Add warnings for unapplied complex spec fields
    # Complex custom indicator parameters and entry/exit conditions are not applied
    # unless already supported by the template
    if spec.indicators:
        warnings.append("Custom indicator parameters not applied to generated source (template defaults used)")
    if spec.entry_conditions:
        warnings.append("Custom entry conditions not applied to generated source (template defaults used)")
    if spec.exit_conditions:
        warnings.append("Custom exit conditions not applied to generated source (template defaults used)")
    if spec.position_sizing.method != "fixed":
        warnings.append("Custom position sizing not applied to generated source (template defaults used)")

    # Step 10: Validate rendered source
    validator = StrategyValidator()
    validation_result = validator.validate_code(source)

    # Handle legacy method compatibility
    # Validator checks for populate_buy_trend/populate_sell_trend (v2)
    # Generated templates use populate_entry_trend/populate_exit_trend (v3)
    filtered_errors = []
    for error in validation_result.errors:
        if "populate_buy_trend" in error and "populate_entry_trend" in source:
            # v3 entry method present, ignore v2 error
            continue
        if "populate_sell_trend" in error and "populate_exit_trend" in source:
            # v3 exit method present, ignore v2 error
            continue
        filtered_errors.append(error)

    errors.extend(filtered_errors)
    warnings.extend(validation_result.warnings)

    # Step 7: Python syntax validation
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(source)
            temp_path = f.name

        py_compile.compile(temp_path, doraise=True)
        Path(temp_path).unlink()
    except py_compile.PyCompileError as e:
        errors.append(f"Python syntax error: {e}")
        try:
            Path(temp_path).unlink()
        except:
            pass
    except Exception as e:
        errors.append(f"Syntax validation failed: {e}")
        try:
            Path(temp_path).unlink()
        except:
            pass

    # Step 8: Return result
    if errors:
        return {
            "source": None,
            "errors": errors,
            "warnings": warnings,
            "template": template_name,
        }

    return {
        "source": source,
        "errors": [],
        "warnings": warnings,
        "template": template_name,
    }


# ---------------------------------------------------------------------------
# Safe Working Copy — save rendered strategy source to disk
# ---------------------------------------------------------------------------

_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


@dataclass
class SaveResult:
    """Result of a save/delete operation on a rendered strategy file."""

    path: Path | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _validate_name_component(name: str, label: str) -> str | None:
    """Validate a path component for safety.

    Returns None on success, or an error message string on failure.
    """
    if not name or not name.strip():
        return f"{label} must not be empty"
    if "/" in name or "\\" in name or "\0" in name:
        return f"{label} contains path separators or null bytes: {name!r}"
    if ".." in name:
        return f"{label} must not contain '..': {name!r}"
    if not _SAFE_NAME_RE.match(name):
        return f"{label} must only contain a-z, A-Z, 0-9, _, -: {name!r}"
    return None


def save_rendered_strategy(
    *,
    source: str,
    strategy_name: str,
    run_id: str,
    candidate_label: str = "",
    base_path: str | Path = "user_data/strategies/rendered",
) -> SaveResult:
    """Save rendered strategy source to a run/candidate-specific working file.

    Args:
        source: Valid Python source code of the rendered strategy.
        strategy_name: Name of the strategy (used in filename).
        run_id: Run identifier (creates a subdirectory under base_path).
        candidate_label: Optional label for variant/candidate naming.
        base_path: Root directory for rendered strategies.

    Returns:
        SaveResult with the resolved path, errors, and warnings.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- source validation ---
    if not source or not source.strip():
        errors.append("Source must not be empty")
        return SaveResult(errors=errors)

    try:
        compile(source, "<string>", "exec")
    except SyntaxError as e:
        errors.append(f"Python syntax error: {e}")
        return SaveResult(errors=errors)

    # --- name component validation ---
    for val, label in [
        (strategy_name, "strategy_name"),
        (run_id, "run_id"),
    ]:
        err = _validate_name_component(val, label)
        if err:
            errors.append(err)
            return SaveResult(errors=errors)

    if candidate_label:
        err = _validate_name_component(candidate_label, "candidate_label")
        if err:
            errors.append(err)
            return SaveResult(errors=errors)

    # --- path building ---
    base = Path(base_path).resolve()
    run_dir = base / run_id
    safe_name = strategy_name

    # Safety: run_id must create a distinct subdirectory
    if run_dir.resolve() == base:
        errors.append("run_id must create a subdirectory under base_path")
        return SaveResult(errors=errors)

    # --- filename with optional label and auto-increment ---
    stem = f"{safe_name}_{candidate_label}" if candidate_label else safe_name
    counter = 0
    while True:
        suffix = f"_v{counter}" if counter > 0 else ""
        filename = f"{stem}{suffix}.py"
        target = run_dir / filename
        if not target.exists():
            break
        counter += 1

    # --- atomic write ---
    try:
        atomic_write_text(target, source)
    except Exception as e:
        errors.append(f"Failed to write strategy file: {e}")
        return SaveResult(errors=errors)

    if counter > 0:
        warnings.append(f"File already existed, saved as {filename}")

    return SaveResult(path=target, warnings=warnings)


def delete_rendered_strategy(
    path: str | Path,
    base_path: str | Path = "user_data/strategies/rendered",
) -> SaveResult:
    """Delete a rendered strategy file and its empty parent run directory.

    Args:
        path: Full path to the rendered strategy file to delete.
        base_path: Root directory for rendered strategies (safety boundary).

    Returns:
        SaveResult with the deleted path, errors, and warnings.
    """
    target = Path(path).resolve()
    base = Path(base_path).resolve()

    if target == base:
        return SaveResult(
            errors=[f"Cannot delete the base path itself: {base}"],
        )

    try:
        target.relative_to(base)
    except ValueError:
        return SaveResult(
            errors=[f"Path {target} is outside allowed base path {base}"],
        )

    if not target.exists():
        return SaveResult(errors=[f"File not found: {target}"])

    if not target.is_file():
        return SaveResult(errors=[f"Not a file: {target}"])

    try:
        target.unlink()
    except Exception as e:
        return SaveResult(errors=[f"Failed to delete {target}: {e}"])

    # Remove empty parent run directory (one level only, not the base)
    parent = target.parent
    if parent != base and parent.exists() and not any(parent.iterdir()):
        try:
            parent.rmdir()
        except Exception:
            pass

    return SaveResult(path=target)
