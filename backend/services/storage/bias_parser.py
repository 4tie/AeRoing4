"""
Bias Check Result Parser
Parses outputs from Freqtrade lookahead and recursive analysis.
"""

import csv
import re
from typing import Dict, Any, List, Optional
from pathlib import Path


class BiasParser:
    """Parser for Bias Check command outputs."""
    
    @staticmethod
    def parse_lookahead_csv(csv_path: str) -> Dict[str, Any]:
        """Parse lookahead analysis CSV export."""
        path = Path(csv_path)
        if not path.exists():
            return {"status": "error", "message": "CSV file not found"}
            
        results = []
        has_bias = False
        
        try:
            with open(path, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # freqtrade lookahead analysis export usually has columns like
                    # pair, profit_ratio, has_bias, etc.
                    # We look for a clear indicator of bias.
                    results.append(row)
                    if str(row.get('has_bias', 'false')).lower() == 'true':
                        has_bias = True
                        
            return {
                "status": "success",
                "has_bias": has_bias,
                "evidence": results,
                "message": "Lookahead analysis completed successfully."
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to parse CSV: {str(e)}"}
            
    @staticmethod
    def parse_lookahead_stdout(stdout: str) -> Dict[str, Any]:
        """Fallback parse from stdout if CSV is missing or empty."""
        if "Lookahead bias found" in stdout or "has lookahead bias" in stdout.lower():
            return {"status": "success", "has_bias": True, "message": "Bias found in stdout"}
        elif "No lookahead bias" in stdout or "0 pairs with lookahead" in stdout.lower():
             return {"status": "success", "has_bias": False, "message": "No bias found in stdout"}
        
        # If we can't determine it, we assume we failed to parse
        return {"status": "error", "message": "Malformed or unrecognized lookahead analysis output"}
        
    @staticmethod
    def parse_recursive_stdout(stdout: str) -> Dict[str, Any]:
        """Parse recursive analysis stdout."""
        # Freqtrade recursive analysis prints if indicators change when starting from different points.
        # e.g., "Recursive bias found" or "Recursive formula issue detected"
        if "Recursive formula issue detected" in stdout or "recursive bias found" in stdout.lower() or "indicators are recursive" in stdout.lower():
            return {"status": "success", "has_bias": True, "message": "Recursive issue detected in stdout"}
        elif "No recursive formula" in stdout or "0 recursive" in stdout.lower() or "All indicators are stable" in stdout.lower() or "No issues found" in stdout:
             return {"status": "success", "has_bias": False, "message": "No recursive issue found in stdout"}
             
        # Catch standard freqtrade successful completion text if no specific "No recursive" message
        if "recursive-analysis completed" in stdout.lower():
             return {"status": "success", "has_bias": False, "message": "Command completed, no recursive issue raised"}
             
        # Fallback to error
        return {"status": "error", "message": "Malformed or unrecognized recursive analysis output"}

