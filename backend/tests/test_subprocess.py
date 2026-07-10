"""backend/tests/test_subprocess.py — Subprocess error classifier tests.

Tests for the subprocess error classifier, including:
- _classify_subprocess_error() correctness
- Actionable error messages for common failure modes
"""

from __future__ import annotations

import pytest

import backend.services.auto_quant.pipeline as pl


class TestSubprocessErrorClassifier:
    """Verify _classify_subprocess_error produces useful, actionable messages."""

    def test_no_data_found_message_includes_hint(self):
        stdout = (
            "No history for BTC/USDT, spot, 5m found.\n"
            "No data found. Terminating.\n"
        )
        msg = pl._classify_subprocess_error(2, stdout, "Stage 1")
        assert "download" in msg.lower() or "data" in msg.lower()

    def test_import_error_message_mentions_import(self):
        stdout = "ImportError: No module named 'some_lib'\n"
        msg = pl._classify_subprocess_error(1, stdout, "Stage 1")
        assert "import" in msg.lower() or "module" in msg.lower()

    def test_generic_fallback_includes_exit_code(self):
        stdout = "Something went wrong unexpectedly\n"
        msg = pl._classify_subprocess_error(99, stdout, "Stage 2")
        assert "99" in msg or "failed" in msg.lower()

    def test_strategy_class_not_found(self):
        stdout = "OperationalError: Strategy class MyStrat cannot be resolved\n"
        msg = pl._classify_subprocess_error(2, stdout, "Stage 1")
        assert "class" in msg.lower() or "strategy" in msg.lower() or "resolved" in msg.lower()

    def test_config_error_message_mentions_config(self):
        stdout = "Configuration error: Missing 'exchange' key\n"
        msg = pl._classify_subprocess_error(2, stdout, "Stage 1")
        assert "config" in msg.lower() or "configuration" in msg.lower()

    def test_buy_space_hyperopt_parameter_mismatch_message(self):
        stdout = (
            "The 'buy' space is included into the hyperoptimization "
            "but no parameter for this space was found in your Strategy. "
            "Please make sure to have parameters for this space enabled...\n"
        )
        msg = pl._classify_subprocess_error(2, stdout, "Stage 2")
        assert "buy" in msg.lower() and "hyperopt" in msg.lower()
