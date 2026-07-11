"""Candidate Executor for the AeRoing4 Controlled Research Loop.

Reuses the EXISTING BacktestRunner — no new execution engine. The executor:
  * freezes the Parent Champion research context (pairs, timeframe, DEVELOP
    timerange, exchange, trading mode, wallet/stake, max_open_trades, config
    identity, protocol version, metrics version). Only the approved mutation
    differs.
  * builds a ParamsSchema from the candidate's mutated sidecar and runs it via
    the internal ``BacktestRunner.run_candidate_backtest`` (params_override),
    so the champion's accepted version is NOT mutated.
  * returns a typed CandidateExecutionResult with the underlying execution id,
    status, artifact references, and a CanonicalMetricsSnapshot resolved from
    the backtest result via the existing metrics adapter. It does NOT compute
    metrics locally.

The BacktestRunner is injected so tests can use a fake that returns a
deterministic result without invoking Freqtrade.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from types import SimpleNamespace

from pydantic import BaseModel, Field

from .champions import ChampionReference
from .experiments import ExactChange
from ..metrics.adapters import from_parsed_summary
from ..metrics.models import CanonicalMetricsSnapshot


class CandidateExecutionStatus(str, Enum):
    SUCCESS = "success"
    EXECUTION_FAILURE = "execution_failure"   # freqtrade non-zero / no raw_result
    PARSE_FAILURE = "parse_failure"
    NO_TRADES = "no_trades"
    SYSTEM_FAILURE = "system_failure"


class CandidateExecutionResult(BaseModel):
    """Typed result of one candidate execution (not persisted here)."""

    underlying_execution_id: Optional[str] = None
    status: CandidateExecutionStatus
    candidate_dir: str
    artifacts: dict[str, str] = Field(default_factory=dict)
    metrics: Optional[CanonicalMetricsSnapshot] = None
    failure_classification: Optional[str] = None


class CandidateExecutor:
    """Runs a candidate through the existing BacktestRunner on the DEVELOP zone."""

    def __init__(self, runs_root: Path, backtest_runner: Any):
        self.runs_root = Path(runs_root)
        self.backtest_runner = backtest_runner

    def execute(
        self,
        *,
        run_id: str,
        strategy_name: str,
        version_id: str,
        champion: ChampionReference,
        candidate_artifact_result: Any,  # CandidateArtifactResult
        exact_change: ExactChange,
        develop_timerange: str,
        pairs: list[str],
        timeframe: str,
        exchange: str = "binance",
        trading_mode: str = "spot",
        dry_run_wallet: float = 1000.0,
        max_open_trades: int = 4,
        config_file: str = "config.json",
        protocol_version: str = "1.0.0",
        metrics_version: str = "1.0.0",
    ) -> CandidateExecutionResult:
        # Build a ParamsSchema from the candidate's mutated sidecar.
        params = self._build_params_from_sidecar(
            strategy_name=strategy_name,
            version_id=version_id,
            sidecar_path=Path(self.runs_root / candidate_artifact_result.parameter_artifact.artifact_path),
            pairs=pairs,
            extra={
                "max_open_trades": max_open_trades,
                "dry_run_wallet": dry_run_wallet,
                "exchange": exchange,
                "trading_mode": trading_mode,
            },
        )

        candidate_dir = Path(candidate_artifact_result.candidate_dir)
        # Candidate strategy .py copy is supplied as the strategy_path so the
        # champion's original file is never touched.
        candidate_py_path = self.runs_root / candidate_artifact_result.strategy_artifact.artifact_path

        # Build a RunRequest-shaped call via the injected runner.
        request = self._build_run_request(
            strategy_name=strategy_name,
            version_id=version_id,
            config_file=config_file,
            timerange=develop_timerange,  # DEVELOP only
            timeframe=timeframe,
            pairs=pairs,
            max_open_trades=max_open_trades,
            dry_run_wallet=dry_run_wallet,
        )

        strategy_record = self._make_strategy_record(
            strategy_name=strategy_name, file_path=str(candidate_py_path)
        )

        try:
            execution_id = self.backtest_runner.run_candidate_backtest(
                strategy_record,
                version_id,
                request,
                params_override=params,
            )
        except Exception as exc:  # noqa: BLE001 - surface as SYSTEM_FAILURE
            return CandidateExecutionResult(
                underlying_execution_id=None,
                status=CandidateExecutionStatus.SYSTEM_FAILURE,
                candidate_dir=str(candidate_dir),
                artifacts={},
                metrics=None,
                failure_classification=f"candidate_execution_error: {exc}",
            )

        # Resolve metrics via the existing adapter (no local computation).
        metrics = self._resolve_metrics(execution_id)
        status, failure = self._classify(execution_id, metrics)

        artifacts = {
            "candidate_strategy": str(candidate_py_path),
            "candidate_sidecar": str(
                self.runs_root / candidate_artifact_result.parameter_artifact.artifact_path
            ),
            "underlying_run_dir": execution_id or "",
        }

        return CandidateExecutionResult(
            underlying_execution_id=execution_id,
            status=status,
            candidate_dir=str(candidate_dir),
            artifacts=artifacts,
            metrics=metrics,
            failure_classification=failure,
        )

    # ── Helpers ────────────────────────────────────────────────────────────

    def _build_params_from_sidecar(
        self, *, strategy_name: str, version_id: str, sidecar_path: Path,
        pairs: list[str], extra: dict[str, Any],
    ):
        """Build a ParamsSchema from the candidate's mutated sidecar copy.

        Reads the sidecar JSON (already mutated by CandidateArtifactService)
        and lifts known fields into a ParamsSchema. Missing fields default to
        safe empties — the candidate run uses these params via params_override.
        """
        from ....models import ParamsSchema

        data = {"parameters": {}}
        if sidecar_path.exists():
            try:
                data = json.loads(sidecar_path.read_text(encoding="utf-8"))
            except Exception:
                data = {"parameters": {}}
        params_block = data.get("parameters", {}) or {}
        flat = {}
        for name, meta in params_block.items():
            if isinstance(meta, dict):
                flat[name] = meta.get("current", meta.get("default"))
            else:
                flat[name] = meta

        return ParamsSchema(
            strategy_name=strategy_name,
            version_id=version_id,
            extracted_at=datetime.now(UTC),
            pair_list=list(pairs),
            buy_params={k: v for k, v in flat.items() if str(k).startswith("buy")},
            sell_params={k: v for k, v in flat.items() if str(k).startswith("sell")},
            protection_params={k: v for k, v in flat.items() if str(k).startswith("protection")},
            roi_table=data.get("roi", {}),
            stoploss=float(flat.get("stoploss", -0.1)),
            trailing_stop=bool(flat.get("trailing_stop", False)),
            trailing_stop_positive=flat.get("trailing_stop_positive"),
            trailing_stop_positive_offset=flat.get("trailing_stop_positive_offset"),
            trailing_only_offset_is_reached=flat.get("trailing_only_offset_is_reached"),
            custom_params=flat,
        )

    def _build_run_request(self, **kwargs):
        from ....models import RunRequest

        return RunRequest(**kwargs)

    def _make_strategy_record(self, *, strategy_name: str, file_path: str):
        """Build the strategy reference the BacktestRunner consumes.

        Only ``strategy_name`` and ``file_path`` are required by
        ``BacktestRunner.run_backtest`` (used as ``strategy.strategy_name`` and
        ``strategy.file_path``). We use a lightweight object to avoid
        reconstructing a full ``StrategyRecord`` from registry metadata here.
        """
        return SimpleNamespace(strategy_name=strategy_name, file_path=str(file_path))

    def _resolve_metrics(self, execution_id: Optional[str]) -> Optional[CanonicalMetricsSnapshot]:
        """Resolve CanonicalMetricsSnapshot from the backtest result.

        Delegates to the existing metrics adapter. Returns None if no result
        is available (caller classifies as PARSE_FAILURE / NO_TRADES).
        """
        if not execution_id:
            return None
        try:
            summary = self._load_backtest_summary(execution_id)
            if summary is None:
                return None
            return from_parsed_summary(summary, source_run_id=execution_id)
        except Exception:
            return None

    def _load_backtest_summary(self, execution_id: str):
        """Best-effort load of a parsed backtest summary for the execution id.

        The metrics adapter (``from_parsed_summary``) reads attributes
        (``.total_trades``, ``.win_rate_pct``, ...), so a raw JSON dict must be
        adapted into an attribute-accessible object. Uses the injected runner's
        repository when available; returns None if the result cannot be located.
        Tests supply a fake that returns a dict-backed object.
        """
        repo = getattr(self.backtest_runner, "run_repository", None)
        if repo is None:
            return None
        try:
            run_dir = repo.find_run_dir(execution_id)
            summary_path = Path(run_dir) / "parsed_summary.json"
            if not summary_path.exists():
                return None
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            # Adapt dict -> attribute-accessible object for the metrics adapter.
            if isinstance(data, dict):
                return SimpleNamespace(
                    total_trades=data.get("total_trades"),
                    win_rate_pct=data.get("win_rate_pct", data.get("win_rate")),
                    net_profit_currency=data.get("net_profit_currency", data.get("net_profit_abs")),
                    net_profit_pct=data.get("net_profit_pct"),
                    profit_factor=data.get("profit_factor"),
                    expectancy=data.get("expectancy"),
                    sharpe_ratio=data.get("sharpe_ratio", data.get("sharpe")),
                    sortino_ratio=data.get("sortino_ratio", data.get("sortino")),
                    calmar_ratio=data.get("calmar_ratio", data.get("calmar")),
                    max_drawdown_currency=data.get("max_drawdown_currency", data.get("max_drawdown_abs")),
                    max_drawdown_pct=data.get("max_drawdown_pct"),
                    avg_trade_duration_minutes=data.get("avg_trade_duration_minutes"),
                    run_id=execution_id,
                )
            return data  # already an object (real ParsedSummary)
        except Exception:
            return None

    def _classify(self, execution_id, metrics):
        if not execution_id:
            return CandidateExecutionStatus.EXECUTION_FAILURE, "no_execution_id"
        if metrics is None:
            return CandidateExecutionStatus.PARSE_FAILURE, "metrics_unavailable"
        total = None
        try:
            total = metrics.total_trades.value
        except Exception:
            total = None
        if total is not None and total == 0:
            return CandidateExecutionStatus.NO_TRADES, "zero_trades"
        return CandidateExecutionStatus.SUCCESS, None
