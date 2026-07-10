"""Backend-computed candidate readiness report.

The report is advisory in v1. It aggregates evidence that already exists in
the workspace and never starts new validation work by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable
import json
import math


SCHEMA_VERSION = "candidate_readiness_v1"
VALID_GATE_STATUSES = {"pass", "warn", "fail", "missing"}
VALID_PROFILES = {"scalping", "intraday", "swing", "position"}


DEFAULT_THRESHOLDS: dict[str, Any] = {
    "validation": {
        "min_profit_factor": 1.35,
        "max_drawdown": 18.0,
        "min_trades_floor": 40,
        "min_win_rate": 45.0,
        "min_pair_pass_rate": 0.65,
        "min_oos_retention": 0.70,
    },
    "elite_validation": {
        "min_profit_factor": 1.80,
        "max_drawdown": 10.0,
        "min_walk_forward_pass_rate": 0.70,
        "min_pair_pass_rate": 0.80,
    },
}


@dataclass
class SourceBundle:
    optimizer_session: Any | None = None
    optimizer_trial: Any | None = None
    backtest_detail: Any | None = None
    candidate_run: Any | None = None
    stress_session: Any | None = None
    stress_api_session: dict[str, Any] | None = None
    temporal_session: dict[str, Any] | None = None
    inferred_backtest_run_id: str | None = None


class ReadinessService:
    """Builds the ProfitabilityScore / CandidateReadiness report."""

    def __init__(
        self,
        *,
        root_dir: Path | str,
        run_repository: Any | None = None,
        optimizer_store: Any | None = None,
        sweep_store: Any | None = None,
        session_store: Any | None = None,
        candidate_run_lookup: Callable[[str], Any | None] | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.run_repository = run_repository
        self.optimizer_store = optimizer_store
        self.sweep_store = sweep_store
        self.session_store = session_store
        self.candidate_run_lookup = candidate_run_lookup

    def build_report(
        self,
        *,
        strategy_name: str | None = None,
        optimizer_session_id: str | None = None,
        trial_number: int | None = None,
        backtest_run_id: str | None = None,
        candidate_run_id: str | None = None,
        stress_session_id: str | None = None,
        temporal_stress_session_id: str | None = None,
        profile: str | None = None,
    ) -> dict[str, Any]:
        missing_sources: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        sources = self._load_sources(
            optimizer_session_id=optimizer_session_id,
            trial_number=trial_number,
            backtest_run_id=backtest_run_id,
            candidate_run_id=candidate_run_id,
            stress_session_id=stress_session_id,
            temporal_stress_session_id=temporal_stress_session_id,
            missing_sources=missing_sources,
        )

        effective_backtest_run_id = backtest_run_id or sources.inferred_backtest_run_id
        if effective_backtest_run_id and not sources.backtest_detail:
            sources.backtest_detail = self._load_backtest_detail(effective_backtest_run_id, missing_sources)

        timeframe = self._infer_timeframe(sources)
        selected_profile = self._select_profile(profile, timeframe)
        thresholds = self._load_thresholds(selected_profile)
        validation = dict(DEFAULT_THRESHOLDS["validation"])
        validation.update(_mapping(thresholds.get("validation")))
        elite_validation = dict(DEFAULT_THRESHOLDS["elite_validation"])
        elite_validation.update(_mapping(thresholds.get("elite_validation")))

        gates: list[dict[str, Any]] = []
        gates.extend(self._optimizer_gates(sources, validation))
        gates.extend(self._backtest_gates(sources, validation))
        gates.extend(self._validation_gates(sources, validation, elite_validation))
        gates.extend(self._stress_gates(sources, validation))
        gates.extend(self._pair_gates(sources, validation))
        gates.extend(self._exit_gates(sources))

        source_summary = self._build_source_summary(sources)
        usable_sources = [
            name
            for name, loaded in source_summary.items()
            if loaded.get("available") and name in {"optimizer", "backtest", "candidate"}
        ]

        blocking_failures = [
            self._blocking_summary(gate)
            for gate in gates
            if gate.get("blocking") and gate.get("status") == "fail"
        ]

        validation_evidence = self._has_oos_or_wfo_evidence(sources)
        if not validation_evidence:
            warnings.append(
                {
                    "code": "missing_oos_wfo",
                    "message": "OOS or walk-forward evidence is required before a Ready label.",
                    "severity": "warn",
                }
            )

        score = self._overall_score(gates)
        if not usable_sources:
            status = "insufficient_data"
            readiness_label = "Insufficient Data"
            score = 0
        elif blocking_failures or score < 50:
            status = "not_ready"
            readiness_label = "Not Ready"
        elif score >= 75 and validation_evidence:
            status = "ready"
            readiness_label = "Ready"
        else:
            status = "watch"
            readiness_label = "Watch"

        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "inputs": {
                "strategy_name": strategy_name,
                "optimizer_session_id": optimizer_session_id,
                "trial_number": trial_number,
                "backtest_run_id": effective_backtest_run_id,
                "candidate_run_id": candidate_run_id,
                "stress_session_id": stress_session_id,
                "temporal_stress_session_id": temporal_stress_session_id,
                "profile": selected_profile,
                "requested_profile": profile,
                "timeframe": timeframe,
            },
            "overall_score": score,
            "readiness_label": readiness_label,
            "status": status,
            "gates": gates,
            "blocking_failures": blocking_failures,
            "warnings": warnings,
            "missing_sources": missing_sources,
            "source_summary": source_summary,
            "threshold_tier": "validation",
            "thresholds": {
                "validation": validation,
                "elite_validation": elite_validation,
                "elite_validation_note": "Aspirational only; not required for v1 readiness.",
            },
            "draft_next_actions": self._draft_next_actions(
                status=status,
                sources=sources,
                missing_sources=missing_sources,
                validation_evidence=validation_evidence,
                blocking_failures=blocking_failures,
            ),
        }

    def _load_sources(
        self,
        *,
        optimizer_session_id: str | None,
        trial_number: int | None,
        backtest_run_id: str | None,
        candidate_run_id: str | None,
        stress_session_id: str | None,
        temporal_stress_session_id: str | None,
        missing_sources: list[dict[str, Any]],
    ) -> SourceBundle:
        sources = SourceBundle()

        if optimizer_session_id:
            sources.optimizer_session = self._safe_load(
                "optimizer_session",
                optimizer_session_id,
                missing_sources,
                lambda: self.optimizer_store.load_session(optimizer_session_id) if self.optimizer_store else None,
            )
            if sources.optimizer_session:
                sources.optimizer_trial = self._select_optimizer_trial(sources.optimizer_session, trial_number)
                if not sources.optimizer_trial:
                    missing_sources.append(
                        {
                            "source": "optimizer_trial",
                            "id": optimizer_session_id,
                            "detail": f"Trial {trial_number!r} was not found in optimizer session.",
                        }
                    )
                else:
                    sources.inferred_backtest_run_id = _string(_value(sources.optimizer_trial, "run_id"))

        if backtest_run_id:
            sources.backtest_detail = self._load_backtest_detail(backtest_run_id, missing_sources)

        if candidate_run_id:
            if self.candidate_run_lookup:
                sources.candidate_run = self._safe_load(
                    "candidate_run",
                    candidate_run_id,
                    missing_sources,
                    lambda: self.candidate_run_lookup(candidate_run_id),
                )
            else:
                missing_sources.append(
                    {
                        "source": "candidate_run",
                        "id": candidate_run_id,
                        "detail": "Candidate run lookup is not available.",
                    }
                )

        if stress_session_id:
            sources.stress_api_session, sources.stress_session = self._load_stress_sources(
                stress_session_id, missing_sources
            )

        if temporal_stress_session_id:
            sources.temporal_session = self._load_api_session(
                "temporal_stress_session",
                temporal_stress_session_id,
                missing_sources,
            )

        return sources

    def _load_backtest_detail(
        self, backtest_run_id: str, missing_sources: list[dict[str, Any]]
    ) -> Any | None:
        return self._safe_load(
            "backtest_run",
            backtest_run_id,
            missing_sources,
            lambda: self.run_repository.load_detail(backtest_run_id) if self.run_repository else None,
        )

    def _safe_load(
        self,
        source: str,
        identifier: str,
        missing_sources: list[dict[str, Any]],
        loader: Callable[[], Any | None],
    ) -> Any | None:
        try:
            loaded = loader()
        except Exception as exc:  # noqa: BLE001 - report missing evidence, not a 500.
            missing_sources.append({"source": source, "id": identifier, "detail": str(exc)})
            return None
        if loaded is None:
            missing_sources.append({"source": source, "id": identifier, "detail": "Not found."})
        return loaded

    def _load_api_session(
        self, source: str, identifier: str, missing_sources: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        return self._safe_load(
            source,
            identifier,
            missing_sources,
            lambda: self.session_store.get(identifier) if self.session_store else None,
        )

    def _load_stress_sources(
        self, stress_session_id: str, missing_sources: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, Any | None]:
        api_session = self._load_api_session("stress_session", stress_session_id, [])
        sweep_session_id = _string(_value(_value(api_session, "result"), "sweep_session_id")) if api_session else None
        if sweep_session_id:
            sweep = self._safe_load(
                "stress_sweep_session",
                sweep_session_id,
                missing_sources,
                lambda: self.sweep_store.load_session(sweep_session_id) if self.sweep_store else None,
            )
            return api_session, sweep

        direct_sweep = self._safe_load(
            "stress_session",
            stress_session_id,
            missing_sources,
            lambda: self.sweep_store.load_session(stress_session_id) if self.sweep_store else None,
        )
        return api_session, direct_sweep

    def _select_optimizer_trial(self, session: Any, trial_number: int | None) -> Any | None:
        trials = _value(session, "trials") or []
        if not trials:
            return None
        selected_number = trial_number
        if selected_number is None:
            selected_number = _value(session, "best_trial_number")
        if selected_number is not None:
            for trial in trials:
                if _int(_value(trial, "trial_number")) == _int(selected_number):
                    return trial
        return trials[0]

    def _optimizer_gates(self, sources: SourceBundle, validation: dict[str, Any]) -> list[dict[str, Any]]:
        trial = sources.optimizer_trial
        metrics = _value(trial, "metrics") if trial else None
        if not metrics:
            return [
                self._gate(
                    "optimizer.evidence",
                    "Optimizer",
                    "Optimizer Trial",
                    "missing",
                    "No optimizer trial evidence attached.",
                    weight=0,
                    source="optimizer",
                )
            ]

        score = _number(_value(metrics, "score"))
        profit_factor = _number(_value(metrics, "profit_factor"))
        drawdown = _abs_number(_value(metrics, "max_drawdown_pct"))
        trades = _number(_value(metrics, "total_trades"))
        net_profit = _number(_value(metrics, "net_profit_pct"))
        status = "pass"
        if net_profit is not None and net_profit <= 0:
            status = "fail"
        elif drawdown is not None and drawdown > _number(validation.get("max_drawdown"), 18.0):
            status = "warn"
        elif profit_factor is not None and profit_factor < _number(validation.get("min_profit_factor"), 1.35):
            status = "warn"

        return [
            self._gate(
                "optimizer.selected_trial_quality",
                "Optimizer",
                "Selected Trial Quality",
                status,
                self._metric_reason(
                    {
                        "score": score,
                        "net_profit_pct": net_profit,
                        "profit_factor": profit_factor,
                        "max_drawdown_pct": drawdown,
                        "total_trades": trades,
                    }
                ),
                observed={
                    "score": score,
                    "net_profit_pct": net_profit,
                    "profit_factor": profit_factor,
                    "max_drawdown_pct": drawdown,
                    "total_trades": trades,
                },
                weight=8,
                source="optimizer",
            )
        ]

    def _backtest_gates(self, sources: SourceBundle, validation: dict[str, Any]) -> list[dict[str, Any]]:
        detail = sources.backtest_detail
        summary = _value(detail, "parsed_summary") if detail else None
        source = "backtest"
        if not summary:
            summary = self._candidate_backtest_metrics(sources.candidate_run)
            source = "candidate"
        if not summary:
            return [
                self._gate(
                    "backtest.core",
                    "Backtest",
                    "Core Backtest",
                    "missing",
                    "No usable backtest summary was found.",
                    weight=18,
                    source="backtest",
                )
            ]

        min_profit_factor = _number(validation.get("min_profit_factor"), 1.35)
        max_drawdown = _number(validation.get("max_drawdown"), 18.0)
        min_trades = _number(validation.get("min_trades_floor"), 40.0)
        min_win_rate = _number(validation.get("min_win_rate"), 45.0)

        net_profit = _number(_value(summary, "net_profit_pct"))
        profit_factor = _number(_value(summary, "profit_factor"))
        drawdown = _abs_number(_value(summary, "max_drawdown_pct"))
        trades = _number(_value(summary, "total_trades"))
        win_rate = _number(_value(summary, "win_rate_pct"))
        expectancy = _number(_value(summary, "expectancy"))

        return [
            self._gate(
                "backtest.net_profit",
                "Backtest",
                "Net Profit",
                "pass" if net_profit is not None and net_profit > 0 else "fail",
                _reason_value("Net profit", net_profit, suffix="%"),
                observed=net_profit,
                threshold="> 0%",
                blocking=net_profit is None or net_profit <= 0,
                weight=12,
                source=source,
            ),
            self._gate(
                "backtest.profit_factor",
                "Backtest",
                "Profit Factor",
                _threshold_status(profit_factor, min_profit_factor, better="higher", warn_ratio=0.85),
                _reason_value("Profit factor", profit_factor),
                observed=profit_factor,
                threshold=f">= {min_profit_factor:g}",
                blocking=profit_factor is None or profit_factor < min_profit_factor,
                weight=12,
                source=source,
            ),
            self._gate(
                "backtest.max_drawdown",
                "Backtest",
                "Max Drawdown",
                _threshold_status(drawdown, max_drawdown, better="lower", warn_ratio=1.20),
                _reason_value("Max drawdown", drawdown, suffix="%"),
                observed=drawdown,
                threshold=f"<= {max_drawdown:g}%",
                blocking=drawdown is None or drawdown > max_drawdown,
                weight=12,
                source=source,
            ),
            self._gate(
                "backtest.trade_count",
                "Backtest",
                "Trade Count",
                _threshold_status(trades, min_trades, better="higher", warn_ratio=0.75),
                _reason_value("Trades", trades),
                observed=trades,
                threshold=f">= {min_trades:g}",
                blocking=trades is None or trades < min_trades,
                weight=10,
                source=source,
            ),
            self._gate(
                "backtest.win_expectancy",
                "Backtest",
                "Win Rate / Expectancy",
                "pass"
                if (win_rate is not None and win_rate >= min_win_rate and (expectancy is None or expectancy >= 0))
                else "warn",
                self._metric_reason({"win_rate_pct": win_rate, "expectancy": expectancy}),
                observed={"win_rate_pct": win_rate, "expectancy": expectancy},
                threshold=f"win rate >= {min_win_rate:g}% and non-negative expectancy",
                weight=6,
                source=source,
            ),
        ]

    def _validation_gates(
        self,
        sources: SourceBundle,
        validation: dict[str, Any],
        elite_validation: dict[str, Any],
    ) -> list[dict[str, Any]]:
        temporal = sources.temporal_session
        result = _value(temporal, "result") if temporal else None
        segments = _list(_value(result, "segments"))
        candidate_evidence = self._candidate_validation_evidence(sources.candidate_run)
        if not segments and not candidate_evidence:
            return [
                self._gate(
                    "validation.oos_wfo_evidence",
                    "Validation",
                    "OOS / WFO Evidence",
                    "missing",
                    "No OOS or walk-forward evidence is attached.",
                    observed=None,
                    threshold="required for Ready",
                    weight=12,
                    source="validation",
                )
            ]

        profitable_segments = [
            segment
            for segment in segments
            if (_number(_value(segment, "net_profit_pct")) or 0) > 0
            and str(_value(segment, "status") or "completed").lower() != "failed"
        ]
        pass_rate = (len(profitable_segments) / len(segments)) if segments else None
        consistency = _number(_value(result, "consistency_score"))
        min_retention = _number(validation.get("min_oos_retention"), 0.70)
        min_wfo_pass = _number(elite_validation.get("min_walk_forward_pass_rate"), 0.70)
        gate_status = "pass"
        if pass_rate is not None and pass_rate < min_wfo_pass:
            gate_status = "fail" if pass_rate < 0.5 else "warn"
        elif candidate_evidence and candidate_evidence.get("status") in {"fail", "warn"}:
            gate_status = candidate_evidence["status"]
        if consistency is not None and consistency < min_retention:
            gate_status = "warn" if gate_status == "pass" else gate_status

        return [
            self._gate(
                "validation.oos_wfo_evidence",
                "Validation",
                "OOS / WFO Evidence",
                gate_status,
                self._metric_reason(
                    {
                        "profitable_window_pass_rate": pass_rate,
                        "consistency_score": consistency,
                        "candidate_validation": candidate_evidence,
                    }
                ),
                observed={
                    "profitable_window_pass_rate": pass_rate,
                    "consistency_score": consistency,
                    "candidate_validation": candidate_evidence,
                },
                threshold=f"pass rate >= {min_wfo_pass:g}, consistency >= {min_retention:g}",
                weight=12,
                source="validation",
            )
        ]

    def _stress_gates(self, sources: SourceBundle, validation: dict[str, Any]) -> list[dict[str, Any]]:
        gates: list[dict[str, Any]] = []
        stress = sources.stress_session
        iterations = _list(_value(stress, "iterations")) if stress else []
        if iterations:
            completed = [item for item in iterations if str(_value(item, "status") or "").lower() == "completed"]
            failed_count = len(iterations) - len(completed)
            profits = [_number(_value(_value(item, "metrics"), "net_profit_pct")) for item in completed]
            profits = [profit for profit in profits if profit is not None]
            avg_profit = sum(profits) / len(profits) if profits else None
            failed_rate = failed_count / len(iterations) if iterations else None
            status = "pass"
            if avg_profit is None or avg_profit < 0 or (failed_rate is not None and failed_rate > 0.50):
                status = "fail"
            elif avg_profit < 1 or (failed_rate is not None and failed_rate > 0.20):
                status = "warn"
            gates.append(
                self._gate(
                    "stress.pair_sweep",
                    "Stress",
                    "Pair Sweep Robustness",
                    status,
                    self._metric_reason({"avg_net_profit_pct": avg_profit, "failed_iterations": failed_count}),
                    observed={"avg_net_profit_pct": avg_profit, "failed_iterations": failed_count},
                    threshold="positive average profit and <= 20% failed iterations",
                    weight=8,
                    source="stress",
                )
            )
        else:
            gates.append(
                self._gate(
                    "stress.pair_sweep",
                    "Stress",
                    "Pair Sweep Robustness",
                    "missing",
                    "No stress-lab pair sweep evidence is attached.",
                    weight=4,
                    source="stress",
                )
            )

        temporal = sources.temporal_session
        result = _value(temporal, "result") if temporal else None
        segments = _list(_value(result, "segments"))
        if segments:
            worst_profit = _number(_value(result, "worst_net_profit_pct"))
            if worst_profit is None:
                segment_profits = [_number(_value(segment, "net_profit_pct")) for segment in segments]
                segment_profits = [value for value in segment_profits if value is not None]
                worst_profit = min(segment_profits) if segment_profits else None
            drawdown_variance = _number(_value(result, "max_drawdown_variance"))
            status = "pass"
            if worst_profit is not None and worst_profit < 0:
                status = "fail"
            elif drawdown_variance is not None and drawdown_variance > _number(validation.get("max_drawdown"), 18.0):
                status = "warn"
            gates.append(
                self._gate(
                    "stress.temporal_worst_segment",
                    "Stress",
                    "Temporal Worst Segment",
                    status,
                    self._metric_reason(
                        {"worst_net_profit_pct": worst_profit, "max_drawdown_variance": drawdown_variance}
                    ),
                    observed={
                        "worst_net_profit_pct": worst_profit,
                        "max_drawdown_variance": drawdown_variance,
                    },
                    threshold="worst segment >= 0% net profit",
                    weight=8,
                    source="temporal_stress",
                )
            )
        else:
            gates.append(
                self._gate(
                    "stress.temporal_worst_segment",
                    "Stress",
                    "Temporal Worst Segment",
                    "missing",
                    "No temporal stress evidence is attached.",
                    weight=4,
                    source="temporal_stress",
                )
            )
        return gates

    def _pair_gates(self, sources: SourceBundle, validation: dict[str, Any]) -> list[dict[str, Any]]:
        pairs = _list(_value(sources.backtest_detail, "pair_results")) if sources.backtest_detail else []
        if not pairs:
            return [
                self._gate(
                    "pairs.health",
                    "Pairs",
                    "Pair Health",
                    "missing",
                    "No pair breakdown is attached.",
                    weight=6,
                    source="pairs",
                )
            ]

        profits = [_number(_value(pair, "net_profit_currency")) for pair in pairs]
        if all(value is None for value in profits):
            profits = [_number(_value(pair, "net_profit_pct")) for pair in pairs]
        profits = [0.0 if value is None else value for value in profits]
        positive = [value for value in profits if value > 0]
        losing = [value for value in profits if value < 0]
        pass_rate = len(positive) / len(profits) if profits else 0
        total_positive = sum(positive)
        concentration = max(positive) / total_positive if total_positive > 0 else 0
        min_pair_pass_rate = _number(validation.get("min_pair_pass_rate"), 0.65)

        pass_rate_status = "pass" if pass_rate >= min_pair_pass_rate else "warn" if pass_rate >= 0.50 else "fail"
        concentration_status = "pass" if concentration <= 0.50 else "warn" if concentration <= 0.70 else "fail"

        return [
            self._gate(
                "pairs.pass_rate",
                "Pairs",
                "Pair Pass Rate",
                pass_rate_status,
                self._metric_reason({"pair_pass_rate": pass_rate, "losing_pair_count": len(losing)}),
                observed={"pair_pass_rate": pass_rate, "losing_pair_count": len(losing)},
                threshold=f">= {min_pair_pass_rate:g}",
                weight=8,
                source="pairs",
            ),
            self._gate(
                "pairs.dominant_pair_concentration",
                "Pairs",
                "Dominant Pair Concentration",
                concentration_status,
                self._metric_reason({"positive_profit_concentration": concentration}),
                observed=concentration,
                threshold="<= 0.70",
                blocking=concentration > 0.70,
                weight=10,
                source="pairs",
            ),
        ]

    def _exit_gates(self, sources: SourceBundle) -> list[dict[str, Any]]:
        summary = _value(sources.backtest_detail, "parsed_summary") if sources.backtest_detail else None
        exits = _list(_value(summary, "exit_reason_distribution")) if summary else []
        if not exits:
            return [
                self._gate(
                    "exits.reason_balance",
                    "Exits",
                    "Exit Reason Balance",
                    "missing",
                    "No exit reason breakdown is attached.",
                    weight=3,
                    source="exits",
                )
            ]

        total = 0
        stoploss_count = 0
        roi_count = 0
        signal_count = 0
        for exit_item in exits:
            count = _number(_value(exit_item, "count"), 0) or 0
            total += count
            reason = str(_value(exit_item, "reason") or "").lower()
            if "stop" in reason:
                stoploss_count += count
            if "roi" in reason:
                roi_count += count
            if "signal" in reason or "exit" in reason:
                signal_count += count

        stoploss_ratio = stoploss_count / total if total else 0
        roi_signal_ratio = (roi_count + signal_count) / total if total else 0
        status = "pass" if stoploss_ratio <= 0.35 else "warn" if stoploss_ratio <= 0.50 else "fail"
        return [
            self._gate(
                "exits.reason_balance",
                "Exits",
                "Exit Reason Balance",
                status,
                self._metric_reason(
                    {
                        "stoploss_exit_ratio": stoploss_ratio,
                        "roi_or_signal_exit_ratio": roi_signal_ratio,
                    }
                ),
                observed={
                    "stoploss_exit_ratio": stoploss_ratio,
                    "roi_or_signal_exit_ratio": roi_signal_ratio,
                },
                threshold="stoploss exits <= 35% preferred, > 50% fails",
                weight=5,
                source="exits",
            )
        ]

    def _candidate_validation_evidence(self, candidate_run: Any | None) -> dict[str, Any] | None:
        verdict = _value(candidate_run, "verdict") if candidate_run else None
        gates = []
        if verdict:
            gates.extend(_list(_value(verdict, "gates")))
            gates.extend(_list(_value(verdict, "gate_results")))
        gates.extend(_list(_value(candidate_run, "gates")) if candidate_run else [])
        validation_gates = []
        for gate in gates:
            gate_name = str(
                _value(gate, "name") or _value(gate, "id") or _value(gate, "gate_name") or ""
            ).lower()
            if any(token in gate_name for token in ("oos", "walk", "forward", "validation")):
                validation_gates.append(gate)
        if not validation_gates:
            return None
        statuses = {str(_value(gate, "status") or "").lower() for gate in validation_gates}
        passed_values = [_value(gate, "passed") for gate in validation_gates if _value(gate, "passed") is not None]
        if False in passed_values or "fail" in statuses or "failed" in statuses:
            status = "fail"
        elif "warn" in statuses:
            status = "warn"
        else:
            status = "pass"
        return {"status": status, "gate_count": len(validation_gates)}

    def _candidate_backtest_metrics(self, candidate_run: Any | None) -> dict[str, Any] | None:
        verdict = _value(candidate_run, "verdict") if candidate_run else None
        if not verdict:
            return None
        direct = _mapping(_value(verdict, "backtest_metrics"))
        if direct:
            return direct
        for gate in _list(_value(verdict, "gate_results")):
            gate_name = str(_value(gate, "gate_name") or "").lower()
            if gate_name == "backtest_gate":
                metrics = _mapping(_value(gate, "metrics"))
                if metrics:
                    return {
                        "net_profit_pct": metrics.get("net_profit_pct", metrics.get("profit_pct")),
                        "profit_factor": metrics.get("profit_factor"),
                        "max_drawdown_pct": metrics.get("max_drawdown_pct", metrics.get("max_drawdown")),
                        "total_trades": metrics.get("total_trades", metrics.get("trades")),
                        "win_rate_pct": metrics.get("win_rate_pct", metrics.get("win_rate")),
                        "expectancy": metrics.get("expectancy"),
                    }
        return None

    def _has_oos_or_wfo_evidence(self, sources: SourceBundle) -> bool:
        temporal_result = _value(sources.temporal_session, "result") if sources.temporal_session else None
        if _list(_value(temporal_result, "segments")):
            return True
        return self._candidate_validation_evidence(sources.candidate_run) is not None

    def _build_source_summary(self, sources: SourceBundle) -> dict[str, dict[str, Any]]:
        return {
            "optimizer": {
                "available": sources.optimizer_trial is not None,
                "session_id": _value(sources.optimizer_session, "session_id"),
                "trial_number": _value(sources.optimizer_trial, "trial_number"),
            },
            "backtest": {
                "available": sources.backtest_detail is not None,
                "run_id": _value(_value(sources.backtest_detail, "metadata"), "run_id"),
            },
            "candidate": {
                "available": sources.candidate_run is not None,
                "run_id": _value(sources.candidate_run, "run_id"),
            },
            "stress": {"available": sources.stress_session is not None},
            "temporal_stress": {"available": sources.temporal_session is not None},
        }

    def _draft_next_actions(
        self,
        *,
        status: str,
        sources: SourceBundle,
        missing_sources: list[dict[str, Any]],
        validation_evidence: bool,
        blocking_failures: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        if not validation_evidence:
            actions.append(
                {
                    "type": "draft_oos_validation",
                    "label": "Draft OOS validation",
                    "reason": "Ready requires OOS or walk-forward evidence.",
                    "destructive": False,
                }
            )
            actions.append(
                {
                    "type": "draft_walk_forward_validation",
                    "label": "Draft walk-forward validation",
                    "reason": "Check whether performance survives time-window shifts.",
                    "destructive": False,
                }
            )
        if not sources.stress_session:
            actions.append(
                {
                    "type": "draft_stress_lab_export",
                    "label": "Draft stress-lab payload",
                    "reason": "Pair-sweep stress evidence is missing.",
                    "destructive": False,
                }
            )
        if status in {"ready", "watch"} and not blocking_failures:
            actions.append(
                {
                    "type": "draft_candidate_promotion_review",
                    "label": "Draft candidate promotion review",
                    "reason": "Review evidence before promotion; no overwrite or deploy is performed.",
                    "destructive": False,
                }
            )
        if missing_sources:
            actions.append(
                {
                    "type": "inspect_missing_evidence",
                    "label": "Inspect missing evidence",
                    "reason": "One or more requested run/session IDs could not be loaded.",
                    "destructive": False,
                }
            )
        return actions

    def _overall_score(self, gates: Iterable[dict[str, Any]]) -> int:
        total_weight = 0.0
        total_score = 0.0
        for gate in gates:
            weight = _number(gate.get("weight"), 0.0) or 0.0
            if weight <= 0:
                continue
            total_weight += weight
            total_score += weight * _gate_score(gate.get("status"))
        if total_weight <= 0:
            return 0
        return int(round(max(0.0, min(100.0, (total_score / total_weight) * 100))))

    def _gate(
        self,
        key: str,
        group: str,
        label: str,
        status: str,
        reason: str,
        *,
        observed: Any = None,
        threshold: Any = None,
        weight: float = 1.0,
        source: str | None = None,
        blocking: bool = False,
    ) -> dict[str, Any]:
        normalized_status = status if status in VALID_GATE_STATUSES else "warn"
        return {
            "key": key,
            "group": group,
            "label": label,
            "status": normalized_status,
            "reason": reason,
            "observed": _json_safe(observed),
            "threshold": _json_safe(threshold),
            "weight": weight,
            "source": source,
            "blocking": bool(blocking),
        }

    def _blocking_summary(self, gate: dict[str, Any]) -> dict[str, Any]:
        return {
            "gate": gate.get("key"),
            "label": gate.get("label"),
            "reason": gate.get("reason"),
            "observed": gate.get("observed"),
            "threshold": gate.get("threshold"),
        }

    def _metric_reason(self, values: dict[str, Any]) -> str:
        parts = []
        for key, value in values.items():
            if value is None:
                continue
            if isinstance(value, dict):
                parts.append(f"{key}={_compact_json(value)}")
            else:
                parts.append(f"{key}={_format_number(value)}")
        return ", ".join(parts) if parts else "Evidence is present, but metrics are incomplete."

    def _select_profile(self, requested_profile: str | None, timeframe: str | None) -> str:
        if requested_profile and requested_profile in VALID_PROFILES:
            return requested_profile
        timeframe_key = (timeframe or "").strip().lower()
        if timeframe_key in {"1m", "3m", "5m"}:
            return "scalping"
        if timeframe_key in {"15m", "30m", "45m", "1h"}:
            return "intraday"
        if timeframe_key in {"2h", "3h", "4h"}:
            return "swing"
        if timeframe_key.endswith("d") or timeframe_key.endswith("w") or timeframe_key.endswith("mo"):
            return "position"
        return "intraday"

    def _infer_timeframe(self, sources: SourceBundle) -> str | None:
        metadata = _value(sources.backtest_detail, "metadata") if sources.backtest_detail else None
        timeframe = _string(_value(metadata, "timeframe"))
        if timeframe:
            return timeframe
        config = _value(sources.optimizer_session, "config") if sources.optimizer_session else None
        timeframe = _string(_value(config, "timeframe"))
        if timeframe:
            return timeframe
        api_result = _value(sources.temporal_session, "result") if sources.temporal_session else None
        return _string(_value(api_result, "timeframe"))

    def _load_thresholds(self, profile: str) -> dict[str, Any]:
        candidate_paths = [
            self.root_dir / "backend" / "config" / "thresholds" / f"{profile}.json",
            Path(__file__).resolve().parents[1] / "config" / "thresholds" / f"{profile}.json",
        ]
        for path in candidate_paths:
            try:
                if path.exists():
                    return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
        return DEFAULT_THRESHOLDS


def _threshold_status(value: float | None, threshold: float, *, better: str, warn_ratio: float) -> str:
    if value is None or not math.isfinite(value):
        return "fail"
    if better == "higher":
        if value >= threshold:
            return "pass"
        return "warn" if value >= threshold * warn_ratio else "fail"
    if value <= threshold:
        return "pass"
    return "warn" if value <= threshold * warn_ratio else "fail"


def _reason_value(label: str, value: float | None, *, suffix: str = "") -> str:
    return f"{label}: {_format_number(value)}{suffix if value is not None else ''}"


def _format_number(value: Any) -> str:
    numeric = _number(value)
    if numeric is None:
        return "missing"
    return f"{numeric:.4g}"


def _gate_score(status: Any) -> float:
    if status == "pass":
        return 1.0
    if status == "warn":
        return 0.5
    return 0.0


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _mapping(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return {}


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _number(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    return numeric


def _abs_number(value: Any) -> float | None:
    numeric = _number(value)
    return abs(numeric) if numeric is not None else None


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    if hasattr(value, "dict"):
        return _json_safe(value.dict())
    return str(value)


def _compact_json(value: dict[str, Any]) -> str:
    return json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"))
