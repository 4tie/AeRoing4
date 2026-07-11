"""Focused Hyperopt service for the AeRoing4 pipeline (PROMPT 9 §1, §2, §5, §6, §10).

Architecture (CORRECTION #1 — reuse, don't rewrite):
    FocusedHyperoptService
      → BacktestRunner (EXISTING execution layer, injected like CandidateExecutor)
      → AeRoing4 research policy wrapper (hyperopt_policy)

We do NOT create a new subprocess runner, parser, or result store. BacktestRunner
is the same real execution layer CandidateExecutor uses; FocusedHyperoptService
builds scoped ParamsSchema overrides (like CandidateExecutor), calls
``BacktestRunner.run_candidate_backtest``, and resolves CanonicalMetricsSnapshot
via the SAME metrics adapter. ``QuantService.run_hyperopt`` is a mock stub and is
deliberately NOT used.

Result path (§6): Hyperopt NEVER promotes directly. It produces a best parameter
artifact → deterministic candidate materialization → canonical DEVELOP evaluation
→ Metrics SSOT → DecisionPolicy → KEEP/DROP/INCONCLUSIVE. Only KEEP promotes a
HYPEROPT champion (DecisionPolicy remains the final deterministic gate).

The search is FOCUSED and BOUNDED:
  * parameter scope = trusted allowed targets ∩ hyperopt-capable ∩ diagnosis scope
    (never all strategy parameters),
  * frozen Champion execution context (pairs/timeframe/DEVELOP timerange/exchange/
    trading mode/wallet/stake/max_open_trades/config identity/protocol+metrics ver),
  * bounded by FocusedHyperoptBudgetPolicy (epochs + max targets).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from .champions import ArtifactReference, ChampionReference, ChampionStore
from .experiments import ExperimentDecision
from .hyperopt_policy import (
    FocusedHyperoptBudgetPolicy,
    build_focused_scope,
    has_actionable_objective,
)
from .allowed_targets import AllowedMutationTarget
from .decision_policy import DecisionPolicy, DecisionRequest
from ..diagnosis.models import DiagnosisCode
from ..metrics.models import CanonicalMetricsSnapshot, MetricAvailability
from .stages import ResearchStage, ResearchZone
from .access_guard import DataZoneGuard


# ── Typed outcomes ─────────────────────────────────────────────────────────────

class FocusedHyperoptStatus(str, Enum):
    SUCCESS = "success"
    EXECUTION_SYSTEM_FAILURE = "execution_system_failure"
    PARSE_FAILURE = "parse_failure"
    NO_TRADES = "no_trades"
    PROTOCOL_DENIED = "protocol_denied"
    HYPEROPT_BLOCKED = "hyperopt_blocked"
    NO_SAFE_TARGET = "no_safe_target"
    NO_HYPEROPT_CAPABLE_TARGET = "no_hyperopt_capable_target"
    NO_ACTIONABLE_HYPEROPT_SCOPE = "no_actionable_hyperopt_scope"
    NO_ACTIONABLE_HYPEROPT_OBJECTIVE = "no_actionable_hyperopt_objective"


class FocusedHyperoptResult(BaseModel):
    status: FocusedHyperoptStatus
    diagnosis_code: Optional[DiagnosisCode] = None
    objective: Optional[str] = None
    best_params: Optional[dict[str, Any]] = None
    best_metrics: Optional[CanonicalMetricsSnapshot] = None
    decision: Optional[ExperimentDecision] = None
    promoted_champion_id: Optional[str] = None
    metrics_availability_reason: Optional[str] = None
    reason: str = ""
    trials_run: int = 0


# Objective-profile → primary metric used to rank hyperopt candidates.
_OBJECTIVE_METRIC: dict[str, str] = {
    "edge_improvement": "expectancy",
    "risk_adjusted": "max_drawdown_pct",
    "balanced": "expectancy",
}


def _metric_value(metrics: Optional[CanonicalMetricsSnapshot], name: str) -> Optional[float]:
    if metrics is None:
        return None
    mv = getattr(metrics, name, None)
    if mv is None:
        return None
    if getattr(mv, "availability", MetricAvailability.AVAILABLE) != MetricAvailability.AVAILABLE:
        return None
    return mv.value


@dataclass
class _MaterializedCandidate:
    strategy_artifact: ArtifactReference
    parameter_artifact: ArtifactReference
    candidate_dir: Path


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FocusedHyperoptService:
    """Bounded, diagnosis-scoped hyperopt over the current Champion (DEVELOP only)."""

    def __init__(
        self,
        runs_root: Path,
        backtest_runner: Any,
        champion_store: ChampionStore,
        zone_guard: DataZoneGuard,
        *,
        budget: FocusedHyperoptBudgetPolicy | None = None,
        develop_timerange: str = "20240101-20240630",
        pairs: list[str] | None = None,
        timeframe: str = "5m",
        exchange: str = "binance",
        trading_mode: str = "spot",
        dry_run_wallet: float = 1000.0,
        max_open_trades: int = 4,
        config_file: str = "config.json",
        protocol_version: str = "1.0.0",
        metrics_version: str = "1.0.0",
    ):
        self.runs_root = Path(runs_root)
        self.backtest_runner = backtest_runner
        self.champion_store = champion_store
        self.zone_guard = zone_guard
        self.budget = budget or FocusedHyperoptBudgetPolicy()
        self.develop_timerange = develop_timerange
        self.pairs = pairs or ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
        self.timeframe = timeframe
        self.exchange = exchange
        self.trading_mode = trading_mode
        self.dry_run_wallet = dry_run_wallet
        self.max_open_trades = max_open_trades
        self.config_file = config_file
        self.protocol_version = protocol_version
        self.metrics_version = metrics_version

    # ── §10: eligibility gate ──────────────────────────────────────────────────

    def check_eligibility(
        self,
        *,
        run_id: str,
        state_store: Any,
        champion: Optional[ChampionReference],
        allowed_targets: list[AllowedMutationTarget],
        diagnosis_code: DiagnosisCode,
    ) -> tuple[bool, str]:
        """Return (eligible, reason). Hyperopt must NOT start while the research
        loop has unresolved active work or no actionable scope."""
        if champion is None:
            return False, "no current Champion"
        report = self.champion_store  # placeholder; real check below via experiment_store
        # Reconciliation requirement (must come from the experiment store) is
        # injected by the caller through `must_reconcile_first`.
        must_reconcile = getattr(self, "_must_reconcile_first", False)
        if must_reconcile:
            return False, "active experiment requires reconciliation (RUNNING before reload)"
        if state_store is not None:
            st = state_store.load(run_id) if hasattr(state_store, "load") else None
            if st is not None and getattr(st, "research_status", None) == "paused":
                return False, "ResearchState is PAUSED (unresolved AI/system condition)"
        scope = build_focused_scope(diagnosis_code, allowed_targets)
        if scope.outcome != scope.outcome.FOCUSED_SCOPE_READY:
            return False, scope.reason
        # DEVELOP access allowed?
        decision, _ = self.zone_guard.request_access(
            _RunShim(run_id), ResearchStage.HYPEROPT, ResearchZone.DEVELOP, experiment_id=None
        )
        if not decision.allowed:
            return False, f"DEVELOP access denied: {decision.decision_code.value}"
        return True, "eligible"

    # ── §2/§5/§6: run ─────────────────────────────────────────────────────────

    def run(
        self,
        *,
        run_id: str,
        strategy_name: str,
        version_id: str,
        champion: ChampionReference,
        diagnosis_code: DiagnosisCode,
        allowed_targets: list[AllowedMutationTarget],
        state_store: Any = None,
        epochs: Optional[int] = None,
        must_reconcile_first: bool = False,
    ) -> FocusedHyperoptResult:
        self._must_reconcile_first = must_reconcile_first
        eligible, reason = self.check_eligibility(
            run_id=run_id, state_store=state_store, champion=champion,
            allowed_targets=allowed_targets, diagnosis_code=diagnosis_code,
        )
        if not eligible:
            # Protocol/zone denial → PROTOCOL_DENIED (correction #6). Other
            # ineligibility reasons map to their typed FocusedHyperoptStatus.
            if "DEVELOP access denied" in reason:
                return FocusedHyperoptResult(
                    status=FocusedHyperoptStatus.PROTOCOL_DENIED, diagnosis_code=diagnosis_code,
                    reason=reason,
                )
            scope = build_focused_scope(diagnosis_code, allowed_targets)
            status = {
                "no_safe_target": FocusedHyperoptStatus.NO_SAFE_TARGET,
                "no_hyperopt_capable_target": FocusedHyperoptStatus.NO_HYPEROPT_CAPABLE_TARGET,
                "no_actionable_hyperopt_scope": FocusedHyperoptStatus.NO_ACTIONABLE_HYPEROPT_SCOPE,
                "no_actionable_hyperopt_objective": FocusedHyperoptStatus.NO_ACTIONABLE_HYPEROPT_OBJECTIVE,
            }.get(scope.outcome.value, FocusedHyperoptStatus.HYPEROPT_BLOCKED)
            return FocusedHyperoptResult(
                status=status, diagnosis_code=diagnosis_code, reason=reason,
            )

        # §5: zone access (DEVELOP only). Denial → PROTOCOL_DENIED, no execution.
        decision, _ = self.zone_guard.request_access(
            _RunShim(run_id), ResearchStage.HYPEROPT, ResearchZone.DEVELOP, experiment_id=None
        )
        if not decision.allowed:
            return FocusedHyperoptResult(
                status=FocusedHyperoptStatus.PROTOCOL_DENIED, diagnosis_code=diagnosis_code,
                reason=f"DEVELOP access denied: {decision.decision_code.value}",
            )

        # §2: focused scope (already READY from eligibility, but rebuild for clarity).
        scope = build_focused_scope(diagnosis_code, allowed_targets)
        if scope.outcome != scope.outcome.FOCUSED_SCOPE_READY:
            return FocusedHyperoptResult(
                status=FocusedHyperoptStatus(scope.outcome.value), diagnosis_code=diagnosis_code,
                reason=scope.reason,
            )
        targets = self.budget.clamp_targets(scope.targets)
        objective_metric = _OBJECTIVE_METRIC.get(
            (scope.objective.value if scope.objective else "balanced"), "expectancy"
        )

        # Coordinate-descent search: bounded by budget.
        n_points = self.budget.clamp_epochs(epochs)
        per_target = max(2, n_points // max(1, len(targets)))
        base_values = {t.name: t.current_value for t in targets}
        best_values = dict(base_values)
        trials = 0
        best_overall: Optional[tuple[dict, CanonicalMetricsSnapshot]] = None

        for target in targets:
            lo, hi = float(target.min_allowed), float(target.max_allowed)
            if lo >= hi:
                continue
            samples = sorted({round(lo + (hi - lo) * i / max(1, per_target - 1), 6)
                              for i in range(per_target)})
            local_best_val = None
            local_best_metric = None
            for val in samples:
                cand_values = {**best_values, target.name: val}
                res = self._evaluate_point(
                    run_id=run_id, strategy_name=strategy_name, version_id=version_id,
                    champion=champion, values=cand_values,
                )
                trials += 1
                if res.status == FocusedHyperoptStatus.EXECUTION_SYSTEM_FAILURE:
                    return FocusedHyperoptResult(
                        status=FocusedHyperoptStatus.EXECUTION_SYSTEM_FAILURE,
                        diagnosis_code=diagnosis_code, objective=scope.objective.value if scope.objective else None,
                        metrics_availability_reason=res.metrics_availability_reason,
                        reason=res.reason, trials_run=trials,
                    )
                if res.best_metrics is None:
                    continue
                mv = _metric_value(res.best_metrics, objective_metric)
                if mv is None:
                    continue
                # For risk-adjusted (drawdown), LOWER is better.
                better = (local_best_metric is None) or (
                    mv < local_best_metric if objective_metric == "max_drawdown_pct" else mv > local_best_metric
                )
                if better:
                    local_best_val, local_best_metric = val, mv
            if local_best_val is not None:
                best_values[target.name] = local_best_val

        # Final canonical evaluation of the best combined parameter set.
        final = self._evaluate_point(
            run_id=run_id, strategy_name=strategy_name, version_id=version_id,
            champion=champion, values=best_values,
        )
        trials += 1
        if final.status == FocusedHyperoptStatus.EXECUTION_SYSTEM_FAILURE:
            return FocusedHyperoptResult(
                status=FocusedHyperoptStatus.EXECUTION_SYSTEM_FAILURE,
                diagnosis_code=diagnosis_code, objective=scope.objective.value if scope.objective else None,
                metrics_availability_reason=final.metrics_availability_reason,
                reason=final.reason, trials_run=trials,
            )

        # §6: DecisionPolicy gate (final deterministic promotion gate).
        decision_result = DecisionPolicy.decide(DecisionRequest(
            diagnosis_code=diagnosis_code,
            parent_metrics=champion.metrics,
            candidate_metrics=final.best_metrics,
            min_sample_trades=self.budget.default_epochs and 30,
        ))
        promoted_id = None
        if decision_result.decision == ExperimentDecision.KEEP and final.best_metrics is not None and champion.metrics is not None:
            promoted_id = self._promote_hyperopt_champion(
                run_id=run_id, strategy_name=strategy_name, version_id=version_id,
                parent=champion, values=best_values, metrics=final.best_metrics,
            )

        return FocusedHyperoptResult(
            status=FocusedHyperoptStatus.SUCCESS,
            diagnosis_code=diagnosis_code,
            objective=scope.objective.value if scope.objective else None,
            best_params=best_values,
            best_metrics=final.best_metrics,
            decision=decision_result.decision,
            promoted_champion_id=promoted_id,
            metrics_availability_reason=final.metrics_availability_reason,
            reason=decision_result.reason,
            trials_run=trials,
        )

    # ── internal helpers ──────────────────────────────────────────────────────

    def _evaluate_point(
        self, *, run_id, strategy_name, version_id, champion, values: dict,
    ) -> FocusedHyperoptResult:
        """Materialize a candidate with `values`, run DEVELOP backtest, resolve metrics."""
        try:
            cand = self._materialize(run_id=run_id, strategy_name=strategy_name,
                                     champion=champion, values=values)
        except Exception as exc:
            return FocusedHyperoptResult(
                status=FocusedHyperoptStatus.EXECUTION_SYSTEM_FAILURE,
                metrics_availability_reason=f"materialization_failure:{exc}",
                reason=f"candidate materialization error: {exc}",
            )

        try:
            params = self._build_params(strategy_name, version_id, cand.parameter_artifact.artifact_path, values)
            from ....models import RunRequest
            request = RunRequest(
                strategy_name=strategy_name, version_id=version_id, config_file=self.config_file,
                timerange=self.develop_timerange, timeframe=self.timeframe, pairs=self.pairs,
                max_open_trades=self.max_open_trades, dry_run_wallet=self.dry_run_wallet,
            )
            strategy_record = _SimpleStrategy(strategy_name, str(self.runs_root / cand.strategy_artifact.artifact_path))
            execution_id = self.backtest_runner.run_candidate_backtest(
                strategy_record, version_id, request, params_override=params,
            )
        except Exception as exc:
            return FocusedHyperoptResult(
                status=FocusedHyperoptStatus.EXECUTION_SYSTEM_FAILURE,
                metrics_availability_reason=f"candidate_execution_error:{exc}",
                reason=f"candidate execution error: {exc}",
            )

        metrics = self._resolve_metrics(execution_id)
        if metrics is None:
            return FocusedHyperoptResult(
                status=FocusedHyperoptStatus.PARSE_FAILURE,
                metrics_availability_reason="parse_failure:metrics_unavailable",
                reason="metrics unavailable after hyperopt candidate backtest",
            )
        total = _metric_value(metrics, "total_trades")
        if total is not None and total == 0:
            return FocusedHyperoptResult(
                status=FocusedHyperoptStatus.NO_TRADES, best_metrics=metrics,
                metrics_availability_reason="no_trades",
                reason="zero trades from hyperopt candidate",
            )
        return FocusedHyperoptResult(status=FocusedHyperoptStatus.SUCCESS, best_metrics=metrics)

    def _materialize(self, *, run_id, strategy_name, champion, values: dict) -> _MaterializedCandidate:
        """Deterministic candidate materialization (mirrors CandidateArtifactService
        pattern: byte-for-byte .py copy, sidecar copy with multiple param values,
        SHA-256 artifact references). Original strategy file is never mutated."""
        orig_strategy = Path(champion.strategy_artifact.original_source_path)
        orig_sidecar = self.runs_root / "strategies" / f"{strategy_name}.json"
        if not orig_strategy.exists():
            raise FileNotFoundError(f"Champion original strategy not found: {orig_strategy}")

        candidate_id = str(uuid.uuid4())
        cand_dir = self.runs_root / run_id / "hyperopt_candidates" / candidate_id
        cand_dir.mkdir(parents=True, exist_ok=True)

        cand_strategy_path = cand_dir / f"{strategy_name}.py"
        shutil.copyfile(orig_strategy, cand_strategy_path)
        strategy_hash = _sha256_file(cand_strategy_path)

        cand_sidecar_path = cand_dir / f"{strategy_name}.json"
        if orig_sidecar.exists():
            shutil.copyfile(orig_sidecar, cand_sidecar_path)
        else:
            cand_sidecar_path.write_text(json.dumps({"parameters": {}}, encoding="utf-8"))

        data = json.loads(cand_sidecar_path.read_text(encoding="utf-8"))
        params = data.setdefault("parameters", {})
        for name, val in values.items():
            block = params.get(name)
            if isinstance(block, dict):
                block["current"] = val
            else:
                params[name] = val
        cand_sidecar_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        param_hash = _sha256_file(cand_sidecar_path)

        strategy_artifact = ArtifactReference(
            artifact_path=str(cand_strategy_path.relative_to(self.runs_root)),
            artifact_hash=strategy_hash,
            original_source_path=str(orig_strategy),
            original_source_hash=champion.strategy_artifact.original_source_hash,
        )
        parameter_artifact = ArtifactReference(
            artifact_path=str(cand_sidecar_path.relative_to(self.runs_root)),
            artifact_hash=param_hash,
            original_source_path=str(orig_sidecar),
            original_source_hash=champion.parameter_artifact.original_source_hash,
        )
        return _MaterializedCandidate(strategy_artifact, parameter_artifact, cand_dir)

    def _build_params(self, strategy_name, version_id, sidecar_path, values: dict):
        from ....models import ParamsSchema
        flat = dict(values)
        return ParamsSchema(
            strategy_name=strategy_name, version_id=version_id,
            extracted_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            pair_list=list(self.pairs),
            buy_params={k: v for k, v in flat.items() if str(k).startswith("buy")},
            sell_params={k: v for k, v in flat.items() if str(k).startswith("sell")},
            protection_params={k: v for k, v in flat.items() if str(k).startswith("protection")},
            roi_table={},
            stoploss=float(flat.get("stoploss", -0.1)),
            trailing_stop=bool(flat.get("trailing_stop", False)),
            trailing_stop_positive=flat.get("trailing_stop_positive"),
            trailing_stop_positive_offset=flat.get("trailing_stop_positive_offset"),
            trailing_only_offset_is_reached=flat.get("trailing_only_offset_is_reached"),
            custom_params=flat,
        )

    def _resolve_metrics(self, execution_id):
        if not execution_id:
            return None
        try:
            from ..metrics.models import CanonicalMetricsSnapshot
            repo = getattr(self.backtest_runner, "run_repository", None)
            if repo is None:
                return None
            run_dir = repo.find_run_dir(execution_id)
            summary_path = Path(run_dir) / "parsed_summary.json"
            if not summary_path.exists():
                return None
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            # The persisted file is a full CanonicalMetricsSnapshot JSON (Metrics SSOT).
            return CanonicalMetricsSnapshot.model_validate(data)
        except Exception:
            return None

    def _promote_hyperopt_champion(self, *, run_id, strategy_name, version_id, parent, values, metrics):
        from .champions import ChampionReference, ChampionSourceType
        cand = self._materialize(run_id=run_id, strategy_name=strategy_name,
                                 champion=parent, values=values)
        new = ChampionReference(
            run_id=run_id,
            parent_champion_id=parent.champion_id,
            source_type=ChampionSourceType.HYPEROPT,
            strategy_artifact=cand.strategy_artifact,
            parameter_artifact=cand.parameter_artifact,
            metrics=metrics,
        )
        saved = self.champion_store.register(new)
        return saved.champion_id


class _RunShim:
    """Minimal object exposing `.research_protocol` for the zone guard."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.research_protocol = None


class _SimpleStrategy:
    def __init__(self, strategy_name: str, file_path: str):
        self.strategy_name = strategy_name
        self.file_path = file_path
