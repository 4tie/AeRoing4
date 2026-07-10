"""Pipeline start and template generation endpoints for Auto-Quant."""

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from ....services.auto_quant import pipeline as _pl
from ....services.auto_quant.generator import (
    generate_strategy_source,
    generate_strategy_source_adaptive,
    generate_strategy_source_ensemble,
    generate_strategy_source_momentum,
    generate_strategy_source_omni,
)
from ....services.auto_quant.pipeline import get_timeframe_thresholds
from ....services.auto_quant.policy import (
    build_run_config,
    date_ranges_for_depth,
    latest_complete_day,
)
from ....services.auto_quant.strategy_designer import generate_strategy_spec, generate_strategy_spec_simple
from ....services.auto_quant.ollama_service import create_strategy_lab_client

from .schemas import (
    StartAutoQuantRequest,
    StartAutoQuantResponse,
    GenerateTemplateRequest,
    GenerateTemplateResponse,
    GenerateStrategySpecRequest,
    GenerateStrategySpecResponse,
)


def register_pipeline_start_endpoints(router: APIRouter) -> None:
    """Register pipeline start and template generation endpoints on the given router."""
    
    @router.get(
        "/default-ranges",
        summary="Get dynamic default date ranges for AutoQuant",
    )
    async def get_default_ranges() -> dict:
        """Return current dynamic default date ranges from policy.

        Returns ranges for quick, standard, and deep analysis depths,
        all calculated relative to the latest complete day.
        """
        from datetime import datetime

        latest_day = latest_complete_day()
        generated_at = latest_day.strftime("%Y-%m-%d")

        quick_is, quick_oos = date_ranges_for_depth("quick")
        standard_is, standard_oos = date_ranges_for_depth("standard")
        deep_is, deep_oos = date_ranges_for_depth("deep")

        return {
            "quick": {
                "in_sample_range": quick_is,
                "out_sample_range": quick_oos,
            },
            "standard": {
                "in_sample_range": standard_is,
                "out_sample_range": standard_oos,
            },
            "deep": {
                "in_sample_range": deep_is,
                "out_sample_range": deep_oos,
            },
            "latest_complete_day": generated_at,
            "generated_at": datetime.utcnow().isoformat(),
        }

    @router.post(
        "/start",
        response_model=StartAutoQuantResponse,
        status_code=202,
        summary="Launch Auto-Quant Factory pipeline",
    )
    async def start_pipeline(body: StartAutoQuantRequest, request: Request) -> StartAutoQuantResponse:
        return await _start_pipeline_from_body(body, request)

    @router.post(
        "/runs",
        response_model=StartAutoQuantResponse,
        status_code=202,
        summary="Compatibility alias for launching Auto-Quant runs",
    )
    async def start_pipeline_runs_alias(
        body: StartAutoQuantRequest,
        request: Request,
    ) -> StartAutoQuantResponse:
        return await _start_pipeline_from_body(body, request)

    @router.post(
        "/generate-template",
        response_model=GenerateTemplateResponse,
        status_code=201,
        summary="Generate a CategoricalParameter strategy template",
    )
    async def generate_template(
        body: GenerateTemplateRequest, request: Request
    ) -> GenerateTemplateResponse:
        name = body.strategy_name.strip()

        if not name:
            raise HTTPException(status_code=422, detail="strategy_name must not be empty.")

        if "/" in name or "\\" in name or ".." in name:
            raise HTTPException(
                status_code=422,
                detail="strategy_name must not contain path separators.",
            )

        services = request.app.state.services
        settings = services.settings_store.load()
        strategies_dir = Path(settings.strategies_directory_path)
        strategies_dir.mkdir(parents=True, exist_ok=True)

        target = strategies_dir / f"{name}.py"
        if target.exists():
            raise HTTPException(
                status_code=409,
                detail=f"Strategy '{name}' already exists. Choose a different name.",
            )

        if body.omni:
            source = generate_strategy_source_omni(name, timeframe=body.timeframe)
        elif body.momentum:
            source = generate_strategy_source_momentum(name)
        elif body.ensemble:
            source = generate_strategy_source_ensemble(name)
        elif body.adaptive:
            source = generate_strategy_source_adaptive(name)
        else:
            source = generate_strategy_source(name)
        target.write_text(source, encoding="utf-8")

        return GenerateTemplateResponse(
            strategy_name=name,
            file_path=str(target),
        )

    @router.post(
        "/generate-strategy-spec",
        response_model=GenerateStrategySpecResponse,
        summary="Generate a StrategySpec using Hermes AI",
    )
    async def generate_strategy_spec_endpoint(
        body: GenerateStrategySpecRequest, request: Request
    ) -> GenerateStrategySpecResponse:
        """Generate a structured StrategySpec using the Hermes AI model.

        This endpoint uses the configured strategy lab model (ollama_model_strategylab)
        to generate a StrategySpec based on user inputs. The AI only generates the
        structured spec, not actual strategy code or profitability decisions.
        """
        services = request.app.state.services
        settings = services.settings_store.load()

        # Create Ollama client with strategy lab model override
        client = create_strategy_lab_client(settings.user_data_directory_path)
        if client is None:
            return GenerateStrategySpecResponse(
                spec=None,
                errors=["OLLAMA_CLIENT_NOT_AVAILABLE"],
                raw_response="",
            )

        # Generate the strategy spec using simplified approach
        result = await generate_strategy_spec_simple(
            client,
            trading_style=body.trading_style,
            timeframe=body.timeframe_preference,
            direction=body.direction,
            risk_profile=body.risk_profile,
            description=body.user_notes,
        )

        # Convert StrategySpec to dict if successful
        spec_dict = None
        if result["spec"] is not None:
            spec_dict = result["spec"].model_dump(mode="json")

        return GenerateStrategySpecResponse(
            spec=spec_dict,
            errors=result["errors"],
            raw_response=result.get("raw_response", ""),
        )

    @router.get(
        "/timeframe-thresholds/{timeframe}",
        summary="Return dynamic profitability thresholds for a given timeframe",
    )
    async def timeframe_thresholds(timeframe: str) -> dict:
        """Return the recommended success thresholds for *timeframe*.

        The frontend uses this to auto-populate the risk-threshold fields whenever
        the user changes the Timeframe dropdown so that scalping and swing runs are
        evaluated against appropriately calibrated criteria.
        """
        return get_timeframe_thresholds(timeframe)


