"""Policy single source of truth for AutoQuant robustness decisions.

All thresholds, score weights, timeframe mappings, readiness labels, and pair
universe targets are loaded from backend/config. Pipeline stages should import
from this module instead of duplicating policy values.
"""

from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any


CONFIG_ROOT = Path(__file__).resolve().parents[3] / "config"

DEFAULT_DATE_RANGES = {
    "quick": ("20230101-20240101", "20240101-20240601"),
    "standard": ("20230101-20240101", "20240101-20241201"),
    "deep": ("20220101-20240101", "20240101-20250101"),
}


def subtract_months(dt: datetime, months: int) -> datetime:
    """Subtract exact calendar months from a datetime, preserving day when possible.

    This uses stdlib calendar to handle month/year rollovers correctly and clamps
    to the last day of the target month when necessary (e.g., Jan 31 - 1 month = Dec 31).

    Args:
        dt: Source datetime
        months: Number of months to subtract (must be >= 0)

    Returns:
        New datetime with months subtracted, day clamped to valid date in target month

    Example:
        >>> subtract_months(datetime(2024, 1, 31), 1)
        datetime(2023, 12, 31)
        >>> subtract_months(datetime(2024, 3, 31), 1)
        datetime(2024, 2, 29)  # Clamped to Feb 29 in leap year
    """
    if months < 0:
        raise ValueError("months must be non-negative")
    if months == 0:
        return dt

    year = dt.year
    month = dt.month
    day = dt.day

    # Calculate target year and month
    total_months = year * 12 + month - months
    target_year = total_months // 12
    target_month = total_months % 12

    if target_month == 0:
        target_year -= 1
        target_month = 12

    # Get last day of target month
    last_day_of_month = calendar.monthrange(target_year, target_month)[1]

    # Clamp day to valid date in target month
    target_day = min(day, last_day_of_month)

    return datetime(target_year, target_month, target_day, dt.hour, dt.minute, dt.second, dt.microsecond)


