"""Structured strategy design contract for AI-proposed strategies."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import Field

from .base import StrictModel


IndicatorName = Literal[
    "rsi",
    "macd",
    "bbands",
    "ema_cross",
    "adx",
    "atr",
    "cci",
    "stoch",
    "ichimoku",
]

SignalType = Literal[
    "indicator_cross",
    "indicator_threshold",
    "indicator_divergence",
    "combined",
]

TradingStyle = Literal[
    "trend_following",
    "mean_reversion",
    "momentum",
    "breakout",
    "adaptive",
    "ensemble",
]

Direction = Literal["long", "short", "both"]

PositionSizingMethod = Literal["fixed", "atr_percent", "risk_per_trade"]

VALID_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}
VALID_OPERATORS = {">", "<", ">=", "<=", "==", "!=", "crosses_above", "crosses_below"}
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


class IndicatorSpec(StrictModel):
    name: IndicatorName
    params: dict[str, float] = Field(default_factory=dict)


class SignalCondition(StrictModel):
    type: SignalType
    indicator_a: str
    operator: str
    value_or_indicator_b: str | float


class PositionSizing(StrictModel):
    method: PositionSizingMethod = "fixed"
    atr_multiplier: float | None = None
    risk_per_trade_pct: float | None = None


class TrailingStopSpec(StrictModel):
    trailing_stop: bool = False
    trailing_stop_positive: float | None = None
    trailing_stop_offset: float | None = None
    trailing_only_offset_is_reached: bool = False


class StrategySpec(StrictModel):
    name: str
    description: str = ""
    timeframe: str = "5m"
    trading_style: TradingStyle
    direction: Direction = "both"

    indicators: list[IndicatorSpec] = Field(default_factory=list)
    entry_conditions: list[SignalCondition] = Field(default_factory=list)
    exit_conditions: list[SignalCondition] = Field(default_factory=list)

    stoploss: float = -0.10
    trailing: TrailingStopSpec = Field(default_factory=TrailingStopSpec)
    position_sizing: PositionSizing = Field(default_factory=PositionSizing)
    max_open_trades: int = 3
    roi: list[tuple[int, float]] = Field(default_factory=list)

    max_iterations: int = 3
    iteration_count: int = 0
    parent_spec_hash: str = ""

    def spec_hash(self) -> str:
        payload = self.model_dump(mode="json")
        payload.pop("iteration_count", None)
        payload.pop("parent_spec_hash", None)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_spec(spec: StrategySpec, strict_validation: bool = False) -> list[str]:
    errors: list[str] = []

    if not _NAME_RE.fullmatch(spec.name or ""):
        errors.append("INVALID_NAME")

    if spec.timeframe not in VALID_TIMEFRAMES:
        errors.append("INVALID_TIMEFRAME")

    if len(spec.description) > 500:
        errors.append("DESCRIPTION_TOO_LONG")

    indicator_names = [indicator.name for indicator in spec.indicators]
    indicator_set = set(indicator_names)
    if not indicator_names:
        errors.append("NO_INDICATORS")
    if len(indicator_names) != len(indicator_set):
        errors.append("DUPLICATE_INDICATORS")

    # Strict validation: limit max indicators to 5
    if strict_validation and len(spec.indicators) > 5:
        errors.append("TOO_MANY_INDICATORS")

    for indicator in spec.indicators:
        for param_name, value in indicator.params.items():
            if value <= 0:
                errors.append(f"INVALID_INDICATOR_PARAM: {indicator.name}.{param_name}")
            # Strict validation: limit max parameters per indicator to 3
            if strict_validation and len(indicator.params) > 3:
                errors.append(f"TOO_MANY_PARAMS: {indicator.name}")

    if not spec.entry_conditions:
        errors.append("NO_ENTRY_CONDITIONS")
    _validate_conditions(spec.entry_conditions, indicator_set, errors, "ENTRY")

    if not spec.exit_conditions and not spec.trailing.trailing_stop:
        errors.append("NO_EXIT_CONDITIONS")
    _validate_conditions(spec.exit_conditions, indicator_set, errors, "EXIT")

    if spec.stoploss >= 0 or spec.stoploss < -0.50:
        errors.append("INVALID_STOPLOSS")

    if spec.roi:
        minutes = [minute for minute, _ in spec.roi]
        if minutes != sorted(minutes):
            errors.append("INVALID_ROI_ORDER")
        if spec.roi[-1][1] <= abs(spec.stoploss):
            errors.append("INVALID_ROI_TARGET")

    if spec.trailing.trailing_stop:
        if spec.trailing.trailing_stop_positive is None or spec.trailing.trailing_stop_positive <= 0:
            errors.append("INVALID_TRAILING_STOP")

    if spec.position_sizing.method == "atr_percent":
        if spec.position_sizing.atr_multiplier is None or spec.position_sizing.atr_multiplier <= 0:
            errors.append("MISSING_ATR_MULTIPLIER")
    if spec.position_sizing.method == "risk_per_trade":
        if spec.position_sizing.risk_per_trade_pct is None or spec.position_sizing.risk_per_trade_pct <= 0:
            errors.append("MISSING_RISK_PER_TRADE_PCT")

    if spec.max_iterations < 1 or spec.max_iterations > 10:
        errors.append("INVALID_MAX_ITERATIONS")
    if spec.iteration_count >= spec.max_iterations:
        errors.append("MAX_ITERATIONS_REACHED")

    if spec.parent_spec_hash and spec.spec_hash() == spec.parent_spec_hash:
        errors.append("PARENT_SPEC_UNCHANGED")

    return errors


def _validate_conditions(
    conditions: list[SignalCondition],
    indicator_set: set[str],
    errors: list[str],
    label: str,
) -> None:
    for condition in conditions:
        if condition.operator not in VALID_OPERATORS:
            errors.append(f"INVALID_{label}_OPERATOR")
        if condition.indicator_a not in indicator_set:
            errors.append(f"MISSING_{label}_INDICATOR: {condition.indicator_a}")
        value = condition.value_or_indicator_b
        if isinstance(value, str) and value not in indicator_set:
            errors.append(f"MISSING_{label}_INDICATOR: {value}")
