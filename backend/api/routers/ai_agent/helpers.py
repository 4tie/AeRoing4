"""Helper functions for AI agent router."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Request

from .session_manager import get_session_manager


def _strategies_dir(request: Request) -> Path:
    """Get the strategies directory from settings."""
    settings = request.app.state.services.settings_store.load()
    return Path(settings.strategies_directory_path).resolve()


def _log_action(session_id: str | None, action: str, details: dict[str, Any], request: Request | None = None) -> None:
    """Log an action to the session if session exists."""
    if session_id:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "details": details
        }
        get_session_manager(request).add_log(session_id, log_entry)


def _replace_section(content: str, section: str, new_section_code: str) -> str:
    """Replace a specific section in strategy file content.
    
    This is a simplified implementation. In production, you'd want more sophisticated
    AST-based parsing to reliably identify and replace sections.
    """
    # Define section markers
    section_patterns = {
        "buy_rules": ("# Buy signals", "# Sell signals"),
        "sell_rules": ("# Sell signals", "# Protections"),
        "indicators": ("# Indicators", "# Buy signals"),
        "protections": ("# Protections", "# ROI tables"),
        "parameters": ("# Parameters", "# Indicators")
    }
    
    if section == "full_file":
        return new_section_code
    
    if section not in section_patterns:
        # If we don't have a pattern for this section, append to end
        return content + f"\n\n# {section.upper()}\n{new_section_code}"
    
    start_marker, end_marker = section_patterns[section]
    
    # Find the section and replace it
    if start_marker in content:
        start_idx = content.find(start_marker)
        if end_marker in content:
            end_idx = content.find(end_marker)
            return content[:start_idx] + start_marker + "\n" + new_section_code + "\n" + content[end_idx:]
        else:
            return content[:start_idx] + start_marker + "\n" + new_section_code + "\n" + content[start_idx + len(start_marker):]
    else:
        # Section not found, append it
        return content + f"\n\n{start_marker}\n{new_section_code}\n"
