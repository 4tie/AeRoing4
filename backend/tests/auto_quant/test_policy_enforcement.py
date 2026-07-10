"""Policy Enforcement Tests - Ensure no hardcoded policy constants in business logic.

This test suite verifies that pipeline stages use policy helpers instead of
hardcoded constants for thresholds, timeframes, pair counts, etc.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

# Common hardcoded threshold patterns that should NOT appear in business logic
FORBIDDEN_PATTERNS = [
    # Threshold defaults should come from policy/config. Do not flag percentage
    # conversion, scoring, display formatting, or test fixture arithmetic.
    r"(max_drawdown|drawdown_threshold|min_win_rate|win_rate_threshold|min_profit_factor|profit_factor_threshold|min_sharpe)\s*=\s*(0\.[345]\d?|[345]0\.0?|1\.[035])",
    r"(min_trades|trade_count_threshold)\s*=\s*(15|100)",
    # Timeframe strings that should come from policy
    r'"1m"',        # 1m timeframe
    r'"5m"',        # 5m timeframe
    r'"15m"',       # 15m timeframe
    r'"1h"',        # 1h timeframe
    r'"4h"',        # 4h timeframe
    r'"1d"',        # 1d timeframe
    # Risk profile strings
    r'"conservative"',
    r'"balanced"',
    r'"aggressive"',
]

# Allowed patterns (e.g., in comments, tests, or policy module itself)
ALLOWED_CONTEXTS = [
    "test_",
    "policy",
    "config",
    "thresholds",
    "#",
    '"""',
    "'''",
]


def _is_in_allowed_context(line: str, file_path: Path) -> bool:
    """Check if a line is in an allowed context (test, policy, comment)."""
    for allowed in ALLOWED_CONTEXTS:
        if allowed in line.lower():
            return True
    # Skip the policy module itself
    if "policy" in str(file_path).lower():
        return True
    return False


def _scan_file_for_hardcoded_constants(file_path: Path) -> list[tuple[int, str, str]]:
    """Scan a Python file for hardcoded policy constants.
    
    Returns:
        List of (line_number, line_content, matched_pattern) tuples
    """
    violations = []
    
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split("\n")
        
        for line_num, line in enumerate(lines, 1):
            if _is_in_allowed_context(line, file_path):
                continue
                
            for pattern in FORBIDDEN_PATTERNS:
                if re.search(pattern, line):
                    violations.append((line_num, line.strip(), pattern))
                    break
    except Exception:
        pass
    
    return violations


def test_no_hardcoded_thresholds_in_stages():
    """Test that pipeline stage modules don't hardcode threshold values."""
    pipeline_modules_dir = Path(__file__).parent.parent.parent / "services" / "auto_quant" / "pipeline_modules"
    
    stage_files = [
        "stages_optimization.py",
        "stages_validation.py",
        "stages_assessment.py",
        "orchestrator.py",
    ]
    
    all_violations = []
    
    for stage_file in stage_files:
        file_path = pipeline_modules_dir / stage_file
        if not file_path.exists():
            continue
            
        violations = _scan_file_for_hardcoded_constants(file_path)
        if violations:
            all_violations.extend([(stage_file, *v) for v in violations])
    
    if all_violations:
        violation_msg = "Found hardcoded policy constants in stage modules:\n"
        for file_name, line_num, line, pattern in all_violations:
            violation_msg += f"  {file_name}:{line_num}: {line} (pattern: {pattern})\n"
        pytest.fail(violation_msg)


def test_policy_helpers_used_for_thresholds():
    """Test that policy helpers are used for accessing thresholds."""
    pipeline_modules_dir = Path(__file__).parent.parent.parent / "services" / "auto_quant" / "pipeline_modules"
    
    stage_files = [
        "stages_optimization.py",
        "stages_validation.py",
        "stages_assessment.py",
    ]
    
    for stage_file in stage_files:
        file_path = pipeline_modules_dir / stage_file
        if not file_path.exists():
            continue
            
        content = file_path.read_text(encoding="utf-8")
        
        # Check that policy helpers are imported
        if "from ..policy import" not in content and "from ...policy import" not in content:
            pytest.fail(f"{stage_file} does not import from policy module")
        
        # Check that policy helpers are used
        policy_helpers = [
            "load_policy",
            "thresholds_for",
            "style_timeframes",
            "pair_target_count",
            "default_pair_universe",
            "score_strategy",
            "readiness_for_score",
            "walk_forward_windows_for_depth",
            "min_wfo_windows",
            "wfo_skip_note",
        ]
        
        helpers_used = any(helper in content for helper in policy_helpers)
        if not helpers_used:
            pytest.fail(f"{stage_file} imports policy but doesn't use any policy helpers")


def test_no_magic_numbers_for_timeframes():
    """Test that timeframe values come from policy, not hardcoded strings."""
    pipeline_modules_dir = Path(__file__).parent.parent.parent / "services" / "auto_quant" / "pipeline_modules"
    
    stage_files = [
        "stages_optimization.py",
        "stages_validation.py",
        "stages_assessment.py",
        "orchestrator.py",
    ]
    
    for stage_file in stage_files:
        file_path = pipeline_modules_dir / stage_file
        if not file_path.exists():
            continue
            
        content = file_path.read_text(encoding="utf-8")
        
        # Look for timeframe string literals not in policy context
        lines = content.split("\n")
        for line_num, line in enumerate(lines, 1):
            if _is_in_allowed_context(line, file_path):
                continue
                
            # Check for hardcoded timeframe strings
            if re.search(r'["\']([135]m|[14]h|1d)["\']', line):
                # Allow if it's in a comparison or assignment from policy
                if "policy" not in line.lower() and "style_timeframes" not in line:
                    pytest.fail(
                        f"{stage_file}:{line_num}: Hardcoded timeframe string found: {line.strip()}"
                    )


def test_policy_module_exists_and_is_complete():
    """Test that policy module exists and has required helpers."""
    policy_path = Path(__file__).parent.parent.parent / "services" / "auto_quant" / "policy" / "__init__.py"
    
    if not policy_path.exists():
        pytest.fail("Policy module does not exist")
    
    content = policy_path.read_text(encoding="utf-8")
    
    required_helpers = [
        "thresholds_for",
        "style_timeframes",
        "pair_target_count",
        "default_pair_universe",
        "score_strategy",
        "readiness_for_score",
        "discovery_timeframe_gates",
        "discovery_pair_gates",
        "min_wfo_windows",
        "wfo_skip_note",
    ]
    
    for helper in required_helpers:
        if f"def {helper}" not in content:
            pytest.fail(f"Policy module missing required helper: {helper}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
