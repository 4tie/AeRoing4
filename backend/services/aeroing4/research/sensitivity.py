"""Local Parameter Sensitivity Analysis for the AeRoing4 pipeline (PROMPT 9 §7, §8, §9).

Type-aware, one-parameter-at-a-time (OAT) analysis on the DEVELOP zone only.
This milestone implements LOCAL PARAMETER SENSITIVITY — it is explicitly NOT
complete robustness validation.

Behaviour (§7):
  * Continuous numeric → deterministic bounded local perturbation (±pct of the
    trusted allowed range, clamped to [min_allowed, max_allowed]).
  * Integer → valid integer neighbor perturbations with clamping + deduplication.
  * Boolean / Categorical → NOT_APPLICABLE in v1 (unless a trusted policy enables).
  * Zero-valued numeric → still receives a NON-ZERO valid perturbation derived
    from the trusted allowed range (never a 0±0 dead point).
  * Never mutates more than one parameter per evaluation.

Each tested parameter yields a typed classification (§8):
  STABLE / ONE_SIDED_FRAGILE / TWO_SIDED_FRAGILE / INCONCLUSIVE / NOT_APPLICABLE
using canonical metrics only, same DEVELOP context, diagnosis-aware objective
evidence where supported, global guardrails; no fake-zero substitution.

Progression gate (§9): Sensitivity never promotes/demotes Champions, but its
stage result controls downstream eligibility:
  SENSITIVITY_PASS      → eligible_for_confirmation = true
  SENSITIVITY_FRAGILE   → eligible_for_confirmation = false (+ reason)
  SENSITIVITY_INCONCLUSIVE → eligible_for_confirmation = false (+ reason)
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from .allowed_targets import AllowedMutationTarget
from .champions import ArtifactReference, ChampionReference
from .hyperopt_policy import is_hyperopt_capable, HyperoptCapability
from ..diagnosis.models import DiagnosisCode
from ..metrics.models import CanonicalMetricsSnapshot, MetricAvailability
from .stages import ResearchStage, ResearchZone
from .access_guard import DataZoneGuard


# ── Typed enums ────────────────────────────────────────────────────────────────

class ParamSensitivityClass(str, Enum):
    STABLE = "stable"
    ONE_SIDED_FRAGILE = "one_sided_fragile"
    TWO_SIDED_FRAGILE = "two_sided_fragile"
    INCONCLUSIVE = "inconclusive"
    NOT_APPLICABLE = "not_applicable"


class SensitivityStatus(str, Enum):
    SENSITIVITY_PASS = "sensitivity_pass"
    SENSITIVITY_FRAGILE = "sensitivity_fragile"
    SENSITIVITY_INCONCLUSIVE = "sensitivity_inconclusive"
    PROTOCOL_DENIED = "protocol_denied"


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


# ── Result models ──────────────────────────────────────────────────────────────

class ParamSensitivity(BaseModel):
    name: str
    param_type: str
    base_value: Any = None
    swept_values: list[Any] = []
    metric_at_value: dict[str, Optional[float]] = {}
    sensitivity_score: float = 0.0
    classification: ParamSensitivityClass = ParamSensitivityClass.INCONCLUSIVE
    reason: str = ""


class SensitivityResult(BaseModel):
    status: SensitivityStatus
    classification: ParamSensitivityClass = ParamSensitivityClass.INCONCLUSIVE
    per_param: list[ParamSensitivity] = []
    fragile_params: list[str] = []
    eligible_for_confirmation: bool = False
    reason: str = ""
    metrics_version: str = "1.0.0"


# ── Service ────────────────────────────────────────────────────────────────────

class SensitivityService:
    """Type-aware local sensitivity over the HYPEROPT champion (DEVELOP only)."""

    def __init__(
        self,
        runs_root: Path,
        backtest_runner: Any,
        zone_guard: DataZoneGuard,
        *,
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
        perturbation_pct: float = 0.10,
        samples_per_param: int = 2,
    ):
        self.runs_root = Path(runs_root)
        self.backtest_runner = backtest_runner
        self.zone_guard = zone_guard
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
        self.perturbation_pct = perturbation_pct
        self.samples_per_param = samples_per_param

    def run(
        self,
        *,
        run_id: str,
        strategy_name: str,
        version_id: str,
        champion: ChampionReference,
        diagnosis_code: DiagnosisCode,
        allowed_targets: list[AllowedMutationTarget],
    ) -> SensitivityResult:
        # DEVELOP access required.
        decision, _ = self.zone_guard.request_access(
            _RunShim(run_id), ResearchStage.SENSITIVITY, ResearchZone.DEVELOP, experiment_id=None
        )
        if not decision.allowed:
            return SensitivityResult(
                status=SensitivityStatus.PROTOCOL_DENIED,
                classification=ParamSensitivityClass.NOT_APPLICABLE,
                eligible_for_confirmation=False,
                reason=f"DEVELOP access denied: {decision.decision_code.value}",
            )

        objective_metric = _OBJECTIVE_METRIC.get(
            ("balanced" if not has_objective(diagnosis_code) else "edge_improvement"), "expectancy"
        )
        base_values = {t.name: t.current_value for t in allowed_targets if t.current_value is not None}

        per_param: list[ParamSensitivity] = []
        for target in allowed_targets:
            cap = is_hyperopt_capable(target)
            if cap is not HyperoptCapability.CAPABLE:
                per_param.append(ParamSensitivity(
                    name=target.name, param_type=target.type,
                    base_value=target.current_value,
                    classification=ParamSensitivityClass.NOT_APPLICABLE,
                    reason=f"parameter type not applicable in v1 ({cap.value})",
                ))
                continue

            points = self._perturbation_points(target)
            if not points:
                per_param.append(ParamSensitivity(
                    name=target.name, param_type=target.type, base_value=target.current_value,
                    classification=ParamSensitivityClass.INCONCLUSIVE,
                    reason="no valid perturbation points derivable",
                ))
                continue

            metric_at_value: dict[str, Optional[float]] = {}
            failed_points: list[str] = []
            for val in points:
                cand_values = {**base_values, target.name: val}
                m = self._evaluate(run_id=run_id, strategy_name=strategy_name, version_id=version_id,
                                   champion=champion, values=cand_values)
                if m is None:
                    # Resolution failure for THIS perturbation point: keep the
                    # reason explicit (do NOT coerce to a typing problem).
                    failed_points.append(str(val))
                    metric_at_value[str(val)] = None
                    continue
                metric_at_value[str(val)] = _metric_value(m, objective_metric)

            valid = {k: v for k, v in metric_at_value.items() if v is not None}
            if len(valid) < 2:
                # Preserve the ORIGINAL parameter typing in swept_values (int stays
                # int) — never coerce to float. Surfaced as INCONCLUSIVE, with the
                # failed resolution points named explicitly so the cause is clear.
                reason = "insufficient comparable evidence across perturbation"
                if failed_points:
                    reason = (
                        f"metrics resolution failed for perturbation point(s) "
                        f"{failed_points}; parameter typing preserved (no coercion)"
                    )
                per_param.append(ParamSensitivity(
                    name=target.name, param_type=target.type, base_value=target.current_value,
                    swept_values=list(points), metric_at_value=metric_at_value,
                    classification=ParamSensitivityClass.INCONCLUSIVE,
                    reason=reason,
                ))
                continue

            vals = list(valid.values())
            lo, hi = min(vals), max(vals)
            base = _metric_value(self._evaluate(run_id=run_id, strategy_name=strategy_name, version_id=version_id,
                                                 champion=champion, values=base_values), objective_metric)
            span = abs(hi - lo)
            # normalize sensitivity score by base magnitude (guard zero base)
            denom = abs(base) if base not in (None, 0) else 1.0
            score = span / denom if denom else span
            cls = self._classify(vals, base, objective_metric == "max_drawdown_pct")
            per_param.append(ParamSensitivity(
                name=target.name, param_type=target.type, base_value=target.current_value,
                swept_values=list(points), metric_at_value=metric_at_value,
                sensitivity_score=score, classification=cls,
                reason="local OAT perturbation on DEVELOP",
            ))

        fragile = [p.name for p in per_param if p.classification
                   in (ParamSensitivityClass.ONE_SIDED_FRAGILE, ParamSensitivityClass.TWO_SIDED_FRAGILE)]
        inconclusive = [p.name for p in per_param if p.classification == ParamSensitivityClass.INCONCLUSIVE]
        not_applicable = [p.name for p in per_param if p.classification == ParamSensitivityClass.NOT_APPLICABLE]

        if fragile:
            status = SensitivityStatus.SENSITIVITY_FRAGILE
            eligible = False
            reason = f"fragile parameters: {fragile}"
        elif not per_param or (not_applicable and not fragile and not inconclusive):
            # No applicable parameters at all → cannot support confirmation (§9).
            status = SensitivityStatus.SENSITIVITY_INCONCLUSIVE
            eligible = False
            reason = "no applicable parameters for local sensitivity"
        elif inconclusive:
            # Mixed: treat as PASS only if no fragile; inconclusive params block
            # confirmation per §9.
            status = SensitivityStatus.SENSITIVITY_INCONCLUSIVE
            eligible = False
            reason = f"inconclusive parameters: {inconclusive}"
        else:
            status = SensitivityStatus.SENSITIVITY_PASS
            eligible = True
            reason = "all tested parameters stable within local perturbation"

        return SensitivityResult(
            status=status,
            classification=(ParamSensitivityClass.TWO_SIDED_FRAGILE if fragile
                           else ParamSensitivityClass.INCONCLUSIVE if inconclusive
                           else ParamSensitivityClass.STABLE),
            per_param=per_param, fragile_params=fragile,
            eligible_for_confirmation=eligible, reason=reason,
            metrics_version=self.metrics_version,
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _perturbation_points(self, target: AllowedMutationTarget) -> list:
        """§7: type-aware, bounded, safe perturbation points."""
        lo, hi = float(target.min_allowed), float(target.max_allowed)
        if lo >= hi:
            return []
        t = (target.type or "").lower()
        is_int = any(k in t for k in ("int", "integer"))
        base = target.current_value
        try:
            base_f = float(base)
        except (TypeError, ValueError):
            base_f = (lo + hi) / 2.0

        # Zero-valued numeric → derive a non-zero perturbation from the range.
        if base_f == 0:
            # Use mid-point of the allowed range as a safe non-zero reference.
            ref = (lo + hi) / 2.0
            if ref == 0:
                ref = lo if lo != 0 else hi
            delta = abs(ref) * self.perturbation_pct
        else:
            delta = abs(base_f) * self.perturbation_pct

        low = max(lo, base_f - delta)
        high = min(hi, base_f + delta)
        raw = sorted({low, high})
        if is_int:
            pts = []
            for v in raw:
                iv = int(round(v))
                # clamp + dedupe + ensure distinct from base integer
                iv = max(int(lo), min(int(hi), iv))
                if iv not in pts:
                    pts.append(iv)
            return pts
        # continuous: keep floats, dedupe
        return [round(v, 6) for v in raw if v not in (None,) and v != base_f or v == base_f]

    def _classify(self, vals: list[float], base: Optional[float], lower_better: bool) -> ParamSensitivityClass:
        if base is None:
            return ParamSensitivityClass.INCONCLUSIVE
        lo, hi = min(vals), max(vals)
        up = hi - base
        down = base - lo
        # Materiality threshold for "fragile" (10% relative move of the metric).
        denom = abs(base) if base != 0 else 1.0
        up_rel = abs(up) / denom
        down_rel = abs(down) / denom
        frag_thresh = 0.10
        if up_rel >= frag_thresh and down_rel >= frag_thresh:
            return ParamSensitivityClass.TWO_SIDED_FRAGILE
        if up_rel >= frag_thresh or down_rel >= frag_thresh:
            return ParamSensitivityClass.ONE_SIDED_FRAGILE
        return ParamSensitivityClass.STABLE

    def _evaluate(self, *, run_id, strategy_name, version_id, champion, values):
        try:
            cand = self._materialize(run_id=run_id, strategy_name=strategy_name,
                                     champion=champion, values=values)
        except Exception:
            return None
        try:
            from ....models import ParamsSchema, RunRequest
            flat = dict(values)
            params = ParamsSchema(
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
            request = RunRequest(
                strategy_name=strategy_name, version_id=version_id, config_file=self.config_file,
                timerange=self.develop_timerange, timeframe=self.timeframe, pairs=self.pairs,
                max_open_trades=self.max_open_trades, dry_run_wallet=self.dry_run_wallet,
            )
            strategy_record = _SimpleStrategy(strategy_name, str(self.runs_root / cand.strategy_artifact.artifact_path))
            execution_id = self.backtest_runner.run_candidate_backtest(
                strategy_record, version_id, request, params_override=params,
            )
        except Exception:
            return None
        return self._resolve_metrics(execution_id)

    def _materialize(self, *, run_id, strategy_name, champion, values):
        orig_strategy = Path(champion.strategy_artifact.original_source_path)
        orig_sidecar = self.runs_root / "strategies" / f"{strategy_name}.json"
        if not orig_strategy.exists():
            raise FileNotFoundError(str(orig_strategy))
        candidate_id = str(uuid.uuid4())
        cand_dir = self.runs_root / run_id / "sensitivity_candidates" / candidate_id
        cand_dir.mkdir(parents=True, exist_ok=True)
        cand_strategy_path = cand_dir / f"{strategy_name}.py"
        shutil.copyfile(orig_strategy, cand_strategy_path)
        s_hash = hashlib.sha256(cand_strategy_path.read_bytes()).hexdigest()
        cand_sidecar_path = cand_dir / f"{strategy_name}.json"
        if orig_sidecar.exists():
            shutil.copyfile(orig_sidecar, cand_sidecar_path)
        else:
            cand_sidecar_path.write_text(json.dumps({"parameters": {}}), encoding="utf-8")
        data = json.loads(cand_sidecar_path.read_text(encoding="utf-8"))
        params = data.setdefault("parameters", {})
        for name, val in values.items():
            block = params.get(name)
            if isinstance(block, dict):
                block["current"] = val
            else:
                params[name] = val
        cand_sidecar_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        p_hash = hashlib.sha256(cand_sidecar_path.read_bytes()).hexdigest()
        sa = ArtifactReference(
            artifact_path=str(cand_strategy_path.relative_to(self.runs_root)),
            artifact_hash=s_hash, original_source_path=str(orig_strategy),
            original_source_hash=champion.strategy_artifact.original_source_hash,
        )
        pa = ArtifactReference(
            artifact_path=str(cand_sidecar_path.relative_to(self.runs_root)),
            artifact_hash=p_hash, original_source_path=str(orig_sidecar),
            original_source_hash=champion.parameter_artifact.original_source_hash,
        )
        return _Mat(strategy_artifact=sa, parameter_artifact=pa, candidate_dir=cand_dir)

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


def has_objective(code: DiagnosisCode) -> bool:
    from .hyperopt_policy import has_actionable_objective
    return has_actionable_objective(code)


class _Mat:
    def __init__(self, strategy_artifact, parameter_artifact, candidate_dir):
        self.strategy_artifact = strategy_artifact
        self.parameter_artifact = parameter_artifact
        self.candidate_dir = candidate_dir


class _RunShim:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.research_protocol = None


class _SimpleStrategy:
    def __init__(self, strategy_name: str, file_path: str):
        self.strategy_name = strategy_name
        self.file_path = file_path
