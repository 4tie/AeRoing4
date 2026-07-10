"""
Bias Check Runner
External integration for Freqtrade lookahead and recursive analysis.
"""

from typing import List, Optional
from dataclasses import dataclass
import subprocess
import time
from pathlib import Path


@dataclass
class BiasCheckCommandConfig:
    """Configuration for bias check execution."""
    strategy_name: str
    strategy_path: Optional[str] = None
    timeframe: str = "5m"
    pairs: List[str] = None
    timerange: str = ""
    export_filename: Optional[str] = None
    timeout_seconds: int = 600


@dataclass
class BiasCheckCommandResult:
    """Raw result of a bias check command execution."""
    success: bool
    exit_code: Optional[int]
    stdout: str
    stderr: str
    duration_seconds: float
    timeout: bool = False
    command: str = ""


class BiasCheckRunner:
    """Executor for Freqtrade lookahead and recursive analysis."""
    
    def __init__(self, freqtrade_path: Optional[str] = None):
        self.freqtrade_path = freqtrade_path or "freqtrade"
    
    def run_lookahead_analysis(self, config: BiasCheckCommandConfig) -> BiasCheckCommandResult:
        """Execute lookahead analysis."""
        cmd = [
            self.freqtrade_path,
            'lookahead-analysis',
            '--strategy', config.strategy_name,
            '--timeframe', config.timeframe,
            '--timerange', config.timerange,
        ]
        
        if config.strategy_path:
            cmd.extend(['--strategy-path', config.strategy_path])
            
        if config.pairs:
            for pair in config.pairs:
                cmd.extend(['--pairs', pair])
                
        if config.export_filename:
            cmd.extend(['--lookahead-analysis-exportfilename', config.export_filename])
            
        return self._execute_command(cmd, config.timeout_seconds)
        
    def run_recursive_analysis(self, config: BiasCheckCommandConfig) -> BiasCheckCommandResult:
        """Execute recursive analysis."""
        cmd = [
            self.freqtrade_path,
            'recursive-analysis',
            '--strategy', config.strategy_name,
            '--timeframe', config.timeframe,
            '--timerange', config.timerange,
        ]
        
        if config.strategy_path:
            cmd.extend(['--strategy-path', config.strategy_path])
            
        if config.pairs:
            for pair in config.pairs:
                cmd.extend(['--pairs', pair])
                
        return self._execute_command(cmd, config.timeout_seconds)
        
    def _execute_command(self, cmd: List[str], timeout: int) -> BiasCheckCommandResult:
        """Internal execution helper."""
        cmd_str = " ".join(cmd)
        start_time = time.time()
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            duration = time.time() - start_time
            
            return BiasCheckCommandResult(
                success=(result.returncode == 0),
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_seconds=duration,
                timeout=False,
                command=cmd_str
            )
            
        except subprocess.TimeoutExpired as e:
            duration = time.time() - start_time
            return BiasCheckCommandResult(
                success=False,
                exit_code=None,
                stdout=e.stdout.decode('utf-8') if e.stdout else "",
                stderr=e.stderr.decode('utf-8') if e.stderr else "",
                duration_seconds=duration,
                timeout=True,
                command=cmd_str
            )
        except Exception as e:
            duration = time.time() - start_time
            return BiasCheckCommandResult(
                success=False,
                exit_code=None,
                stdout="",
                stderr=str(e),
                duration_seconds=duration,
                timeout=False,
                command=cmd_str
            )
