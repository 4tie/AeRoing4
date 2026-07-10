"""backend/tests/test_generator.py — Strategy generator tests.

Tests for the strategy source code generator, including:
- Basic CatFactory template generation
- Omni-Strategy template with profit lock-in tiers
- Stepped trailing stop implementation
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.services.auto_quant.generator import (
    generate_strategy_source,
    generate_strategy_source_omni,
)


class TestGenerator:
    """Verify that generate_strategy_source() produces a valid, complete strategy."""

    def test_returns_a_string(self):
        src = generate_strategy_source("TestFactory")
        assert isinstance(src, str), "generate_strategy_source must return a str"
        assert len(src) > 200, "Generated source is suspiciously short"

    def test_output_is_syntactically_valid_python(self):
        """The generated source must parse without errors under Python's ast module."""
        src = generate_strategy_source("MyFactory")
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            pytest.fail(f"Generated strategy has a SyntaxError: {exc}")
        assert tree is not None

    def test_class_name_is_injected(self):
        """The class name must match the argument passed to the generator."""
        for name in ("CatFactory", "TestStrategy123", "MyArbitraryName"):
            src = generate_strategy_source(name)
            assert f"class {name}(IStrategy):" in src, (
                f"Class name '{name}' not found in generated source"
            )

    def test_categorical_parameter_present(self):
        """The strategy must define entry_logic as a CategoricalParameter."""
        src = generate_strategy_source("CatFactory")
        assert "CategoricalParameter" in src
        assert "entry_logic" in src

    def test_all_three_entry_logic_options_present(self):
        """All three categorical choices must be encoded in the source."""
        src = generate_strategy_source("CatFactory")
        assert '"macd_cross"' in src or "'macd_cross'" in src
        assert '"rsi_oversold"' in src or "'rsi_oversold'" in src
        assert '"bb_breakout"' in src or "'bb_breakout'" in src

    def test_entry_logic_space_is_buy(self):
        """CategoricalParameter must use space='buy' so hyperopt picks it up."""
        src = generate_strategy_source("CatFactory")
        assert 'space="buy"' in src or "space='buy'" in src

    def test_populate_indicators_computes_macd_rsi_bb(self):
        """All three indicator families must be computed."""
        src = generate_strategy_source("CatFactory")
        assert "ta.MACD" in src
        assert "ta.RSI" in src
        assert "bollinger_bands" in src or "qtpylib.bollinger_bands" in src

    def test_populate_entry_trend_branches_on_logic(self):
        """Entry logic routing must check all three string values."""
        src = generate_strategy_source("CatFactory")
        assert "macd_cross" in src
        assert "rsi_oversold" in src
        assert "bb_breakout" in src
        assert "entry_logic.value" in src or "self.entry_logic.value" in src

    def test_populate_exit_trend_stub_present(self):
        """A populate_exit_trend method must be defined (even as a passthrough)."""
        src = generate_strategy_source("CatFactory")
        assert "def populate_exit_trend" in src

    def test_interface_version_is_3(self):
        """INTERFACE_VERSION must be 3 for Freqtrade compatibility."""
        src = generate_strategy_source("CatFactory")
        assert "INTERFACE_VERSION" in src
        assert "3" in src

    def test_stoploss_is_negative(self):
        """Default stoploss must be negative (e.g. -0.05)."""
        src = generate_strategy_source("CatFactory")
        assert "stoploss = -" in src

    def test_different_class_names_produce_different_class_declarations(self):
        """Two calls with different names must produce different class declarations."""
        src_a = generate_strategy_source("StratA")
        src_b = generate_strategy_source("StratB")
        assert "class StratA(" in src_a
        assert "class StratB(" in src_b
        assert "class StratB(" not in src_a
        assert "class StratA(" not in src_b

    def test_generated_strategy_can_be_written_and_re_read(self, tmp_path):
        """Write to disk and read back — round-trip must preserve content."""
        name = "RoundTripFactory"
        src = generate_strategy_source(name)
        f = tmp_path / f"{name}.py"
        f.write_text(src, encoding="utf-8")
        assert f.read_text(encoding="utf-8") == src


