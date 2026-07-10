"""Disk persistence functions for pipeline state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...ai_suggestions import normalize_ai_suggestions
from ..logging import logger
from ...policy import get_policy_versions
from .data_structures import PipelineState


def _state_file(state: PipelineState) -> Path:
    return Path(state.user_data_dir) / "auto_quant" / state.run_id / "state.json"


def _run_dir(state: PipelineState) -> Path:
    return Path(state.user_data_dir) / "auto_quant" / state.run_id


def _write_versioned_json(
    run_dir: Path,
    stem: str,
    payload: dict[str, Any],
    *,
    legacy_name: str | None = None,
) -> dict[str, str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    existing_versions = []
    for path in run_dir.glob(f"{stem}_v*.json"):
        suffix = path.stem.removeprefix(f"{stem}_v")
        if suffix.isdigit():
            existing_versions.append(int(suffix))
    next_version = max(existing_versions, default=0) + 1
    versioned = run_dir / f"{stem}_v{next_version}.json"
    latest = run_dir / f"{stem}_latest.json"
    versioned.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    latest.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    artifacts = {f"{stem}_v{next_version}": versioned.name, f"{stem}_latest": latest.name}
    if legacy_name:
        legacy = run_dir / legacy_name
        legacy.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        artifacts[legacy_name.rsplit(".", 1)[0]] = legacy.name
    return artifacts


def _save_state_to_disk(state: PipelineState) -> None:
    """Persist current pipeline state to disk so it survives restarts."""
    try:
        path = _state_file(state)
        run_dir = path.parent
        run_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(
            "[%s] Writing state.json → %s  (status=%s, stage=%d)",
            state.run_id, path, state.status, state.current_stage,
        )
        payload: dict[str, Any] = {
            "run_id": state.run_id,
            "strategy": state.strategy,
            "original_strategy": state.original_strategy,
            "original_strategy_hash": state.original_strategy_hash,
            "timeframe": state.timeframe,
            "in_sample_range": state.in_sample_range,
            "out_sample_range": state.out_sample_range,
            "exchange": state.exchange,
            "config_file": state.config_file,
            "freqtrade_path": state.freqtrade_path,
            "user_data_dir": state.user_data_dir,
            "status": state.status,
            "current_stage": state.current_stage,
            "stages": [
                {"index": s.index, "name": s.name, "status": s.status,
                 "message": s.message, "data": s.data,
                 "started_at": s.started_at, "duration_s": s.duration_s}
                for s in state.stages
            ],
            "error": state.error,
            "created_at": state.created_at,
            "completed_at": state.completed_at,
            "report": state.report,
            "max_drawdown_threshold": state.max_drawdown_threshold,
            "min_win_rate": state.min_win_rate,
            "min_profit_factor": state.min_profit_factor,
            "min_sharpe": state.min_sharpe,
            "monte_carlo_threshold": state.monte_carlo_threshold,
            "hyperopt_loss": state.hyperopt_loss,
            "hyperopt_spaces": state.hyperopt_spaces,
            "hyperopt_epochs": state.hyperopt_epochs,
            "hyperopt_workers": state.hyperopt_workers,
            "min_oos_profit": state.min_oos_profit,
            "retry_count": state.retry_count,
            "max_retries": state.max_retries,
            "retry_history": state.retry_history,
            "generalization_failure": state.generalization_failure,
            "sensitivity": state.sensitivity,
            "wfo_enabled": state.wfo_enabled,
            "wfo_is_months": state.wfo_is_months,
            "wfo_oos_months": state.wfo_oos_months,
            "wfo_recency_weight": state.wfo_recency_weight,
            "wfo_windows": state.wfo_windows,
            "wfo_skip_reason": state.wfo_skip_reason,
            "ensemble_enabled": state.ensemble_enabled,
            "pair_universe": state.pair_universe,
            "winning_pairs": state.winning_pairs,
            "selected_pairs": state.selected_pairs,
            "excluded_time_windows": state.excluded_time_windows,
            "ai_enabled": state.ai_enabled,
            "ai_suggestions": normalize_ai_suggestions(state.ai_suggestions),
            "pending_ai_suggestion_id": state.pending_ai_suggestion_id,
            "ai_interactions": state.ai_interactions,
            "ollama_available": state.ollama_available,
            "param_overrides": state.param_overrides,
            "data_healing_warmup_candles": state.data_healing_warmup_candles,
            "data_healing_timeout": state.data_healing_timeout,
            "phase1_heal_attempts": state.phase1_heal_attempts,
            "stability_scores": state.stability_scores,
            "portfolio_weights": state.portfolio_weights,
            "baseline_trade_counts": state.baseline_trade_counts,
            "max_open_trades": state.max_open_trades,
            "strategy_source": state.strategy_source,
            "trading_style": state.trading_style,
            "risk_profile": state.risk_profile,
            "analysis_depth": state.analysis_depth,
            "uploaded_strategy_id": state.uploaded_strategy_id,
            "advanced_overrides": state.advanced_overrides,
            "auto_discovery_enabled": state.auto_discovery_enabled,
            "discovery_results": state.discovery_results,
            "validation_notes": state.validation_notes,
            "run_config_snapshot": state.run_config_snapshot,
            "policy_versions": state.policy_versions or get_policy_versions(),
            "selected_timeframe": state.selected_timeframe,
            "selected_pair_universe": state.selected_pair_universe,
            "score": state.score,
            "validation_status": state.validation_status,
            "readiness_label": state.readiness_label,
            "score_explanation": state.score_explanation,
            "progress_percent": state.progress_percent,
            "eta_seconds": state.eta_seconds,
            "progress_counters": state.progress_counters,
            "strategy_runtime_dir": state.strategy_runtime_dir,
            "strategy_variants": state.strategy_variants,
            "artifact_versions": state.artifact_versions,
            "user_approved_pairs": state.user_approved_pairs,
            "portfolio_baseline_result": state.portfolio_baseline_result,
            "workflow_mode": state.workflow_mode,
            "max_attempts": state.max_attempts,
            "validation_attempts": state.validation_attempts,
            "oos_validation_result": state.oos_validation_result,
            "final_verdict": state.final_verdict,
            "candidate_label": state.candidate_label,
            "rejection_report": state.rejection_report,
            "best_observed_result": state.best_observed_result,
        }
        state.artifact_versions.update(
            _write_versioned_json(run_dir, "state", payload, legacy_name="state.json")
        )
    except Exception:
        logger.exception("[%s] FAILED to write state.json — state will not survive restart.", state.run_id)


def load_runs_from_disk(user_data_dir: str) -> None:
    """Scan user_data/auto_quant/ and populate the in-memory registry.

    Two-pass strategy so every historical run surfaces in the Run History
    dashboard after a backend restart:

    Pass 1 — state.json files (authoritative, written by this pipeline on
              every state transition).  Provides the full picture including
              in-progress / failed / cancelled runs.

    Pass 2 — report.json files in any run directory that has NO state.json
              (legacy runs created before state persistence was introduced, or
              runs whose state.json was accidentally deleted).  Only completed
              runs produce a report.json so these are always marked
              "completed".

    Called once at app startup.  Running/pending runs found on disk are
    marked as 'failed' (their subprocess is gone and cannot be resumed).
    """
    from .data_structures import _states, StageState
    from .utilities import _state_snapshot

    base = Path(user_data_dir) / "auto_quant"
    if not base.exists():
        logger.info("load_runs_from_disk: base dir does not exist yet (%s)", base)
        return

    logger.info("load_runs_from_disk: scanning %s for persisted pipeline runs…", base)

    # Pass 1: Load state.json files
    for run_dir in base.iterdir():
        if not run_dir.is_dir():
            continue
        state_file = run_dir / "state.json"
        if not state_file.exists():
            continue
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            stages = [
                StageState(
                    index=s["index"],
                    name=s["name"],
                    status=s["status"],
                    message=s.get("message", ""),
                    data=s.get("data", {}),
                    started_at=s.get("started_at"),
                    duration_s=s.get("duration_s"),
                )
                for s in data.get("stages", [])
            ]
            state = PipelineState(
                run_id=data["run_id"],
                strategy=data["strategy"],
                timeframe=data["timeframe"],
                in_sample_range=data["in_sample_range"],
                out_sample_range=data["out_sample_range"],
                exchange=data["exchange"],
                config_file=data["config_file"],
                freqtrade_path=data["freqtrade_path"],
                user_data_dir=data["user_data_dir"],
                original_strategy=data.get("original_strategy"),
                original_strategy_hash=data.get("original_strategy_hash"),
                status=data.get("status", "pending"),
                current_stage=data.get("current_stage", 0),
                stages=stages,
                report=data.get("report"),
                error=data.get("error"),
                created_at=data.get("created_at", ""),
                completed_at=data.get("completed_at"),
                max_drawdown_threshold=data.get("max_drawdown_threshold", 0.30),
                min_win_rate=data.get("min_win_rate", 0.40),
                min_profit_factor=data.get("min_profit_factor", 1.0),
                min_sharpe=data.get("min_sharpe", 0.0),
                monte_carlo_threshold=data.get("monte_carlo_threshold", 0.20),
                hyperopt_loss=data.get("hyperopt_loss", "OnlyProfitHyperOptLoss"),
                hyperopt_spaces=data.get("hyperopt_spaces", ["buy", "stoploss", "roi"]),
                hyperopt_epochs=data.get("hyperopt_epochs", 200),
                hyperopt_workers=data.get("hyperopt_workers", 1),
                min_oos_profit=data.get("min_oos_profit", 0.0),
                retry_count=data.get("retry_count", 0),
                max_retries=data.get("max_retries", 3),
                retry_history=data.get("retry_history", []),
                generalization_failure=data.get("generalization_failure"),
                sensitivity=data.get("sensitivity"),
                wfo_enabled=data.get("wfo_enabled", False),
                wfo_is_months=data.get("wfo_is_months", 3),
                wfo_oos_months=data.get("wfo_oos_months", 1),
                wfo_recency_weight=data.get("wfo_recency_weight", 1.0),
                wfo_windows=data.get("wfo_windows", []),
                wfo_skip_reason=data.get("wfo_skip_reason"),
                ensemble_enabled=data.get("ensemble_enabled", False),
                pair_universe=data.get("pair_universe", []),
                winning_pairs=data.get("winning_pairs", []),
                selected_pairs=data.get("selected_pairs", []),
                excluded_time_windows=data.get("excluded_time_windows", {}),
                ai_enabled=data.get("ai_enabled", True),
                ai_suggestions=data.get("ai_suggestions", []),
                pending_ai_suggestion_id=data.get("pending_ai_suggestion_id"),
                ai_interactions=data.get("ai_interactions", []),
                ollama_available=data.get("ollama_available", False),
                param_overrides=data.get("param_overrides", {}),
                data_healing_warmup_candles=data.get("data_healing_warmup_candles", 200),
                data_healing_timeout=data.get("data_healing_timeout", 300),
                phase1_heal_attempts=data.get("phase1_heal_attempts", 0),
                stability_scores=data.get("stability_scores", {}),
                portfolio_weights=data.get("portfolio_weights", {}),
                baseline_trade_counts=data.get("baseline_trade_counts", {}),
                max_open_trades=data.get("max_open_trades", 5),
                strategy_source=data.get("strategy_source", "existing"),
                trading_style=data.get("trading_style", "swing"),
                risk_profile=data.get("risk_profile", "balanced"),
                analysis_depth=data.get("analysis_depth", "deep"),
                uploaded_strategy_id=data.get("uploaded_strategy_id"),
                advanced_overrides=data.get("advanced_overrides", {}),
                auto_discovery_enabled=data.get("auto_discovery_enabled", False),
                discovery_results=data.get("discovery_results", {}),
                validation_notes=data.get("validation_notes", []),
                run_config_snapshot=data.get("run_config_snapshot", {}),
                policy_versions=data.get("policy_versions", {}),
                selected_timeframe=data.get("selected_timeframe"),
                selected_pair_universe=data.get("selected_pair_universe", []),
                score=data.get("score", {}),
                validation_status=data.get("validation_status", "Candidate"),
                readiness_label=data.get("readiness_label", "Candidate"),
                score_explanation=data.get("score_explanation", []),
                progress_percent=data.get("progress_percent", 0),
                eta_seconds=data.get("eta_seconds"),
                progress_counters=data.get("progress_counters", {}),
                strategy_runtime_dir=data.get("strategy_runtime_dir"),
                strategy_variants=data.get("strategy_variants", []),
                artifact_versions=data.get("artifact_versions", {}),
                user_approved_pairs=data.get("user_approved_pairs", []),
                portfolio_baseline_result=data.get("portfolio_baseline_result", {}),
                workflow_mode=data.get("workflow_mode", "auto_quant"),
                max_attempts=data.get("max_attempts", 3),
                validation_attempts=data.get("validation_attempts", []),
                oos_validation_result=data.get("oos_validation_result", {}),
                final_verdict=data.get("final_verdict"),
                candidate_label=data.get("candidate_label"),
                rejection_report=data.get("rejection_report", {}),
                best_observed_result=data.get("best_observed_result", {}),
            )
            # Mark in-progress runs as failed since subprocess is gone
            if state.status in {"pending", "running"}:
                state.status = "failed"
                state.error = "Backend restarted while run was in progress"
                state.completed_at = data.get("completed_at")
            _states[state.run_id] = state
            logger.info("load_runs_from_disk: loaded state for run %s (status=%s)", state.run_id, state.status)
        except Exception as exc:
            logger.warning("load_runs_from_disk: failed to load %s: %s", state_file, exc)

    # Pass 2: Load legacy report.json files for runs without state.json
    for run_dir in base.iterdir():
        if not run_dir.is_dir():
            continue
        state_file = run_dir / "state.json"
        if state_file.exists():
            continue
        report_file = run_dir / "report.json"
        if not report_file.exists():
            continue
        run_id = run_dir.name
        if run_id in _states:
            continue
        try:
            data = json.loads(report_file.read_text(encoding="utf-8"))
            state = PipelineState(
                run_id=run_id,
                strategy=data.get("strategy", "unknown"),
                timeframe=data.get("timeframe", "unknown"),
                in_sample_range=data.get("in_sample_range", ""),
                out_sample_range=data.get("out_sample_range", ""),
                exchange=data.get("exchange", ""),
                config_file=data.get("config_file", ""),
                freqtrade_path=data.get("freqtrade_path", ""),
                user_data_dir=user_data_dir,
                status="completed",
                current_stage=0,
                stages=[],
                report=data,
                created_at=data.get("created_at", ""),
                completed_at=data.get("completed_at"),
            )
            _states[run_id] = state
            logger.info("load_runs_from_disk: loaded legacy report for run %s", run_id)
        except Exception as exc:
            logger.warning("load_runs_from_disk: failed to load legacy report %s: %s", report_file, exc)

    logger.info("load_runs_from_disk: loaded %d runs from disk", len(_states))
