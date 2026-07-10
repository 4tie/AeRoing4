"""Optimizer search space building from strategy parameters.

Handles extraction and building of parameter search spaces from strategy definitions.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ...models import (
    ParameterSearchSpace,
    ParameterSearchType,
    StrategyParameterDefinition,
)
from ..strategy.strategy_registry import StrategyRegistry
from ..strategy.strategy_source import StrategySourceParser


class OptimizerSearchSpaceBuilder:
    """Builds parameter search spaces from strategy definitions."""

    def __init__(
        self,
        registry: StrategyRegistry,
        source_parser: StrategySourceParser,
    ) -> None:
        self.registry = registry
        self.source_parser = source_parser

    def build_search_spaces_from_strategy(
        self, strategy_name: str
    ) -> list[ParameterSearchSpace]:
        """Extract parameter definitions from the strategy and build default search spaces."""
        strategy = self.registry.get_strategy(strategy_name)
        spaces: list[ParameterSearchSpace] = []
        for param in strategy.parameters:
            space = self.param_def_to_search_space(param)
            if space is not None:
                spaces.append(space)
        # Append advanced spaces (all disabled by default)
        spaces.extend(self.build_advanced_search_spaces(strategy_name))
        return spaces

    def build_advanced_search_spaces(
        self, strategy_name: str
    ) -> list[ParameterSearchSpace]:
        """Build search spaces for stoploss, ROI table, and trailing stop from strategy source."""
        strategy = self.registry.get_strategy(strategy_name)
        path = Path(strategy.file_path)
        parsed = self.source_parser.parse(path)
        rd = parsed.raw_defaults
        spaces: list[ParameterSearchSpace] = []

        # ── Stoploss ──────────────────────────────────────────────────────────
        sl_default = float(rd.get("stoploss") or -0.10)
        # Range: 3× the default (more negative) to half the default (less negative),
        # clamped to [-0.30, -0.01] but always containing the default value.
        # Floor min (round toward more negative) and ceil max (round toward less negative)
        # at 2 decimal places to guarantee the default lies within the range.
        sl_min_raw = max(sl_default * 3.0, -0.30)
        sl_max_raw = min(sl_default * 0.5, -0.01)
        sl_min = math.floor(sl_min_raw * 100) / 100
        sl_max = math.ceil(sl_max_raw * 100) / 100
        # Ensure the default always falls within [sl_min, sl_max]
        sl_min = min(sl_min, math.floor(sl_default * 100) / 100)
        sl_max = max(sl_max, math.ceil(sl_default * 100) / 100)
        spaces.append(ParameterSearchSpace(
            name="stoploss__value",
            param_type=ParameterSearchType.DECIMAL,
            space="stoploss",
            default=sl_default,
            enabled=False,
            optimizable=True,
            min_value=sl_min,
            max_value=sl_max,
            step=0.01,
        ))

        # ── ROI table ─────────────────────────────────────────────────────────
        roi_dict: dict[str, float] = {
            str(k): float(v)
            for k, v in (rd.get("minimal_roi") or {"0": 0.10}).items()
        }
        for time_key, roi_default in sorted(roi_dict.items(), key=lambda x: int(x[0])):
            spaces.append(ParameterSearchSpace(
                name=f"roi__{time_key}",
                param_type=ParameterSearchType.DECIMAL,
                space="roi",
                default=roi_default,
                enabled=False,
                optimizable=True,
                min_value=0.001,
                max_value=0.30,
                step=0.001,
            ))

        # ── Trailing stop ─────────────────────────────────────────────────────
        trailing_default = bool(rd.get("trailing_stop", False))
        spaces.append(ParameterSearchSpace(
            name="trailing__stop",
            param_type=ParameterSearchType.BOOLEAN,
            space="trailing",
            default=trailing_default,
            enabled=False,
            optimizable=True,
            choices=[True, False],
        ))
        tp_default = rd.get("trailing_stop_positive")
        spaces.append(ParameterSearchSpace(
            name="trailing__positive",
            param_type=ParameterSearchType.DECIMAL,
            space="trailing",
            default=float(tp_default) if tp_default is not None else 0.01,
            enabled=False,
            optimizable=True,
            min_value=0.001,
            max_value=0.10,
            step=0.001,
        ))
        to_default = rd.get("trailing_stop_positive_offset")
        spaces.append(ParameterSearchSpace(
            name="trailing__offset",
            param_type=ParameterSearchType.DECIMAL,
            space="trailing",
            default=float(to_default) if to_default is not None else 0.005,
            enabled=False,
            optimizable=True,
            min_value=0.001,
            max_value=0.05,
            step=0.001,
        ))

        return spaces

    def param_def_to_search_space(
        self, param: StrategyParameterDefinition
    ) -> ParameterSearchSpace | None:
        """Translate parsed strategy parameter metadata into optimizer search space settings."""
        type_map = {
            "IntParameter": ParameterSearchType.INT,
            "DecimalParameter": ParameterSearchType.DECIMAL,
            "RealParameter": ParameterSearchType.DECIMAL,
            "CategoricalParameter": ParameterSearchType.CATEGORICAL,
            "BooleanParameter": ParameterSearchType.BOOLEAN,
        }
        param_type = type_map.get(param.parameter_type)
        if param_type is None:
            return None
        default = param.default
        min_val: float | None = None
        max_val: float | None = None
        step: float | None = None
        choices: list[Any] | None = None

        if param_type == ParameterSearchType.INT:
            if param.min_value is not None and param.max_value is not None:
                min_val = int(param.min_value)
                max_val = int(param.max_value)
            elif isinstance(default, int):
                min_val = max(1, default - max(5, default // 2))
                max_val = default + max(5, default // 2)
            else:
                min_val, max_val = 1, 50
            step = 1.0
        elif param_type == ParameterSearchType.DECIMAL:
            if param.min_value is not None and param.max_value is not None:
                min_val = float(param.min_value)
                max_val = float(param.max_value)
            elif isinstance(default, (int, float)):
                lo = max(0.0, float(default) * 0.5)
                hi = float(default) * 2.0
                min_val, max_val = round(lo, 4), round(hi, 4)
            else:
                min_val, max_val = 0.0, 1.0
            if param.decimals is not None and param.decimals >= 0:
                step = 10 ** (-param.decimals)
            else:
                step = 0.01
        elif param_type == ParameterSearchType.CATEGORICAL:
            choices = list(param.choices or [])
            if not choices and default is not None:
                choices = [default]
        elif param_type == ParameterSearchType.BOOLEAN:
            choices = [True, False]

        return ParameterSearchSpace(
            name=param.name,
            param_type=param_type,
            space=param.space,
            default=default,
            enabled=True,
            optimizable=param.optimizable,
            min_value=min_val,
            max_value=max_val,
            step=step,
            choices=choices,
        )
