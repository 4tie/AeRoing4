"""Final Unseen Evaluation for the AeRoing4 pipeline (PROMPT 11).

Architecture (reuse, don't rewrite — mirrors PROMPT 10 Confirmation):
    FinalUnseenService
      → BacktestRunner (EXISTING execution, frozen Champion params)
      → DataZoneGuard + AccessLedger (EXISTING FINAL_UNSEEN zone + audit)
      → ConfirmationResult (PROMPT 10, parent link)
      → ResearchProtocolState confirmation gate (must be PASS)
      → ChampionStore (READ-ONLY)

Cardinal rule: Final Unseen is TERMINAL evidence, not optimization.
    * no AI, no mutation, no Hyperopt, no repair, no sensitivity, no param change
    * no retry-on-performance, no tuning after the result

PROMPT 11 amendments (user-required):
    (1) Preflight (NON-DATA) check BEFORE request_access(FINAL_UNSEEN):
        freqtrade binary exists · config exists · champion artifacts exist ·
        params loadable · runner structurally invokable.
        If Freqtrade missing → BLOCKED / REAL_FREQTRADE_UNAVAILABLE,
        NO access request, NO ledger consumption, NO result.
    (2) No retry after consumption: once request_access + execution happened,
        any recorded result is terminal. Same-identity reuse happens ONLY
        BEFORE access and performs NO new execution.

Ordering (correction #5 + amendments):
    eligibility → verify frozen Champion hashes → verify Confirmation PASS identity
    → compute identity → reusable lookup (reuse if exists, NO access)
    → preflight (non-data) → request_access(FINAL_UNSEEN) → persist ledger
    → one execution only → Metrics SSOT → FinalUnseenPolicy
    → persist FinalUnseenResult (terminal) → update ResearchState summary
    → on PASS set delivery_eligible=true
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel

from .access_guard import DataZoneGuard
from .champions import ChampionReference, ChampionStore
from .confirmation import ConfirmationResult, ConfirmationStore
from .confirmation_policy import ConfirmationDecision
from .data_zones import ResearchZone, compute_boundary_hash
from .final_unseen_policy import (
    FINAL_UNSEEN_POLICY_VERSION,
    FinalUnseenDecision,
    FinalUnseenExecutionStatus,
    FinalUnseenPolicy,
)
from .stages import ResearchStage


class FinalUnseenResult(BaseModel):
    """Typed, persistent Final Unseen result (correction #1). Source of truth —
    not the ResearchState summary fields."""

    result_id: str
    run_id: str
    champion_id: str
    parent_confirmation_result_id: Optional[str] = None
    strategy_hash: str
    parameter_hash: str
    boundary_hash: str
    final_unseen_timerange: str
    configuration_hash: str
    protocol_version: str
    metrics_version: str
    final_unseen_policy_version: str
    access_ledger_entry_id: Optional[str] = None
    underlying_execution_id: Optional[str] = None
    canonical_metrics_snapshot: Optional[dict] = None
    metrics_snapshot_hash: Optional[str] = None
    execution_status: FinalUnseenExecutionStatus
    decision: Optional[FinalUnseenDecision] = None
    reason_codes: list[str] = []
    evaluated_at: datetime
    delivery_eligible: bool = False
    final_unseen_identity: str


class FinalUnseenStore:
    """Atomic, lock-guarded JSON store (one file per result, sibling to state.json)."""

    def __init__(self, runs_root: Path):
        self.runs_root = Path(runs_root)

    def _file(self, result_id: str) -> Path:
        return self.runs_root / "final_unseen" / f"{result_id}.json"

    def _index_file(self, run_id: str) -> Path:
        return self.runs_root / run_id / "final_unseen_index.json"

    def save(self, result: FinalUnseenResult) -> None:
        d = self._file(result.result_id)
        d.parent.mkdir(parents=True, exist_ok=True)
        tmp = d.with_suffix(".tmp")
        tmp.write_text(result.model_dump_json(), encoding="utf-8")
        tmp.replace(d)
        idx = self._index_file(result.run_id)
        idx.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if idx.exists():
            try:
                data = json.loads(idx.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data[result.final_unseen_identity] = result.result_id
        tmp = idx.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(idx)

    def load(self, result_id: str) -> Optional[FinalUnseenResult]:
        d = self._file(result_id)
        if not d.exists():
            return None
        return FinalUnseenResult.model_validate_json(d.read_text(encoding="utf-8"))

    def find_by_identity(self, run_id: str, identity: str) -> Optional[FinalUnseenResult]:
        idx = self._index_file(run_id)
        if not idx.exists():
            return None
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
        except Exception:
            return None
        rid = data.get(identity)
        return self.load(rid) if rid else None

    def latest_for_run(self, run_id: str) -> Optional[FinalUnseenResult]:
        idx = self._index_file(run_id)
        if not idx.exists():
            return None
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
        except Exception:
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


def compute_final_unseen_identity(
    *, champion_id, strategy_hash, parameter_hash, boundary_hash,
    configuration_hash, timeframe, pair_set, protocol_version,
    metrics_version, final_unseen_policy_version,
) -> str:
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
        "final_unseen_policy_version": final_unseen_policy_version,
    }, sort_keys=True)
    return _hash_str(canonical)


class _RunShim:
    def __init__(self, run_id: str):
        self.run_id = run_id


class FinalUnseenService:
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
        # Injection point for tests; default = REAL preflight (amendment #1).
        preflight_check: Optional[Callable[[], tuple[bool, str]]] = None,
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
        self.policy = FinalUnseenPolicy()
        self._preflight_check = preflight_check

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

    # ── preflight (NON-DATA) check (amendment #1) ─────────────────────────────

    def _real_preflight(self) -> tuple[bool, str]:
        """Structural environment checks that must pass BEFORE consuming the
        FINAL_UNSEEN zone. No data is touched here."""
        if shutil.which("freqtrade") is None:
            return False, "REAL_FREQTRADE_UNAVAILABLE"
        if not Path(self.config_file).exists():
            return False, "config_missing"
        if not (self.champion_store is not None):
            return False, "champion_store_missing"
        return True, "preflight_ok"

    def _preflight(self) -> tuple[bool, str]:
        if self._preflight_check is not None:
            return self._preflight_check()
        return self._real_preflight()

    # ── eligibility gate (strict, typed) ──────────────────────────────────────

    def check_eligibility(
        self, *, run_id, state_store, champion, confirmation_result,
        protocol_confirmation_passed, eligible_for_confirmation, strategy_hash,
        parameter_hash, champion_strategy_hash, champion_parameter_hash,
        paused=False,
    ) -> tuple[bool, str, FinalUnseenExecutionStatus]:
        if confirmation_result is None:
            return False, "no ConfirmationResult", FinalUnseenExecutionStatus.SKIPPED
        if confirmation_result.decision != ConfirmationDecision.PASS:
            return False, "Confirmation decision != PASS", FinalUnseenExecutionStatus.BLOCKED
        if not protocol_confirmation_passed:
            return False, "ResearchProtocolState.confirmation_passed is false", FinalUnseenExecutionStatus.BLOCKED
        if champion is None:
            return False, "no current Champion", FinalUnseenExecutionStatus.BLOCKED
        if not eligible_for_confirmation:
            return False, "Sensitivity was not PASS (eligible_for_confirmation was false)", FinalUnseenExecutionStatus.BLOCKED
        # Frozen-context integrity: confirmed hashes must match the live Champion.
        if strategy_hash != champion_strategy_hash:
            return False, "strategy hash differs from confirmed Champion", FinalUnseenExecutionStatus.BLOCKED
        if parameter_hash != champion_parameter_hash:
            return False, "parameter hash differs from confirmed Champion", FinalUnseenExecutionStatus.BLOCKED
        if paused:
            return False, "unresolved PAUSED state", FinalUnseenExecutionStatus.BLOCKED
        return True, "eligible", FinalUnseenExecutionStatus.COMPLETED

    # ── metrics resolution (Metrics SSOT) ─────────────────────────────────────

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
        confirmation_result: Optional[ConfirmationResult], protocol_confirmation_passed: bool,
        eligible_for_confirmation: bool, state_store=None,
        strategy_hash: Optional[str] = None, parameter_hash: Optional[str] = None,
        paused: bool = False,
    ) -> FinalUnseenResult:
        now = datetime.now(UTC)
        trusted_strategy_hash = strategy_hash if strategy_hash is not None else (
            champion.strategy_artifact.artifact_hash if champion.strategy_artifact else None)
        trusted_parameter_hash = parameter_hash if parameter_hash is not None else (
            champion.parameter_artifact.artifact_hash if champion.parameter_artifact else None)
        champ_strategy_hash = champion.strategy_artifact.artifact_hash if champion.strategy_artifact else None
        champ_parameter_hash = champion.parameter_artifact.artifact_hash if champion.parameter_artifact else None

        # 1) Eligibility gate
        ok, reason, status = self.check_eligibility(
            run_id=run_id, state_store=state_store, champion=champion,
            confirmation_result=confirmation_result,
            protocol_confirmation_passed=protocol_confirmation_passed,
            eligible_for_confirmation=eligible_for_confirmation,
            strategy_hash=trusted_strategy_hash, parameter_hash=trusted_parameter_hash,
            champion_strategy_hash=champ_strategy_hash, champion_parameter_hash=champ_parameter_hash,
            paused=paused,
        )
        if not ok:
            return FinalUnseenResult(
                result_id=str(uuid.uuid4()), run_id=run_id,
                champion_id=champion.champion_id if champion else "?",
                parent_confirmation_result_id=confirmation_result.result_id if confirmation_result else None,
                strategy_hash=trusted_strategy_hash or "", parameter_hash=trusted_parameter_hash or "",
                boundary_hash=self._boundary_hash(), final_unseen_timerange=self.final_unseen_timerange,
                configuration_hash=self._configuration_hash(), protocol_version=self.protocol_version,
                metrics_version=self.metrics_version, final_unseen_policy_version=FINAL_UNSEEN_POLICY_VERSION,
                execution_status=status, decision=None, reason_codes=[reason], evaluated_at=now,
                delivery_eligible=False, final_unseen_identity="",
            )

        # 2) compute deterministic identity
        identity = compute_final_unseen_identity(
            champion_id=champion.champion_id, strategy_hash=trusted_strategy_hash,
            parameter_hash=trusted_parameter_hash, boundary_hash=self._boundary_hash(),
            configuration_hash=self._configuration_hash(), timeframe=self.timeframe,
            pair_set=self.pairs, protocol_version=self.protocol_version,
            metrics_version=self.metrics_version, final_unseen_policy_version=FINAL_UNSEEN_POLICY_VERSION,
        )

        # 3) REUSE before access (no new execution, no ledger consumption)
        store = FinalUnseenStore(self.runs_root)
        existing = store.find_by_identity(run_id, identity)
        if existing is not None:
            return existing

        # 4) Preflight (NON-DATA) — if Freqtrade/env missing, BLOCKED, NO access,
        #    NO ledger consumption, NO result (amendment #1).
        pf_ok, pf_reason = self._preflight()
        if not pf_ok:
            return FinalUnseenResult(
                result_id=str(uuid.uuid4()), run_id=run_id,
                champion_id=champion.champion_id,
                parent_confirmation_result_id=confirmation_result.result_id if confirmation_result else None,
                strategy_hash=trusted_strategy_hash or "", parameter_hash=trusted_parameter_hash or "",
                boundary_hash=self._boundary_hash(), final_unseen_timerange=self.final_unseen_timerange,
                configuration_hash=self._configuration_hash(), protocol_version=self.protocol_version,
                metrics_version=self.metrics_version, final_unseen_policy_version=FINAL_UNSEEN_POLICY_VERSION,
                execution_status=FinalUnseenExecutionStatus.BLOCKED,
                decision=None, reason_codes=[f"preflight_failed:{pf_reason}"],
                evaluated_at=now, delivery_eligible=False, final_unseen_identity=identity,
            )

        # 5) FINAL_UNSEEN zone access
        decision, _ = self.zone_guard.request_access(
            _RunShim(run_id), ResearchStage.FINAL_UNSEEN, ResearchZone.FINAL_UNSEEN, experiment_id=None,
        )
        access_ledger_entry_id = getattr(decision, "decision_code", None)
        if not decision.allowed:
            return FinalUnseenResult(
                result_id=str(uuid.uuid4()), run_id=run_id, champion_id=champion.champion_id,
                parent_confirmation_result_id=confirmation_result.result_id if confirmation_result else None,
                strategy_hash=trusted_strategy_hash or "", parameter_hash=trusted_parameter_hash or "",
                boundary_hash=self._boundary_hash(), final_unseen_timerange=self.final_unseen_timerange,
                configuration_hash=self._configuration_hash(), protocol_version=self.protocol_version,
                metrics_version=self.metrics_version, final_unseen_policy_version=FINAL_UNSEEN_POLICY_VERSION,
                access_ledger_entry_id=access_ledger_entry_id.value if access_ledger_entry_id else None,
                execution_status=FinalUnseenExecutionStatus.PROTOCOL_DENIED, decision=None,
                reason_codes=[f"FINAL_UNSEEN access denied: {decision.decision_code.value}"],
                evaluated_at=now, delivery_eligible=False, final_unseen_identity=identity,
            )

        # 6) ONE execution only — exact frozen Champion on FINAL_UNSEEN zone
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
                timerange=self.final_unseen_timerange, timeframe=self.timeframe, pairs=self.pairs,
                max_open_trades=self.max_open_trades, dry_run_wallet=self.dry_run_wallet,
            )
            strategy_record = _SimpleStrategy(strategy_name, str(self.runs_root / champion.strategy_artifact.artifact_path))
            execution_id = self.backtest_runner.run_candidate_backtest(
                strategy_record, version_id, request, params_override=p_schema,
            )
        except Exception as exc:
            # TERMINAL system failure after execution started — NOT INCONCLUSIVE.
            return FinalUnseenResult(
                result_id=str(uuid.uuid4()), run_id=run_id, champion_id=champion.champion_id,
                parent_confirmation_result_id=confirmation_result.result_id if confirmation_result else None,
                strategy_hash=trusted_strategy_hash or "", parameter_hash=trusted_parameter_hash or "",
                boundary_hash=self._boundary_hash(), final_unseen_timerange=self.final_unseen_timerange,
                configuration_hash=self._configuration_hash(), protocol_version=self.protocol_version,
                metrics_version=self.metrics_version, final_unseen_policy_version=FINAL_UNSEEN_POLICY_VERSION,
                execution_status=FinalUnseenExecutionStatus.EXECUTION_SYSTEM_FAILURE, decision=None,
                reason_codes=[f"candidate_execution_error:{exc}"], evaluated_at=now,
                delivery_eligible=False, final_unseen_identity=identity,
            )

        metrics = self._resolve_metrics(execution_id)
        if metrics is None:
            return FinalUnseenResult(
                result_id=str(uuid.uuid4()), run_id=run_id, champion_id=champion.champion_id,
                parent_confirmation_result_id=confirmation_result.result_id if confirmation_result else None,
                strategy_hash=trusted_strategy_hash or "", parameter_hash=trusted_parameter_hash or "",
                boundary_hash=self._boundary_hash(), final_unseen_timerange=self.final_unseen_timerange,
                configuration_hash=self._configuration_hash(), protocol_version=self.protocol_version,
                metrics_version=self.metrics_version, final_unseen_policy_version=FINAL_UNSEEN_POLICY_VERSION,
                execution_status=FinalUnseenExecutionStatus.EXECUTION_SYSTEM_FAILURE, decision=None,
                reason_codes=["parse_failure:metrics_unavailable"], evaluated_at=now,
                delivery_eligible=False, final_unseen_identity=identity,
            )

        # 7) FinalUnseenPolicy (absolute OOS gate)
        decision_enum, reason_codes = self.policy.evaluate(metrics, self.timeframe)
        snap = json.loads(metrics.model_dump_json())
        metrics_hash = _hash_str(metrics.model_dump_json())
        delivery_eligible = decision_enum == FinalUnseenDecision.PASS

        # 8) persist terminal result (no retry)
        result = FinalUnseenResult(
            result_id=str(uuid.uuid4()), run_id=run_id, champion_id=champion.champion_id,
            parent_confirmation_result_id=confirmation_result.result_id if confirmation_result else None,
            strategy_hash=trusted_strategy_hash or "", parameter_hash=trusted_parameter_hash or "",
            boundary_hash=self._boundary_hash(), final_unseen_timerange=self.final_unseen_timerange,
            configuration_hash=self._configuration_hash(), protocol_version=self.protocol_version,
            metrics_version=self.metrics_version, final_unseen_policy_version=FINAL_UNSEEN_POLICY_VERSION,
            access_ledger_entry_id=access_ledger_entry_id.value if access_ledger_entry_id else None,
            underlying_execution_id=execution_id, canonical_metrics_snapshot=snap,
            metrics_snapshot_hash=metrics_hash, execution_status=FinalUnseenExecutionStatus.COMPLETED,
            decision=decision_enum, reason_codes=reason_codes, evaluated_at=now,
            delivery_eligible=delivery_eligible, final_unseen_identity=identity,
        )
        store.save(result)

        # 9) update ResearchState summary (summary only)
        if state_store is not None and hasattr(state_store, "load"):
            st = state_store.load(run_id)
            if st is not None:
                st.final_unseen_status = decision_enum.value if decision_enum else "completed"
                st.latest_final_unseen_result_id = result.result_id
                st.delivery_eligible = delivery_eligible
                state_store.save(st)

        return result


class _SimpleStrategy:
    def __init__(self, strategy_name: str, file_path: str):
        self.strategy_name = strategy_name
        self.file_path = file_path
