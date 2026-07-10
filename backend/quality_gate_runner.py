"""quality_gate_runner.py contains backend logic for quality gate runner.

This file is intentionally documented in plain English so readers can follow
what each section does even without deep Python experience.
"""

from __future__ import annotations
import ast
import importlib
import importlib.util
import json
import sys
from pathlib import Path


PARAMETER_CLASS_NAMES = {
    "IntParameter",
    "DecimalParameter",
    "CategoricalParameter",
    "BooleanParameter",
}


def main() -> int:
    """main implements function-level backend logic."""
    strategy_path = Path(sys.argv[1]).resolve()
    params_path = Path(sys.argv[2]).resolve()
    stub_root = Path(sys.argv[3]).resolve()

    sys.path.insert(0, str(stub_root))
    sys.path.insert(0, str(strategy_path.parent))

    source_text = strategy_path.read_text(encoding="utf-8")
    params_payload = json.loads(params_path.read_text(encoding="utf-8"))
    checks: list[dict[str, str | None]] = []

    try:
        tree = ast.parse(source_text, filename=str(strategy_path))
        checks.append({"check_name": "ast_parse", "status": "pass", "error_detail": None})
    except SyntaxError as exc:
        checks.append(
            {
                "check_name": "ast_parse",
                "status": "fail",
                "error_detail": f"{exc.msg} (line {exc.lineno})",
            }
        )
        print(json.dumps(checks))
        return 0

    strategy_class = None
    declared_params: set[str] = set()
    method_names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        base_names = {_name(base) for base in node.bases}
        class_methods = {child.name for child in node.body if isinstance(child, ast.FunctionDef)}
        if "IStrategy" in base_names or {
            "populate_indicators",
            "populate_entry_trend",
            "populate_exit_trend",
        }.issubset(class_methods):
            strategy_class = node
            method_names = class_methods
            for child in node.body:
                if isinstance(child, ast.Assign) and len(child.targets) == 1 and isinstance(
                    child.targets[0], ast.Name
                ):
                    if isinstance(child.value, ast.Call) and _name(child.value.func) in PARAMETER_CLASS_NAMES:
                        declared_params.add(child.targets[0].id)
                elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    if isinstance(child.value, ast.Call) and _name(child.value.func) in PARAMETER_CLASS_NAMES:
                        declared_params.add(child.target.id)
            break

    checks.append(
        {
            "check_name": "strategy_class_present",
            "status": "pass" if strategy_class else "fail",
            "error_detail": None if strategy_class else "No strategy class could be identified.",
        }
    )

    required_methods = {
        "populate_indicators",
        "populate_entry_trend",
        "populate_exit_trend",
    }
    missing_methods = sorted(required_methods - method_names)
    checks.append(
        {
            "check_name": "required_methods",
            "status": "pass" if not missing_methods else "fail",
            "error_detail": None
            if not missing_methods
            else f"Missing required methods: {', '.join(missing_methods)}",
        }
    )

    missing_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if importlib.util.find_spec(alias.name) is None:
                    missing_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and importlib.util.find_spec(node.module) is None:
                missing_imports.append(node.module)
    checks.append(
        {
            "check_name": "missing_imports",
            "status": "pass" if not missing_imports else "fail",
            "error_detail": None
            if not missing_imports
            else f"Missing imports: {', '.join(sorted(set(missing_imports)))}",
        }
    )

    try:
        spec = importlib.util.spec_from_file_location(strategy_path.stem, strategy_path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        getattr(module, strategy_class.name if strategy_class else "")
        checks.append({"check_name": "module_import", "status": "pass", "error_detail": None})
    except Exception as exc:
        checks.append({"check_name": "module_import", "status": "fail", "error_detail": str(exc)})

    params_keys = set(params_payload.get("buy_params", {}).keys())
    params_keys |= set(params_payload.get("sell_params", {}).keys())
    params_keys |= set(params_payload.get("protection_params", {}).keys())
    params_keys |= set(params_payload.get("custom_params", {}).keys())
    unknown_keys = sorted(params_keys - declared_params)
    checks.append(
        {
            "check_name": "params_schema",
            "status": "pass" if not unknown_keys else "fail",
            "error_detail": None
            if not unknown_keys
            else f"Unrecognised parameter keys: {', '.join(unknown_keys)}",
        }
    )

    print(json.dumps(checks))
    return 0


def _name(expr: ast.AST) -> str:
    """_name implements function-level backend logic."""
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
