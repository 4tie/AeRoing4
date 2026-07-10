"""Adapters: existing trusted metric sources → CanonicalMetricsSnapshot.

Binding migration principle (Prompt 2 §2): prefer an existing, trusted value
over recalculating from raw data. A metric is only calculated here
(delegating to `calculator.py`) when the trusted source does not provide it.

This module does not parse Freqtrade artifacts. It only adapts already
produced objects (`ParsedSummary`, Pair Explorer group-result dicts, raw
trade dicts).
"""

from __future__ import annotations

from typing import Any

from . import calculator
from .models import CanonicalMetricsSnapshot, MetricValue
from .provenance import SourceType, build_provenance


def _mv_from_optional(value: float | int | None) -> MetricValue:
    """Wrap an already-trusted optional numeric value as a MetricValue."""
    if value is None:
        return MetricValue.unavailable()
    return MetricValue.available(value)


def _extract_profit_ratio(trade: Any) -> float | None:
    """Read `profit_ratio` off a trade regardless of whether it is a typed
    `BacktestTrade`-like object or a plain dict (both shapes occur across
    AeRoing4 consumers — e.g. Pair Discovery's raw group-result trades)."""
    if trade is None:
        return None
    if isinstance(trade, dict):
        value = trade.get("profit_ratio")
    else:
        value = getattr(trade, "profit_ratio", None)
    return float(value) if value is not None else None


def from_parsed_summary(summary: Any, *, source_run_id: str | None = None) -> CanonicalMetricsSnapshot:
    """Adapt a `backend.models.runs.ParsedSummary` into a canonical snapshot.

    Every field on `ParsedSummary` used here is treated as already trusted
    (produced by `ResultParser`) and is passed through unchanged — this
    adapter performs no recalculation. Fields absent from `ParsedSummary`
    entirely (`bootstrap_sharpe_p5`) are left UNAVAILABLE since they require
    a raw return series this adapter does not have access to; see
    `from_parsed_summary_with_trades` for the variant that can derive them.
    """
    adapted_metrics = [
        "net_profit_abs",
        "net_profit_pct",
        "win_rate",
        "profit_factor",
        "expectancy",
        "sharpe",
        "sortino",
        "calmar",
        "max_drawdown_abs",
        "max_drawdown_pct",
        "average_trade_duration_minutes",
        "total_trades",
    ]
    unavailable = [name for name in ("bootstrap_sharpe_p5",)]

    total_trades = summary.total_trades
    win_rate_pct = summary.win_rate_pct
    winning_trades = None
    losing_trades = None
    if total_trades is not None and win_rate_pct is not None:
        winning_trades = round(total_trades * win_rate_pct / 100)
        losing_trades = total_trades - winning_trades

    snapshot = CanonicalMetricsSnapshot(
        total_trades=_mv_from_optional(total_trades),
        winning_trades=_mv_from_optional(winning_trades),
        losing_trades=_mv_from_optional(losing_trades),
        net_profit_abs=_mv_from_optional(summary.net_profit_currency),
        net_profit_pct=_mv_from_optional(summary.net_profit_pct),
        win_rate=_mv_from_optional(summary.win_rate_pct),
        profit_factor=_mv_from_optional(summary.profit_factor),
        expectancy=_mv_from_optional(summary.expectancy),
        sharpe=_mv_from_optional(summary.sharpe_ratio),
        sortino=_mv_from_optional(summary.sortino_ratio),
        calmar=_mv_from_optional(summary.calmar_ratio),
        max_drawdown_abs=_mv_from_optional(summary.max_drawdown_currency),
        max_drawdown_pct=_mv_from_optional(summary.max_drawdown_pct),
        average_trade_duration_minutes=_mv_from_optional(summary.avg_trade_duration_minutes),
        bootstrap_sharpe_p5=MetricValue.unavailable(),
        provenance=build_provenance(
            source_type=SourceType.PARSED_SUMMARY,
            source_run_id=source_run_id or getattr(summary, "run_id", None),
            source_parser_version="ResultParser",
            adapted_metrics=adapted_metrics,
            unavailable_metrics=unavailable,
        ),
    )
    return snapshot


