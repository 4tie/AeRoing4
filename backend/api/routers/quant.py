"""Router: /api/quant/*

  POST /api/quant/backtest        — Run a backtest
  POST /api/quant/download        — Download market data
  POST /api/quant/hyperopt        — Run hyperopt optimization
  POST /api/quant/compare         — Compare strategies
  POST /api/quant/report          — Generate a report
  GET  /api/quant/reports         — List available reports
  GET  /api/quant/reports/{name}  — Get specific report
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ...app_services import AppServices
from ..dependencies import get_services

router = APIRouter(prefix="/api/quant", tags=["Quant"])


# ── Request / response models ─────────────────────────────────────────────────


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    strategy: str = Field(..., description="Strategy name")
    timeframe: str = Field("1h", description="Timeframe (e.g., 1h, 4h, 1d)")
    timerange: str = Field("20240101-20240601", description="Time range")
    pairs: list[str] | None = Field(None, description="Trading pairs")


class DownloadRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pairs: list[str] = Field(..., description="Trading pairs")
    timeframe: str = Field("1h", description="Timeframe")
    timerange: str = Field("20240101-20240601", description="Time range")


class HyperoptRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    strategy: str = Field(..., description="Strategy name")
    timeframe: str = Field("1h", description="Timeframe")
    timerange: str = Field("20240101-20240601", description="Time range")
    spaces: list[str] | None = Field(None, description="Optimization spaces")
    epochs: int = Field(100, description="Number of epochs")


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    strategies: list[str] = Field(..., description="Strategy names")
    timeframe: str = Field("1h", description="Timeframe")
    timerange: str = Field("20240101-20240601", description="Time range")


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: dict = Field(..., description="Data to include in report")
    report_type: str = Field("backtest", description="Report type")


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post(
    "/backtest",
    summary="Run a backtest",
    description="Run a backtest for a strategy with specified parameters.",
)
async def run_backtest(
    request: BacktestRequest,
    services: AppServices = Depends(get_services),
) -> dict:
    """Run a backtest for a strategy."""
    from ...services.quant import QuantService

    quant_service = QuantService(services.settings_store, services.root_dir)
    results = await quant_service.run_backtest(
        request.strategy,
        request.timeframe,
        request.timerange,
        request.pairs,
    )
    return results


@router.post(
    "/download",
    summary="Download market data",
    description="Download market data for specified pairs.",
)
async def download_data(
    request: DownloadRequest,
    services: AppServices = Depends(get_services),
) -> dict:
    """Download market data for pairs."""
    from ...services.quant import QuantService

    quant_service = QuantService(services.settings_store, services.root_dir)
    results = await quant_service.download_data(
        request.pairs,
        request.timeframe,
        request.timerange,
    )
    return results


@router.post(
    "/hyperopt",
    summary="Run hyperopt optimization",
    description="Run hyperopt optimization for a strategy.",
)
async def run_hyperopt(
    request: HyperoptRequest,
    services: AppServices = Depends(get_services),
) -> dict:
    """Run hyperopt optimization."""
    from ...services.quant import QuantService

    quant_service = QuantService(services.settings_store, services.root_dir)
    results = await quant_service.run_hyperopt(
        request.strategy,
        request.timeframe,
        request.timerange,
        request.spaces,
        request.epochs,
    )
    return results


@router.post(
    "/compare",
    summary="Compare strategies",
    description="Compare multiple strategies.",
)
async def compare_strategies(
    request: CompareRequest,
    services: AppServices = Depends(get_services),
) -> dict:
    """Compare multiple strategies."""
    from ...services.quant import QuantService

    quant_service = QuantService(services.settings_store, services.root_dir)
    results = await quant_service.compare_strategies(
        request.strategies,
        request.timeframe,
        request.timerange,
    )
    return results


@router.post(
    "/report",
    summary="Generate a report",
    description="Generate a Markdown report from data.",
)
async def generate_report(
    request: ReportRequest,
    services: AppServices = Depends(get_services),
) -> dict:
    """Generate a Markdown report."""
    from ...services.quant import QuantService

    quant_service = QuantService(services.settings_store, services.root_dir)
    report_path = await quant_service.generate_report(request.data, request.report_type)
    return {"report_path": report_path}


@router.get(
    "/reports",
    summary="List available reports",
    description="List all available Quant reports.",
)
async def list_reports(
    services: AppServices = Depends(get_services),
) -> dict:
    """List all available reports."""
    from ...services.quant import QuantService

    quant_service = QuantService(services.settings_store, services.root_dir)
    reports = quant_service.list_reports()
    return {"reports": reports}


@router.get(
    "/reports/{report_name}",
    summary="Get a specific report",
    description="Get the content of a specific report.",
)
async def get_report(
    report_name: str,
    services: AppServices = Depends(get_services),
) -> dict:
    """Get a specific report content."""
    from ...services.quant import QuantService

    quant_service = QuantService(services.settings_store, services.root_dir)
    content = quant_service.get_report(report_name)
    
    if content is None:
        raise HTTPException(status_code=404, detail="Report not found")
    
    return {"name": report_name, "content": content}
