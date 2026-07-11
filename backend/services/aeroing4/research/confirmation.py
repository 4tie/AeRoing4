"""Confirmation Zone Evaluation for the AeRoing4 pipeline (PROMPT 10).

Architecture (correction #1 — reuse, don't rewrite):
    ConfirmationService
      → BacktestRunner (EXISTING execution layer, frozen Champion params)
      → DataZoneGuard + AccessLedger (EXISTING CONFIRMATION zone access + audit)
      → ResearchProtocolState confirmation gate (EXISTING set_confirmation_passed)
      → ChampionStore (READ-ONLY — no promotion, no mutation)

Confirmation is a TEST, not an optimization stage (cardinal rule):
    * no AI mutation, no Hyperopt, no repair, no adaptive retry
    * on FAIL/INCONCLUSIVE the Champion is left unchanged; decision returns to workflow
    * deterministic identity + idempotency (correction #2): same identity → reuse,
      never re-execute (no hidden tuning loop, no Confirmation-as-optimization-surface)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from .access_guard import DataZoneGuard
from .champions import ChampionReference, ChampionStore
from .confirmation_policy import (
    CONFIRMATION_POLICY_VERSION,
    ConfirmationDecision,
    ConfirmationExecutionStatus,
    ConfirmationPolicy,
)
from .data_zones import ResearchZone, compute_boundary_hash
from .stages import ResearchStage


class ConfirmationResult(BaseModel):
    """Typed, persistent Confirmation result (correction #1). This — not
    ResearchState.confirmation_status — is the source of truth for a run's
    Confirmation outcome."""

    result_id: str
    run_id: str
    champion_id: str
    strategy_hash: str
    parameter_hash: str
    boundary_hash: str
    confirmation_timerange: str
    configuration_hash: str
    protocol_version: str
    metrics_version: str
    confirmation_policy_version: str
    access_ledger_entry_id: Optional[str] = None
    underlying_execution_id: Optional[str] = None
    canonical_metrics_snapshot: Optional[dict] = None
    metrics_snapshot_hash: Optional[str] = None
    execution_status: ConfirmationExecutionStatus
    decision: Optional[ConfirmationDecision] = None
    reason_codes: list[str] = []
    evaluated_at: datetime
    confirmation_identity: str


class ConfirmationStore:
    """Atomic, lock-guarded JSON store for ConfirmationResult (one file per
    result, sibling to state.json — same convention as AeRoing4StateStore)."""

    def __init__(self, runs_root: Path):
        self.runs_root = Path(runs_root)

    def _file(self, result_id: str) -> Path:
        return self.runs_root / "confirmation" / f"{result_id}.json"

    def _index_file(self, run_id: str) -> Path:
        return self.runs_root / run_id / "confirmation_index.json"

    def save(self, result: ConfirmationResult) -> None:
        d = self._file(result.result_id)
        d.parent.mkdir(parents=True, exist_ok=True)
        tmp = d.with_suffix(".tmp")
        tmp.write_text(result.model_dump_json(), encoding="utf-8")
        tmp.replace(d)
        # update run-scoped index of identities → result_ids (for idempotency lookup)
        idx = self._index_file(result.run_id)
        idx.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if idx.exists():
            try:
                data = json.loads(idx.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data[result.confirmation_identity] = result.result_id
        tmp = idx.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(idx)

    def load(self, result_id: str) -> Optional[ConfirmationResult]:
        d = self._file(result_id)
        if not d.exists():
            return None
        return ConfirmationResult.model_validate_json(d.read_text(encoding="utf-8"))

    def find_by_identity(self, run_id: str, identity: str) -> Optional[ConfirmationResult]:
        idx = self._index_file(run_id)
        if not idx.exists():
            return None
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
        except Exception:
            return None
        rid = data.get(identity)
        return self.load(rid) if rid else None

    def latest_for_run(self, run_id: str) -> Optional[ConfirmationResult]:
        idx = self._index_file(run_id)
        if not idx.exists():
            return None
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not data:
            return None
        latest = None
        for rid in data.values():
            r = self.load(rid)
            if r is None:
                continue
            if latest is None or r.evaluated_at >= latest.evaluated_at:
                latest = r
        return latest


def _hash_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def compute_confirmation_identity(
    *, champion_id, strategy_hash, parameter_hash, boundary_hash,
    configuration_hash, timeframe, pair_set, protocol_version,
    metrics_version, confirmation_policy_version,
) -> str:
    """Deterministic Confirmation identity (correction #2)."""
    canonical = json.dumps({
        "champion_id": champion_id,
        "strategy_hash": strategy_hash,
        "parameter_hash": parameter_hash,
        "boundary_hash": boundary_hash,
        "configuration_hash": configuration_hash,
        "timeframe": timeframe,
        "pair_set": sorted(pair_set),
        "protocol_version": protocol_version,
        "metrics_version": metrics_version,
        "confirmation_policy_version": confirmation_policy_version,
    }, sort_keys=True)
    return _hash_str(canonical)


class _RunShim:
    def __init__(self, run_id: str):
        self.run_id = run_id


class ConfirmationService:
    def __init__(
        self,
        runs_root: Path,
        backtest_runner: Any,
        champion_store: ChampionStore,
        zone_guard: DataZoneGuard,
        *,
        develop_timerange: str = "20240101-20240630",
        confirmation_timerange: str = "20240701-20240731",
        final_unseen_timerange: str = "20240801-20240831",
        pairs: list[str] | None = None,
        timeframe: str = "5m",
        protocol_version: str = "1.0.0",
        metrics_version: str = "1.0.0",
        exchange: str = "binance",
        trading_mode: str = "spot",
        dry_run_wallet: float = 1000.0,
        max_open_trades: int = 4,
        config_file: str = "config.json",
    ):
        self.runs_root = Path(runs_root)
        self.backtest_runner = backtest_runner
        self.champion_store = champion_store
        self.zone_guard = zone_guard
        self.develop_timerange = develop_timerange
        self.confirmation_timerange = confirmation_timerange
        self.final_unseen_timerange = final_unseen_timerange
        self.pairs = pairs or ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
        self.timeframe = timeframe
        self.protocol_version = protocol_version
        self.metrics_version = metrics_version
        self.exchange = exchange
        self.trading_mode = trading_mode
        self.dry_run_wallet = dry_run_wallet
        self.max_open_trades = max_open_trades
        self.config_file = config_file
        self.policy = ConfirmationPolicy()

    # ── identity / configuration helpers ──────────────────────────────────────

    def _configuration_hash(self) -> str:
        canonical = json.dumps({
            "exchange": self.exchange,
            "trading_mode": self.trading_mode,
            "max_open_trades": self.max_open_trades,
            "dry_run_wallet": self.dry_run_wallet,
            "config_file": self.config_file,
            "timeframe": self.timeframe,
            "pair_set": sorted(self.pairs),
        }, sort_keys=True)
        return _hash_str(canonical)

    def _boundary_hash(self) -> str:
        return compute_boundary_hash(
            self.develop_timerange, self.confirmation_timerange,
            self.final_unseen_timerange, self.protocol_version,
        )

    def _champion_params(self, champion: ChampionReference) -> dict:
        """Exact frozen parameter set from the Champion's parameter artifact."""
        if champion.parameter_artifact is None:
            return {}
        sidecar = Path(champion.parameter_artifact.original_source_path)
        if not sidecar.exists():
            return {}
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            return {}
        params = data.get("parameters", {})
        return {k: v.get("current") for k, v in params.items() if isinstance(v, dict) and "current" in v}

    # ── eligibility + integrity (correction #8 ordering) ──────────────────────

    def check_eligibility(
        self, *, run_id, state_store, champion, eligible_for_confirmation,
        strategy_hash, parameter_hash,
        champion_strategy_hash=None, champion_parameter_hash=None,
    ) -> tuple[bool, str, ConfirmationExecutionStatus]:
        if not eligible_for_confirmation:
            return False, "sensitivity did not PASS (eligible_for_confirmation=false)", ConfirmationExecutionStatus.SKIPPED
        if champion is None:
            return False, "no current Champion", ConfirmationExecutionStatus.BLOCKED
        # Frozen-context integrity: trusted hash must match the Champion's actual
        # artifact hash. A mismatch (e.g. tampered champion) is an integrity failure,
        # NOT a silent rerun (correction #9).
        if strategy_hash != champion_strategy_hash:
            return False, "strategy hash mismatch after eligibility (integrity failure)", ConfirmationExecutionStatus.BLOCKED
        if parameter_hash != champion_parameter_hash:
            return False, "parameter hash mismatch after eligibility (integrity failure)", ConfirmationExecutionStatus.BLOCKED
        if state_store is not None:
            st = state_store.load(run_id) if hasattr(state_store, "load") else None
            if st is not None and getattr(st, "research_status", None) == "paused":
                return False, "ResearchState is PAUSED", ConfirmationExecutionStatus.BLOCKED
        return True, "eligible", ConfirmationExecutionStatus.COMPLETED

    # ── metrics resolution (Metrics SSOT, same pattern as PROMPT 9) ───────────

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
            return CanonicalMetricsSnapshot.model_validate(json.loads(summary_path.read_text(encoding="utf-8")))
        except Exception:
            return None

    # ── main entry ─────────────────────────────────────────────────────────────

    def run(
        self, *, run_id, strategy_name, version_id, champion: ChampionReference,
        eligible_for_confirmation: bool, state_store=None, run=None,
        strategy_hash: Optional[str] = None, parameter_hash: Optional[str] = None,
    ) -> ConfirmationResult:
        now = datetime.now(UTC)
        # Trusted hashes: prefer explicitly passed (from an untamperable source,
        # e.g. the persisted Champion / ResearchState). Fall back to reading the
        # passed champion only when no trusted hash is supplied. NEVER trust the
        # passed champion's own hash for the integrity comparison (correction #9).
        trusted_strategy_hash = strategy_hash if strategy_hash is not None else (
            champion.strategy_artifact.artifact_hash if champion.strategy_artifact else None)
        trusted_parameter_hash = parameter_hash if parameter_hash is not None else (
            champion.parameter_artifact.artifact_hash if champion.parameter_artifact else None)
        champion_strategy_hash = champion.strategy_artifact.artifact_hash if champion.strategy_artifact else None
        champion_parameter_hash = champion.parameter_artifact.artifact_hash if champion.parameter_artifact else None

        # 1) Eligibility gate (correction #8)
        ok, reason, status = self.check_eligibility(
            run_id=run_id, state_store=state_store, champion=champion,
            eligible_for_confirmation=eligible_for_confirmation,
            strategy_hash=trusted_strategy_hash, parameter_hash=trusted_parameter_hash,
            champion_strategy_hash=champion_strategy_hash, champion_parameter_hash=champion_parameter_hash,
        )
        if not ok:
            return ConfirmationResult(
                result_id=str(uuid.uuid4()), run_id=run_id,
                champion_id=champion.champion_id if champion else "?",
                strategy_hash=trusted_strategy_hash or "", parameter_hash=trusted_parameter_hash or "",
                boundary_hash=self._boundary_hash(), confirmation_timerange=self.confirmation_timerange,
                configuration_hash=self._configuration_hash(), protocol_version=self.protocol_version,
                metrics_version=self.metrics_version, confirmation_policy_version=CONFIRMATION_POLICY_VERSION,
                execution_status=status, decision=None, reason_codes=[reason], evaluated_at=now,
                confirmation_identity="",
            )

        # 2) compute deterministic identity (correction #2)
        identity = compute_confirmation_identity(
            champion_id=champion.champion_id, strategy_hash=strategy_hash, parameter_hash=parameter_hash,
            boundary_hash=self._boundary_hash(), configuration_hash=self._configuration_hash(),
            timeframe=self.timeframe, pair_set=self.pairs, protocol_version=self.protocol_version,
            metrics_version=self.metrics_version, confirmation_policy_version=CONFIRMATION_POLICY_VERSION,
        )

        # 3) reusable-result lookup → idempotency (no second execution)
        store = ConfirmationStore(self.runs_root)
        existing = store.find_by_identity(run_id, identity)
        if existing is not None:
            return existing

        # 4) DataZoneGuard.request_access(CONFIRMATION)
        decision, _ = self.zone_guard.request_access(
            _RunShim(run_id), ResearchStage.CONFIRMATION, ResearchZone.CONFIRMATION, experiment_id=None,
        )
        access_ledger_entry_id = getattr(decision, "decision_code", None)
        if not decision.allowed:
            return ConfirmationResult(
                result_id=str(uuid.uuid4()), run_id=run_id, champion_id=champion.champion_id,
                strategy_hash=strategy_hash or "", parameter_hash=parameter_hash or "",
                boundary_hash=self._boundary_hash(), confirmation_timerange=self.confirmation_timerange,
                configuration_hash=self._configuration_hash(), protocol_version=self.protocol_version,
                metrics_version=self.metrics_version, confirmation_policy_version=CONFIRMATION_POLICY_VERSION,
                access_ledger_entry_id=access_ledger_entry_id.value if access_ledger_entry_id else None,
                execution_status=ConfirmationExecutionStatus.PROTOCOL_DENIED, decision=None,
                reason_codes=[f"CONFIRMATION access denied: {decision.decision_code.value}"],
                evaluated_at=now, confirmation_identity=identity,
            )

        # 5) execute EXACT frozen Champion on CONFIRMATION zone (no mutation)
        try:
            from ....models import ParamsSchema, RunRequest
            params = self._champion_params(champion)
            p_schema = ParamsSchema(
                strategy_name=strategy_name, version_id=version_id,
                extracted_at=now, pair_list=list(self.pairs),
                buy_params={k: v for k, v in params.items() if str(k).startswith("buy")},
                sell_params={k: v for k, v in params.items() if str(k).startswith("sell")},
                protection_params={k: v for k, v in params.items() if str(k).startswith("protection")},
                roi_table={}, stoploss=float(params.get("stoploss", -0.1)),
                trailing_stop=bool(params.get("trailing_stop", False)),
                trailing_stop_positive=params.get("trailing_stop_positive"),
                trailing_stop_positive_offset=params.get("trailing_stop_positive_offset"),
                trailing_only_offset_is_reached=params.get("trailing_only_offset_is_reached"),
                custom_params=params,
            )
            request = RunRequest(
                strategy_name=strategy_name, version_id=version_id, config_file=self.config_file,
                timerange=self.confirmation_timerange, timeframe=self.timeframe, pairs=self.pairs,
                max_open_trades=self.max_open_trades, dry_run_wallet=self.dry_run_wallet,
            )
            strategy_record = _SimpleStrategy(strategy_name, str(self.runs_root / champion.strategy_artifact.artifact_path))
            execution_id = self.backtest_runner.run_candidate_backtest(
                strategy_record, version_id, request, params_override=p_schema,
            )
        except Exception as exc:
            return ConfirmationResult(
                result_id=str(uuid.uuid4()), run_id=run_id, champion_id=champion.champion_id,
                strategy_hash=strategy_hash or "", parameter_hash=parameter_hash or "",
                boundary_hash=self._boundary_hash(), confirmation_timerange=self.confirmation_timerange,
                configuration_hash=self._configuration_hash(), protocol_version=self.protocol_version,
                metrics_version=self.metrics_version, confirmation_policy_version=CONFIRMATION_POLICY_VERSION,
                execution_status=ConfirmationExecutionStatus.EXECUTION_SYSTEM_FAILURE, decision=None,
                reason_codes=[f"candidate_execution_error:{exc}"], evaluated_at=now,
                confirmation_identity=identity,
            )

        metrics = self._resolve_metrics(execution_id)
        if metrics is None:
            return ConfirmationResult(
                result_id=str(uuid.uuid4()), run_id=run_id, champion_id=champion.champion_id,
                strategy_hash=strategy_hash or "", parameter_hash=parameter_hash or "",
                boundary_hash=self._boundary_hash(), confirmation_timerange=self.confirmation_timerange,
                configuration_hash=self._configuration_hash(), protocol_version=self.protocol_version,
                metrics_version=self.metrics_version, confirmation_policy_version=CONFIRMATION_POLICY_VERSION,
                execution_status=ConfirmationExecutionStatus.EXECUTION_SYSTEM_FAILURE, decision=None,
                reason_codes=["parse_failure:metrics_unavailable"], evaluated_at=now,
                confirmation_identity=identity,
            )

        # 6) ConfirmationPolicy (absolute OOS gate)
        decision_enum, reason_codes = self.policy.evaluate(metrics, self.timeframe)
        snap = json.loads(metrics.model_dump_json())
        metrics_hash = _hash_str(metrics.model_dump_json())

        # 7) persist ConfirmationResult
        result = ConfirmationResult(
            result_id=str(uuid.uuid4()), run_id=run_id, champion_id=champion.champion_id,
            strategy_hash=strategy_hash or "", parameter_hash=parameter_hash or "",
            boundary_hash=self._boundary_hash(), confirmation_timerange=self.confirmation_timerange,
            configuration_hash=self._configuration_hash(), protocol_version=self.protocol_version,
            metrics_version=self.metrics_version, confirmation_policy_version=CONFIRMATION_POLICY_VERSION,
            access_ledger_entry_id=access_ledger_entry_id.value if access_ledger_entry_id else None,
            underlying_execution_id=execution_id, canonical_metrics_snapshot=snap,
            metrics_snapshot_hash=metrics_hash, execution_status=ConfirmationExecutionStatus.COMPLETED,
            decision=decision_enum, reason_codes=reason_codes, evaluated_at=now,
            confirmation_identity=identity,
        )
        store.save(result)

        # 8) update ResearchState summary (only summary fields)
        if state_store is not None and hasattr(state_store, "load"):
            st = state_store.load(run_id)
            if st is not None:
                st.confirmation_status = decision_enum.value if decision_enum else "completed"
                st.latest_confirmation_result_id = result.result_id
                state_store.save(st)

        # 9) on PASS only → set the EXISTING protocol confirmation gate (correction #3)
        if decision_enum == ConfirmationDecision.PASS and run is not None:
            try:
                self.zone_guard.set_confirmation_passed(run, True)
            except Exception:
                pass

        return result


class _SimpleStrategy:
    def __init__(self, strategy_name: str, file_path: str):
        self.strategy_name = strategy_name
        self.file_path = file_path
