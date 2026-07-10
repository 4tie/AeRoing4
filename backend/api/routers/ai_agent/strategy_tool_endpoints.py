"""Strategy tool endpoints for AI agent router."""

import json
import re
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, Request

from .helpers import _log_action, _replace_section, _strategies_dir
from .schemas import ToolExecutionRequest, ToolExecutionResponse


def register_strategy_tool_endpoints(router: APIRouter) -> None:
    """Register strategy tool endpoints on the given router."""
    
    @router.post(
        "/tools/read_strategy_file",
        summary="Read a strategy file",
        description="Read a Freqtrade strategy .py and .json files from the strategies directory.",
    )
    async def read_strategy_file(body: ToolExecutionRequest, request: Request) -> ToolExecutionResponse:
        """Read a strategy file."""
        try:
            strategy_name = body.parameters.get("strategy_name")
            if not strategy_name:
                return ToolExecutionResponse(
                    success=False,
                    error="Missing required parameter: strategy_name"
                )
            
            strategies_dir = _strategies_dir(request)
            py_path = strategies_dir / f"{strategy_name}.py"
            json_path = strategies_dir / f"{strategy_name}.json"
            
            if not py_path.exists():
                return ToolExecutionResponse(
                    success=False,
                    error=f"Strategy file '{strategy_name}.py' not found in {strategies_dir}"
                )
            
            python_content = py_path.read_text(encoding="utf-8", errors="replace")
            json_content = None
            if json_path.exists():
                json_content = json_path.read_text(encoding="utf-8", errors="replace")
            
            result = {
                "strategy_name": strategy_name,
                "python_content": python_content,
                "json_content": json_content,
                "python_path": str(py_path),
                "json_path": str(json_path) if json_path.exists() else None
            }
            
            _log_action(body.session_id, "read_strategy_file", {"strategy_name": strategy_name}, request)
            
            return ToolExecutionResponse(
                success=True,
                result=result,
                logs=[{"message": f"Successfully read strategy file: {strategy_name}"}]
            )
            
        except Exception as e:
            return ToolExecutionResponse(
                success=False,
                error=f"Failed to read strategy file: {str(e)}"
            )

    @router.post(
        "/tools/list_strategies",
        summary="List all available strategies",
        description="List all available strategies in the strategies directory.",
    )
    async def list_strategies(body: ToolExecutionRequest, request: Request) -> ToolExecutionResponse:
        """List all available strategies."""
        try:
            strategies_dir = _strategies_dir(request)
            py_files = {p.stem: p.name for p in strategies_dir.glob("*.py")}
            json_files = {p.stem: p.name for p in strategies_dir.glob("*.json")}
            all_stems = sorted(set(py_files) | set(json_files))
            
            strategies = []
            for stem in all_stems:
                py_f = py_files.get(stem)
                json_f = json_files.get(stem)
                if py_f:
                    strategies.append({
                        "name": stem,
                        "py_file": py_f,
                        "json_file": json_f,
                        "has_json": json_f is not None
                    })
            
            result = {
                "strategies": strategies,
                "strategies_dir": str(strategies_dir),
                "count": len(strategies)
            }
            
            _log_action(body.session_id, "list_strategies", {"count": len(strategies)}, request)
            
            return ToolExecutionResponse(
                success=True,
                result=result,
                logs=[{"message": f"Found {len(strategies)} strategies"}]
            )
            
        except Exception as e:
            return ToolExecutionResponse(
                success=False,
                error=f"Failed to list strategies: {str(e)}"
            )

    @router.post(
        "/tools/edit_strategy_section",
        summary="Edit a strategy section",
        description="Edit a specific section of a strategy file with versioning and validation.",
    )
    async def edit_strategy_section(body: ToolExecutionRequest, request: Request) -> ToolExecutionResponse:
        """Edit a strategy section with versioning and validation."""
        try:
            strategy_name = body.parameters.get("strategy_name")
            section = body.parameters.get("section")
            changes = body.parameters.get("changes")
            reason = body.parameters.get("reason")
            
            if not all([strategy_name, section, changes, reason]):
                return ToolExecutionResponse(
                    success=False,
                    error="Missing required parameters: strategy_name, section, changes, reason"
                )
            
            strategies_dir = _strategies_dir(request)
            py_path = strategies_dir / f"{strategy_name}.py"
            
            if not py_path.exists():
                return ToolExecutionResponse(
                    success=False,
                    error=f"Strategy file '{strategy_name}.py' not found"
                )
            
            # Create snapshot before editing
            services = request.app.state.services
            try:
                snap = services.snapshot_service.create_snapshot(
                    strategy_name, strategies_dir, trigger="ai_agent_edit"
                )
                snapshot_log = f"Created snapshot: {snap.get('timestamp', 'unknown')}"
            except Exception as e:
                snapshot_log = f"Snapshot creation failed: {str(e)}"
            
            # Read current content
            current_content = py_path.read_text(encoding="utf-8", errors="replace")
            
            # Apply changes based on section type
            if section == "full_file":
                new_content = changes
            else:
                # For section edits, we need to find and replace the specific section
                # This is a simplified approach - in production, you'd want more sophisticated parsing
                new_content = _replace_section(current_content, section, changes)
            
            # Validate syntax before saving
            try:
                import py_compile
                with tempfile.NamedTemporaryFile(mode="w", suffix=".py", encoding="utf-8", delete=False) as tf:
                    tf.write(new_content)
                    tmp_path = Path(tf.name)
                try:
                    py_compile.compile(str(tmp_path), doraise=True)
                    syntax_valid = True
                    syntax_error = None
                except py_compile.PyCompileError as e:
                    syntax_valid = False
                    syntax_error = str(e)
                finally:
                    tmp_path.unlink(missing_ok=True)
            except Exception as e:
                syntax_valid = False
                syntax_error = str(e)
            
            if not syntax_valid:
                return ToolExecutionResponse(
                    success=False,
                    error=f"Syntax validation failed: {syntax_error}",
                    logs=[snapshot_log, {"message": "Edit rejected due to syntax error"}]
                )
            
            # Save the new content
            try:
                tmp = py_path.with_suffix(py_path.suffix + ".tmp")
                tmp.write_text(new_content, encoding="utf-8")
                tmp.replace(py_path)
            except Exception as e:
                tmp.unlink(missing_ok=True)
                return ToolExecutionResponse(
                    success=False,
                    error=f"Failed to save file: {str(e)}",
                    logs=[snapshot_log]
                )
            
            result = {
                "strategy_name": strategy_name,
                "section_edited": section,
                "snapshot_created": snapshot_log,
                "syntax_valid": syntax_valid,
                "file_path": str(py_path)
            }
            
            _log_action(body.session_id, "edit_strategy_section", {
                "strategy_name": strategy_name,
                "section": section,
                "reason": reason
            }, request)
            
            return ToolExecutionResponse(
                success=True,
                result=result,
                logs=[
                    snapshot_log,
                    {"message": f"Successfully edited {section} section of {strategy_name}"},
                    {"message": "Syntax validation passed"}
                ]
            )
            
        except Exception as e:
            return ToolExecutionResponse(
                success=False,
                error=f"Failed to edit strategy section: {str(e)}"
            )

    @router.post(
        "/tools/validate_strategy_syntax",
        summary="Validate strategy syntax",
        description="Validate a strategy's Python syntax and Freqtrade compatibility.",
    )
    async def validate_strategy_syntax(body: ToolExecutionRequest, request: Request) -> ToolExecutionResponse:
        """Validate strategy syntax and Freqtrade compatibility."""
        try:
            strategy_name = body.parameters.get("strategy_name")
            if not strategy_name:
                return ToolExecutionResponse(
                    success=False,
                    error="Missing required parameter: strategy_name"
                )
            
            strategies_dir = _strategies_dir(request)
            py_path = strategies_dir / f"{strategy_name}.py"
            
            if not py_path.exists():
                return ToolExecutionResponse(
                    success=False,
                    error=f"Strategy file '{strategy_name}.py' not found"
                )
            
            content = py_path.read_text(encoding="utf-8", errors="replace")
            errors = []
            warnings = []
            output_lines = []
            
            # Step 1: py_compile syntax check
            try:
                import py_compile
                with tempfile.NamedTemporaryFile(mode="w", suffix=".py", encoding="utf-8", delete=False) as tf:
                    tf.write(content)
                    tmp_path = Path(tf.name)
                try:
                    py_compile.compile(str(tmp_path), doraise=True)
                    output_lines.append("✓ Python syntax OK")
                except py_compile.PyCompileError as exc:
                    msg = str(exc).replace(str(tmp_path), f"{strategy_name}.py")
                    errors.append(msg)
                    output_lines.append(f"✗ Syntax error: {msg}")
                finally:
                    tmp_path.unlink(missing_ok=True)
            except Exception as exc:
                errors.append(str(exc))
                output_lines.append(f"✗ Syntax check failed: {exc}")
            
            if errors:
                _log_action(body.session_id, "validate_strategy_syntax", {
                    "strategy_name": strategy_name,
                    "valid": False,
                    "errors": errors
                }, request)
                return ToolExecutionResponse(
                    success=False,
                    error="Syntax validation failed",
                    result={
                        "valid": False,
                        "errors": errors,
                        "warnings": warnings,
                        "output": "\n".join(output_lines)
                    },
                    logs=output_lines
                )
            
            # Step 2: Extract class name for Freqtrade validation
            class_match = re.search(r"^class\s+(\w+)\s*[\(:]", content, re.MULTILINE)
            class_name = class_match.group(1) if class_match else None
            
            if not class_name:
                warnings.append("Could not detect strategy class name — skipping Freqtrade check.")
                _log_action(body.session_id, "validate_strategy_syntax", {
                    "strategy_name": strategy_name,
                    "valid": True,
                    "warnings": warnings
                }, request)
                return ToolExecutionResponse(
                    success=True,
                    result={
                        "valid": True,
                        "errors": errors,
                        "warnings": warnings,
                        "output": "\n".join(output_lines)
                    },
                    logs=output_lines
                )
            
            # Step 3: freqtrade test-strategy
            services = request.app.state.services
            settings = services.settings_store.load()
            freqtrade_exe = settings.freqtrade_executable_path
            user_data_dir = settings.user_data_directory_path
            
            temp_strat_name = f"_ai_agent_validate_{class_name}"
            temp_strat_file = strategies_dir / f"{temp_strat_name}.py"
            patched = re.sub(
                r"(^class\s+)" + re.escape(class_name) + r"(\s*[\(:])",
                rf"\g<1>{temp_strat_name}\2",
                content, count=1, flags=re.MULTILINE,
            )
            
            try:
                temp_strat_file.write_text(patched, encoding="utf-8")
                # Handle "py -m freqtrade" command by splitting it
                if freqtrade_exe == "py -m freqtrade":
                    cmd = ["py", "-m", "freqtrade", "test-strategy", "--userdir", str(user_data_dir), "--strategy", temp_strat_name]
                else:
                    cmd = [freqtrade_exe, "test-strategy", "--userdir", str(user_data_dir), "--strategy", temp_strat_name]
                proc = subprocess.run(
                    cmd,
                    capture_output=True, text=True, timeout=60,
                    cwd=str(strategies_dir.parent.parent),
                )
                combined = (proc.stdout + proc.stderr).strip()
                output_lines += ["", "── Freqtrade test-strategy ──"] + (combined.splitlines() or ["(no output)"])
                if proc.returncode != 0:
                    for line in combined.splitlines():
                        if any(k in line.lower() for k in ("error", "exception", "traceback")):
                            errors.append(line.replace(temp_strat_name, class_name))
                else:
                    output_lines += ["", "✓ Freqtrade structural validation passed"]
            except subprocess.TimeoutExpired:
                warnings.append("Freqtrade test-strategy timed out after 60 s.")
                output_lines.append("⚠ timed out.")
            except FileNotFoundError:
                warnings.append(f"freqtrade not found at '{freqtrade_exe}'.")
                output_lines.append("⚠ freqtrade not found — skipping structural check.")
            except Exception as exc:
                warnings.append(f"Freqtrade check failed: {exc}")
                output_lines.append(f"⚠ {exc}")
            finally:
                temp_strat_file.unlink(missing_ok=True)
                import sys
                pyc_ver = f"cpython-{sys.version_info.major}{sys.version_info.minor}"
                pyc = strategies_dir / "__pycache__" / f"{temp_strat_name}.{pyc_ver}.pyc"
                pyc.unlink(missing_ok=True)
            
            valid = len(errors) == 0
            _log_action(body.session_id, "validate_strategy_syntax", {
                "strategy_name": strategy_name,
                "valid": valid,
                "errors": errors,
                "warnings": warnings
            }, request)
            
            return ToolExecutionResponse(
                success=valid,
                error=errors[0] if errors else None,
                result={
                    "valid": valid,
                    "errors": errors,
                    "warnings": warnings,
                    "output": "\n".join(output_lines)
                },
                logs=output_lines
            )
            
        except Exception as e:
            return ToolExecutionResponse(
                success=False,
                error=f"Failed to validate strategy syntax: {str(e)}"
            )
