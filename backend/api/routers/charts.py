"""Router: Professional chart data endpoints using mplfinance.

Provides chart data for candlestick charts, technical indicators, and overlays
from Freqtrade backtest results.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...core.errors import BackendError
from ...models import (
    ChartDataResponse,
    ChartRequest,
)
from ...services.charting import MplfinanceService
from ...services.storage.run_repository import RunRepository
from ..dependencies import get_services

router = APIRouter(prefix="/api/charts", tags=["Charts"])


@router.get(
    "/backtest/{run_id}/candlestick",
    response_model=ChartDataResponse,
    summary="Get candlestick chart data for backtest",
    description=(
        "Returns OHLC candlestick data with optional technical indicators "
        "for a specific backtest run."
    ),
)
async def get_backtest_candlestick(
    run_id: str,
    include_sma: bool = True,
    include_ema: bool = True,
    include_rsi: bool = True,
    include_macd: bool = True,
    include_bollinger: bool = True,
    services=Depends(get_services),
) -> ChartDataResponse:
    """Get candlestick chart data for a backtest run."""
    try:
        # Load trades from backtest result
        run_repo = services.run_repository
        trades_data = run_repo.load_trades(run_id)
        
        if not trades_data:
            # Return empty chart data instead of 404 error
            empty_chart = {
                "candlestick": {
                    "timestamps": [],
                    "open": [],
                    "high": [],
                    "low": [],
                    "close": [],
                    "volume": []
                },
                "indicators": {}
            }
            return ChartDataResponse(**empty_chart)
        
        # Convert trades to list of dicts
        trades = [trade.model_dump() if hasattr(trade, 'model_dump') else trade for trade in trades_data]
        
        # Generate chart data
        chart_service = MplfinanceService()
        chart_data = chart_service.prepare_chart_data(
            trades=trades,
            include_sma=include_sma,
            include_ema=include_ema,
            include_rsi=include_rsi,
            include_macd=include_macd,
            include_bollinger=include_bollinger,
        )
        
        return ChartDataResponse(**chart_data)
        
    except BackendError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate chart data: {str(e)}")


@router.get(
    "/autoquant/{run_id}/candlestick",
    response_model=ChartDataResponse,
    summary="Get candlestick chart data for AutoQuant run",
    description=(
        "Returns OHLC candlestick data with optional technical indicators "
        "for a specific AutoQuant run."
    ),
)
async def get_autoquant_candlestick(
    run_id: str,
    include_sma: bool = True,
    include_ema: bool = True,
    include_rsi: bool = True,
    include_macd: bool = True,
    include_bollinger: bool = True,
    services=Depends(get_services),
) -> ChartDataResponse:
    """Get candlestick chart data for an AutoQuant run."""
    try:
        # Load trades from AutoQuant result
        run_repo = services.run_repository
        trades_data = run_repo.load_trades(run_id)
        
        if not trades_data:
            # Return empty chart data instead of 404 error
            empty_chart = {
                "candlestick": {
                    "timestamps": [],
                    "open": [],
                    "high": [],
                    "low": [],
                    "close": [],
                    "volume": []
                },
                "indicators": {}
            }
            return ChartDataResponse(**empty_chart)
        
        # Convert trades to list of dicts
        trades = [trade.model_dump() if hasattr(trade, 'model_dump') else trade for trade in trades_data]
        
        # Generate chart data
        chart_service = MplfinanceService()
        chart_data = chart_service.prepare_chart_data(
            trades=trades,
            include_sma=include_sma,
            include_ema=include_ema,
            include_rsi=include_rsi,
            include_macd=include_macd,
            include_bollinger=include_bollinger,
        )
        
        return ChartDataResponse(**chart_data)
        
    except BackendError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate chart data: {str(e)}")
