"""Download and export endpoints for Auto-Quant."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ....services.auto_quant import pipeline as _pl

from .export_helpers import create_export_bundle


def register_download_endpoints(router: APIRouter) -> None:
    """Register download and export endpoints on the given router."""
    
    @router.get(
        "/download/{run_id}/{filename}",
        summary="Download pipeline output file",
    )
    async def download_file(run_id: str, filename: str) -> FileResponse:
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")

        # Security: only allow specific filenames
        allowed_suffixes = {".py", ".json"}
        if Path(filename).suffix not in allowed_suffixes:
            raise HTTPException(status_code=400, detail="Only .py and .json files can be downloaded.")
        if "/" in filename or "\\" in filename or ".." in filename:
            raise HTTPException(status_code=400, detail="Invalid filename.")

        out_dir = Path(state.user_data_dir) / "auto_quant" / run_id
        file_path = out_dir / filename

        # Also check strategies dir for the .py file
        if not file_path.exists() and filename.endswith(".py"):
            runtime_dir = Path(state.user_data_dir) / "auto_quant" / run_id / "strategies"
            file_path = runtime_dir / filename
        if not file_path.exists() and filename.endswith(".py"):
            strategies_dir = Path(state.user_data_dir) / "strategies"
            file_path = strategies_dir / filename

        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"File '{filename}' not found.")

        media_type = "text/x-python" if filename.endswith(".py") else "application/json"
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type=media_type,
        )

    @router.post(
        "/export/{run_id}",
        status_code=200,
        summary="Download a Freqtrade-ready deployment bundle for a completed run",
    )
    async def export_pipeline(run_id: str) -> FileResponse:
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        if state.status != "completed":
            raise HTTPException(
                status_code=409,
                detail=f"Pipeline run '{run_id}' is not completed (current status: {state.status}).",
            )

        zip_path, zip_filename = create_export_bundle(state, run_id)

        return FileResponse(
            path=str(zip_path),
            filename=zip_filename,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
        )
