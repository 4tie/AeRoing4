"""Workflow tool registry - single source of truth for tool definitions.

This registry defines:
- Tool name and description
- Argument model (Pydantic schema)
- Ollama tool schema
- Safety classification
- Whether it's exposed to the model
- Whether it's long-running
- Executor handler name
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from .workflow_tool_models import (
    EditStrategySectionArgs,
    GetPairUniverseArgs,
    InspectAppStructureArgs,
    ListStrategiesArgs,
    ReadStrategyFileArgs,
    RunBacktestArgs,
    RunOptimizerArgs,
    RunPairExplorerArgs,
    RunPairStressLabArgs,
    RunTemporalStressTestArgs,
    ToolSafety,
    ValidateStrategySyntaxArgs,
    ViewBestParamsArgs,
    ViewTrialParamsArgs,
)


# ── Tool registry entries ────────────────────────────────────────────────────────


class ToolSpec:
    """Specification for a single workflow tool."""

    def __init__(
        self,
        name: str,
        description: str,
        argument_model: type,
        safety: ToolSafety,
        exposed_to_model: bool = True,
        long_running: bool = False,
        result_size_limit: int = 100_000,
        handler_name: str | None = None,
    ):
        self.name = name
        self.description = description
        self.argument_model = argument_model
        self.safety = safety
        self.exposed_to_model = exposed_to_model
        self.long_running = long_running
        self.result_size_limit = result_size_limit
        self.handler_name = handler_name or name

    def to_ollama_schema(self) -> dict[str, Any]:
        """Convert to Ollama tool schema format.

        Ollama (and OpenAI-compatible servers) expect each tool wrapped as
        ``{"type": "function", "function": {name, description, parameters}}``.
        Without the wrapper, models ignore the tool and answer with plain text,
        which silently breaks the whole tool-calling loop.
        """
        function = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }

        # Extract Pydantic model schema
        if hasattr(self.argument_model, "model_fields"):
            for field_name, field_info in self.argument_model.model_fields.items():
                prop_schema = {"type": "string"}  # Default to string for simplicity
                
                # Try to infer type from field
                if field_info.annotation:
                    annotation_str = str(field_info.annotation)
                    if "int" in annotation_str:
                        prop_schema["type"] = "integer"
                    elif "float" in annotation_str:
                        prop_schema["type"] = "number"
                    elif "bool" in annotation_str:
                        prop_schema["type"] = "boolean"
                    elif "list" in annotation_str:
                        prop_schema["type"] = "array"
                        prop_schema["items"] = {"type": "string"}

                function["parameters"]["properties"][field_name] = prop_schema
                
                # Check if required
                if field_info.is_required():
                    function["parameters"]["required"].append(field_name)

        return {"type": "function", "function": function}


# ── Registry definition ───────────────────────────────────────────────────────────


_TOOL_REGISTRY: dict[str, ToolSpec] = {
    # READ-ONLY, AUTO-EXECUTE
    "inspect_app_structure": ToolSpec(
        name="inspect_app_structure",
        description="Inspect the app structure to understand available tools, strategy folder location, and how to run Pair Explorer, Backtest, Optimizer, and Stress Test Lab. Returns the app configuration and available endpoints.",
        argument_model=InspectAppStructureArgs,
        safety=ToolSafety.READ_ONLY,
        exposed_to_model=True,
        long_running=False,
    ),
    "list_strategies": ToolSpec(
        name="list_strategies",
        description="List all available strategies in the strategies directory. Returns strategy names, file paths, and metadata.",
        argument_model=ListStrategiesArgs,
        safety=ToolSafety.READ_ONLY,
        exposed_to_model=True,
        long_running=False,
    ),
    "read_strategy_file": ToolSpec(
        name="read_strategy_file",
        description="Read a Freqtrade strategy .py and .json files from the strategies directory. Returns the file contents for analysis and editing.",
        argument_model=ReadStrategyFileArgs,
        safety=ToolSafety.READ_ONLY,
        exposed_to_model=True,
        long_running=False,
    ),
    "validate_strategy_syntax": ToolSpec(
        name="validate_strategy_syntax",
        description="Validate a strategy's Python syntax and Freqtrade compatibility. Runs py_compile and freqtrade test-strategy checks. Use this before and after editing to ensure the strategy remains valid.",
        argument_model=ValidateStrategySyntaxArgs,
        safety=ToolSafety.READ_ONLY,
        exposed_to_model=True,
        long_running=False,
    ),
    "view_best_params": ToolSpec(
        name="view_best_params",
        description="View the best trial parameters from an optimizer session without writing files.",
        argument_model=ViewBestParamsArgs,
        safety=ToolSafety.READ_ONLY,
        exposed_to_model=True,
        long_running=False,
    ),
    "view_trial_params": ToolSpec(
        name="view_trial_params",
        description="View a specific trial's parameters from an optimizer session without writing files.",
        argument_model=ViewTrialParamsArgs,
        safety=ToolSafety.READ_ONLY,
        exposed_to_model=True,
        long_running=False,
    ),
    "get_pair_universe": ToolSpec(
        name="get_pair_universe",
        description=(
            "Return the real application pair universe from PairSelectorService. "
            "Supports optional filters: quote_currency (e.g. 'USDT' keeps only */USDT pairs), "
            "exclude_pairs (list of pairs to omit), and max_candidates (cap). "
            "Does NOT claim profitability — returns available candidates only. "
            "Call this before run_pair_explorer to determine which pairs to test."
        ),
        argument_model=GetPairUniverseArgs,
        safety=ToolSafety.READ_ONLY,
        exposed_to_model=True,
        long_running=False,
    ),
    # CONFIRMATION REQUIRED
    "run_backtest": ToolSpec(
        name="run_backtest",
        description="Run a backtest for a strategy with specified parameters. Returns detailed metrics including profit, drawdown, trade count, win rate, and other performance indicators.",
        argument_model=RunBacktestArgs,
        safety=ToolSafety.CONFIRMATION_REQUIRED,
        exposed_to_model=True,
        long_running=True,
        handler_name="run_backtest",
    ),
    "run_optimizer": ToolSpec(
        name="run_optimizer",
        description="Run the optimizer to find optimal parameters for a strategy. Optimizes specified parameter spaces and returns the best parameters found.",
        argument_model=RunOptimizerArgs,
        safety=ToolSafety.CONFIRMATION_REQUIRED,
        exposed_to_model=True,
        long_running=True,
        handler_name="run_optimizer",
    ),
    # HIDDEN - Not yet implemented
    "run_pair_explorer": ToolSpec(
        name="run_pair_explorer",
        description="Run Pair Explorer to test a strategy across a broad pair universe. Tests multiple pairs and returns performance metrics for each pair including net profit, profit factor, drawdown, trade count, expectancy, and win rate.",
        argument_model=RunPairExplorerArgs,
        safety=ToolSafety.CONFIRMATION_REQUIRED,
        exposed_to_model=True,
        long_running=True,
        handler_name="run_pair_explorer",
    ),
    "run_pair_stress_lab": ToolSpec(
        name="run_pair_stress_lab",
        description="Run Pair Stress Lab to test strategy robustness across random pair sets.",
        argument_model=RunPairStressLabArgs,
        safety=ToolSafety.CONFIRMATION_REQUIRED,
        exposed_to_model=False,  # Hidden until implemented
        long_running=True,
        handler_name="run_pair_stress_lab",
    ),
    "run_temporal_stress_test": ToolSpec(
        name="run_temporal_stress_test",
        description="Run Temporal Stress Test Lab including Time Split (out-of-sample validation), Monte Carlo simulation, and crash gauntlet tests.",
        argument_model=RunTemporalStressTestArgs,
        safety=ToolSafety.CONFIRMATION_REQUIRED,
        exposed_to_model=False,  # Hidden until implemented
        long_running=True,
        handler_name="run_temporal_stress_test",
    ),
    "edit_strategy_section": ToolSpec(
        name="edit_strategy_section",
        description="Edit a specific section of a strategy file (buy rules, sell rules, indicators, etc.). Creates a versioned snapshot before editing, validates syntax, and allows rollback. Use this to modify existing strategies rather than creating entirely new files.",
        argument_model=EditStrategySectionArgs,
        safety=ToolSafety.CONFIRMATION_REQUIRED,
        exposed_to_model=False,  # Hidden until implemented
        long_running=False,
        handler_name="edit_strategy_section",
    ),
}


# ── Registry access functions ─────────────────────────────────────────────────────


def get_tool_spec(name: str) -> ToolSpec | None:
    """Get tool specification by name."""
    return _TOOL_REGISTRY.get(name)


def validate_tool_arguments(name: str, arguments: dict[str, Any]) -> tuple[bool, str | None, Any]:
    """Validate tool arguments against the registered model.
    
    Returns:
        (is_valid, error_message, validated_model)
    """
    spec = get_tool_spec(name)
    if spec is None:
        return False, f"Unknown tool: {name}", None
    
    try:
        validated = spec.argument_model(**arguments)
        return True, None, validated
    except ValidationError as exc:
        error_msg = f"Invalid arguments for {name}: " + str(exc)
        return False, error_msg, None


def get_model_tools(mode: str | None = None) -> list[dict[str, Any]]:
    """Get all tools exposed to the model for a given mode.
    
    Args:
        mode: Optional mode filter (e.g., 'autoquant', 'strategylab')
              Currently all exposed tools are returned regardless of mode.
    
    Returns:
        List of Ollama tool schemas.
    """
    return [
        spec.to_ollama_schema()
        for spec in _TOOL_REGISTRY.values()
        if spec.exposed_to_model
    ]


def get_tool_safety(name: str) -> ToolSafety:
    """Get safety classification for a tool."""
    spec = get_tool_spec(name)
    if spec is None:
        return ToolSafety.FORBIDDEN
    return spec.safety


def is_long_running(name: str) -> bool:
    """Check if a tool is long-running."""
    spec = get_tool_spec(name)
    if spec is None:
        return False
    return spec.long_running


def calculate_arguments_hash(name: str, arguments: dict[str, Any]) -> str:
    """Calculate a canonical hash for tool name + normalized arguments.
    
    Used for duplicate detection within a single turn.
    """
    # Normalize arguments: sort keys, convert to consistent JSON
    normalized = json.dumps(arguments, sort_keys=True, default=str)
    payload = f"{name}:{normalized}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def list_all_tools() -> list[str]:
    """List all registered tool names."""
    return sorted(_TOOL_REGISTRY.keys())


def get_handler_name(name: str) -> str | None:
    """Get the executor handler name for a tool."""
    spec = get_tool_spec(name)
    if spec is None:
        return None
    return spec.handler_name
