"""Router: GET /api/backtest/results/{run_id}

Returns a rich results payload for a completed backtest run, including
smart heuristic flags computed from the parsed summary.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...models import (
    BacktestAdvancedMetrics,
    BacktestTrade,
    HealthReport,
    PairResult,
    ParsedSummary,
    SmartFlag,
)
from ...services.backtest.results_analysis_service import (
    compute_health_report,
    compute_smart_flags,
    read_json,
)
from ..dependencies import get_services

router = APIRouter(prefix="/api/backtest", tags=["Backtest"])


class BacktestResultsResponse(BaseModel):
    run_id: str
    parsed_summary: ParsedSummary
    pair_results: list[PairResult]
    trades: list[BacktestTrade]
    advanced_metrics: BacktestAdvancedMetrics | None
    smart_flags: list[SmartFlag]
    health_report: HealthReport | None = None


@router.get(
    "/results/{run_id}",
    response_model=BacktestResultsResponse,
    summary="Get rich backtest results",
    description=(
        "Returns the full parsed results for a completed backtest run, "
        "including smart heuristic flags, exit reason breakdown, "
        "pair metrics, and individual trade list."
    ),
)
async def get_backtest_results(run_id: str, services=Depends(get_services)) -> BacktestResultsResponse:
    try:
        run_dir = services.run_repository.find_run_dir(run_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    summary_raw = read_json(run_dir / "parsed_summary.json")
    if summary_raw is None:
        metadata_raw = read_json(run_dir / "metadata.json")
        status = (metadata_raw or {}).get("run_status", "unknown")
        if status == "failed":
            exit_code = (metadata_raw or {}).get("freqtrade_exit_code")
            code_hint = f" (exit code {exit_code})" if exit_code is not None else ""
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Backtest run '{run_id}' failed{code_hint} and produced no results. "
                    "Check the run logs for the error details."
                ),
            )
        if status in {"running", "queued", "downloading"}:
            raise HTTPException(
                status_code=202,
                detail=f"Run '{run_id}' is still in progress (status: {status}).",
            )
        if status == "cancelled":
            raise HTTPException(
                status_code=410,
                detail=f"Run '{run_id}' was cancelled before it completed.",
            )
        raise HTTPException(
            status_code=404,
            detail=f"No results found for run '{run_id}' (status: {status}). The run may still be in progress.",
        )

    try:
        summary = ParsedSummary.model_validate(summary_raw)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to parse summary: {exc}")

    pair_results_raw = read_json(run_dir / "pair_results.json", default=[]) or []
    pair_results = [PairResult.model_validate(item) for item in pair_results_raw if isinstance(item, dict)]

    trades_raw = read_json(run_dir / "trades.json", default=[]) or []
    trades = [BacktestTrade.model_validate(item) for item in trades_raw if isinstance(item, dict)]

    advanced_raw = read_json(run_dir / "advanced_metrics.json")
    advanced = BacktestAdvancedMetrics.model_validate(advanced_raw) if advanced_raw else None

    smart_flags = compute_smart_flags(summary, trades)
    health_report = compute_health_report(summary, trades)

    return BacktestResultsResponse(
        run_id=run_id,
        parsed_summary=summary,
        pair_results=pair_results,
        trades=trades,
        advanced_metrics=advanced,
        smart_flags=smart_flags,
        health_report=health_report,
    ) 