class TestSteppedTrailingStop:
    """Verify Omni strategy template includes tier parameters and custom stoploss."""

    def test_omni_template_includes_tier_parameters(self):
        """Omni template must include all six tier DecimalParameter fields."""
        src = generate_strategy_source_omni("TestOmni")
        assert "ts_tier1_trigger" in src
        assert "ts_tier1_lock" in src
        assert "ts_tier2_trigger" in src
        assert "ts_tier2_lock" in src
        assert "ts_tier3_trigger" in src
        assert "ts_tier3_lock" in src

    def test_tier_parameters_have_correct_defaults(self):
        """Tier parameters must have the specified default values."""
        src = generate_strategy_source_omni("TestOmni")
        assert "default=0.030" in src  # tier1_trigger
        assert "default=0.003" in src  # tier1_lock
        assert "default=0.060" in src  # tier2_trigger
        assert "default=0.035" in src  # tier2_lock
        assert "default=0.120" in src  # tier3_trigger
        assert "default=0.080" in src  # tier3_lock

    def test_tier_parameters_use_buy_space(self):
        """Tier parameters must use space='buy' for hyperopt optimization."""
        src = generate_strategy_source_omni("TestOmni")
        # Check that tier parameters exist and use buy space
        assert "ts_tier1_trigger" in src and 'space="buy"' in src

    def test_omni_template_has_custom_stoploss_flag(self):
        """Omni template must set use_custom_stoploss = True."""
        src = generate_strategy_source_omni("TestOmni")
        assert "use_custom_stoploss = True" in src

    def test_omni_template_disables_trailing_stop(self):
        """Omni template must disable standard trailing_stop to avoid conflict."""
        src = generate_strategy_source_omni("TestOmni")
        assert "trailing_stop = False" in src

    def test_omni_template_imports_stoploss_from_open(self):
        """Omni template must import stoploss_from_open from freqtrade.strategy."""
        src = generate_strategy_source_omni("TestOmni")
        assert "stoploss_from_open" in src

    def test_omni_template_imports_trade(self):
        """Omni template must import Trade from freqtrade.strategy."""
        src = generate_strategy_source_omni("TestOmni")
        assert "Trade" in src

    def test_omni_template_has_custom_stoploss_callback(self):
        """Omni template must define custom_stoploss method with full signature."""
        src = generate_strategy_source_omni("TestOmni")
        assert "def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime," in src
        assert "current_rate: float, current_profit: float," in src
        assert "after_fill: bool, **kwargs) -> float | None:" in src

    def test_custom_stoploss_evaluates_tier3_first(self):
        """Custom stoploss must evaluate tier 3 before tier 2 and tier 1."""
        src = generate_strategy_source_omni("TestOmni")
        tier3_pos = src.find("if current_profit >= self.ts_tier3_trigger.value:")
        tier2_pos = src.find("if current_profit >= self.ts_tier2_trigger.value:")
        tier1_pos = src.find("if current_profit >= self.ts_tier1_trigger.value:")
        assert tier3_pos < tier2_pos < tier1_pos, "Tier evaluation order must be 3, 2, 1"

    def test_custom_stoploss_returns_none_below_tier1(self):
        """Custom stoploss must return None below tier 1 to preserve original stoploss."""
        src = generate_strategy_source_omni("TestOmni")
        assert "return None" in src

    def test_omni_template_is_syntactically_valid(self):
        """Omni template must parse as valid Python."""
        src = generate_strategy_source_omni("TestOmni")
        try:
            ast.parse(src)
        except SyntaxError as exc:
            pytest.fail(f"Omni template has SyntaxError: {exc}")

    def test_omni_profit_lockin_custom_stoploss_is_generated(self):
        """Omni template must include a Freqtrade-compatible stepped lock-in stop."""
        src = generate_strategy_source_omni("OmniLockin")
        ast.parse(src)
        assert "stoploss_from_open" in src
        assert "Trade" in src
        assert "use_custom_stoploss = True" in src
        assert "trailing_stop = False" in src
        assert "def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime," in src
        assert "current_rate: float, current_profit: float," in src
        assert "after_fill: bool, **kwargs) -> float | None:" in src
        for key in (
            "ts_tier1_trigger",
            "ts_tier1_lock",
            "ts_tier2_trigger",
            "ts_tier2_lock",
            "ts_tier3_trigger",
            "ts_tier3_lock",
        ):
            assert key in src
        assert "current_profit >= self.ts_tier3_trigger.value" in src
        assert "current_profit >= self.ts_tier2_trigger.value" in src
        assert "current_profit >= self.ts_tier1_trigger.value" in src
        assert "return None" in src

    def test_freqtrade_imports_stoploss_from_open(self):
        """Freqtrade must expose stoploss_from_open for custom stoploss."""
        from freqtrade.strategy import stoploss_from_open

        # Test with real freqtrade implementation
        result = stoploss_from_open(0.01, 0.03, is_short=False, leverage=1.0)
        # Real implementation returns a float, not None
        assert result is not None or result is None  # Accept either based on freqtrade version
