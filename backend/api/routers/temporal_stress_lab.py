"""Router: POST /api/temporal-stress-lab/run

Temporal stress testing: runs the strategy across multiple sub-intervals
(Time Split / Walk-Forward, Monte Carlo, or Crash Gauntlet) to evaluate
robustness across different market conditions.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from ...core.errors import BackendError
from ...models import RunRequest
from ...services.stress.temporal_stress_service import (
    consistency_score,
    extract_segment_metrics,
    generate_crash_gauntlet_segments,
    generate_monte_carlo_segments,
    generate_time_split_segments,
)
from ..models import AsyncJobResponse, TemporalStressLabApiRequest
from ..session_store import SessionStore

router = APIRouter(prefix="/api/temporal-stress-lab", tags=["Temporal Stress Lab"])


# ── Endpoint ───────────────────────────────────────────────────────────────────


@router.post(
    "/run",
    response_model=AsyncJobResponse,
    status_code=202,
    summary="Run a temporal stress test",
    description=(
        "Launches a temporal robustness stress test using Time Split, Monte Carlo, "
        "or Crash Gauntlet mode. Each segment is run as a separate Freqtrade backtest. "
        "Returns a session_id immediately; poll /api/session/status/{session_id} for "
        "per-segment progress and aggregate metrics once complete."
    ),
)
async def run_temporal_stress_lab(
    body: TemporalStressLabApiRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> AsyncJobResponse:
    services = request.app.state.services
    store: SessionStore = request.app.state.session_store

    if services.backtest_runner.is_busy():
        raise HTTPException(
            status_code=409,
            detail="Backtest runner is busy. Wait for the current run to finish.",
        )

    try:
        strategy = services.registry.get_strategy(body.strategy_name)
    except BackendError as exc:
        raise HTTPException(status_code=404, detail=exc.message)

    pointer = services.version_manager.get_current_pointer(body.strategy_name)
    if pointer is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Strategy '{body.strategy_name}' has no accepted version. "
                "Accept a version before running the stress lab."
            ),
        )
    version_id = pointer.accepted_version_id

    try:
        if body.mode == "time_split":
            segments = generate_time_split_segments(body.timerange, body.n_splits or 4)
        elif body.mode == "monte_carlo":
            segments = generate_monte_carlo_segments(
                body.timerange, body.n_windows or 5, body.window_days or 14
            )
        elif body.mode == "crash_gauntlet":
            segments = generate_crash_gauntlet_segments()
        else:
            raise HTTPException(status_code=400, detail=f"Unknown stress mode: {body.mode}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    record = store.create("temporal_stress_lab")
    store.update(
        record.session_id,
        status="running",
        started_at=datetime.now(tz=UTC),
        result={
            "mode": body.mode,
            "total_segments": len(segments),
            "completed_segments": 0,
            "current_segment": segments[0]["label"] if segments else None,
            "segments": [],
            "consistency_score": None,
            "exported_trial_id": body.exported_trial_id or None,
            "exported_trial_label": None,
        },
    )

    background_tasks.add_task(
        _run_stress_segments,
        services,
        store,
        record.session_id,
        strategy,
        version_id,
        body,
        segments,
    )

    return AsyncJobResponse(
        session_id=record.session_id,
        status="running",
        message=(
            f"Temporal stress lab started — {len(segments)} segments for "
            f"'{body.strategy_name}' ({body.mode} mode). "
            f"Poll /api/session/status/{record.session_id} for progress."
        ),
    )


# ── Background task ────────────────────────────────────────────────────────────


async def _run_stress_segments(
    services,
    store: SessionStore,
    session_id: str,
    strategy,
    version_id: str,
    body: TemporalStressLabApiRequest,
    segments: list[dict],
) -> None:
    settings = services.settings_store.load()
    config_file = body.config_file or settings.default_config_file_path

    # ── resolve exported trial parameters if requested ─────────────────────
    exported_trial_record: dict | None = None
    if body.exported_trial_id:
        exported_trial_record = services.exported_trial_store.find_by_id(body.exported_trial_id)
        if exported_trial_record is None:
            store.update(
                session_id,
                status="failed",
                completed_at=datetime.now(tz=UTC),
                error=f"Exported trial '{body.exported_trial_id}' not found. It may have been deleted.",
                result={
                    "mode": body.mode,
                    "total_segments": len(segments),
                    "completed_segments": 0,
                    "current_segment": None,
                    "segments": [],
                    "consistency_score": None,
                },
            )
            return

    exported_trial_label: str | None = (
        exported_trial_record.get("label") if exported_trial_record is not None else None
    )

    completed_results: list[dict] = []

    for i, seg in enumerate(segments):
        store.update(
            session_id,
            result={
                "mode": body.mode,
                "total_segments": len(segments),
                "completed_segments": i,
                "current_segment": seg["label"],
                "segments": completed_results,
                "consistency_score": None,
                "exported_trial_id": body.exported_trial_id or None,
                "exported_trial_label": exported_trial_label,
            },
        )

        seg_result: dict = {
            "label": seg["label"],
            "timerange": seg["timerange"],
            "start": seg["start"],
            "end": seg["end"],
            "description": seg.get("description", ""),
            "status": "running",
            "run_id": None,
            "net_profit_pct": None,
            "total_trades": None,
            "win_rate_pct": None,
            "max_drawdown_pct": None,
            "error": None,
        }

        trial_version_id: str | None = None
        try:
            effective_version_id = version_id

            # If an exported trial is selected, inject its parameters via a temporary version
            if exported_trial_record is not None:
                trial_parameters = exported_trial_record.get("parameters", {})
                if not trial_parameters:
                    raise ValueError(
                        f"Exported trial '{body.exported_trial_id}' has no parameter overrides."
                    )
                parent_params = services.version_manager.load_params(
                    body.strategy_name, version_id
                )
                trial_params = services.strategy_optimizer.trial_executor.build_trial_params(
                    parent_params, trial_parameters
                )
                parent_source = services.version_manager.load_strategy_source(
                    body.strategy_name, version_id
                )
                trial_version = services.strategy_optimizer.trial_executor.create_trial_version(
                    body.strategy_name,
                    version_id,
                    parent_source,
                    trial_params,
                    exported_trial_record.get("trial_number", 0),
                )
                trial_version_id = trial_version.version_id
                effective_version_id = trial_version_id

            run_req = RunRequest(
                strategy_name=body.strategy_name,
                version_id=effective_version_id,
                config_file=config_file,
                timerange=seg["timerange"],
                timeframe=body.timeframe or "1h",
                pairs=body.pairs or [],
                max_open_trades=body.max_open_trades,
                dry_run_wallet=body.dry_run_wallet,
            )

            run_id: str = await asyncio.to_thread(
                services.backtest_runner.run_backtest,
                strategy,
                effective_version_id,
                run_req,
                None,
            )
            seg_result["run_id"] = run_id

            run_dir = services.backtest_runner.run_repository.find_run_dir(run_id)
            metrics = extract_segment_metrics(run_dir, body.strategy_name)
            seg_result.update(metrics)

            net = metrics.get("net_profit_pct")
            if net is not None:
                seg_result["status"] = "profitable" if net >= 0 else "loss"
            else:
                seg_result["status"] = "completed"

        except BackendError as exc:
            seg_result["status"] = "failed"
            seg_result["error"] = exc.message
        except Exception as exc:
            seg_result["status"] = "failed"
            seg_result["error"] = str(exc)
        finally:
            # Clean up the temporary trial version
            if trial_version_id:
                try:
                    services.version_manager.reject_version(trial_version_id, "Stress test segment completed")
                except Exception:
                    pass

        completed_results.append(seg_result)

    profits = [r["net_profit_pct"] for r in completed_results if r.get("net_profit_pct") is not None]
    drawdowns = [r["max_drawdown_pct"] for r in completed_results if r.get("max_drawdown_pct") is not None]
    consistency = consistency_score(completed_results)

    profitable_segs = [r for r in completed_results if r.get("net_profit_pct") is not None]
    best = max(profitable_segs, key=lambda r: r["net_profit_pct"], default=None)
    worst = min(profitable_segs, key=lambda r: r["net_profit_pct"], default=None)

    dd_variance = round(max(drawdowns) - min(drawdowns), 4) if len(drawdowns) >= 2 else None

    store.update(
        session_id,
        status="completed",
        completed_at=datetime.now(tz=UTC),
        result={
            "mode": body.mode,
            "total_segments": len(segments),
            "completed_segments": len(completed_results),
            "current_segment": None,
            "segments": completed_results,
            "consistency_score": consistency,
            "avg_net_profit_pct": round(sum(profits) / len(profits), 4) if profits else None,
            "best_net_profit_pct": best["net_profit_pct"] if best else None,
            "best_segment_label": best["label"] if best else None,
            "worst_net_profit_pct": worst["net_profit_pct"] if worst else None,
            "worst_segment_label": worst["label"] if worst else None,
            "max_drawdown_variance": dd_variance,
            "exported_trial_id": body.exported_trial_id or None,
            "exported_trial_label": exported_trial_label,
        },
    )