DEPTH_SETTINGS = {
    "quick": {
        "hyperopt_epochs": 30,
        "wfo_enabled": False,
        "wfo_required": False,
        "is_lookback_months": 18,
        "oos_lookback_months": 6,
    },
    "standard": {
        "hyperopt_epochs": 100,
        "wfo_enabled": True,
        "wfo_required": False,
        "is_lookback_months": 24,
        "oos_lookback_months": 12,
    },
    "deep": {
        "hyperopt_epochs": 150,
        "wfo_enabled": True,
        "wfo_required": True,
        "is_lookback_months": 36,
        "oos_lookback_months": 12,
    },
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_decimal(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return numeric / 100.0 if abs(numeric) > 1 else numeric


def _as_percent(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return numeric if abs(numeric) > 1 else numeric * 100.0


def _valid_choice(value: Any, choices: set[str], default: str) -> str:
    text = str(value or default).strip().lower()
    return text if text in choices else default


def _parse_timerange_days(timerange: str | None) -> int | None:
    if not timerange or "-" not in timerange:
        return None

    start_raw, end_raw = timerange.split("-", 1)
    if not start_raw or not end_raw:
        return None

    try:
        start = datetime.strptime(start_raw[:8], "%Y%m%d")
        end = datetime.strptime(end_raw[:8], "%Y%m%d")
    except ValueError:
        return None

    days = (end - start).days
    return days if days > 0 else None


def _adaptive_min_trades(
    *,
    min_trades_per_year: int | float | None,
    min_trades_floor: int | None,
    min_trades_cap: int | None,
    timerange_days: int | None,
    fallback_min_trades: int | None = None,
) -> int:
    floor = int(min_trades_floor or fallback_min_trades or 1)
    cap = int(min_trades_cap or max(floor, fallback_min_trades or floor))
    per_year = float(min_trades_per_year or fallback_min_trades or floor)

    if not timerange_days:
        fallback = int(round(fallback_min_trades or floor))
        return max(floor, min(cap, fallback))

    scaled = int(round(per_year * (timerange_days / 365.0)))
    return max(floor, min(cap, scaled))


def _resolve_dynamic_thresholds(gates: dict[str, Any], timerange_days: int | None) -> dict[str, Any]:
    resolved = dict(gates)
    fallback_raw = resolved.get("min_trades")
    try:
        fallback_min_trades = int(fallback_raw) if fallback_raw is not None else None
    except (TypeError, ValueError):
        fallback_min_trades = None

    resolved["min_trades"] = _adaptive_min_trades(
        min_trades_per_year=resolved.get("min_trades_per_year"),
        min_trades_floor=resolved.get("min_trades_floor"),
        min_trades_cap=resolved.get("min_trades_cap"),
        timerange_days=timerange_days,
        fallback_min_trades=fallback_min_trades,
    )
    return resolved


def normalize_decimal(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric / 100.0 if abs(numeric) > 1 else numeric


def normalize_percent(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if abs(numeric) > 1 else numeric * 100.0


def latest_complete_day(now: datetime | None = None) -> datetime:
    """Return the latest complete day for data validation.

    For Freqtrade-style timeranges, the end date should be the next boundary
    so the run includes data through the last complete day.

    Args:
        now: Current datetime for testing (defaults to datetime.utcnow())

    Returns:
        datetime representing the latest complete day (yesterday UTC)
    """
    if now is None:
        now = datetime.utcnow()
    return (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def date_ranges_for_depth(
    depth: str,
    as_of: datetime | None = None,
    latest_data_end: datetime | None = None,
) -> tuple[str, str]:
    """Generate dynamic date ranges for a given analysis depth.

    Ranges are calculated relative to the latest complete day, not hard-coded.
    This ensures validation stays current as time progresses.
    Uses exact calendar-month arithmetic via subtract_months().

    Args:
        depth: Analysis depth ("quick", "standard", or "deep")
        as_of: Reference date for calculation (defaults to now)
        latest_data_end: Override latest data end date (defaults to latest_complete_day)

    Returns:
        Tuple of (in_sample_range, out_sample_range) in Freqtrade format (YYYYMMDD-YYYYMMDD)

    Example for 2026-06-23:
        quick: ("20241223-20260101", "20260101-20260623")
        standard: ("20230623-20250623", "20250623-20260623")
        deep: ("20220623-20250623", "20250623-20260623")
    """
    if depth not in DEPTH_SETTINGS:
        depth = "standard"

    settings = DEPTH_SETTINGS[depth]
    is_months = settings["is_lookback_months"]
    oos_months = settings["oos_lookback_months"]

    if latest_data_end is None:
        latest_data_end = latest_complete_day(as_of)

    # Calculate OOS end (next day boundary to include last complete day)
    oos_end = latest_data_end + timedelta(days=1)

    # Calculate OOS start using exact calendar-month arithmetic
    oos_start = subtract_months(oos_end, oos_months)

    # Calculate IS end (same as OOS start)
    is_end = oos_start

    # Calculate IS start using exact calendar-month arithmetic
    is_start = subtract_months(is_end, is_months)

    # Format as Freqtrade timeranges
    is_range = f"{is_start.strftime('%Y%m%d')}-{is_end.strftime('%Y%m%d')}"
    oos_range = f"{oos_start.strftime('%Y%m%d')}-{oos_end.strftime('%Y%m%d')}"

    return is_range, oos_range


def walk_forward_windows_for_depth(
    depth: str,
    as_of: datetime | None = None,
    latest_data_end: datetime | None = None,
) -> list[dict[str, str]]:
    """Generate walk-forward windows for a given analysis depth.

    Windows are rolling and end at the latest data, ensuring recent market
    conditions are tested. The latest window must not fail catastrophically
    for a strategy to be considered Validated or Elite.
    Uses exact calendar-month arithmetic via subtract_months().

    Args:
        depth: Analysis depth ("quick", "standard", or "deep")
        as_of: Reference date for calculation (defaults to now)
        latest_data_end: Override latest data end date (defaults to latest_complete_day)

    Returns:
        List of window dicts with "train" and "test" ranges in Freqtrade format

    Example for deep depth on 2026-06-23:
        [
            {"train": "20220623-20230623", "test": "20230623-20231223"},
            {"train": "20230101-20240101", "test": "20240101-20240701"},
            ...
            {"train": "20250101-20260101", "test": "20260101-20260623"},
        ]
    """
    if depth not in DEPTH_SETTINGS:
        depth = "standard"

    settings = DEPTH_SETTINGS[depth]

    # Skip WFO for quick depth
    if depth == "quick":
        return []

    if latest_data_end is None:
        latest_data_end = latest_complete_day(as_of)

    # Calculate window count based on depth
    if depth == "standard":
        window_count = 3
    else:  # deep
        window_count = 6

    windows = []
    train_months = 12
    test_months = 6

    # Generate rolling windows ending at latest data
    for i in range(window_count):
        # Calculate test end (next day boundary)
        test_end = latest_data_end + timedelta(days=1)

        # Calculate test start using exact calendar-month arithmetic
        test_start = subtract_months(test_end, test_months)

        # Calculate train end (same as test start)
        train_end = test_start

        # Calculate train start using exact calendar-month arithmetic
        train_start = subtract_months(train_end, train_months)

        # Shift windows backward for earlier iterations using calendar-month arithmetic
        shift_months = (window_count - 1 - i) * 6
        train_start = subtract_months(train_start, shift_months)
        train_end = subtract_months(train_end, shift_months)
        test_start = subtract_months(test_start, shift_months)
        test_end = subtract_months(test_end, shift_months)

        windows.append({
            "train": f"{train_start.strftime('%Y%m%d')}-{train_end.strftime('%Y%m%d')}",
            "test": f"{test_start.strftime('%Y%m%d')}-{test_end.strftime('%Y%m%d')}",
        })

    return windows


@dataclass(frozen=True)
class Policy:
    timeframes: dict[str, Any]
    risk_profiles: dict[str, Any]
    pair_universe: dict[str, Any]
    score_weights: dict[str, Any]
    readiness_labels: dict[str, Any]
    thresholds: dict[str, dict[str, Any]]

    @property
    def versions(self) -> dict[str, str]:
        return {
            "timeframes": self.timeframes.get("version", "unknown"),
            "risk_profiles": self.risk_profiles.get("version", "unknown"),
            "pair_universe": self.pair_universe.get("version", "unknown"),
            "score_weights": self.score_weights.get("version", "unknown"),
            "readiness_labels": self.readiness_labels.get("version", "unknown"),
            "thresholds": ",".join(
                f"{style}:{data.get('version', 'legacy')}"
                for style, data in sorted(self.thresholds.items())
            ),
        }

    def style_timeframes(self, style: str) -> list[str]:
        styles = self.timeframes.get("styles", {})
        return list(styles.get(style, styles.get("swing", [])))

    def unsupported_timeframes(self) -> set[str]:
        return set(self.timeframes.get("unsupported_graceful", []))

    def risk_profile(self, risk_profile: str) -> dict[str, Any]:
        profiles = self.risk_profiles.get("profiles", {})
        return dict(profiles.get(risk_profile, profiles.get("balanced", {})))

    def thresholds_for(
        self,
        style: str,
        risk_profile: str = "balanced",
        tier: str = "validation",
        *,
        timerange: str | None = None,
        timerange_days: int | None = None,
    ) -> dict[str, Any]:
        style_thresholds = self.thresholds.get(style) or self.thresholds.get("swing", {})
        raw = dict(style_thresholds.get(tier) or style_thresholds.get("validation") or {})
        risk = self.risk_profile(risk_profile)

        if "max_drawdown" in raw:
            raw["max_drawdown"] = _as_decimal(raw["max_drawdown"]) * float(
                risk.get("drawdown_multiplier", 1.0)
            )
        if "min_win_rate" in raw:
            raw["min_win_rate"] = _as_decimal(raw["min_win_rate"])
        if "min_profit_factor" in raw:
            adjusted = float(raw["min_profit_factor"]) + float(risk.get("profit_factor_delta", 0.0))
            floor = risk.get("min_profit_factor_floor")
            raw["min_profit_factor"] = max(float(floor), adjusted) if floor is not None else adjusted
        if "min_oos_profit" in raw:
            raw["min_oos_profit"] = _as_decimal(raw["min_oos_profit"])
        resolved_days = timerange_days if timerange_days is not None else _parse_timerange_days(timerange)
        return _resolve_dynamic_thresholds(raw, resolved_days)

    def discovery_timeframe_gates(self, style: str, risk_profile: str = "balanced") -> dict[str, Any]:
        """Return permissive discovery gates for timeframe testing.
        
        Discovery gates are intentionally permissive to avoid rejecting strategies
        during the discovery phase. They use lower thresholds than validation gates.
        """
        return self.thresholds_for(style, risk_profile, "discovery")

    def discovery_pair_gates(self, style: str, risk_profile: str = "balanced") -> dict[str, Any]:
        """Return permissive discovery gates for pair universe testing.
        
        Discovery gates are intentionally permissive to avoid rejecting strategies
        during the discovery phase. They use lower thresholds than validation gates.
        """
        return self.thresholds_for(style, risk_profile, "discovery")

    def min_wfo_windows(self) -> int:
        """Return minimum number of WFO windows required for execution.
        
        Returns 3 as the minimum to ensure statistical significance.
        """
        return 3

    def wfo_skip_note(self, window_count: int) -> str:
        """Return validation note for WFO skip due to insufficient windows.
        
        Args:
            window_count: Number of available windows
            
        Returns:
            Validation note message
        """
        return (
            f"Walk-Forward Optimization skipped: only {window_count} valid window(s) found, "
            f"minimum {self.min_wfo_windows()} required. "
            f"Pipeline will continue with standard hyperopt results."
        )

    def pair_target_count(self, style: str, risk_profile: str) -> int:
        counts = self.pair_universe.get("target_counts", {})
        style_counts = counts.get(style, counts.get("swing", {}))
        profile_key = self.risk_profile(risk_profile).get("pair_count_key", risk_profile)
        return int(style_counts.get(profile_key, style_counts.get("balanced", 0)))

    def default_pair_universe(
        self,
        style: str,
        risk_profile: str = "balanced",
        override: list[str] | None = None,
    ) -> list[str]:
        if override:
            return list(dict.fromkeys(override))
        tiers = self.pair_universe.get("tiers", {})
        ordered: list[str] = []
        for tier_name in ("A", "B", "C"):
            ordered.extend(tiers.get(tier_name, []))
        target = self.pair_target_count(style, risk_profile)
        return list(dict.fromkeys(ordered))[:target] if target else list(dict.fromkeys(ordered))

    def score_strategy(
        self,
        *,
        metrics: dict[str, Any],
        style: str,
        risk_profile: str,
        robustness_score: float | None = None,
        oos_score: float | None = None,
        walk_forward_score: float | None = None,
        pair_consistency_score: float | None = None,
    ) -> dict[str, Any]:
        weights = self.score_weights.get("weights", {})
        gates = self.thresholds_for(style, risk_profile, "validation")

        min_expectancy = float(gates.get("min_expectancy") or 0.0)
        min_pf = float(gates.get("min_profit_factor") or 1.0)
        max_dd = float(gates.get("max_drawdown") or 1.0)
        min_trades = max(1, int(gates.get("min_trades") or 1))

        expectancy = float(metrics.get("expectancy", metrics.get("profit_mean_pct", 0.0)) or 0.0)
        profit_factor = float(metrics.get("profit_factor") or 0.0)
        drawdown = _as_decimal(metrics.get("max_drawdown_account", metrics.get("drawdown", 0.0)))
        trades = int(metrics.get("total_trades", metrics.get("trades", 0)) or 0)

        components = {
            "expectancy": _bounded_ratio(expectancy, min_expectancy),
            "profit_factor": _bounded_ratio(max(0.0, profit_factor - 1.0), max(0.01, min_pf - 1.0)),
            "drawdown": max(0.0, min(100.0, 100.0 * (1.0 - (drawdown / max(max_dd, 0.01))))),
            "robustness": _score_passthrough(robustness_score),
            "oos": _score_passthrough(oos_score),
            "walk_forward": _score_passthrough(walk_forward_score),
            "pair_consistency": _score_passthrough(pair_consistency_score),
            "trade_quality": min(100.0, trades / min_trades * 100.0),
        }

        weighted = 0.0
        total_weight = 0.0
        for key, weight in weights.items():
            weighted += components.get(key, 0.0) * float(weight)
            total_weight += float(weight)
        overall = weighted / total_weight if total_weight else 0.0

        label = self.readiness_for_score(overall)
        return {
            "overall": round(max(0.0, min(100.0, overall)), 2),
            "components": {k: round(v, 2) for k, v in components.items()},
            "status": label["status"],
            "readiness_label": label["readiness"],
            "explanation": _score_explanation(components),
        }

    def readiness_for_score(self, score: float) -> dict[str, str]:
        labels = sorted(
            self.readiness_labels.get("labels", []),
            key=lambda item: float(item.get("min_score", 0)),
            reverse=True,
        )
        for item in labels:
            if score >= float(item.get("min_score", 0)):
                return {
                    "status": str(item.get("status", "Rejected")),
                    "readiness": str(item.get("readiness", "Not Ready")),
                }
        return {"status": "Rejected", "readiness": "Not Ready"}

    def build_run_config(
        self,
        *,
        payload: dict[str, Any],
        settings: Any | None = None,
    ) -> dict[str, Any]:
        """Normalize old and new start payloads into one internal run config."""
        advanced = dict(payload.get("advanced_overrides") or {})
        style = _valid_choice(
            payload.get("trading_style") or advanced.get("trading_style"),
            {"scalping", "intraday", "swing", "position"},
            "swing",
        )
        risk = _valid_choice(
            payload.get("risk_profile") or advanced.get("risk_profile"),
            set(self.risk_profiles.get("profiles", {})),
            "balanced",
        )
        depth = _valid_choice(
            payload.get("analysis_depth") or advanced.get("analysis_depth"),
            set(DEPTH_SETTINGS),
            "deep",
        )

        configured_timeframes = self.style_timeframes(style)
        unsupported = self.unsupported_timeframes()
        supported_timeframes = [tf for tf in configured_timeframes if tf not in unsupported]
        explicit_timeframe = (
            advanced.get("timeframe")
            or payload.get("timeframe")
            or None
        )
        notes: list[str] = []
        if explicit_timeframe in unsupported:
            notes.append(
                f"Timeframe {explicit_timeframe} is tracked as unsupported and will be treated as a validation note."
            )
        selected_timeframe = explicit_timeframe or (supported_timeframes[0] if supported_timeframes else "1h")

        if selected_timeframe in unsupported and supported_timeframes:
            selected_timeframe = supported_timeframes[-1]
        unsupported_configured = [tf for tf in configured_timeframes if tf in unsupported]
        for tf in unsupported_configured:
            notes.append(f"Configured style timeframe {tf} is unsupported for automated validation.")

        # Use dynamic date ranges based on current date
        default_is, default_oos = date_ranges_for_depth(depth)
        
        # Get depth defaults for configuration
        depth_defaults = DEPTH_SETTINGS[depth]
        
        # Generate planned WFO windows if enabled
        wfo_enabled = bool(payload.get("wfo_enabled", advanced.get("wfo_enabled", depth_defaults["wfo_enabled"])))
        planned_wfo_windows = []
        if wfo_enabled and depth != "quick":
            planned_wfo_windows = walk_forward_windows_for_depth(depth)
        
        pair_universe = (
            advanced.get("pair_universe")
            or payload.get("pair_universe")
            or None
        )
        if isinstance(pair_universe, str):
            pair_universe = [p.strip() for p in pair_universe.split(",") if p.strip()]
        selected_pairs = self.default_pair_universe(style, risk, pair_universe)

        in_sample_range = advanced.get("in_sample_range") or payload.get("in_sample_range") or default_is
        out_sample_range = advanced.get("out_sample_range") or payload.get("out_sample_range") or default_oos
        validation_timerange = out_sample_range or in_sample_range

        discovery_gates = self.thresholds_for(
            style,
            risk,
            "discovery",
            timerange=in_sample_range,
        )
        thresholds = self.thresholds_for(
            style,
            risk,
            "validation",
            timerange=validation_timerange,
        )
        elite_gates = self.thresholds_for(
            style,
            risk,
            "elite_validation",
            timerange=validation_timerange,
        )
        thresholds["max_drawdown"] = normalize_decimal(
            payload.get("max_drawdown_threshold", advanced.get("max_drawdown_threshold", thresholds.get("max_drawdown"))),
            normalize_decimal(thresholds.get("max_drawdown"), 0.30),
        )
        thresholds["min_win_rate"] = normalize_decimal(
            payload.get("min_win_rate", advanced.get("min_win_rate", thresholds.get("min_win_rate"))),
            normalize_decimal(thresholds.get("min_win_rate"), 0.40),
        )
        thresholds["min_profit_factor"] = float(
            payload.get("min_profit_factor", advanced.get("min_profit_factor", thresholds.get("min_profit_factor", 1.0)))
        )
        thresholds["min_sharpe"] = float(
            payload.get("min_sharpe", advanced.get("min_sharpe", 0.5))
        )
        thresholds["min_oos_profit"] = normalize_decimal(
            payload.get("min_oos_profit", advanced.get("min_oos_profit", thresholds.get("min_oos_profit", 0.0))),
            normalize_decimal(thresholds.get("min_oos_profit"), 0.0),
        )
        thresholds["monte_carlo_threshold"] = normalize_decimal(
            payload.get("monte_carlo_threshold", advanced.get("monte_carlo_threshold", 0.35)),
            0.35,
        )
        thresholds_by_tier = {
            "discovery": discovery_gates,
            "validation": dict(thresholds),
            "elite_validation": elite_gates,
        }

        hyperopt_spaces = payload.get("hyperopt_spaces", advanced.get("hyperopt_spaces", ["stoploss", "roi"]))
        if isinstance(hyperopt_spaces, str):
            hyperopt_spaces = [s.strip() for s in hyperopt_spaces.split(",") if s.strip()]

        workflow_mode = str(
            payload.get("workflow_mode") or advanced.get("workflow_mode") or "auto_quant"
        ).strip().lower()
        if workflow_mode not in {"auto_quant", "validate_existing"}:
            workflow_mode = "auto_quant"
        try:
            max_attempts = int(payload.get("max_attempts", advanced.get("max_attempts", 3)))
        except (TypeError, ValueError):
            max_attempts = 3
        max_attempts = max(1, min(max_attempts, 10))

        strategy = payload.get("strategy") or payload.get("uploaded_strategy_id") or advanced.get("strategy") or ""
        return {
            "strategy": strategy,
            "strategy_source": "existing" if workflow_mode == "validate_existing" else payload.get("strategy_source") or advanced.get("strategy_source") or "existing",
            "workflow_mode": workflow_mode,
            "max_attempts": max_attempts,
            "trading_style": style,
            "risk_profile": risk,
            "analysis_depth": depth,
            "uploaded_strategy_id": payload.get("uploaded_strategy_id"),
            "advanced_overrides": advanced,
            "timeframe": selected_timeframe,
            "configured_timeframes": configured_timeframes,
            "unsupported_timeframes": unsupported_configured,
            "in_sample_range": in_sample_range,
            "out_sample_range": out_sample_range,
            "exchange": payload.get("exchange") or advanced.get("exchange") or "binance",
            "config_file": payload.get("config_file") or advanced.get("config_file"),
            "pair": payload.get("pair") or advanced.get("pair"),
            "pair_universe": selected_pairs,
            "selected_pair_universe": selected_pairs,
            "thresholds": thresholds,
            "thresholds_by_tier": thresholds_by_tier,
            "hyperopt_loss": payload.get("hyperopt_loss") or advanced.get("hyperopt_loss") or "ProfitLockinHyperOptLoss",
            "hyperopt_spaces": hyperopt_spaces,
            "hyperopt_epochs": int(
                payload.get("hyperopt_epochs", advanced.get("hyperopt_epochs", depth_defaults["hyperopt_epochs"]))
            ),
            "wfo_enabled": wfo_enabled,
            "wfo_is_months": int(payload.get("wfo_is_months", advanced.get("wfo_is_months", 3))),
            "wfo_oos_months": int(payload.get("wfo_oos_months", advanced.get("wfo_oos_months", 1))),
            "wfo_recency_weight": float(payload.get("wfo_recency_weight", advanced.get("wfo_recency_weight", 1.0))),
            "planned_wfo_windows": planned_wfo_windows,
            "ensemble_enabled": bool(payload.get("ensemble_enabled", advanced.get("ensemble_enabled", False))),
            "validation_notes": notes,
            "policy_versions": self.versions,
        }

    def public_timeframe_thresholds(self, timeframe: str) -> dict[str, Any]:
        """Return UI/API-facing threshold fields for a timeframe."""
        style = "swing"
        for candidate, timeframes in self.timeframes.get("styles", {}).items():
            if timeframe in timeframes:
                style = candidate
                break
        thresholds = self.thresholds_for(style, "balanced", "validation")
        return {
            "profile": style.capitalize(),
            "min_oos_profit": thresholds.get("min_oos_profit", 0.0),
            "max_drawdown_threshold": normalize_percent(thresholds.get("max_drawdown"), 30.0),
            "min_win_rate": normalize_percent(thresholds.get("min_win_rate"), 40.0),
            "min_profit_factor": thresholds.get("min_profit_factor", 1.0),
            "min_sharpe": thresholds.get("min_sharpe", 0.5),
            "description": f"{style.capitalize()} validation policy from AutoQuant policy config.",
            "policy_versions": self.versions,
        }


def _bounded_ratio(value: float, target: float) -> float:
    if target <= 0:
        return 100.0 if value > 0 else 0.0
    return max(0.0, min(100.0, value / target * 100.0))


def _score_passthrough(value: float | None) -> float:
    if value is None:
        return 0.0
    numeric = float(value)
    return max(0.0, min(100.0, numeric if numeric > 1 else numeric * 100.0))


def _score_explanation(components: dict[str, float]) -> list[str]:
    labels = {
        "expectancy": "Expectancy",
        "profit_factor": "Profit factor",
        "drawdown": "Drawdown quality",
        "robustness": "Robustness",
        "oos": "Out-of-sample performance",
        "walk_forward": "Walk-forward stability",
        "pair_consistency": "Pair consistency",
        "trade_quality": "Trade count quality",
    }
    lines: list[str] = []
    for key, label in labels.items():
        score = components.get(key)
        if score is None:
            continue
        if score >= 75:
            strength = "strong"
        elif score >= 45:
            strength = "moderate"
        else:
            strength = "weak"
        lines.append(f"{label} is {strength} ({score:.0f}/100).")
    return lines


@lru_cache(maxsize=1)
def load_policy() -> Policy:
    thresholds = {}
    for style in ("scalping", "intraday", "swing", "position"):
        thresholds[style] = _read_json(CONFIG_ROOT / "thresholds" / f"{style}.json")
    return Policy(
        timeframes=_read_json(CONFIG_ROOT / "timeframes" / "styles.json"),
        risk_profiles=_read_json(CONFIG_ROOT / "risk_profiles" / "profiles.json"),
        pair_universe=_read_json(CONFIG_ROOT / "pair_universes" / "core.json"),
        score_weights=_read_json(CONFIG_ROOT / "score_weights" / "robustness_v1.json"),
        readiness_labels=_read_json(CONFIG_ROOT / "readiness_labels" / "v1.json"),
        thresholds=thresholds,
    )


def get_policy_versions() -> dict[str, str]:
    return load_policy().versions


def build_run_config(payload: dict[str, Any], settings: Any | None = None) -> dict[str, Any]:
    return load_policy().build_run_config(payload=payload, settings=settings)


def thresholds_for(
    style: str,
    risk_profile: str = "balanced",
    tier: str = "validation",
    *,
    timerange: str | None = None,
    timerange_days: int | None = None,
) -> dict[str, Any]:
    return load_policy().thresholds_for(
        style,
        risk_profile,
        tier,
        timerange=timerange,
        timerange_days=timerange_days,
    )


def get_public_timeframe_thresholds(timeframe: str) -> dict[str, Any]:
    return load_policy().public_timeframe_thresholds(timeframe)


__all__ = [
    "Policy",
    "load_policy",
    "get_policy_versions",
    "build_run_config",
    "thresholds_for",
    "get_public_timeframe_thresholds",
    "normalize_decimal",
    "normalize_percent",
]
