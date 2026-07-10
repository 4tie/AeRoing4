"""
Run Repository
Data access layer for AutoQuant pipeline runs
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import json
from pathlib import Path
from datetime import datetime


@dataclass
class PipelineRun:
    """AutoQuant pipeline run data model"""
    run_id: str
    strategy_id: str
    strategy_name: str
    status: str  # queued, running, completed, failed
    current_stage: str
    progress: float  # 0-100
    candidates: List[Dict[str, Any]]
    promising: List[Dict[str, Any]]
    validated: List[Dict[str, Any]]
    elite: List[Dict[str, Any]]
    errors: List[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    elapsed_seconds: float
    eta_seconds: float


class RunRepository:
    """Repository for AutoQuant pipeline runs"""
    
    def __init__(self, data_dir: str = "user_data/auto_quant"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def save(self, run: PipelineRun) -> bool:
        """Save pipeline run to disk"""
        try:
            run_file = self.data_dir / f"{run.run_id}.json"
            with open(run_file, 'w') as f:
                json.dump({
                    'run_id': run.run_id,
                    'strategy_id': run.strategy_id,
                    'strategy_name': run.strategy_name,
                    'status': run.status,
                    'current_stage': run.current_stage,
                    'progress': run.progress,
                    'candidates': run.candidates,
                    'promising': run.promising,
                    'validated': run.validated,
                    'elite': run.elite,
                    'errors': run.errors,
                    'started_at': run.started_at,
                    'completed_at': run.completed_at,
                    'elapsed_seconds': run.elapsed_seconds,
                    'eta_seconds': run.eta_seconds,
                }, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving run: {e}")
            return False
    
    def load(self, run_id: str) -> Optional[PipelineRun]:
        """Load pipeline run from disk"""
        try:
            run_file = self.data_dir / f"{run_id}.json"
            if not run_file.exists():
                return None
            
            with open(run_file, 'r') as f:
                data = json.load(f)
            
            return PipelineRun(
                run_id=data['run_id'],
                strategy_id=data['strategy_id'],
                strategy_name=data['strategy_name'],
                status=data['status'],
                current_stage=data['current_stage'],
                progress=data['progress'],
                candidates=data['candidates'],
                promising=data['promising'],
                validated=data['validated'],
                elite=data['elite'],
                errors=data['errors'],
                started_at=data['started_at'],
                completed_at=data['completed_at'],
                elapsed_seconds=data['elapsed_seconds'],
                eta_seconds=data['eta_seconds'],
            )
        except Exception as e:
            print(f"Error loading run: {e}")
            return None
    
    def list_all(self) -> List[PipelineRun]:
        """List all pipeline runs"""
        runs = []
        for run_file in self.data_dir.glob("*.json"):
            run = self.load(run_file.stem)
            if run:
                runs.append(run)
        return sorted(runs, key=lambda x: x.started_at or '', reverse=True)
    
    def delete(self, run_id: str) -> bool:
        """Delete pipeline run"""
        try:
            run_file = self.data_dir / f"{run_id}.json"
            if run_file.exists():
                run_file.unlink()
                return True
            return False
        except Exception as e:
            print(f"Error deleting run: {e}")
            return False
    
    def update_status(
        self,
        run_id: str,
        status: str,
        current_stage: Optional[str] = None,
        progress: Optional[float] = None
    ) -> bool:
        """Update run status"""
        run = self.load(run_id)
        if not run:
            return False
        
        run.status = status
        if current_stage:
            run.current_stage = current_stage
        if progress is not None:
            run.progress = progress
        
        if status == 'completed':
            run.completed_at = datetime.now().isoformat()
        
        return self.save(run)