def from_parsed_summary_with_trades(
    summary: Any,
    trades: list[Any],
    *,
    source_run_id: str | None = None,
) -> CanonicalMetricsSnapshot:
    """Like `from_parsed_summary`, but also fills `bootstrap_sharpe_p5`
    (and backfills `sharpe`/`sortino`/`calmar` if the trusted source lacks
    them) by deriving them from the trade-level `profit_ratio` series.

    Any metric derived here (rather than adapted) is recorded in
    `provenance.derived_metrics` so consumers can tell the two apart.
    """
    snapshot = from_parsed_summary(summary, source_run_id=source_run_id)
    returns = [ratio for ratio in (_extract_profit_ratio(t) for t in trades) if ratio is not None]

    derived: list[str] = []
    unavailable = list(snapshot.provenance.unavailable_metrics)

    bootstrap = calculator.compute_bootstrap_sharpe_p5(returns)
    snapshot.bootstrap_sharpe_p5 = bootstrap
    derived.append("bootstrap_sharpe_p5")
    if "bootstrap_sharpe_p5" in unavailable:
        unavailable.remove("bootstrap_sharpe_p5")

    if snapshot.sharpe.availability.value == "unavailable":
        snapshot.sharpe = calculator.compute_sharpe(returns)
        derived.append("sharpe")
    if snapshot.sortino.availability.value == "unavailable":
        snapshot.sortino = calculator.compute_sortino(returns)
        derived.append("sortino")
    if snapshot.calmar.availability.value == "unavailable":
        snapshot.calmar = calculator.compute_calmar(
            summary.net_profit_pct, summary.max_drawdown_pct
        )
        derived.append("calmar")

    adapted = [m for m in snapshot.provenance.adapted_metrics if m not in derived]
    snapshot.provenance = snapshot.provenance.model_copy(
        update={
            "derived_metrics": sorted(set(snapshot.provenance.derived_metrics) | set(derived)),
            "adapted_metrics": sorted(adapted),
            "unavailable_metrics": sorted(unavailable),
        }
    )
    return snapshot


def from_pair_discovery_group(
    pair_data: dict,
    *,
    pair: str,
    source_run_id: str | None = None,
) -> CanonicalMetricsSnapshot:
    """Adapt/derive a canonical snapshot for one pair from a Pair Explorer
    group-result payload (`pair_data`), the shape Pair Discovery already
    receives from `start_pair_explorer_job` / `pair_explorer_service`.

    This is the ONLY source used for the migrated Pair Discovery consumer
    (§0.7 of the architecture doc / Prompt 2 §9): profit_factor and
    expectancy are derived here using the exact same formulas the step
    previously implemented locally (`_compute_profit_factor`,
    `_compute_expectancy`), now centralized so no other consumer can drift
    from them. Summary-level fields the group payload already reports
    (net_profit_pct, max_drawdown_pct, win_rate) are adapted, not
    recalculated, exactly as the pre-migration step behaved.
    """
    trades_present = bool(pair_data) and "trades" in pair_data
    trades: list[dict] = (pair_data or {}).get("trades") or []
    profits = [float(t.get("profit_abs", 0) or 0) for t in trades]
    durations = [
        float(t.get("trade_duration"))
        for t in trades
        if t.get("trade_duration") is not None
    ]

    total_trades_mv, winning_mv, losing_mv = calculator.compute_trade_counts(
        profits if trades_present else None
    )
    profit_factor_mv = calculator.compute_profit_factor(profits)
    expectancy_abs_mv = calculator.compute_expectancy_abs(profits)
    avg_duration_mv = calculator.compute_average_trade_duration_minutes(durations)

    net_profit_pct = pair_data.get("net_profit_pct") if pair_data else None
    max_drawdown_pct = pair_data.get("max_drawdown_pct") if pair_data else None
    win_rate = pair_data.get("win_rate") if pair_data else None

    derived_metrics = ["profit_factor", "expectancy", "average_trade_duration_minutes", "total_trades", "winning_trades", "losing_trades"]
    adapted_metrics = [m for m in ("net_profit_pct", "max_drawdown_pct", "win_rate") if pair_data and pair_data.get(m) is not None]
    unavailable_metrics = [
        name
        for name, mv in (
            ("net_profit_pct", net_profit_pct),
            ("max_drawdown_pct", max_drawdown_pct),
            ("win_rate", win_rate),
        )
        if mv is None
    ] + ["sharpe", "sortino", "calmar", "net_profit_abs", "max_drawdown_abs", "bootstrap_sharpe_p5"]

    return CanonicalMetricsSnapshot(
        total_trades=total_trades_mv,
        winning_trades=winning_mv,
        losing_trades=losing_mv,
        net_profit_abs=MetricValue.unavailable(),
        net_profit_pct=_mv_from_optional(net_profit_pct),
        win_rate=_mv_from_optional(win_rate),
        profit_factor=profit_factor_mv,
        expectancy=expectancy_abs_mv,
        sharpe=MetricValue.unavailable(),
        sortino=MetricValue.unavailable(),
        calmar=MetricValue.unavailable(),
        max_drawdown_abs=MetricValue.unavailable(),
        max_drawdown_pct=_mv_from_optional(max_drawdown_pct),
        average_trade_duration_minutes=avg_duration_mv,
        bootstrap_sharpe_p5=MetricValue.unavailable(),
        provenance=build_provenance(
            source_type=SourceType.PAIR_DISCOVERY_GROUP,
            source_run_id=source_run_id,
            source_artifact=pair,
            derived_metrics=derived_metrics,
            adapted_metrics=adapted_metrics,
            unavailable_metrics=unavailable_metrics,
        ),
    )
