"""services/storage/result_parser.py contains backend logic for result parser.

This file is intentionally documented in plain English so readers can follow
what each section does even without deep Python experience.
"""

from __future__ import annotations
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from ...models import (
    BacktestAdvancedMetrics,
    BacktestCharts,
    BacktestTrade,
    ExitReasonStat,
    HistogramBin,
    PairResult,
    PairTradeBreakdown,
    ParsedSummary,
    RunMetadata,
)
from ...utils import atomic_write_json


class ResultParser:
    """ResultParser contains class-level backend logic."""
    SUMMARY_FIELDS = [
        "starting_balance",
        "final_balance",
        "net_profit_currency",
        "net_profit_pct",
        "total_trades",
        "trades_per_day",
        "win_rate_pct",
        "loss_rate_pct",
        "max_drawdown_pct",
        "max_drawdown_currency",
        "avg_trade_duration_minutes",
        "profit_factor",
        "expectancy",
        "sharpe_ratio",
        "sortino_ratio",
        "calmar_ratio",
    ]

    def parse_run_artifacts(
        self,
        run_dir: Path,
        metadata: RunMetadata,
        warning_logger: callable | None = None,
    ) -> tuple[ParsedSummary, list[PairResult]]:
        """parse_run_artifacts implements function-level backend logic."""
        raw_result_file = run_dir / "raw_result.json"
        try:
            raw_text = raw_result_file.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"raw_result.json not found in {run_dir} — Freqtrade may not have produced output."
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"Failed to read raw_result.json in {run_dir}: {exc}") from exc
        try:
            raw_payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"raw_result.json in {run_dir} contains invalid JSON: {exc}"
            ) from exc
        strategy_block = self._locate_strategy_block(raw_payload, metadata.strategy_name)
        trades = strategy_block.get("trades") or raw_payload.get("trades") or []
        exit_distribution = self._parse_exit_reasons(strategy_block, trades)
        start_date, end_date, total_days = self._parse_date_window(metadata.timerange)
        net_profit_pct = self._derive_profit_pct(strategy_block)
        profit_per_day = (
            net_profit_pct / total_days
            if net_profit_pct is not None and total_days and total_days > 0
            else None
        )
        summary = ParsedSummary(
            run_id=metadata.run_id,
            starting_balance=self._lookup_number(strategy_block, "starting_balance", "dry_run_wallet"),
            final_balance=self._derive_final_balance(strategy_block),
            net_profit_currency=self._lookup_number(
                strategy_block, "profit_total_abs", "net_profit_currency", "absolute_profit"
            ),
            net_profit_pct=net_profit_pct,
            profit_per_day=profit_per_day,
            start_date=start_date,
            end_date=end_date,
            total_days=total_days,
            total_trades=self._lookup_int(strategy_block, "total_trades", "trade_count"),
            trades_per_day=self._derive_trades_per_day(strategy_block, metadata),
            win_rate_pct=self._derive_win_rate(strategy_block, trades),
            loss_rate_pct=self._derive_loss_rate(strategy_block, trades),
            max_drawdown_pct=self._derive_drawdown_pct(strategy_block),
            max_drawdown_currency=self._lookup_number(
                strategy_block, "max_drawdown_abs", "max_drawdown_account_abs"
            ),
            avg_trade_duration_minutes=self._derive_avg_duration(strategy_block, trades),
            profit_factor=self._lookup_number(strategy_block, "profit_factor"),
            expectancy=self._derive_expectancy(strategy_block, trades),
            sharpe_ratio=self._lookup_number(strategy_block, "sharpe", "sharpe_ratio"),
            sortino_ratio=self._lookup_number(strategy_block, "sortino", "sortino_ratio"),
            calmar_ratio=self._lookup_number(strategy_block, "calmar", "calmar_ratio"),
            exit_reason_distribution=exit_distribution,
        )
        self._warn_missing(summary, warning_logger)
        pair_results = self._parse_pair_results(strategy_block, trades)

        parsed_trades = [self._parse_trade(item) for item in trades if isinstance(item, dict)]
        trades_by_pair: dict[str, list[BacktestTrade]] = {}
        for trade in parsed_trades:
            trades_by_pair.setdefault(trade.pair, []).append(trade)

        trade_breakdowns: dict[str, PairTradeBreakdown] = {
            pair: PairTradeBreakdown(pair=pair, trades=items)
            for pair, items in sorted(trades_by_pair.items())
        }

        advanced_metrics = self._build_advanced_metrics(summary, parsed_trades)
        charts = self._build_charts(parsed_trades, summary.starting_balance)

        atomic_write_json(run_dir / "parsed_summary.json", summary.model_dump(mode="json"))
        atomic_write_json(
            run_dir / "pair_results.json",
            [item.model_dump(mode="json") for item in pair_results],
        )
        atomic_write_json(
            run_dir / "trades.json",
            [item.model_dump(mode="json") for item in parsed_trades],
        )
        atomic_write_json(
            run_dir / "trades_by_pair.json",
            {pair: payload.model_dump(mode="json") for pair, payload in trade_breakdowns.items()},
        )
        atomic_write_json(
            run_dir / "advanced_metrics.json",
            advanced_metrics.model_dump(mode="json"),
        )
        atomic_write_json(
            run_dir / "charts.json",
            charts.model_dump(mode="json"),
        )
        return summary, pair_results

    def pretty_print(self, summary: ParsedSummary) -> str:
        """pretty_print implements function-level backend logic."""
        return json.dumps(summary.model_dump(mode="json"), indent=2)

    def parse_pretty(self, content: str) -> ParsedSummary:
        """parse_pretty implements function-level backend logic."""
        return ParsedSummary.model_validate(json.loads(content))

    def _warn_missing(self, summary: ParsedSummary, warning_logger: callable | None) -> None:
        """_warn_missing implements function-level backend logic."""
        if warning_logger is None:
            return
        for field_name in self.SUMMARY_FIELDS:
            if getattr(summary, field_name) is None:
                warning_logger(f"Warning: parsed summary field '{field_name}' was missing in raw output.")

    def _locate_strategy_block(self, raw_payload: Any, strategy_name: str) -> dict[str, Any]:
        """_locate_strategy_block implements function-level backend logic."""
        if isinstance(raw_payload, dict):
            strategy_root = raw_payload.get("strategy")
            if isinstance(strategy_root, dict):
                if strategy_name in strategy_root and isinstance(strategy_root[strategy_name], dict):
                    return strategy_root[strategy_name]
                if len(strategy_root) == 1:
                    value = next(iter(strategy_root.values()))
                    if isinstance(value, dict):
                        return value
            if {"profit_total_abs", "trade_count", "results_per_pair"} & set(raw_payload.keys()):
                return raw_payload
            for value in raw_payload.values():
                located = self._locate_strategy_block(value, strategy_name)
                if located:
                    return located
        elif isinstance(raw_payload, list):
            for item in raw_payload:
                located = self._locate_strategy_block(item, strategy_name)
                if located:
                    return located
        return {}

    def _parse_pair_results(self, strategy_block: dict[str, Any], trades: list[dict[str, Any]]) -> list[PairResult]:
        """_parse_pair_results implements function-level backend logic."""
        raw_pairs = strategy_block.get("results_per_pair") or strategy_block.get("pair_results") or []
        results: list[PairResult] = []
        if raw_pairs:
            for item in raw_pairs:
                pair_name = item.get("key") or item.get("pair")
                if not pair_name or str(pair_name).upper() == "TOTAL":
                    continue
                results.append(
                    PairResult(
                        pair=str(pair_name),
                        net_profit_currency=self._number(item, "profit_total_abs", "profit_abs", "net_profit_currency"),
                        net_profit_pct=self._percent(item, "profit_total", "profit_pct", "net_profit_pct"),
                        total_trades=self._integer(item, "trades", "trade_count", "total_trades"),
                        win_count=self._integer(item, "wins", "win_count"),
                        loss_count=self._integer(item, "losses", "loss_count"),
                        win_rate_pct=self._percent(item, "winrate", "win_rate", "win_rate_pct"),
                        avg_trade_result_pct=self._percent(item, "profit_mean", "avg_profit_pct", "avg_trade_result_pct"),
                        avg_trade_duration_minutes=self._minutes(item.get("duration_avg")),
                        pair_classification=None,
                        classification_rationale=None,
                    )
                )
        if results:
            return results

        trades_by_pair: dict[str, list[dict[str, Any]]] = {}
        for trade in trades:
            pair = str(trade.get("pair", "UNKNOWN"))
            trades_by_pair.setdefault(pair, []).append(trade)
        for pair, pair_trades in sorted(trades_by_pair.items()):
            profits = [float(trade.get("profit_abs", trade.get("profit_abs_pct", 0.0)) or 0.0) for trade in pair_trades]
            profit_pct = [float(trade.get("profit_pct", trade.get("profit_ratio", 0.0)) or 0.0) * 100 for trade in pair_trades]
            wins = sum(1 for value in profits if value > 0)
            losses = sum(1 for value in profits if value <= 0)
            results.append(
                PairResult(
                    pair=pair,
                    net_profit_currency=sum(profits),
                    net_profit_pct=sum(profit_pct),
                    total_trades=len(pair_trades),
                    win_count=wins,
                    loss_count=losses,
                    win_rate_pct=(wins / len(pair_trades) * 100) if pair_trades else None,
                    avg_trade_result_pct=(sum(profit_pct) / len(pair_trades)) if pair_trades else None,
                    avg_trade_duration_minutes=self._average(
                        [self._minutes(item.get("trade_duration")) for item in pair_trades]
                    ),
                    pair_classification=None,
                    classification_rationale=None,
                )
            )
        return results

    def _parse_exit_reasons(
        self, strategy_block: dict[str, Any], trades: list[dict[str, Any]]
    ) -> list[ExitReasonStat]:
        """_parse_exit_reasons implements function-level backend logic."""
        raw_reasons = strategy_block.get("exit_reason_summary") or strategy_block.get("exit_reason_distribution")
        if isinstance(raw_reasons, list):
            parsed: list[ExitReasonStat] = []
            for item in raw_reasons:
                reason = str(item.get("key") or item.get("exit_reason") or item.get("reason") or "")
                if not reason or reason.upper() == "TOTAL":
                    continue
                parsed.append(
                    ExitReasonStat(
                        reason=reason,
                        count=int(item.get("trades") or item.get("count") or 0),
                        total_profit=float(
                            item.get("profit_total_abs")
                            or item.get("profit_abs")
                            or item.get("total_profit")
                            or 0.0
                        ),
                    )
                )
            return parsed

        by_reason: dict[str, ExitReasonStat] = {}
        for trade in trades:
            reason = str(trade.get("exit_reason", "unknown"))
            current = by_reason.setdefault(reason, ExitReasonStat(reason=reason, count=0, total_profit=0.0))
            by_reason[reason] = ExitReasonStat(
                reason=reason,
                count=current.count + 1,
                total_profit=current.total_profit + float(trade.get("profit_abs", 0.0) or 0.0),
            )
        return list(by_reason.values())

    def _derive_final_balance(self, strategy_block: dict[str, Any]) -> float | None:
        """_derive_final_balance implements function-level backend logic."""
        final_balance = self._lookup_number(strategy_block, "final_balance")
        if final_balance is not None:
            return final_balance
        starting = self._lookup_number(strategy_block, "starting_balance", "dry_run_wallet")
        profit = self._lookup_number(strategy_block, "profit_total_abs", "absolute_profit")
        if starting is None or profit is None:
            return None
        return starting + profit

    def _derive_profit_pct(self, strategy_block: dict[str, Any]) -> float | None:
        """_derive_profit_pct implements function-level backend logic."""
        profit = self._lookup_number(strategy_block, "profit_total", "profit_pct", "net_profit_pct")
        if profit is None:
            return None
        return profit * 100 if abs(profit) <= 1 else profit

    def _derive_drawdown_pct(self, strategy_block: dict[str, Any]) -> float | None:
        """_derive_drawdown_pct implements function-level backend logic."""
        drawdown = self._lookup_number(strategy_block, "max_drawdown_account", "max_drawdown_pct")
        if drawdown is None:
            return None
        return drawdown * 100 if abs(drawdown) <= 1 else drawdown

    def _derive_trades_per_day(self, strategy_block: dict[str, Any], metadata: RunMetadata) -> float | None:
        """_derive_trades_per_day implements function-level backend logic."""
        trades_per_day = self._lookup_number(strategy_block, "trades_per_day")
        if trades_per_day is not None:
            return trades_per_day
        total_trades = self._lookup_int(strategy_block, "total_trades", "trade_count")
        if total_trades is None:
            return None
        if "-" in metadata.timerange:
            start_text, end_text = metadata.timerange.split("-", maxsplit=1)
            if len(start_text) == 8 and len(end_text) == 8:
                from datetime import datetime

                start = datetime.strptime(start_text, "%Y%m%d")
                end = datetime.strptime(end_text, "%Y%m%d")
                days = max((end - start).days, 1)
                return total_trades / days
        return None

    def _derive_win_rate(self, strategy_block: dict[str, Any], trades: list[dict[str, Any]]) -> float | None:
        """_derive_win_rate implements function-level backend logic."""
        win_rate = self._lookup_number(strategy_block, "winrate", "win_rate", "win_rate_pct")
        if win_rate is not None:
            return win_rate * 100 if win_rate <= 1 else win_rate
        if not trades:
            return None
        wins = sum(1 for trade in trades if float(trade.get("profit_abs", 0.0) or 0.0) > 0)
        return wins / len(trades) * 100

    def _derive_loss_rate(self, strategy_block: dict[str, Any], trades: list[dict[str, Any]]) -> float | None:
        """_derive_loss_rate implements function-level backend logic."""
        loss_rate = self._lookup_number(strategy_block, "loss_rate_pct")
        if loss_rate is not None:
            return loss_rate * 100 if loss_rate <= 1 else loss_rate
        win_rate = self._derive_win_rate(strategy_block, trades)
        return None if win_rate is None else max(0.0, 100.0 - win_rate)

    def _derive_avg_duration(self, strategy_block: dict[str, Any], trades: list[dict[str, Any]]) -> float | None:
        """_derive_avg_duration implements function-level backend logic."""
        raw = strategy_block.get("holding_avg") or strategy_block.get("avg_trade_duration") or strategy_block.get(
            "avg_trade_duration_minutes"
        )
        minutes = self._minutes(raw)
        if minutes is not None:
            return minutes
        if not trades:
            return None
        return self._average([self._minutes(trade.get("trade_duration")) for trade in trades])

    def _derive_expectancy(self, strategy_block: dict[str, Any], trades: list[dict[str, Any]]) -> float | None:
        """_derive_expectancy implements function-level backend logic."""
        expectancy = self._lookup_number(strategy_block, "expectancy")
        if expectancy is not None:
            return expectancy
        if not trades:
            return None
        wins = [float(trade.get("profit_abs", 0.0) or 0.0) for trade in trades if float(trade.get("profit_abs", 0.0) or 0.0) > 0]
        losses = [abs(float(trade.get("profit_abs", 0.0) or 0.0)) for trade in trades if float(trade.get("profit_abs", 0.0) or 0.0) <= 0]
        if not wins and not losses:
            return None
        win_rate = len(wins) / len(trades)
        loss_rate = len(losses) / len(trades)
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        return win_rate * avg_win - loss_rate * avg_loss

    def _lookup_number(self, payload: dict[str, Any], *keys: str) -> float | None:
        """_lookup_number implements function-level backend logic."""
        return self._number(payload, *keys)

    def _lookup_int(self, payload: dict[str, Any], *keys: str) -> int | None:
        """_lookup_int implements function-level backend logic."""
        return self._integer(payload, *keys)

    def _number(self, payload: dict[str, Any], *keys: str) -> float | None:
        """_number implements function-level backend logic."""
        for key in keys:
            if key in payload and payload[key] is not None:
                try:
                    return float(payload[key])
                except (TypeError, ValueError):
                    continue
        return None

    def _percent(self, payload: dict[str, Any], *keys: str) -> float | None:
        """_percent implements function-level backend logic."""
        value = self._number(payload, *keys)
        if value is None:
            return None
        return value * 100 if abs(value) <= 1 else value

    def _integer(self, payload: dict[str, Any], *keys: str) -> int | None:
        """_integer implements function-level backend logic."""
        for key in keys:
            if key in payload and payload[key] is not None:
                try:
                    return int(payload[key])
                except (TypeError, ValueError):
                    continue
        return None

    def _minutes(self, raw_value: Any) -> float | None:
        """_minutes implements function-level backend logic."""
        if raw_value is None:
            return None
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        if isinstance(raw_value, str):
            if raw_value.isdigit():
                return float(raw_value)
            parts = raw_value.replace(" days, ", ":").replace(" day, ", ":").split(":")
            try:
                if len(parts) == 3:
                    hours, minutes, seconds = [int(part) for part in parts]
                    return hours * 60 + minutes + seconds / 60
                if len(parts) == 4:
                    days, hours, minutes, seconds = [int(part) for part in parts]
                    return days * 24 * 60 + hours * 60 + minutes + seconds / 60
            except ValueError:
                return None
        return None

    def _average(self, values: list[float | None]) -> float | None:
        """_average implements function-level backend logic."""
        filtered = [value for value in values if value is not None]
        if not filtered:
            return None
        return sum(filtered) / len(filtered)

    def _parse_date_window(self, timerange: str) -> tuple[str | None, str | None, int | None]:
        """Parse a YYYYMMDD-YYYYMMDD timerange into (start_date, end_date, total_days)."""
        if not timerange or "-" not in timerange:
            return None, None, None
        parts = timerange.split("-", maxsplit=1)
        if len(parts) != 2 or len(parts[0]) != 8 or len(parts[1]) != 8:
            return None, None, None
        s_raw, e_raw = parts
        try:
            from datetime import datetime
            start_dt = datetime.strptime(s_raw, "%Y%m%d")
            end_dt = datetime.strptime(e_raw, "%Y%m%d")
            start_date = start_dt.strftime("%Y-%m-%d")
            end_date = end_dt.strftime("%Y-%m-%d")
            total_days = max((end_dt - start_dt).days, 1)
            return start_date, end_date, total_days
        except ValueError:
            return None, None, None

    def _parse_trade(self, payload: dict[str, Any]) -> BacktestTrade:
        """_parse_trade implements function-level backend logic."""
        return BacktestTrade.model_validate(
            {
                "pair": str(payload.get("pair") or "UNKNOWN"),
                "open_date": payload.get("open_date"),
                "close_date": payload.get("close_date"),
                "open_timestamp": payload.get("open_timestamp"),
                "close_timestamp": payload.get("close_timestamp"),
                "stake_amount": payload.get("stake_amount"),
                "max_stake_amount": payload.get("max_stake_amount"),
                "amount": payload.get("amount"),
                "open_rate": payload.get("open_rate"),
                "close_rate": payload.get("close_rate"),
                "fee_open": payload.get("fee_open"),
                "fee_close": payload.get("fee_close"),
                "trade_duration": payload.get("trade_duration"),
                "profit_ratio": payload.get("profit_ratio"),
                "profit_abs": payload.get("profit_abs"),
                "exit_reason": payload.get("exit_reason"),
                "enter_tag": payload.get("enter_tag"),
                "initial_stop_loss_abs": payload.get("initial_stop_loss_abs"),
                "initial_stop_loss_ratio": payload.get("initial_stop_loss_ratio"),
                "stop_loss_abs": payload.get("stop_loss_abs"),
                "stop_loss_ratio": payload.get("stop_loss_ratio"),
                "min_rate": payload.get("min_rate"),
                "max_rate": payload.get("max_rate"),
                "leverage": payload.get("leverage"),
                "is_short": payload.get("is_short"),
                "orders": payload.get("orders") or [],
                "funding_fees": payload.get("funding_fees"),
                "weekday": payload.get("weekday"),
            }
        )

    def _build_advanced_metrics(self, summary: ParsedSummary, trades: list[BacktestTrade]) -> BacktestAdvancedMetrics:
        """_build_advanced_metrics implements function-level backend logic."""
        wins = [t for t in trades if (t.profit_abs or 0.0) > 0]
        losses = [t for t in trades if (t.profit_abs or 0.0) <= 0]
        gross_profit = sum((t.profit_abs or 0.0) for t in wins)
        gross_loss = sum(abs(t.profit_abs or 0.0) for t in losses)
        profit_factor = None if gross_loss == 0 else (gross_profit / gross_loss)

        win_rate = None if not trades else (len(wins) / len(trades) * 100)
        loss_rate = None if win_rate is None else max(0.0, 100.0 - win_rate)

        durations = [float(t.trade_duration) for t in trades if t.trade_duration is not None]
        avg_duration_minutes = (sum(durations) / len(durations)) if durations else None

        return BacktestAdvancedMetrics(
            profit_factor=summary.profit_factor or profit_factor,
            expectancy=summary.expectancy,
            sharpe_ratio=summary.sharpe_ratio,
            sortino_ratio=summary.sortino_ratio,
            calmar_ratio=summary.calmar_ratio,
            max_drawdown_pct=summary.max_drawdown_pct,
            max_drawdown_currency=summary.max_drawdown_currency,
            avg_trade_duration_minutes=summary.avg_trade_duration_minutes or avg_duration_minutes,
            win_rate_pct=summary.win_rate_pct or win_rate,
            loss_rate_pct=summary.loss_rate_pct or loss_rate,
            total_trades=summary.total_trades,
            trades_per_day=summary.trades_per_day,
        )

    def _build_histogram(self, values: list[float], bins: int = 24) -> list[HistogramBin]:
        """_build_histogram implements function-level backend logic."""
        if not values:
            return []
        vmin = min(values)
        vmax = max(values)
        if vmin == vmax:
            return [HistogramBin(left=vmin, right=vmax, count=len(values))]
        step = (vmax - vmin) / bins
        counts = [0 for _ in range(bins)]
        for value in values:
            idx = int((value - vmin) / step)
            if idx >= bins:
                idx = bins - 1
            if idx < 0:
                idx = 0
            counts[idx] += 1
        out: list[HistogramBin] = []
        for i, count in enumerate(counts):
            left = vmin + i * step
            right = left + step
            out.append(HistogramBin(left=left, right=right, count=count))
        return out

    def _build_charts(self, trades: list[BacktestTrade], starting_balance: float | None) -> BacktestCharts:
        """_build_charts implements function-level backend logic."""
        profit_ratios = [float(t.profit_ratio) for t in trades if t.profit_ratio is not None]
        duration_minutes = [float(t.trade_duration) for t in trades if t.trade_duration is not None]

        exit_reason_counts: dict[str, int] = {}
        weekday_profit: dict[int, list[float]] = {}
        for t in trades:
            reason = str(t.exit_reason or "unknown")
            exit_reason_counts[reason] = exit_reason_counts.get(reason, 0) + 1
            if t.weekday is not None and t.profit_abs is not None:
                weekday_profit.setdefault(int(t.weekday), []).append(float(t.profit_abs))

        weekday_winrate: dict[str, float] = {}
        for day, profits in weekday_profit.items():
            if not profits:
                continue
            wins = sum(1 for p in profits if p > 0)
            weekday_winrate[str(day)] = wins / len(profits) * 100

        equity_curve = []
        drawdown_curve = []
        if starting_balance is not None:
            equity = float(starting_balance)
            peak = equity
            for t in sorted(trades, key=(lambda item: item.close_timestamp or item.open_timestamp or 0)):
                if t.close_timestamp is None:
                    continue
                equity += float(t.profit_abs or 0.0)
                if equity > peak:
                    peak = equity
                dd = 0.0 if peak == 0 else ((equity - peak) / peak * 100)
                equity_curve.append({"ts": int(t.close_timestamp), "equity": equity})
                drawdown_curve.append({"ts": int(t.close_timestamp), "drawdown_pct": dd})

        return BacktestCharts(
            equity_curve=equity_curve,
            drawdown_curve=drawdown_curve,
            profit_ratio_histogram=self._build_histogram(profit_ratios, bins=30),
            duration_minutes_histogram=self._build_histogram(duration_minutes, bins=30),
            weekday_winrate=weekday_winrate,
            exit_reason_counts=exit_reason_counts,
        )
