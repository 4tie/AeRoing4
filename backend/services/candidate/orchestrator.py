"""Candidate evaluation orchestrator — runs a strategy spec through the multi-gate pipeline."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from backend.models.strategy_spec import StrategySpec
from backend.models import DownloadDataRequest
from backend.utils import utc_now
from backend.services.strategy.strategy_code_writer import (
    render_strategy_from_spec,
    save_rendered_strategy,
    delete_rendered_strategy,
)
from backend.services.execution.data_quality_gate import check_data_quality
from backend.services.execution.backtest_gate import run_backtest_gate
from backend.services.execution.failure_analyzer import analyze_gate_failure
from backend.services.execution.repair_plan_gate import build_repair_plan
from backend.services.execution.ai_repair_proposer import ask_ai_for_repair_proposal
from backend.services.execution.repair_applier import apply_repair_proposal
from backend.services.execution.pair_sweep_runner import (
    run_portfolio_backtest as _run_portfolio_backtest,
    decide_final_pair_set as _decide_final_pair_set,
)

from .models import CandidateConfig, CandidateGateResult, CandidateVerdict, RepairAttempt


def _dedup_gate_results(results: list[CandidateGateResult]) -> list[CandidateGateResult]:
    seen: dict[str, CandidateGateResult] = {}
    for r in results:
        seen[r.gate_name] = r
    return list(seen.values())


async def _empty_pair_sweep(pairs, strategy_name, config_file, timerange, timeframe):
    return []


def _string_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    return [str(value)]


def _extract_missing_pairs(quality_result: dict[str, Any]) -> list[str]:
    missing = [
        pair for pair, details in (quality_result.get("details") or {}).items()
        if details.get("exists") is False or details.get("covers_timerange") is False
    ]
    for error in quality_result.get("errors", []):
        if isinstance(error, str) and (
            error.startswith("MISSING_DATA_FILE:")
            or error.startswith("INSUFFICIENT_HISTORY:")
        ):
            pair = error.split(":", maxsplit=1)[1].split("-", maxsplit=1)[0].strip()
            if pair and pair not in missing:
                missing.append(pair)
    return missing


def _download_command_hint(
    config: CandidateConfig,
    pairs: list[str],
    *,
    prepend: bool = False,
) -> str:
    pair_args = " ".join(list(dict.fromkeys(pairs or config.pairs)))
    command = (
        f"freqtrade download-data -c {config.config_file} "
        f"--timeframes {config.timeframe} "
        f"--timerange {config.timerange} "
        f"--pairs {pair_args}"
    )
    if prepend:
        command = f"{command} --prepend"
    return command


def _is_retryable_data_quality_failure(quality_result: dict[str, Any]) -> bool:
    return any(
        isinstance(error, str) and (
            error.startswith("MISSING_DATA_FILE:")
            or error.startswith("INSUFFICIENT_HISTORY:")
        )
        for error in quality_result.get("errors", [])
    )


def _timerange_start_label(timerange: str) -> str | None:
    start = str(timerange or "").split("-", maxsplit=1)[0].strip()
    return start if len(start) == 8 and start.isdigit() else None


def _download_should_prepend(
    quality_result: dict[str, Any],
    config: CandidateConfig,
) -> bool:
    required_start = _timerange_start_label(config.timerange)
    if not required_start:
        return False
    for details in (quality_result.get("details") or {}).values():
        start_date = str(details.get("start_date") or "")
        if len(start_date) == 8 and start_date.isdigit() and start_date > required_start:
            return True
    return any(
        isinstance(error, str) and "data starts at" in error
        for error in quality_result.get("errors", [])
    )


def _data_download_details(
    config: CandidateConfig,
    pairs: list[str],
    *,
    prepend: bool,
    download_id: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "pairs": list(dict.fromkeys(pairs or config.pairs)),
        "timeframe": config.timeframe,
        "timerange": config.timerange,
        "config_file": config.config_file,
        "user_data_dir": config.user_data_dir,
        "exchange": config.exchange,
        "prepend": prepend,
        "download_command_hint": _download_command_hint(config, pairs, prepend=prepend),
    }
    if download_id:
        details["download_id"] = download_id
    if error:
        details["error"] = error
    return details


def _data_quality_failure_details(
    quality_result: dict[str, Any],
    config: CandidateConfig,
) -> dict[str, Any]:
    missing_pairs = _extract_missing_pairs(quality_result)
    pairs_for_hint = missing_pairs or config.pairs
    return {
        "errors": quality_result.get("errors", []),
        "warnings": quality_result.get("warnings", []),
        "pair_details": quality_result.get("details", {}),
        "missing_pairs": missing_pairs,
        "timeframe": config.timeframe,
        "timerange": config.timerange,
        "config_file": config.config_file,
        "user_data_dir": config.user_data_dir,
        "exchange": config.exchange,
        "download_command_hint": _download_command_hint(config, pairs_for_hint),
    }


def _duration_ms(started_at, finished_at) -> int | None:
    if started_at is None or finished_at is None:
        return None
    return max(0, round((finished_at - started_at).total_seconds() * 1000))


async def _emit_gate_progress(
    progress_sink: Any | None,
    gate_started: dict[str, Any],
    gate_name: str,
    status: str,
    *,
    errors: Any = None,
    warnings: Any = None,
    metrics: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    if progress_sink is None:
        return
    now = utc_now()
    if status == "running":
        gate_started[gate_name] = now
        started_at = now
        finished_at = None
    else:
        started_at = gate_started.get(gate_name) or now
        finished_at = now
    payload = {
        "gate_name": gate_name,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": _duration_ms(started_at, finished_at),
        "errors": _string_list(errors),
        "warnings": _string_list(warnings),
        "metrics": metrics or {},
        "details": details or {},
    }
    try:
        result = progress_sink(payload)
        if inspect.isawaitable(result):
            await result
    except Exception:
        pass


async def _run_post_backtest_gates(
    spec: StrategySpec,
    save_result: Any,
    config: CandidateConfig,
    gate_results: list[CandidateGateResult],
    deps: dict[str, Any],
    progress_sink: Any | None,
    gate_started: dict[str, Any],
) -> CandidateVerdict:
    """Run gates 5-7 (pair sweep, portfolio backtest, final pair decision)."""
    run_pair_sweep = deps.get("run_individual_pair_sweep", _empty_pair_sweep)
    await _emit_gate_progress(
        progress_sink,
        gate_started,
        "individual_pair_sweep",
        "running",
    )
    pair_sweep_results = await run_pair_sweep(
        pairs=config.pairs,
        strategy_name=spec.name,
        config_file=config.config_file,
        timerange=config.timerange,
        timeframe=config.timeframe,
    )
    passed_pairs = [r for r in pair_sweep_results if r.get("status") == "passed"]
    gate_results.append(
        CandidateGateResult(
            gate_name="individual_pair_sweep",
            passed=len(passed_pairs) > 0,
            details={
                "total_pairs": len(pair_sweep_results),
                "passed_pairs": len(passed_pairs),
                "results": pair_sweep_results,
            },
        )
    )
    if not passed_pairs:
        await _emit_gate_progress(
            progress_sink,
            gate_started,
            "individual_pair_sweep",
            "failed",
            details={
                "total_pairs": len(pair_sweep_results),
                "passed_pairs": len(passed_pairs),
                "results": pair_sweep_results,
            },
        )
        return CandidateVerdict(
            passed=False,
            gate_results=_dedup_gate_results(gate_results),
            failure_reason="individual_pair_sweep",
        )

    await _emit_gate_progress(
        progress_sink,
        gate_started,
        "individual_pair_sweep",
        "passed",
        details={
            "total_pairs": len(pair_sweep_results),
            "passed_pairs": len(passed_pairs),
            "results": pair_sweep_results,
        },
    )
    run_portfolio = deps.get("run_portfolio_backtest", _run_portfolio_backtest)
    strategy_path = str(save_result.path) if save_result.path else ""
    await _emit_gate_progress(
        progress_sink,
        gate_started,
        "portfolio_backtest",
        "running",
    )
    portfolio_result = run_portfolio(
        strategy_path=strategy_path,
        strategy_name=spec.name,
        config_file=config.config_file,
        timerange=config.timerange,
        timeframe=config.timeframe,
        pairs=[p["pair"] for p in passed_pairs],
        max_open_trades=spec.max_open_trades,
        user_data_dir=config.user_data_dir,
        exchange=config.exchange,
    )
    portfolio_passed = portfolio_result.get("status") == "passed"
    gate_results.append(
        CandidateGateResult(
            gate_name="portfolio_backtest",
            passed=portfolio_passed,
            details=portfolio_result,
            metrics=portfolio_result.get("portfolio_summary"),
        )
    )
    if not portfolio_passed:
        await _emit_gate_progress(
            progress_sink,
            gate_started,
            "portfolio_backtest",
            "failed",
            errors=portfolio_result.get("failure_reasons", []),
            metrics=portfolio_result.get("portfolio_summary"),
            details=portfolio_result,
        )
        return CandidateVerdict(
            passed=False,
            gate_results=_dedup_gate_results(gate_results),
            portfolio_metrics=portfolio_result.get("portfolio_summary", {}),
            failure_reason="portfolio_backtest",
        )

    await _emit_gate_progress(
        progress_sink,
        gate_started,
        "portfolio_backtest",
        "passed",
        metrics=portfolio_result.get("portfolio_summary"),
        details=portfolio_result,
    )
    decide_pairs = deps.get("decide_final_pair_set", _decide_final_pair_set)
    await _emit_gate_progress(
        progress_sink,
        gate_started,
        "final_pair_decision",
        "running",
    )
    decision = decide_pairs(
        individual_results=pair_sweep_results,
        portfolio_result=portfolio_result,
        risk_profile=config.risk_profile,
    )
    approved = decision.get("verdict") == "approved"
    gate_results.append(
        CandidateGateResult(
            gate_name="final_pair_decision",
            passed=approved,
            details=decision,
        )
    )
    if not approved:
        await _emit_gate_progress(
            progress_sink,
            gate_started,
            "final_pair_decision",
            "failed",
            errors=[decision.get("rejection_reason")] if decision.get("rejection_reason") else [],
            details=decision,
        )
        return CandidateVerdict(
            passed=False,
            gate_results=_dedup_gate_results(gate_results),
            portfolio_metrics=portfolio_result.get("portfolio_summary", {}),
            failure_reason=decision.get("rejection_reason", "final_pair_decision"),
        )

    await _emit_gate_progress(
        progress_sink,
        gate_started,
        "final_pair_decision",
        "passed",
        details=decision,
    )
    return CandidateVerdict(
        passed=True,
        gate_results=_dedup_gate_results(gate_results),
        final_pair_set=decision.get("approved_pairs", []),
        portfolio_metrics=portfolio_result.get("portfolio_summary", {}),
    )


async def evaluate_candidate(
    spec: StrategySpec,
    config: CandidateConfig,
    *,
    deps: dict[str, Any] | None = None,
    progress_sink: Any | None = None,
) -> CandidateVerdict:
    """Run a strategy candidate through the evaluation pipeline.

    Parameters
    ----------
    spec:
        The validated StrategySpec to evaluate.
    config:
        Runtime configuration (timerange, pairs, etc.).
    deps:
        Optional dependency injection container for replacing external
        helpers during testing (e.g. ``{"render_strategy": mock}``).

    Returns
    -------
    CandidateVerdict
        The final verdict with per-gate results.
    """
    deps = deps or {}

    render_strategy = deps.get("render_strategy", render_strategy_from_spec)
    save_strategy = deps.get("save_rendered_strategy", save_rendered_strategy)
    check_quality = deps.get("check_data_quality", check_data_quality)
    data_download_runner = deps.get("data_download_runner")
    run_data_download = deps.get("run_data_download")

    gate_results: list[CandidateGateResult] = []
    gate_started: dict[str, Any] = {}

    # Gate 1: Render spec to strategy source code
    await _emit_gate_progress(progress_sink, gate_started, "render_strategy", "running")
    render_result = render_strategy(spec)
    if render_result.get("source") is None:
        gate_results.append(
            CandidateGateResult(
                gate_name="render_strategy",
                passed=False,
                details={"errors": render_result.get("errors", [])},
            )
        )
        await _emit_gate_progress(
            progress_sink,
            gate_started,
            "render_strategy",
            "failed",
            errors=render_result.get("errors", []),
            warnings=render_result.get("warnings", []),
            details={"template": render_result.get("template")},
        )
        return CandidateVerdict(
            passed=False,
            gate_results=_dedup_gate_results(gate_results),
            failure_reason="render_strategy",
        )

    await _emit_gate_progress(
        progress_sink,
        gate_started,
        "render_strategy",
        "passed",
        warnings=render_result.get("warnings", []),
        details={"template": render_result.get("template")},
    )
    gate_results.append(
        CandidateGateResult(
            gate_name="render_strategy",
            passed=True,
            details={"template": render_result.get("template")},
        )
    )

    # Gate 2: Save rendered strategy as safe working copy
    base_path = f"{config.user_data_dir}/strategies/rendered"
    await _emit_gate_progress(progress_sink, gate_started, "save_working_copy", "running")
    save_result = save_strategy(
        source=render_result["source"],
        strategy_name=spec.name,
        run_id=spec.name,
        base_path=base_path,
    )
    if save_result.errors:
        gate_results.append(
            CandidateGateResult(
                gate_name="save_working_copy",
                passed=False,
                details={"errors": save_result.errors},
            )
        )
        await _emit_gate_progress(
            progress_sink,
            gate_started,
            "save_working_copy",
            "failed",
            errors=save_result.errors,
            warnings=getattr(save_result, "warnings", []),
        )
        return CandidateVerdict(
            passed=False,
            gate_results=_dedup_gate_results(gate_results),
            failure_reason="save_working_copy",
        )

    await _emit_gate_progress(
        progress_sink,
        gate_started,
        "save_working_copy",
        "passed",
        warnings=getattr(save_result, "warnings", []),
        details={"path": str(save_result.path) if save_result.path else None},
    )
    gate_results.append(
        CandidateGateResult(
            gate_name="save_working_copy",
            passed=True,
            details={"path": str(save_result.path) if save_result.path else None},
        )
    )
    previous_save_path = str(save_result.path) if save_result.path else None

    # Gate 3: Data quality check, with one bounded Candidate-only auto-download retry.
    data_download_attempts = 0
    while True:
        await _emit_gate_progress(progress_sink, gate_started, "data_quality", "running")
        quality_result = check_quality(
            pairs=config.pairs,
            timeframe=config.timeframe,
            timerange=config.timerange,
            user_data_dir=config.user_data_dir,
            exchange=config.exchange,
        )
        if quality_result.get("passed"):
            break

        failure_details = _data_quality_failure_details(quality_result, config)
        await _emit_gate_progress(
            progress_sink,
            gate_started,
            "data_quality",
            "failed",
            errors=quality_result.get("errors", []),
            warnings=quality_result.get("warnings", []),
            details=failure_details,
        )

        can_download = (
            config.auto_download_data
            and (data_download_runner is not None or run_data_download is not None)
            and data_download_attempts < config.max_data_download_attempts
            and _is_retryable_data_quality_failure(quality_result)
        )
        if not can_download:
            gate_results.append(
                CandidateGateResult(
                    gate_name="data_quality",
                    passed=False,
                    details=failure_details,
                )
            )
            return CandidateVerdict(
                passed=False,
                gate_results=_dedup_gate_results(gate_results),
                failure_reason="data_quality",
            )

        data_download_attempts += 1
        download_pairs = _extract_missing_pairs(quality_result) or config.pairs
        prepend = _download_should_prepend(quality_result, config)
        download_details = _data_download_details(
            config,
            download_pairs,
            prepend=prepend,
        )
        await _emit_gate_progress(
            progress_sink,
            gate_started,
            "data_download",
            "running",
            details={**download_details, "attempt": data_download_attempts},
        )

        try:
            download_request = DownloadDataRequest(
                config_file=config.config_file,
                timerange=config.timerange,
                timeframes=[config.timeframe],
                pairs=download_pairs,
                prepend=prepend,
            )
            if run_data_download is not None:
                result = run_data_download(download_request)
                download_id = await result if inspect.isawaitable(result) else result
            else:
                download_id = await asyncio.to_thread(
                    data_download_runner.run_download,
                    download_request,
                )
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            failed_details = _data_download_details(
                config,
                download_pairs,
                prepend=prepend,
                error=error,
            )
            gate_results.append(
                CandidateGateResult(
                    gate_name="data_download",
                    passed=False,
                    details=failed_details,
                )
            )
            await _emit_gate_progress(
                progress_sink,
                gate_started,
                "data_download",
                "failed",
                errors=[error],
                details=failed_details,
            )
            return CandidateVerdict(
                passed=False,
                gate_results=_dedup_gate_results(gate_results),
                failure_reason="data_download",
            )

        passed_details = _data_download_details(
            config,
            download_pairs,
            prepend=prepend,
            download_id=download_id,
        )
        gate_results.append(
            CandidateGateResult(
                gate_name="data_download",
                passed=True,
                details={**passed_details, "attempt": data_download_attempts},
            )
        )
        await _emit_gate_progress(
            progress_sink,
            gate_started,
            "data_download",
            "passed",
            details={**passed_details, "attempt": data_download_attempts},
        )

    await _emit_gate_progress(
        progress_sink,
        gate_started,
        "data_quality",
        "passed",
        warnings=quality_result.get("warnings", []),
        details={"pair_count": len(config.pairs)},
    )
    gate_results.append(
        CandidateGateResult(
            gate_name="data_quality",
            passed=True,
            details={"pair_count": len(config.pairs)},
        )
    )

    # Gate 4: Backtest Gate
    run_backtest = deps.get("run_backtest_gate", run_backtest_gate)
    analyze_failure = deps.get("analyze_gate_failure", analyze_gate_failure)
    build_repair = deps.get("build_repair_plan", build_repair_plan)

    await _emit_gate_progress(progress_sink, gate_started, "backtest_gate", "running")
    bt_result = run_backtest(
        strategy_path=str(save_result.path) if save_result.path else "",
        strategy_name=spec.name,
        config_file=config.config_file,
        timerange=config.timerange,
        timeframe=config.timeframe,
        pairs=config.pairs,
        max_open_trades=spec.max_open_trades,
        user_data_dir=config.user_data_dir,
        exchange=config.exchange,
    )

    if bt_result.gate_status == "passed":
        gate_results.append(
            CandidateGateResult(
                gate_name="backtest_gate",
                passed=True,
                metrics=bt_result.metrics,
                details={"failures": bt_result.failures},
            )
        )
        await _emit_gate_progress(
            progress_sink,
            gate_started,
            "backtest_gate",
            "passed",
            warnings=bt_result.warnings,
            metrics=bt_result.metrics,
            details={"failures": bt_result.failures},
        )
        return await _run_post_backtest_gates(
            spec, save_result, config, gate_results, deps, progress_sink, gate_started,
        )

    gate_results.append(
        CandidateGateResult(
            gate_name="backtest_gate",
            passed=False,
            details={
                "gate_status": bt_result.gate_status,
                "failures": bt_result.failures,
                "errors": bt_result.errors,
            },
            metrics=bt_result.metrics,
        )
    )
    await _emit_gate_progress(
        progress_sink,
        gate_started,
        "backtest_gate",
        "failed",
        errors=bt_result.errors,
        warnings=bt_result.warnings,
        metrics=bt_result.metrics,
        details={
            "gate_status": bt_result.gate_status,
            "failures": bt_result.failures,
        },
    )

    # Gate 5: Failure Analyzer
    await _emit_gate_progress(progress_sink, gate_started, "failure_analyzer", "running")
    classification = analyze_failure(bt_result)
    gate_results.append(
        CandidateGateResult(
            gate_name="failure_analyzer",
            passed=False,
            details={
                "primary_class": classification.primary_class,
                "next_route": classification.next_route,
                "failed_metrics": classification.failed_metrics,
            },
        )
    )
    await _emit_gate_progress(
        progress_sink,
        gate_started,
        "failure_analyzer",
        "passed",
        details={
            "primary_class": classification.primary_class,
            "next_route": classification.next_route,
            "failed_metrics": classification.failed_metrics,
        },
    )

    # Gate 6: Repair Plan
    await _emit_gate_progress(progress_sink, gate_started, "repair_plan", "running")
    repair_plan = build_repair(classification, spec=spec)
    gate_results.append(
        CandidateGateResult(
            gate_name="repair_plan",
            passed=repair_plan.can_repair,
            details={
                "scope": repair_plan.scope,
                "can_repair": repair_plan.can_repair,
                "reason": repair_plan.reason,
            },
        )
    )
    await _emit_gate_progress(
        progress_sink,
        gate_started,
        "repair_plan",
        "passed" if repair_plan.can_repair else "failed",
        details={
            "scope": repair_plan.scope,
            "can_repair": repair_plan.can_repair,
            "reason": repair_plan.reason,
        },
    )

    # Repair loop — only when can_repair is True
    if repair_plan.can_repair:
        ollama_client = deps.get("ollama_client")
        ask_ai = deps.get("ask_ai_for_repair_proposal", ask_ai_for_repair_proposal)
        apply_repair_fn = deps.get("apply_repair_proposal", apply_repair_proposal)
        del_rendered = deps.get("delete_rendered_strategy", delete_rendered_strategy)

        if ollama_client is None:
            await _emit_gate_progress(
                progress_sink,
                gate_started,
                "repair_attempts",
                "failed",
                errors=["repair_ai_unavailable"],
            )
            return CandidateVerdict(
                passed=False,
                gate_results=_dedup_gate_results(gate_results),
                failure_reason="repair_ai_unavailable",
            )

        remaining = spec.max_iterations - spec.iteration_count
        max_iter = max(0, min(config.max_repair_iterations, remaining))
        if max_iter == 0:
            await _emit_gate_progress(
                progress_sink,
                gate_started,
                "repair_attempts",
                "skipped",
                details={"reason": "repair_max_iterations"},
            )
            return CandidateVerdict(
                passed=False,
                gate_results=_dedup_gate_results(gate_results),
                failure_reason="repair_max_iterations",
            )

        await _emit_gate_progress(
            progress_sink,
            gate_started,
            "repair_attempts",
            "running",
            details={"max_iterations": max_iter},
        )
        repair_attempts: list[RepairAttempt] = []
        current_spec = spec
        current_repair_plan = repair_plan
        current_classification = classification
        iteration = 0

        while iteration < max_iter:
            proposal = await ask_ai(
                ollama_client, current_repair_plan, current_spec, current_classification,
            )
            if proposal is None:
                repair_attempts.append(RepairAttempt(
                    iteration=iteration,
                    scope=current_repair_plan.scope,
                    outcome="ai_returned_none",
                ))
                await _emit_gate_progress(
                    progress_sink,
                    gate_started,
                    "repair_attempts",
                    "failed",
                    errors=["ai_returned_none"],
                    details={"attempts": [a.model_dump(mode="json") for a in repair_attempts]},
                )
                break

            new_spec, app_errors = apply_repair_fn(current_spec, proposal)
            if app_errors:
                repair_attempts.append(RepairAttempt(
                    iteration=iteration,
                    scope=current_repair_plan.scope,
                    change_applied=proposal.get("change"),
                    outcome="apply_failed",
                ))
                await _emit_gate_progress(
                    progress_sink,
                    gate_started,
                    "repair_attempts",
                    "failed",
                    errors=app_errors,
                    details={"attempts": [a.model_dump(mode="json") for a in repair_attempts]},
                )
                break

            repair_attempts.append(RepairAttempt(
                iteration=iteration,
                scope=current_repair_plan.scope,
                change_applied=proposal.get("change"),
                outcome="applied_and_retested",
            ))

            # Re-run gates 1-4 for the repaired spec
            await _emit_gate_progress(progress_sink, gate_started, "render_strategy", "running")
            render_result = render_strategy(new_spec)
            if render_result.get("source") is None:
                await _emit_gate_progress(
                    progress_sink,
                    gate_started,
                    "render_strategy",
                    "failed",
                    errors=render_result.get("errors", []),
                    warnings=render_result.get("warnings", []),
                )
                break

            await _emit_gate_progress(
                progress_sink,
                gate_started,
                "render_strategy",
                "passed",
                warnings=render_result.get("warnings", []),
                details={"template": render_result.get("template")},
            )
            new_base_path = f"{config.user_data_dir}/strategies/rendered"
            if previous_save_path:
                del_rendered(previous_save_path, new_base_path)
            await _emit_gate_progress(progress_sink, gate_started, "save_working_copy", "running")
            save_result = save_strategy(
                source=render_result["source"],
                strategy_name=new_spec.name,
                run_id=new_spec.name,
                base_path=new_base_path,
            )
            previous_save_path = str(save_result.path) if save_result.path else None
            if save_result.errors:
                await _emit_gate_progress(
                    progress_sink,
                    gate_started,
                    "save_working_copy",
                    "failed",
                    errors=save_result.errors,
                    warnings=getattr(save_result, "warnings", []),
                )
                break

            await _emit_gate_progress(
                progress_sink,
                gate_started,
                "save_working_copy",
                "passed",
                warnings=getattr(save_result, "warnings", []),
                details={"path": str(save_result.path) if save_result.path else None},
            )
            await _emit_gate_progress(progress_sink, gate_started, "data_quality", "running")
            quality_result = check_quality(
                pairs=config.pairs,
                timeframe=config.timeframe,
                timerange=config.timerange,
                user_data_dir=config.user_data_dir,
                exchange=config.exchange,
            )
            if not quality_result.get("passed"):
                await _emit_gate_progress(
                    progress_sink,
                    gate_started,
                    "data_quality",
                    "failed",
                    errors=quality_result.get("errors", []),
                    warnings=quality_result.get("warnings", []),
                    details=quality_result.get("details", {}),
                )
                break

            await _emit_gate_progress(
                progress_sink,
                gate_started,
                "data_quality",
                "passed",
                warnings=quality_result.get("warnings", []),
                details={"pair_count": len(config.pairs)},
            )
            await _emit_gate_progress(progress_sink, gate_started, "backtest_gate", "running")
            bt_result = run_backtest(
                strategy_path=str(save_result.path) if save_result.path else "",
                strategy_name=new_spec.name,
                config_file=config.config_file,
                timerange=config.timerange,
                timeframe=config.timeframe,
                pairs=config.pairs,
                max_open_trades=new_spec.max_open_trades,
                user_data_dir=config.user_data_dir,
                exchange=config.exchange,
            )

            if bt_result.gate_status == "passed":
                gate_results.append(
                    CandidateGateResult(
                        gate_name="backtest_gate",
                        passed=True,
                        metrics=bt_result.metrics,
                        details={"failures": bt_result.failures},
                    )
                )
                await _emit_gate_progress(
                    progress_sink,
                    gate_started,
                    "backtest_gate",
                    "passed",
                    warnings=bt_result.warnings,
                    metrics=bt_result.metrics,
                    details={"failures": bt_result.failures},
                )
                await _emit_gate_progress(
                    progress_sink,
                    gate_started,
                    "repair_attempts",
                    "passed",
                    details={"attempts": [a.model_dump(mode="json") for a in repair_attempts]},
                )
                verdict = await _run_post_backtest_gates(
                    new_spec, save_result, config, gate_results, deps, progress_sink, gate_started,
                )
                verdict.repair_attempts = repair_attempts
                return verdict

            await _emit_gate_progress(
                progress_sink,
                gate_started,
                "backtest_gate",
                "failed",
                errors=bt_result.errors,
                warnings=bt_result.warnings,
                metrics=bt_result.metrics,
                details={
                    "gate_status": bt_result.gate_status,
                    "failures": bt_result.failures,
                },
            )
            # Re-analyze failure for the new spec
            await _emit_gate_progress(progress_sink, gate_started, "failure_analyzer", "running")
            current_classification = analyze_failure(bt_result)
            await _emit_gate_progress(
                progress_sink,
                gate_started,
                "failure_analyzer",
                "passed",
                details={
                    "primary_class": current_classification.primary_class,
                    "next_route": current_classification.next_route,
                    "failed_metrics": current_classification.failed_metrics,
                },
            )
            await _emit_gate_progress(progress_sink, gate_started, "repair_plan", "running")
            current_repair_plan = build_repair(current_classification, spec=new_spec)
            await _emit_gate_progress(
                progress_sink,
                gate_started,
                "repair_plan",
                "passed" if current_repair_plan.can_repair else "failed",
                details={
                    "scope": current_repair_plan.scope,
                    "can_repair": current_repair_plan.can_repair,
                    "reason": current_repair_plan.reason,
                },
            )
            if not current_repair_plan.can_repair:
                break

            current_spec = new_spec
            iteration += 1

        # All repair attempts exhausted
        await _emit_gate_progress(
            progress_sink,
            gate_started,
            "repair_attempts",
            "failed",
            details={"attempts": [a.model_dump(mode="json") for a in repair_attempts]},
        )
        return CandidateVerdict(
            passed=False,
            gate_results=_dedup_gate_results(gate_results),
            repair_attempts=repair_attempts,
            failure_reason=current_classification.primary_class or "repair_max_iterations",
        )

    await _emit_gate_progress(
        progress_sink,
        gate_started,
        "repair_attempts",
        "skipped",
        details={"reason": classification.primary_class or "repair_not_allowed"},
    )
    failure_reason = classification.primary_class or "repair_not_allowed"
    return CandidateVerdict(
        passed=False,
        gate_results=_dedup_gate_results(gate_results),
        failure_reason=failure_reason,
    )
