"""Pair Discovery step for AeRoing4 Milestone 2A.

Evaluates a discovery universe of pairs using the existing PairExplorerService /
start_pair_explorer_job infrastructure.  Does NOT call AutoQuant PipelineState.

Flow:
  1. Determine the discovery universe (explicit list or default liquid pairs).
  2. Per-pair data readiness check + download.
  3. Run each usable pair through BacktestRunner via start_pair_explorer_job.
  4. Parse results → hard rejection gates.
  5. Score and rank valid candidates.
  6. Persist full discovery result in AeRoing4 state.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ....services.pairs import pair_explorer_service as pair_explorer_api
from ....services.workflow_jobs.pair_explorer_job import start_pair_explorer_job
from ..metrics.adapters import from_pair_discovery_group
from ..models import (
    AeRoing4StepStatus,
    PairCandidateStatus,
    PairDiscoveryResult,
    PairEvaluationRecord,
    StepResult,
)
from ..scoring import (
    RANKING_POLICY_VERSION,
    PairScoreInputs,
    get_min_trades,
    rank_candidates_with_trades,
    score_pair,
)

if TYPE_CHECKING:
    from ...app_services import AppServices

logger = logging.getLogger(__name__)

# ── Default discovery universe ───────────────────────────────────────────────
# A conservative set of ~25 liquid USDT pairs.
# Used only when discovery_pairs is not provided in the request AND
# the pair_selector service does not have a configured liquid universe.
DEFAULT_DISCOVERY_UNIVERSE: list[str] = [
    "BTC/USDT",
    "ETH/USDT",
    "BNB/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "DOGE/USDT",
    "DOT/USDT",
    "MATIC/USDT",
    "LINK/USDT",
    "LTC/USDT",
    "UNI/USDT",
    "ATOM/USDT",
    "ETC/USDT",
    "XLM/USDT",
    "ALGO/USDT",
    "NEAR/USDT",
    "FIL/USDT",
    "APT/USDT",
    "ARB/USDT",
    "OP/USDT",
    "INJ/USDT",
    "TRX/USDT",
    "ICP/USDT",
]

# How long to wait (seconds) between progress polls while exploring
_POLL_INTERVAL = 5.0
# Total timeout for the entire pair-discovery exploration phase
_EXPLORATION_TIMEOUT = 7200.0  # 2 hours


class PairDiscoveryStep:
    """Pair Discovery step.

    Runs the strategy against a universe of pairs, ranks the results,
    and produces an auditable ranked candidate list.
    """

    def __init__(self, services: "AppServices"):
        """Initialize pair discovery step with services."""
        self.services = services

    async def execute(
        self,
        strategy_name: str,
        timeframe: str,
        discovery_timerange: str,
        discovery_pairs: list[str] | None = None,
    ) -> StepResult:
        """Execute pair discovery step.

        Args:
            strategy_name: Name of the strategy to evaluate
            timeframe: Candle timeframe to use for discovery
            discovery_timerange: Date range for discovery backtests
            discovery_pairs: Explicit pair universe; uses default if None

        Returns:
            StepResult with PairDiscoveryResult persisted in data
        """
        started_at = datetime.now(UTC)

        try:
            # ── 1. Determine universe ────────────────────────────────────────
            universe = self._resolve_universe(discovery_pairs)
            logger.info(
                "[PairDiscovery] Starting with universe of %d pairs for strategy '%s'",
                len(universe),
                strategy_name,
            )

            # ── 2. Per-pair data readiness ───────────────────────────────────
            settings = self.services.settings_store.load()
            exchange = self._detect_exchange(settings)

            per_pair_data: dict[str, bool] = {}
            download_errors: dict[str, str] = {}

            for pair in universe:
                ready, err = await self._ensure_pair_data(
                    pair=pair,
                    timeframe=timeframe,
                    timerange=discovery_timerange,
                    settings=settings,
                    exchange=exchange,
                )
                per_pair_data[pair] = ready
                if err:
                    download_errors[pair] = err

            usable_pairs = [p for p in universe if per_pair_data.get(p, False)]
            data_unavailable_pairs = [p for p in universe if not per_pair_data.get(p, False)]

            logger.info(
                "[PairDiscovery] Data ready: %d usable, %d unavailable",
                len(usable_pairs),
                len(data_unavailable_pairs),
            )

            if not usable_pairs:
                # No pairs have data — terminal failure
                return self._make_failure(
                    started_at=started_at,
                    error="No discovery pairs have usable data",
                    universe=universe,
                    per_pair_data=per_pair_data,
                    discovery_timerange=discovery_timerange,
                    timeframe=timeframe,
                    strategy_name=strategy_name,
                    download_errors=download_errors,
                )

            # ── 3. Run pair exploration via existing infrastructure ──────────
            session_id, _ = await start_pair_explorer_job(
                services=self.services,
                strategy_name=strategy_name,
                pairs=usable_pairs,
                timeframe=timeframe,
                timerange=discovery_timerange,
                dry_run_wallet=1000.0,
                max_open_trades=1,  # one pair per group for isolated evidence
            )

            logger.info(
                "[PairDiscovery] PairExplorer session %s started for %d pairs",
                session_id,
                len(usable_pairs),
            )

            # ── 4. Wait for exploration to complete ──────────────────────────
            session_data = await self._wait_for_session(session_id, settings)

            # ── 5. Parse results into per-pair records ───────────────────────
            min_trades = get_min_trades(timeframe)
            evaluation_records = self._parse_session_results(
                session_data=session_data,
                universe=universe,
                usable_pairs=usable_pairs,
                data_unavailable_pairs=data_unavailable_pairs,
                download_errors=download_errors,
                timeframe=timeframe,
                min_trades=min_trades,
                session_id=session_id,
            )

            # ── 6. Rank valid candidates ─────────────────────────────────────
            ranked = self._rank_valid_candidates(evaluation_records, timeframe)

            # ── 7. Build and return discovery result ─────────────────────────
            valid_records = [r for r in evaluation_records if r.status == PairCandidateStatus.VALID_CANDIDATE]
            rejected_records = [r for r in evaluation_records if r.status != PairCandidateStatus.VALID_CANDIDATE]

            result = PairDiscoveryResult(
                universe_size=len(universe),
                usable_pairs_count=len(usable_pairs),
                evaluated_pairs_count=len(usable_pairs),
                valid_candidates_count=len(valid_records),
                rejected_pairs_count=len(rejected_records),
                ranked_pairs=ranked,
                all_evaluations=evaluation_records,
                discovery_pairs_requested=universe,
                discovery_timerange=discovery_timerange,
                timeframe=timeframe,
                strategy_name=strategy_name,
                explorer_session_id=session_id,
                ranking_policy_version=RANKING_POLICY_VERSION,
            )

            if not valid_records:
                # Discovery ran but no valid candidates found
                return StepResult(
                    step_name="pair_discovery",
                    status=AeRoing4StepStatus.PASSED,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    data={
                        "outcome": "no_pair_candidates",
                        "discovery_result": result.model_dump(),
                    },
                )

            return StepResult(
                step_name="pair_discovery",
                status=AeRoing4StepStatus.PASSED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                data={
                    "outcome": "valid_candidates_found",
                    "discovery_result": result.model_dump(),
                },
            )

        except Exception as exc:
            logger.exception("[PairDiscovery] Step failed unexpectedly: %s", exc)
            return StepResult(
                step_name="pair_discovery",
                status=AeRoing4StepStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error=f"Pair discovery step failed: {str(exc)}",
                data={"outcome": "step_error"},
            )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _resolve_universe(self, discovery_pairs: list[str] | None) -> list[str]:
        """Resolve the discovery universe from request or default.

        Deduplicates pairs while preserving order; duplicate entries would break
        the per-pair ranking remap which keys on pair name.
        """
        if discovery_pairs:
            seen: set[str] = set()
            cleaned: list[str] = []
            for p in discovery_pairs:
                normalised = p.strip().upper()
                if normalised and normalised not in seen:
                    seen.add(normalised)
                    cleaned.append(normalised)
            if cleaned:
                return cleaned

        # Try pair_selector's available_pairs if populated
        try:
            selector = self.services.pair_selector
            all_pairs = list(selector.get_all_pairs())
            if all_pairs:
                # Cap at 25 pairs
                return sorted(all_pairs)[:25]
        except Exception:
            pass

        return list(DEFAULT_DISCOVERY_UNIVERSE)

    def _detect_exchange(self, settings) -> str:
        """Detect exchange name from config file."""
        try:
            import json
            from pathlib import Path
            config_data = json.loads(
                Path(settings.default_config_file_path).read_text(encoding="utf-8")
            )
            return config_data.get("exchange", {}).get("name", "binance")
        except Exception:
            return "binance"

    async def _ensure_pair_data(
        self,
        pair: str,
        timeframe: str,
        timerange: str,
        settings,
        exchange: str,
    ) -> tuple[bool, str | None]:
        """Check and optionally download data for a pair.

        Returns:
            (data_ready, error_message_or_None)
        """
        try:
            err = await pair_explorer_api.ensure_data(
                runner=self.services.data_download_runner,
                pair=pair,
                timeframe=timeframe,
                timerange=timerange,
                config_file=settings.default_config_file_path,
                user_data_dir=settings.user_data_directory_path,
                exchange=exchange,
            )
            if err:
                return False, err
            return True, None
        except Exception as exc:
            return False, str(exc)

    async def _wait_for_session(
        self,
        session_id: str,
        settings,
    ) -> dict[str, Any]:
        """Poll pair explorer session until complete or timeout."""
        deadline = time.monotonic() + _EXPLORATION_TIMEOUT
        while time.monotonic() < deadline:
            session = pair_explorer_api.get_session(session_id)
            if session is None:
                # Try loading from disk
                all_sessions = pair_explorer_api.load_all_sessions(
                    settings.user_data_directory_path
                )
                session = all_sessions.get(session_id)

            if session is not None:
                status = session.get("status", "running")
                completed = session.get("completed", 0)
                total = session.get("total", 1)
                logger.debug(
                    "[PairDiscovery] Session %s: status=%s completed=%d/%d",
                    session_id,
                    status,
                    completed,
                    total,
                )
                if status in ("completed", "failed") or completed >= total:
                    return session

            await asyncio.sleep(_POLL_INTERVAL)

        # Timeout: return whatever state we have
        session = pair_explorer_api.get_session(session_id) or {}
        session["status"] = "failed"
        logger.error("[PairDiscovery] Session %s timed out", session_id)
        return session

    def _parse_session_results(
        self,
        session_data: dict[str, Any],
        universe: list[str],
        usable_pairs: list[str],
        data_unavailable_pairs: list[str],
        download_errors: dict[str, str],
        timeframe: str,
        min_trades: int,
        session_id: str,
    ) -> list[PairEvaluationRecord]:
        """Convert raw session data into structured PairEvaluationRecord objects."""
        records: list[PairEvaluationRecord] = []

        # DATA_UNAVAILABLE records first
        for pair in data_unavailable_pairs:
            records.append(
                PairEvaluationRecord(
                    pair=pair,
                    status=PairCandidateStatus.DATA_UNAVAILABLE,
                    rejection_reasons=[
                        download_errors.get(pair, "Data not available for discovery timerange")
                    ],
                    backtest_run_id=None,
                    explorer_session_id=session_id,
                )
            )

        # Parse each group result from the session
        raw_results = pair_explorer_api.coerce_results_dict(session_data)

        for pair in usable_pairs:
            # Each pair ran as its own group (max_open_trades=1)
            group_key = pair_explorer_api.group_key([pair])
            group_result = raw_results.get(group_key, {})

            if not group_result or group_result.get("status") == "failed":
                error_msg = group_result.get("error", "Freqtrade execution failed")
                records.append(
                    PairEvaluationRecord(
                        pair=pair,
                        status=PairCandidateStatus.EXECUTION_FAILURE,
                        rejection_reasons=[error_msg],
                        backtest_run_id=None,
                        explorer_session_id=session_id,
                    )
                )
                continue

            # Extract metrics — never substitute None with 0
            total_trades: int = group_result.get("total_trades") or 0
            trades_by_pair: dict = group_result.get("trades_by_pair", {})
            pair_data = trades_by_pair.get(pair, {})

            net_profit_pct: float | None = group_result.get("total_profit_pct")
            metrics_snapshot = from_pair_discovery_group(
                pair_data, pair=pair, source_run_id=session_id
            )
            profit_factor: float | None = (
                metrics_snapshot.profit_factor.value
                if metrics_snapshot.profit_factor.availability.value == "available"
                else None
            )
            expectancy: float | None = self._scoring_expectancy(metrics_snapshot, total_trades)
            max_drawdown_pct: float | None = group_result.get("max_drawdown")
            win_rate: float | None = pair_data.get("win_rate") if pair_data else None
            avg_trade_duration: float | None = None  # available if trade-level data present

            # ── Hard rejection gates ───────────────────────────────────────
            if total_trades == 0:
                records.append(
                    PairEvaluationRecord(
                        pair=pair,
                        status=PairCandidateStatus.ZERO_TRADES,
                        rejection_reasons=["Strategy produced zero trades on this pair"],
                        total_trades=0,
                        backtest_run_id=None,
                        explorer_session_id=session_id,
                        metrics_available=self._availability_map(
                            profit_factor, net_profit_pct, expectancy, max_drawdown_pct
                        ),
                    )
                )
                continue

            if total_trades < min_trades:
                records.append(
                    PairEvaluationRecord(
                        pair=pair,
                        status=PairCandidateStatus.INSUFFICIENT_TRADES,
                        rejection_reasons=[
                            f"Insufficient trades: {total_trades} < {min_trades} "
                            f"(minimum for {timeframe} timeframe)"
                        ],
                        total_trades=total_trades,
                        net_profit_pct=net_profit_pct,
                        profit_factor=profit_factor,
                        expectancy=expectancy,
                        max_drawdown_pct=max_drawdown_pct,
                        win_rate=win_rate,
                        backtest_run_id=None,
                        explorer_session_id=session_id,
                        metrics_available=self._availability_map(
                            profit_factor, net_profit_pct, expectancy, max_drawdown_pct
                        ),
                    )
                )
                continue

            # ── Compute rank score ─────────────────────────────────────────
            score_inputs = PairScoreInputs(
                pair=pair,
                total_trades=total_trades,
                timeframe=timeframe,
                profit_factor=profit_factor,
                net_profit_pct=net_profit_pct,
                expectancy=expectancy,
                max_drawdown_pct=max_drawdown_pct,
            )
            score_result = score_pair(score_inputs)

            records.append(
                PairEvaluationRecord(
                    pair=pair,
                    status=PairCandidateStatus.VALID_CANDIDATE,
                    rejection_reasons=[],
                    total_trades=total_trades,
                    net_profit_pct=net_profit_pct,
                    profit_factor=profit_factor,
                    expectancy=expectancy,
                    max_drawdown_pct=max_drawdown_pct,
                    win_rate=win_rate,
                    avg_trade_duration=avg_trade_duration,
                    rank_score=score_result.rank_score,
                    score_components=score_result.components,
                    backtest_run_id=None,
                    explorer_session_id=session_id,
                    metrics_available=score_result.metrics_available,
                )
            )

        return records

    def _rank_valid_candidates(
        self,
        records: list[PairEvaluationRecord],
        timeframe: str,
    ) -> list[PairEvaluationRecord]:
        """Return only valid candidates, sorted by rank score with tie-breaking."""
        valid = [r for r in records if r.status == PairCandidateStatus.VALID_CANDIDATE]
        pairs_with_trades = [(r, r.total_trades or 0) for r in valid]
        ranked = rank_candidates_with_trades(
            [(self._to_score_result(r), t) for r, t in pairs_with_trades]
        )
        # Re-map back to records in ranked order, assign rank numbers
        pair_to_record = {r.pair: r for r in valid}
        result: list[PairEvaluationRecord] = []
        for rank_num, (score_res, _) in enumerate(ranked, start=1):
            rec = pair_to_record[score_res.pair]
            rec.rank = rank_num
            result.append(rec)
        return result

    def _to_score_result(self, record: PairEvaluationRecord):
        """Convert a PairEvaluationRecord to a PairScoreResult for ranking."""
        from ..scoring import PairScoreResult
        return PairScoreResult(
            pair=record.pair,
            rank_score=record.rank_score or 0.0,
            components=record.score_components or {},
            trade_sufficiency_multiplier=record.score_components.get(
                "trade_sufficiency_multiplier", 1.0
            ) if record.score_components else 1.0,
            metrics_available=record.metrics_available or {},
        )

    # Wallet size used to normalize expectancy into the dimensionless ratio
    # `scoring.py` has always been calibrated against. Preserved unchanged
    # from the pre-Metrics-SSOT implementation so ranking behavior does not
    # change (see docs/AEROING4_TARGET_ARCHITECTURE.md §0.7).
    _SCORING_EXPECTANCY_WALLET = 1000.0

    def _scoring_expectancy(self, metrics_snapshot, total_trades: int) -> float | None:
        """Convert the canonical (currency-absolute) expectancy into the
        normalized ratio `scoring.py` expects.

        Canonical `expectancy` = sum(profit_abs) / total_trades (currency).
        Dividing by `_SCORING_EXPECTANCY_WALLET` reproduces the exact
        pre-migration value (`total_profit / total_trades / 1000.0`), since
        both formulas reduce to the same sum(profit_abs) / total_trades
        numerator — see `metrics/calculator.py::compute_expectancy_abs` for
        the algebraic equivalence note.
        """
        if total_trades == 0:
            return None
        if metrics_snapshot.expectancy.availability.value != "available":
            return None
        return round(metrics_snapshot.expectancy.value / self._SCORING_EXPECTANCY_WALLET, 6)

    @staticmethod
    def _availability_map(
        profit_factor: float | None,
        net_profit_pct: float | None,
        expectancy: float | None,
        max_drawdown_pct: float | None,
    ) -> dict[str, bool]:
        return {
            "profit_factor": profit_factor is not None,
            "net_profit_pct": net_profit_pct is not None,
            "expectancy": expectancy is not None,
            "max_drawdown_pct": max_drawdown_pct is not None,
        }

    def _make_failure(
        self,
        started_at: datetime,
        error: str,
        universe: list[str],
        per_pair_data: dict[str, bool],
        discovery_timerange: str,
        timeframe: str,
        strategy_name: str,
        download_errors: dict[str, str],
    ) -> StepResult:
        all_records = [
            PairEvaluationRecord(
                pair=p,
                status=PairCandidateStatus.DATA_UNAVAILABLE,
                rejection_reasons=[download_errors.get(p, "No data")],
            )
            for p in universe
        ]
        result = PairDiscoveryResult(
            universe_size=len(universe),
            usable_pairs_count=0,
            evaluated_pairs_count=0,
            valid_candidates_count=0,
            rejected_pairs_count=len(universe),
            ranked_pairs=[],
            all_evaluations=all_records,
            discovery_pairs_requested=universe,
            discovery_timerange=discovery_timerange,
            timeframe=timeframe,
            strategy_name=strategy_name,
            ranking_policy_version=RANKING_POLICY_VERSION,
        )
        return StepResult(
            step_name="pair_discovery",
            status=AeRoing4StepStatus.FAILED,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            error=error,
            data={
                "outcome": "no_usable_data",
                "discovery_result": result.model_dump(),
            },
        )
