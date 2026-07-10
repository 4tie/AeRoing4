"""Fast VectorBT pre-screening for optimizer parameter candidates."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pandas as pd

from ...models import (
    OptimizerScoreMetric,
    OptimizerScoreWeights,
    OptimizerSession,
    OptimizerTrialMetrics,
    ParameterSearchSpace,
    VectorBTScreeningCandidate,
    VectorBTScreeningReport,
)
from ...settings_store import SettingsStore
from ...utils import detect_data_file_format, get_data_file_path, utc_now
from ..strategy.strategy_optimizer_search import select_parameters_for_trial
from ..strategy.strategy_registry import StrategyRegistry


ScoreFn = Callable[[Any, OptimizerScoreMetric, OptimizerScoreWeights | None], float | None]


@dataclass
class VectorBTScreeningOutcome:
    """Result returned to the optimizer execution loop."""

    report: VectorBTScreeningReport
    selected_parameters: list[dict[str, Any]]


@dataclass
class _RankedCandidate:
    parameters: dict[str, Any]
    metrics: OptimizerTrialMetrics


class VectorBTParameterScreener:
    """Rank optimizer candidates with VectorBT before Freqtrade validation."""

    def __init__(
        self,
        settings_store: SettingsStore,
        registry: StrategyRegistry,
        vectorbt_module: Any | None = None,
    ) -> None:
        self.settings_store = settings_store
        self.registry = registry
        self._vectorbt_module = vectorbt_module

    async def screen_parameter_spaces(
        self,
        session: OptimizerSession,
        spaces: list[ParameterSearchSpace],
        score_fn: ScoreFn | None = None,
    ) -> VectorBTScreeningOutcome:
        """Run screening in a worker thread so the API loop stays responsive."""
        return await asyncio.to_thread(
            self.screen_parameter_spaces_sync,
            session,
            spaces,
            score_fn,
        )

    def screen_parameter_spaces_sync(
        self,
        session: OptimizerSession,
        spaces: list[ParameterSearchSpace],
        score_fn: ScoreFn | None = None,
    ) -> VectorBTScreeningOutcome:
        """Evaluate and rank candidate parameter sets with VectorBT."""
        started_at = utc_now()
        started_monotonic = time.monotonic()
        config = session.config

        if not config.enable_vectorbt_screening:
            return self._skipped(started_at, started_monotonic, "disabled")

        enabled_spaces = [space for space in spaces if space.enabled]
        if not enabled_spaces:
            return self._skipped(started_at, started_monotonic, "no_enabled_spaces")

        try:
            vbt = self._load_vectorbt()
        except Exception as exc:
            return self._skipped(
                started_at,
                started_monotonic,
                "vectorbt_unavailable",
                error=str(exc),
            )

        try:
            candles = self._load_market_data(config.pairs, config.timeframe, config.timerange)
        except Exception as exc:
            return self._skipped(
                started_at,
                started_monotonic,
                "missing_data",
                error=str(exc),
            )

        try:
            strategy_cls = self._load_strategy_class(config.strategy_name)
        except Exception as exc:
            return self._skipped(
                started_at,
                started_monotonic,
                "strategy_load_failed",
                error=str(exc),
            )

        candidates = self._generate_candidates(session, enabled_spaces)
        if not candidates:
            return self._skipped(started_at, started_monotonic, "no_candidates")

        ranked: list[_RankedCandidate] = []
        timed_out = False
        last_error: str | None = None
        timeout_seconds = max(int(config.vectorbt_timeout_seconds), 1)

        for parameters in candidates:
            if time.monotonic() - started_monotonic >= timeout_seconds:
                timed_out = True
                break
            try:
                metrics = self._evaluate_candidate(
                    vbt=vbt,
                    strategy_cls=strategy_cls,
                    candles=candles,
                    parameters=parameters,
                    session=session,
                    score_fn=score_fn,
                )
            except Exception as exc:
                last_error = str(exc)
                continue
            ranked.append(_RankedCandidate(parameters=parameters, metrics=metrics))

        if not ranked:
            reason = "timeout" if timed_out else "no_successful_candidates"
            return self._skipped(
                started_at,
                started_monotonic,
                reason,
                error=last_error,
            )

        ranked.sort(
            key=lambda item: (
                item.metrics.score is not None,
                item.metrics.score if item.metrics.score is not None else float("-inf"),
            ),
            reverse=True,
        )
        keep_target = max(
            int(config.total_trials),
            int(math.ceil(len(ranked) * float(config.vectorbt_keep_ratio))),
        )
        selected = ranked[: min(keep_target, len(ranked))]
        duration = round(time.monotonic() - started_monotonic, 3)
        top = [
            VectorBTScreeningCandidate(
                rank=index,
                parameters=item.parameters,
                metrics=item.metrics,
            )
            for index, item in enumerate(ranked[:20], start=1)
        ]
        selected_count = len(selected)
        evaluated_count = len(ranked)
        reduction_pct = (
            round(max(0.0, 100.0 * (1.0 - (selected_count / evaluated_count))), 3)
            if evaluated_count
            else None
        )
        report = VectorBTScreeningReport(
            status="partial" if timed_out else "completed",
            started_at=started_at,
            completed_at=utc_now(),
            evaluated_count=evaluated_count,
            selected_count=selected_count,
            reduction_pct=reduction_pct,
            duration_seconds=duration,
            skipped_reason="timeout" if timed_out else None,
            error=last_error if timed_out else None,
            top_candidates=top,
        )
        return VectorBTScreeningOutcome(
            report=report,
            selected_parameters=[item.parameters for item in selected],
        )

    def _load_vectorbt(self) -> Any:
        if self._vectorbt_module is not None:
            return self._vectorbt_module
        import vectorbt as vbt  # type: ignore

        return vbt

    def _load_market_data(
        self,
        pairs: list[str],
        timeframe: str,
        timerange: str,
    ) -> dict[str, pd.DataFrame]:
        settings = self.settings_store.load()
        user_data_dir = settings.user_data_directory_path
        candles: dict[str, pd.DataFrame] = {}
        for pair in pairs:
            data_format = detect_data_file_format(user_data_dir, pair, timeframe)
            data_file = get_data_file_path(user_data_dir, pair, timeframe, "binance", data_format)
            if not data_file.exists():
                raise FileNotFoundError(f"{pair} data file not found at {data_file}")
            df = self._read_candles(data_file, data_format)
            df = self._filter_timerange(df, timerange)
            if df.empty:
                raise ValueError(f"{pair} has no candles inside timerange {timerange}")
            candles[pair] = df
        if not candles:
            raise ValueError("No pairs were provided for screening")
        return candles

    def _read_candles(self, data_file: Path, data_format: str) -> pd.DataFrame:
        if data_format == "feather":
            df = pd.read_feather(data_file)
        else:
            raw = json.loads(data_file.read_text(encoding="utf-8"))
            df = pd.DataFrame(raw, columns=["date", "open", "high", "low", "close", "volume"])

        required = {"date", "open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"{data_file} missing candle columns: {sorted(missing)}")
        df = df[["date", "open", "high", "low", "close", "volume"]].copy()
        if pd.api.types.is_integer_dtype(df["date"]):
            df["date"] = pd.to_datetime(df["date"], unit="ms", utc=True)
        else:
            df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
        df = df.dropna(subset=["date", "close"]).sort_values("date")
        for column in ("open", "high", "low", "close", "volume"):
            df[column] = pd.to_numeric(df[column], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close", "volume"])
        return df.set_index("date", drop=False)

    def _filter_timerange(self, df: pd.DataFrame, timerange: str) -> pd.DataFrame:
        start_text, end_text = timerange.split("-", maxsplit=1)
        result = df
        if len(start_text) == 8:
            start = datetime.strptime(start_text, "%Y%m%d").replace(tzinfo=timezone.utc)
            result = result[result.index >= start]
        if len(end_text) == 8:
            end = datetime.strptime(end_text, "%Y%m%d").replace(tzinfo=timezone.utc)
            result = result[result.index <= end]
        return result

    def _load_strategy_class(self, strategy_name: str) -> type:
        record = self.registry.get_strategy(strategy_name)
        strategy_path = Path(record.file_path)
        module_name = f"_vectorbt_screen_{strategy_name}_{abs(hash(strategy_path))}"
        spec = importlib.util.spec_from_file_location(module_name, strategy_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not import strategy from {strategy_path}")
        module = importlib.util.module_from_spec(spec)
        parent = str(strategy_path.parent)
        added_path = False
        if parent not in sys.path:
            sys.path.insert(0, parent)
            added_path = True
        try:
            spec.loader.exec_module(module)
        finally:
            if added_path:
                try:
                    sys.path.remove(parent)
                except ValueError:
                    pass
        strategy_cls = getattr(module, strategy_name, None)
        if isinstance(strategy_cls, type):
            return strategy_cls
        for value in module.__dict__.values():
            if isinstance(value, type) and value.__name__ == strategy_name:
                return value
        raise RuntimeError(f"Strategy class '{strategy_name}' was not found in {strategy_path}")

    def _generate_candidates(
        self,
        session: OptimizerSession,
        spaces: list[ParameterSearchSpace],
    ) -> list[dict[str, Any]]:
        target = max(int(session.config.vectorbt_candidate_count), 1)
        attempts = max(target * 10, target + 20)
        candidates: list[dict[str, Any]] = []
        seen = {
            self._params_key(trial.parameters)
            for trial in session.trials
            if trial.parameters
        }
        for trial_number in range(1, attempts + 1):
            params = select_parameters_for_trial(session, spaces, trial_number)
            if not params:
                continue
            key = self._params_key(params)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(params)
            if len(candidates) >= target:
                break
        return candidates

    def _evaluate_candidate(
        self,
        *,
        vbt: Any,
        strategy_cls: type,
        candles: dict[str, pd.DataFrame],
        parameters: dict[str, Any],
        session: OptimizerSession,
        score_fn: ScoreFn | None,
    ) -> OptimizerTrialMetrics:
        close_cols: dict[str, pd.Series] = {}
        entry_cols: dict[str, pd.Series] = {}
        exit_cols: dict[str, pd.Series] = {}

        for pair, base_df in candles.items():
            strategy = self._instantiate_strategy(strategy_cls)
            self._apply_parameters(strategy, parameters)
            df = base_df.copy(deep=True)
            if hasattr(strategy, "populate_indicators"):
                next_df = strategy.populate_indicators(df, {"pair": pair})
                if next_df is not None:
                    df = next_df
            if hasattr(strategy, "populate_entry_trend"):
                next_df = strategy.populate_entry_trend(df, {"pair": pair})
                if next_df is not None:
                    df = next_df
            if hasattr(strategy, "populate_exit_trend"):
                next_df = strategy.populate_exit_trend(df, {"pair": pair})
                if next_df is not None:
                    df = next_df
            close_cols[pair] = pd.to_numeric(df["close"], errors="coerce")
            entry_cols[pair] = self._signal_series(df, ("enter_long", "buy"))
            exit_cols[pair] = self._signal_series(df, ("exit_long", "sell"))

        close = pd.DataFrame(close_cols).dropna(how="any")
        if close.empty:
            raise ValueError("No aligned close prices available for VectorBT")
        entries = pd.DataFrame(entry_cols).reindex(close.index).fillna(False).astype(bool)
        exits = pd.DataFrame(exit_cols).reindex(close.index).fillna(False).astype(bool)

        kwargs: dict[str, Any] = {
            "init_cash": session.config.dry_run_wallet,
            "fees": session.config.fee_rate,
            "freq": self._to_pandas_freq(session.config.timeframe),
        }
        stoploss = self._candidate_stoploss(parameters)
        if stoploss is not None:
            kwargs["sl_stop"] = stoploss

        try:
            portfolio = vbt.Portfolio.from_signals(
                close,
                entries,
                exits,
                cash_sharing=True,
                group_by=True,
                **kwargs,
            )
        except TypeError:
            portfolio = vbt.Portfolio.from_signals(close, entries, exits, **kwargs)

        metrics = self._portfolio_metrics(portfolio)
        score = self._score(metrics, session.config.score_metric, session.config.score_weights, score_fn)
        return metrics.model_copy(update={"score": score})

    def _instantiate_strategy(self, strategy_cls: type) -> Any:
        try:
            return strategy_cls()
        except TypeError:
            return strategy_cls({})

    def _apply_parameters(self, strategy: Any, parameters: dict[str, Any]) -> None:
        for name, value in parameters.items():
            if name == "stoploss__value":
                setattr(strategy, "stoploss", float(value))
                continue
            if name.startswith("roi__"):
                roi = dict(getattr(strategy, "minimal_roi", {}) or {})
                roi[name[5:]] = float(value)
                setattr(strategy, "minimal_roi", roi)
                continue
            if name == "trailing__stop":
                setattr(strategy, "trailing_stop", bool(value))
                continue
            if name == "trailing__positive":
                setattr(strategy, "trailing_stop_positive", float(value))
                continue
            if name == "trailing__offset":
                setattr(strategy, "trailing_stop_positive_offset", float(value))
                continue

            parameter_obj = getattr(strategy, name, None)
            if parameter_obj is not None and hasattr(parameter_obj, "value"):
                try:
                    parameter_obj = copy.copy(parameter_obj)
                    setattr(strategy, name, parameter_obj)
                except Exception:
                    pass
                try:
                    parameter_obj.value = value
                except Exception:
                    setattr(strategy, name, value)
            elif hasattr(strategy, name):
                setattr(strategy, name, value)

            for container_name in ("buy_params", "sell_params", "protection_params"):
                container = getattr(strategy, container_name, None)
                if isinstance(container, dict) and name in container:
                    container[name] = value

    def _signal_series(self, df: pd.DataFrame, names: tuple[str, ...]) -> pd.Series:
        for name in names:
            if name in df.columns:
                return df[name].fillna(0).astype(bool)
        return pd.Series(False, index=df.index)

    def _portfolio_metrics(self, portfolio: Any) -> OptimizerTrialMetrics:
        net_profit_pct = self._call_metric(portfolio, "total_return", multiplier=100.0)
        net_profit_abs = self._call_metric(portfolio, "total_profit")
        max_drawdown_pct = self._call_metric(portfolio, "max_drawdown", multiplier=100.0)
        sharpe_ratio = self._call_metric(portfolio, "sharpe_ratio")
        trades = getattr(portfolio, "trades", None)
        total_trades = self._call_metric(trades, "count", aggregate="sum") if trades is not None else None
        win_rate = self._call_metric(trades, "win_rate") if trades is not None else None
        if win_rate is not None and abs(win_rate) <= 1.0:
            win_rate *= 100.0
        profit_factor = self._call_metric(trades, "profit_factor") if trades is not None else None
        return OptimizerTrialMetrics(
            net_profit_pct=net_profit_pct,
            net_profit_abs=net_profit_abs,
            win_rate_pct=win_rate,
            max_drawdown_pct=max_drawdown_pct,
            total_trades=int(total_trades) if total_trades is not None else None,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
        )

    def _score(
        self,
        metrics: OptimizerTrialMetrics,
        metric: OptimizerScoreMetric,
        weights: OptimizerScoreWeights,
        score_fn: ScoreFn | None,
    ) -> float | None:
        summary = SimpleNamespace(
            net_profit_pct=metrics.net_profit_pct,
            net_profit_currency=metrics.net_profit_abs,
            sharpe_ratio=metrics.sharpe_ratio,
            profit_factor=metrics.profit_factor,
            win_rate_pct=metrics.win_rate_pct,
            max_drawdown_pct=metrics.max_drawdown_pct,
            total_trades=metrics.total_trades,
        )
        if score_fn is not None:
            return self._finite_or_none(score_fn(summary, metric, weights))
        return self._finite_or_none(self._compute_score(summary, metric, weights))

    def _compute_score(
        self,
        summary: Any,
        metric: OptimizerScoreMetric,
        weights: OptimizerScoreWeights,
    ) -> float | None:
        if metric == OptimizerScoreMetric.TOTAL_PROFIT_PCT:
            return summary.net_profit_pct
        if metric == OptimizerScoreMetric.NET_PROFIT_ABS:
            return summary.net_profit_currency
        if metric == OptimizerScoreMetric.SHARPE_RATIO:
            return summary.sharpe_ratio
        if metric == OptimizerScoreMetric.PROFIT_FACTOR:
            return summary.profit_factor
        if metric == OptimizerScoreMetric.WIN_RATE:
            return summary.win_rate_pct
        if metric == OptimizerScoreMetric.MAX_DRAWDOWN_PCT:
            if summary.max_drawdown_pct is None:
                return None
            return -abs(float(summary.max_drawdown_pct))
        if metric == OptimizerScoreMetric.TOTAL_TRADES:
            if summary.total_trades is None:
                return None
            return float(summary.total_trades)

        score = 0.0
        weight_total = 0.0
        if summary.net_profit_pct is not None and weights.net_profit_pct != 0.0:
            score += summary.net_profit_pct * weights.net_profit_pct
            weight_total += abs(weights.net_profit_pct)
        if summary.net_profit_currency is not None and weights.net_profit_abs != 0.0:
            score += summary.net_profit_currency * weights.net_profit_abs
            weight_total += abs(weights.net_profit_abs)
        if summary.sharpe_ratio is not None and weights.sharpe_ratio != 0.0:
            score += summary.sharpe_ratio * weights.sharpe_ratio
            weight_total += abs(weights.sharpe_ratio)
        if summary.profit_factor is not None and weights.profit_factor != 0.0:
            score += min(summary.profit_factor, 100.0) * weights.profit_factor
            weight_total += abs(weights.profit_factor)
        if summary.win_rate_pct is not None and weights.win_rate_pct != 0.0:
            score += summary.win_rate_pct * weights.win_rate_pct
            weight_total += abs(weights.win_rate_pct)
        if summary.max_drawdown_pct is not None and weights.max_drawdown_pct != 0.0:
            score -= abs(float(summary.max_drawdown_pct)) * weights.max_drawdown_pct
            weight_total += abs(weights.max_drawdown_pct)
        if summary.total_trades is not None and weights.total_trades != 0.0:
            score += float(summary.total_trades) * weights.total_trades
            weight_total += abs(weights.total_trades)
        if weight_total == 0:
            return None
        return score

    def _call_metric(
        self,
        owner: Any,
        name: str,
        *,
        multiplier: float = 1.0,
        aggregate: str = "mean",
    ) -> float | None:
        if owner is None:
            return None
        attr = getattr(owner, name, None)
        if attr is None:
            return None
        value = attr() if callable(attr) else attr
        number = self._as_number(value, aggregate=aggregate)
        return self._finite_or_none(number * multiplier) if number is not None else None

    def _as_number(self, value: Any, *, aggregate: str = "mean") -> float | None:
        if value is None:
            return None
        if isinstance(value, pd.DataFrame):
            series = value.select_dtypes(include="number").stack()
            if series.empty:
                return None
            return self._finite_or_none(series.sum() if aggregate == "sum" else series.mean())
        if isinstance(value, pd.Series):
            numeric = pd.to_numeric(value, errors="coerce").dropna()
            if numeric.empty:
                return None
            return self._finite_or_none(numeric.sum() if aggregate == "sum" else numeric.mean())
        if isinstance(value, (list, tuple)):
            numeric = pd.to_numeric(pd.Series(value), errors="coerce").dropna()
            if numeric.empty:
                return None
            return self._finite_or_none(numeric.sum() if aggregate == "sum" else numeric.mean())
        try:
            return self._finite_or_none(value)
        except (TypeError, ValueError):
            try:
                return self._finite_or_none(value.item())
            except Exception:
                return None

    def _finite_or_none(self, value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    def _candidate_stoploss(self, parameters: dict[str, Any]) -> float | None:
        value = parameters.get("stoploss__value")
        if value is None:
            return None
        try:
            stoploss = abs(float(value))
        except (TypeError, ValueError):
            return None
        return stoploss if stoploss > 0 else None

    def _to_pandas_freq(self, timeframe: str) -> str:
        if timeframe.endswith("m"):
            return f"{timeframe[:-1]}min"
        return timeframe

    def _params_key(self, params: dict[str, Any]) -> str:
        return json.dumps(params, sort_keys=True, default=str, separators=(",", ":"))

    def _skipped(
        self,
        started_at: Any,
        started_monotonic: float,
        reason: str,
        *,
        error: str | None = None,
    ) -> VectorBTScreeningOutcome:
        report = VectorBTScreeningReport(
            status="skipped",
            started_at=started_at,
            completed_at=utc_now(),
            evaluated_count=0,
            selected_count=0,
            reduction_pct=None,
            duration_seconds=round(time.monotonic() - started_monotonic, 3),
            skipped_reason=reason,
            error=error,
            top_candidates=[],
        )
        return VectorBTScreeningOutcome(report=report, selected_parameters=[])
