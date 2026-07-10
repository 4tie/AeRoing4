"""Report endpoints for Auto-Quant."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from ....services.auto_quant import pipeline as _pl

from .html_report import _build_html_report


def register_reports_endpoints(router: APIRouter) -> None:
    """Register report endpoints on the given router."""
    
    @router.get(
        "/report/{run_id}",
        summary="Get final pipeline report",
    )
    async def get_report(run_id: str) -> dict:
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        if state.status not in ("completed", "failed", "interrupted"):
            raise HTTPException(status_code=409,
                                detail="Pipeline has not completed yet. Poll /status first.")
        if state.report is None:
            # Try loading from disk
            import json
            out_dir = Path(state.user_data_dir) / "auto_quant" / run_id
            for report_path in (out_dir / "report_latest.json", out_dir / "report.json"):
                if report_path.exists():
                    return json.loads(report_path.read_text(encoding="utf-8"))
            raise HTTPException(status_code=404, detail="Report not found.")
        return state.report

    @router.get(
        "/report/{run_id}/html",
        summary="Download HTML summary report for a completed pipeline run",
    )
    async def get_report_html(run_id: str) -> Response:
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        if state.status not in ("completed", "failed", "interrupted"):
            raise HTTPException(status_code=409,
                                detail="Pipeline has not completed yet. Poll /status first.")

        report: dict[str, Any] | None = state.report
        if report is None:
            import json
            out_dir = Path(state.user_data_dir) / "auto_quant" / run_id
            for report_path in (out_dir / "report_latest.json", out_dir / "report.json"):
                if report_path.exists():
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    break
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found.")

        wfo_windows: list = state.wfo_windows or report.get("wfo_windows") or []
        html = _build_html_report(report, wfo_windows)
        return Response(
            content=html,
            media_type="text/html",
            headers={"Content-Disposition": f'attachment; filename="report-{run_id}.html"'},
        )