async def _start_pipeline_from_body(
    body: StartAutoQuantRequest,
    request: Request,
) -> StartAutoQuantResponse:
    services = request.app.state.services
    settings = services.settings_store.load()
    normalized = build_run_config(body.model_dump(exclude_none=True), settings)

    # Resolve config file
    config_file = normalized.get("config_file") or settings.default_config_file_path
    if not Path(config_file).exists():
        raise HTTPException(status_code=400, detail=f"Config file not found: {config_file}")

    # Validate strategy exists
    strategy_name = normalized.get("strategy")
    if not strategy_name:
        raise HTTPException(status_code=422, detail="strategy or uploaded_strategy_id is required.")
    strategies_dir = Path(settings.strategies_directory_path)
    strategy_path = strategies_dir / f"{strategy_name}.py"
    if not strategy_path.exists():
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_name}' not found.")

    thresholds = normalized["thresholds"]
    run_config_snapshot = {
        "schema_version": "run_config_snapshot_v1",
        "policy_versions": normalized["policy_versions"],
        "strategy": strategy_name,
        "strategy_source": normalized["strategy_source"],
        "workflow_mode": normalized["workflow_mode"],
        "max_attempts": normalized["max_attempts"],
        "uploaded_strategy_id": normalized.get("uploaded_strategy_id"),
        "generated_by": normalized.get("generated_by"),
        "trading_style": normalized["trading_style"],
        "risk_profile": normalized["risk_profile"],
        "analysis_depth": normalized["analysis_depth"],
        "timeframe": normalized["timeframe"],
        "configured_timeframes": normalized["configured_timeframes"],
        "unsupported_timeframes": normalized["unsupported_timeframes"],
        "selected_pairs": normalized["selected_pair_universe"],
        "date_ranges": {
            "in_sample": normalized["in_sample_range"],
            "out_of_sample": normalized["out_sample_range"],
        },
        "optimization": {
            "hyperopt_loss": normalized["hyperopt_loss"],
            "hyperopt_spaces": normalized["hyperopt_spaces"],
            "hyperopt_epochs": normalized["hyperopt_epochs"],
            "wfo_enabled": normalized["wfo_enabled"],
            "wfo_is_months": normalized["wfo_is_months"],
            "wfo_oos_months": normalized["wfo_oos_months"],
            "wfo_recency_weight": normalized["wfo_recency_weight"],
            "planned_wfo_windows": normalized.get("planned_wfo_windows", []),
        },
        "thresholds": thresholds,
        "thresholds_by_tier": normalized.get("thresholds_by_tier", {}),
        "exchange": normalized["exchange"],
        "advanced_overrides": normalized["advanced_overrides"],
    }

    run_id = _pl.create_run(
        strategy=strategy_name,
        timeframe=normalized["timeframe"],
        in_sample_range=normalized["in_sample_range"],
        out_sample_range=normalized["out_sample_range"],
        exchange=normalized["exchange"],
        config_file=config_file,
        freqtrade_path=settings.freqtrade_executable_path,
        user_data_dir=settings.user_data_directory_path,
        max_drawdown_threshold=thresholds["max_drawdown"],
        min_win_rate=thresholds["min_win_rate"],
        min_profit_factor=thresholds["min_profit_factor"],
        min_sharpe=thresholds["min_sharpe"],
        min_oos_profit=thresholds["min_oos_profit"],
        monte_carlo_threshold=thresholds["monte_carlo_threshold"],
        hyperopt_loss=normalized["hyperopt_loss"],
        hyperopt_spaces=normalized["hyperopt_spaces"],
        hyperopt_epochs=normalized["hyperopt_epochs"],
        hyperopt_workers=settings.hyperopt_workers,
        wfo_enabled=normalized["wfo_enabled"],
        wfo_is_months=normalized["wfo_is_months"],
        wfo_oos_months=normalized["wfo_oos_months"],
        wfo_recency_weight=normalized["wfo_recency_weight"],
        planned_wfo_windows=normalized.get("planned_wfo_windows", []),
        ensemble_enabled=normalized["ensemble_enabled"],
        pair=normalized["pair"] or None,
        pair_universe=normalized["pair_universe"],
        strategy_source=normalized["strategy_source"],
        trading_style=normalized["trading_style"],
        risk_profile=normalized["risk_profile"],
        analysis_depth=normalized["analysis_depth"],
        uploaded_strategy_id=normalized.get("uploaded_strategy_id"),
        advanced_overrides=normalized["advanced_overrides"],
        auto_discovery_enabled=bool(body.trading_style or body.risk_profile or body.analysis_depth),
        validation_notes=normalized["validation_notes"],
        run_config_snapshot=run_config_snapshot,
        policy_versions=normalized["policy_versions"],
        selected_timeframe=normalized["timeframe"],
        selected_pair_universe=normalized["selected_pair_universe"],
        workflow_mode=normalized["workflow_mode"],
        max_attempts=normalized["max_attempts"],
    )

    _pl.launch_pipeline_task(run_id)

    return StartAutoQuantResponse(
        run_id=run_id,
        status="running",
        message=(
            f"Auto-Quant Factory started for '{strategy_name}'. "
            f"Connect to /api/auto-quant/ws/{run_id} for live progress."
        ),
    )
