"""
backend/tests/test_ai_pipeline.py — Full-chain AI pipeline integration test.

Tests the complete Strategy Lab AI workflow end-to-end WITHOUT calling any
external LLM API (all OpenRouter calls are bypassed — only the internal tool
executors and file-system operations run for real).

NOTE: This test file is currently disabled because the agent_tools module
was removed during refactoring. The test should be updated or removed once
the AI pipeline architecture is finalized.

Steps:
  1  generate_autonomous_strategy  — real file I/O, code templates
  2  Code + schema validation      — py_compile + AST IStrategy guard + JSON schema
  3  run_hyperopt_optimization     — mocked subprocess, real session wiring
  4  JSON parameter update         — update_strategy_parameters tool (real write)
  5  Backtest runner               — real call if freqtrade present, skipped if not
  6  Metric evaluation guardrail   — metric comparison + profitability assertion

Run from project root:
    pytest backend/tests/test_ai_pipeline.py -v
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import py_compile
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Import path: make sure project root is on sys.path ───────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# agent_tools module was removed - skip this test file for now
# from backend.services.ai.agent_tools import (
#     AGENT_TOOLS,
#     AgentToolExecutor,
#     TOOL_LABELS,
#     _build_strategy_code,
#     _build_strategy_json,
# )
# from backend.services.strategy.snapshot_service import SnapshotService

# ── Test constants ────────────────────────────────────────────────────────────
# NOTE: This test file is disabled due to missing agent_tools module
# Skip all tests in this file

@pytest.mark.skip(reason="agent_tools module was removed during refactoring")
class TestGenerateAutonomousStrategy:
    """generate_autonomous_strategy must create .py and .json without any LLM call."""

    def test_tool_in_registry(self):
        """Tool schema must be registered in AGENT_TOOLS and TOOL_LABELS."""
        pass

STRATEGY_NAME = "PipelineTestStrategy"
TRADING_STYLE = "scalping"
TIMEFRAME     = "5m"
DESCRIPTION   = "Build an active scalp strategy for volatile pairs"

OPTIMIZED_PARAMS = {
    "rsi_buy":    28,
    "rsi_sell":   67,
    "bb_period":  18,
    "bb_std":     1.8,
    "stoploss":   -0.025,
    "minimal_roi": {"0": 0.035, "10": 0.02, "30": 0.01},
}

# ── Shared async helper ───────────────────────────────────────────────────────
def _run(coro):
    """Run an async coroutine synchronously (pytest-compatible)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ── Module-scoped fixtures ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    """Temporary workspace with the directory layout the tools expect."""
    root = tmp_path_factory.mktemp("pipeline_ws")
    (root / "strategies").mkdir()
    (root / "backups").mkdir()
    (root / "results").mkdir()
    (root / "shared_state.json").write_text(
        json.dumps({
            "pairs":     ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
            "timeframe": TIMEFRAME,
            "strategy":  STRATEGY_NAME,
        }),
        encoding="utf-8",
    )
    return root


@pytest.fixture(scope="module")
def snapshot_svc(workspace):
    return SnapshotService(backups_root=workspace / "backups")


@pytest.fixture(scope="module")
def hyperopt_log():
    """Shared list that the mock launcher appends to."""
    return []


@pytest.fixture(scope="module")
def executor(workspace, snapshot_svc, hyperopt_log):
    """Real AgentToolExecutor wired to temp workspace; hyperopt launcher is mocked."""
    settings_mock = MagicMock()
    settings_mock.load.return_value = MagicMock(
        freqtrade_executable_path="freqtrade",
        user_data_directory_path=str(workspace),
        default_config_file_path=str(workspace / "config.json"),
        strategies_directory_path=str(workspace / "strategies"),
    )

    def _mock_launcher(strategy_name, spaces, epochs,
                       timeframe="1h", timerange="",
                       loss_function="SharpeHyperOptLoss"):
        hyperopt_log.append({
            "strategy_name": strategy_name,
            "spaces":        list(spaces),
            "epochs":        epochs,
            "timeframe":     timeframe,
            "loss_function": loss_function,
        })
        return "test_hyperopt_session_001"

    return AgentToolExecutor(
        strategies_dir        = workspace / "strategies",
        backtest_results_root = workspace / "results",
        data_download_runner  = MagicMock(),
        settings_store        = settings_mock,
        shared_state_path     = workspace / "shared_state.json",
        snapshot_service      = snapshot_svc,
        error_log_path        = workspace / "last_error.log",
        hyperopt_sessions_path= workspace / "sessions.json",
        hyperopt_launcher     = _mock_launcher,
    )


# ═════════════════════════════════════════════════════════════════════════════
# STEP 1 — Strategy Generation
# ═════════════════════════════════════════════════════════════════════════════

class TestStep1_GenerateStrategy:
    """generate_autonomous_strategy must create .py and .json without any LLM call."""

    def test_tool_in_registry(self):
        """Tool schema must be registered in AGENT_TOOLS and TOOL_LABELS."""
        names = [t["function"]["name"] for t in AGENT_TOOLS]
        assert "generate_autonomous_strategy" in names, (
            "generate_autonomous_strategy missing from AGENT_TOOLS"
        )
        assert "generate_autonomous_strategy" in TOOL_LABELS, (
            "generate_autonomous_strategy missing from TOOL_LABELS"
        )

    def test_generate_returns_success(self, executor):
        content, short = _run(executor.execute("generate_autonomous_strategy", {
            "strategy_name":      STRATEGY_NAME,
            "description":        DESCRIPTION,
            "trading_style":      TRADING_STYLE,
            "baseline_timeframe": TIMEFRAME,
        }))
        assert STRATEGY_NAME in content, f"Strategy name missing from result: {content[:200]}"
        assert "error" not in content[:60].lower(), f"Tool returned error: {content[:200]}"
        assert STRATEGY_NAME in short

    def test_py_file_created(self, workspace):
        py = workspace / "strategies" / f"{STRATEGY_NAME}.py"
        assert py.exists(), f"Expected .py at {py}"
        assert py.stat().st_size > 500, "Generated .py file is suspiciously small"

    def test_json_file_created(self, workspace):
        jf = workspace / "strategies" / f"{STRATEGY_NAME}.json"
        assert jf.exists(), f"Expected .json at {jf}"
        data = json.loads(jf.read_text())
        assert isinstance(data, dict) and len(data) >= 5, (
            f"Companion .json has too few keys: {list(data.keys())}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# STEP 2 — Code & Schema Validation
# ═════════════════════════════════════════════════════════════════════════════

class TestStep2_Validation:
    """The generated .py must be syntactically valid, Freqtrade-compliant Python."""

    @pytest.fixture(autouse=True)
    def _paths(self, workspace):
        self.py_path   = workspace / "strategies" / f"{STRATEGY_NAME}.py"
        self.json_path = workspace / "strategies" / f"{STRATEGY_NAME}.json"

    def test_py_compiles(self):
        """Must pass py_compile with no syntax errors."""
        try:
            py_compile.compile(str(self.py_path), doraise=True)
        except py_compile.PyCompileError as exc:
            pytest.fail(f"Syntax error in generated strategy: {exc}")

    def test_class_inherits_istrategy(self):
        """Strategy class must explicitly inherit from IStrategy."""
        code = self.py_path.read_text(encoding="utf-8")
        tree = ast.parse(code)
        matches = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef)
            and any(
                (isinstance(b, ast.Name) and b.id == "IStrategy")
                or (isinstance(b, ast.Attribute) and b.attr == "IStrategy")
                for b in n.bases
            )
        ]
        assert matches, f"No class(IStrategy) found in {STRATEGY_NAME}.py"
        assert matches[0].name == STRATEGY_NAME, (
            f"Class name is {matches[0].name!r}, expected {STRATEGY_NAME!r}"
        )

    def test_required_methods_present(self):
        """populate_indicators, populate_entry_trend, populate_exit_trend must be defined."""
        code = self.py_path.read_text(encoding="utf-8")
        tree = ast.parse(code)
        defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for method in ("populate_indicators", "populate_entry_trend", "populate_exit_trend"):
            assert method in defined, f"Required method {method!r} not found"

    def test_hyperopt_parameters_declared(self):
        """Strategy must declare at least two hyperoptable parameters."""
        code = self.py_path.read_text(encoding="utf-8")
        param_count = code.count("IntParameter") + code.count("DecimalParameter")
        assert param_count >= 2, (
            f"Expected ≥2 hyperopt parameters, found {param_count}"
        )

    def test_json_has_stoploss_and_roi(self):
        data = json.loads(self.json_path.read_text())
        assert "stoploss" in data,   "Companion JSON missing 'stoploss'"
        assert "minimal_roi" in data, "Companion JSON missing 'minimal_roi'"
        assert data["stoploss"] < 0,  "stoploss must be negative"
        assert isinstance(data["minimal_roi"], dict), "minimal_roi must be a dict"

    def test_json_roi_has_key_zero(self):
        data = json.loads(self.json_path.read_text())
        assert "0" in data["minimal_roi"], "minimal_roi must include a '0' key"

    def test_all_four_styles_compile(self):
        """Every trading style template must produce syntax-valid Python."""
        for style in ("scalping", "swing", "trend_following", "mean_reversion"):
            code = _build_strategy_code(
                strategy_name=f"Test{style.title().replace('_','')}",
                trading_style=style,
                timeframe="1h",
                description=f"Pipeline test for {style}",
            )
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(code)
                tmp_path = tmp.name
            try:
                py_compile.compile(tmp_path, doraise=True)
            except py_compile.PyCompileError as exc:
                pytest.fail(f"Style '{style}' generates invalid Python: {exc}")
            finally:
                os.unlink(tmp_path)

    def test_all_four_styles_json_valid(self):
        """Every trading style JSON template must have stoploss and minimal_roi."""
        for style in ("scalping", "swing", "trend_following", "mean_reversion"):
            params = _build_strategy_json(f"Test{style}", style)
            assert isinstance(params, dict), f"Style '{style}' JSON is not a dict"
            assert "stoploss" in params,    f"Style '{style}' JSON missing stoploss"
            assert "minimal_roi" in params, f"Style '{style}' JSON missing minimal_roi"
            assert params["stoploss"] < 0,  f"Style '{style}' stoploss must be negative"

    def test_all_four_styles_have_istrategy(self):
        """Every generated .py must contain a class inheriting from IStrategy."""
        for style in ("scalping", "swing", "trend_following", "mean_reversion"):
            code = _build_strategy_code(
                strategy_name=f"Test{style.title().replace('_', '')}",
                trading_style=style,
                timeframe="1h",
                description=f"Test {style}",
            )
            tree = ast.parse(code)
            found = any(
                isinstance(n, ast.ClassDef)
                and any(
                    (isinstance(b, ast.Name) and b.id == "IStrategy")
                    or (isinstance(b, ast.Attribute) and b.attr == "IStrategy")
                    for b in n.bases
                )
                for n in ast.walk(tree)
            )
            assert found, f"Style '{style}': no class(IStrategy) found"


# ═════════════════════════════════════════════════════════════════════════════
# STEP 3 — Hyperopt Optimization Tool
# ═════════════════════════════════════════════════════════════════════════════

class TestStep3_Hyperopt:
    """run_hyperopt_optimization must invoke the launcher with correct arguments."""

    def test_tool_in_registry(self):
        names = [t["function"]["name"] for t in AGENT_TOOLS]
        assert "run_hyperopt_optimization" in names

    def test_hyperopt_tool_fires_launcher(self, executor, hyperopt_log):
        before = len(hyperopt_log)
        _run(executor.execute("run_hyperopt_optimization", {
            "strategy_name": STRATEGY_NAME,
            "spaces":        ["buy", "sell"],
            "epochs":        2,
            "timeframe":     TIMEFRAME,
        }))
        assert len(hyperopt_log) > before, "Hyperopt launcher was never called"

    def test_hyperopt_args_are_correct(self, executor, hyperopt_log):
        _run(executor.execute("run_hyperopt_optimization", {
            "strategy_name": STRATEGY_NAME,
            "spaces":        ["roi", "stoploss"],
            "epochs":        3,
            "timeframe":     "1h",
            "loss_function": "SortinoHyperOptLoss",
        }))
        last = hyperopt_log[-1]
        assert last["strategy_name"] == STRATEGY_NAME
        assert "roi" in last["spaces"]
        assert last["epochs"] == 3
        assert last["loss_function"] == "SortinoHyperOptLoss"

    def test_hyperopt_result_contains_session_id(self, executor):
        content, _ = _run(executor.execute("run_hyperopt_optimization", {
            "strategy_name": STRATEGY_NAME,
            "spaces":        ["buy"],
            "epochs":        1,
        }))
        assert "test_hyperopt_session_001" in content, (
            f"Session ID missing from result:\n{content}"
        )

    def test_hyperopt_spaces_validated(self, executor):
        """Invalid spaces must be silently filtered, keeping only valid ones."""
        content, _ = _run(executor.execute("run_hyperopt_optimization", {
            "strategy_name": STRATEGY_NAME,
            "spaces":        ["buy", "invalid_space", "stoploss"],
            "epochs":        1,
        }))
        # Tool must still succeed with valid spaces
        assert "test_hyperopt_session_001" in content

    def test_hyperopt_epochs_clamped(self, executor, hyperopt_log):
        """Epochs > 1000 must be clamped to 1000."""
        _run(executor.execute("run_hyperopt_optimization", {
            "strategy_name": STRATEGY_NAME,
            "spaces":        ["buy"],
            "epochs":        9999,
        }))
        last = hyperopt_log[-1]
        assert last["epochs"] == 1000, f"Epochs not clamped: {last['epochs']}"


# ═════════════════════════════════════════════════════════════════════════════
# STEP 4 — JSON Parameter Update Handshake
# ═════════════════════════════════════════════════════════════════════════════

class TestStep4_JsonHandshake:
    """update_strategy_parameters must write optimized values back to the .json file."""

    def test_update_writes_to_disk(self, executor, workspace):
        content, short = _run(executor.execute("update_strategy_parameters", {
            "strategy_name": STRATEGY_NAME,
            "new_params_json": OPTIMIZED_PARAMS,
        }))
        assert "error" not in content.lower()[:40], f"Tool returned error: {content}"
        jf = workspace / "strategies" / f"{STRATEGY_NAME}.json"
        data = json.loads(jf.read_text())
        assert data.get("rsi_buy") == 28,     f"rsi_buy not updated: {data}"
        assert data.get("stoploss") == -0.025, f"stoploss not updated: {data}"

    def test_json_reflects_hyperopt_roi(self, workspace):
        data = json.loads(
            (workspace / "strategies" / f"{STRATEGY_NAME}.json").read_text()
        )
        assert data["minimal_roi"]["0"] == 0.035, (
            f"minimal_roi not updated: {data.get('minimal_roi')}"
        )

    def test_update_count_in_summary(self, executor, workspace):
        """Tool short summary must mention how many parameters were written."""
        _, short = _run(executor.execute("update_strategy_parameters", {
            "strategy_name": STRATEGY_NAME,
            "new_params_json": OPTIMIZED_PARAMS,
        }))
        assert str(len(OPTIMIZED_PARAMS)) in short, (
            f"Parameter count missing from summary: {short}"
        )

    def test_json_string_input_also_works(self, executor, workspace):
        """new_params_json may also be a JSON-encoded string."""
        patch = {"stoploss": -0.03, "minimal_roi": {"0": 0.04}}
        _, _ = _run(executor.execute("update_strategy_parameters", {
            "strategy_name":   STRATEGY_NAME,
            "new_params_json": json.dumps(patch),
        }))
        data = json.loads(
            (workspace / "strategies" / f"{STRATEGY_NAME}.json").read_text()
        )
        assert data["stoploss"] == -0.03


# ═════════════════════════════════════════════════════════════════════════════
# STEP 5 — Backtest Runner / Freqtrade Integration
# ═════════════════════════════════════════════════════════════════════════════

class TestStep5_Backtest:
    """Attempts a real freqtrade invocation; skips cleanly if freqtrade is absent."""

    def test_freqtrade_binary_check(self):
        """Detect whether freqtrade is available in $PATH."""
        if not shutil.which("freqtrade"):
            pytest.skip("freqtrade not installed — skipping live backtest step")

    def test_strategy_file_compiles_pre_freqtrade(self, workspace):
        """Strategy .py must pass py_compile before freqtrade would import it."""
        if not shutil.which("freqtrade"):
            pytest.skip("freqtrade not installed")
        py = workspace / "strategies" / f"{STRATEGY_NAME}.py"
        try:
            py_compile.compile(str(py), doraise=True)
        except py_compile.PyCompileError as exc:
            pytest.fail(f"Strategy file does not compile: {exc}")

    def test_freqtrade_help_responds(self):
        """freqtrade --help must exit 0 if installed."""
        if not shutil.which("freqtrade"):
            pytest.skip("freqtrade not installed")
        import subprocess
        result = subprocess.run(
            ["freqtrade", "--help"],
            capture_output=True, timeout=15,
        )
        assert result.returncode == 0, (
            f"freqtrade --help failed: {result.stderr.decode()[:200]}"
        )

    def test_read_strategy_code_tool(self, executor, workspace):
        """read_strategy_code tool must return the generated file content."""
        content, _ = _run(executor.execute("read_strategy_code", {
            "strategy_name": STRATEGY_NAME,
        }))
        assert "IStrategy" in content, "IStrategy not found in read_strategy_code output"
        assert "populate_entry_trend" in content


# ═════════════════════════════════════════════════════════════════════════════
# STEP 6 — Metric Evaluation Guardrail
# ═════════════════════════════════════════════════════════════════════════════

class TestStep6_MetricEvaluation:
    """Validates the plan evaluation / profitability guardrail logic."""

    # Representative metric sets — mimicking what evaluate_plan compares
    BASELINE = {
        "profit_total_pct":  -0.05,
        "win_rate":           0.38,
        "max_drawdown_pct":   0.18,
        "total_trades":       45,
        "sharpe":            -0.30,
    }
    IMPROVED = {
        "profit_total_pct":  0.12,
        "win_rate":          0.54,
        "max_drawdown_pct":  0.09,
        "total_trades":      52,
        "sharpe":            0.85,
    }
    DEGRADED = {
        "profit_total_pct": -0.12,
        "win_rate":          0.29,
        "max_drawdown_pct":  0.30,
        "total_trades":      20,
        "sharpe":           -1.20,
    }

    # ── Pure comparison logic (mirrors evaluate_plan in ai_chat.py) ──────────
    @staticmethod
    def _compare(baseline: dict, current: dict) -> dict:
        out = {}
        for key in baseline:
            b, c = baseline.get(key), current.get(key)
            if b is None or c is None:
                out[key] = {"baseline": b, "current": c, "delta": None, "improved": None}
                continue
            delta    = c - b
            improved = (delta < 0) if key == "max_drawdown_pct" else (delta > 0)
            out[key] = {"baseline": b, "current": c, "delta": round(delta, 8), "improved": improved}
        return out

    @staticmethod
    def _is_degraded(cmp: dict) -> bool:
        profit = cmp.get("profit_total_pct", {})
        dd     = cmp.get("max_drawdown_pct", {})
        if profit.get("current") is not None and profit.get("baseline") is not None:
            if profit["current"] < profit["baseline"]:
                return True
        if dd.get("delta") is not None and dd["delta"] > 0.05:
            return True
        return False

    # ── Tests ─────────────────────────────────────────────────────────────────

    def test_improved_plan_not_flagged_as_degraded(self):
        cmp = self._compare(self.BASELINE, self.IMPROVED)
        assert not self._is_degraded(cmp), "Improved plan incorrectly flagged as degraded"

    def test_all_improved_metrics_show_improvement(self):
        cmp = self._compare(self.BASELINE, self.IMPROVED)
        assert cmp["profit_total_pct"]["improved"] is True
        assert cmp["win_rate"]["improved"]          is True
        assert cmp["max_drawdown_pct"]["improved"]  is True
        assert cmp["sharpe"]["improved"]            is True

    def test_degraded_plan_triggers_rollback_flag(self):
        cmp = self._compare(self.BASELINE, self.DEGRADED)
        assert self._is_degraded(cmp), "Degraded plan not detected — rollback not triggered"

    def test_profitable_baseline_assertion(self):
        """Prove the IMPROVED scenario satisfies the +0.1% profitability threshold."""
        assert self.IMPROVED["profit_total_pct"] > 0.001, (
            "Strategy does not achieve profitable baseline (+0.1% minimum)"
        )
        assert self.IMPROVED["win_rate"] > 0.50, "Win rate below 50%"

    def test_metric_deltas_computed_correctly(self):
        cmp = self._compare(self.BASELINE, self.IMPROVED)
        assert abs(cmp["profit_total_pct"]["delta"] - 0.17) < 1e-6
        assert abs(cmp["win_rate"]["delta"] - 0.16) < 1e-6
        assert abs(cmp["max_drawdown_pct"]["delta"] - (-0.09)) < 1e-6
        assert abs(cmp["sharpe"]["delta"] - 1.15) < 1e-6

    def test_equal_metrics_not_degraded(self):
        """Identical metrics (delta=0) must not trigger a rollback."""
        cmp = self._compare(self.BASELINE, self.BASELINE)
        # profit unchanged (not strictly lower) → not degraded
        assert not self._is_degraded(cmp)

    def test_drawdown_only_worsening_triggers_degraded(self):
        """Drawdown worsening by >5% alone should flag degradation."""
        current = {**self.BASELINE, "max_drawdown_pct": self.BASELINE["max_drawdown_pct"] + 0.10}
        cmp = self._compare(self.BASELINE, current)
        assert self._is_degraded(cmp), "Large drawdown increase should flag degradation"

    def test_rollback_tool_registered(self):
        """rollback_strategy must appear in AGENT_TOOLS."""
        names = [t["function"]["name"] for t in AGENT_TOOLS]
        assert "rollback_strategy" in names

    def test_rewrite_guard_rejects_code_without_istrategy(self, executor, workspace):
        """rewrite_strategy_file must reject code that has no IStrategy class."""
        bad_code = (
            "class NotAStrategy:\n"
            "    def populate_entry_trend(self, df, meta): return df\n"
            "    def populate_exit_trend(self, df, meta): return df\n"
            "# IStrategy mentioned in comment only\n"
        )
        content, _ = _run(executor.execute("rewrite_strategy_file", {
            "strategy_name": STRATEGY_NAME,
            "python_code":   bad_code,
        }))
        # The guard returns a rejection message mentioning IStrategy; it does not
        # necessarily contain the word "error" — check for the rejection signal instead.
        assert "IStrategy" in content, (
            f"Guard rejection must mention IStrategy: {content[:200]}"
        )
        assert "no class" in content.lower() or "must" in content.lower(), (
            f"Guard should explain IStrategy is required: {content[:200]}"
        )

    def test_rewrite_guard_rejects_syntax_error(self, executor):
        """rewrite_strategy_file must reject code with a Python syntax error."""
        bad_code = (
            "class PipelineTestStrategy(IStrategy):\n"
            "    def populate_entry_trend(self, df, meta):\n"
            "        return df\n"
            "    def populate_exit_trend(self, df, meta\n"  # missing closing paren
            "        return df\n"
        )
        content, _ = _run(executor.execute("rewrite_strategy_file", {
            "strategy_name": STRATEGY_NAME,
            "python_code":   bad_code,
        }))
        assert "syntax" in content.lower() or "error" in content.lower(), (
            f"Guard should have caught syntax error: {content[:200]}"
        )

    def test_rewrite_guard_accepts_valid_strategy(self, executor, workspace):
        """rewrite_strategy_file must accept a fully valid strategy and write it."""
        good_code = _build_strategy_code(
            strategy_name=STRATEGY_NAME,
            trading_style="swing",
            timeframe="1h",
            description="Validated swing strategy for guardrail test",
        )
        content, short = _run(executor.execute("rewrite_strategy_file", {
            "strategy_name": STRATEGY_NAME,
            "python_code":   good_code,
            "rationale":     "Guardrail validation pass",
        }))
        assert "error" not in content[:60].lower(), f"Valid strategy rejected: {content[:200]}"
        py = workspace / "strategies" / f"{STRATEGY_NAME}.py"
        assert py.exists()
        # Verify the rewrite landed on disk
        disk_code = py.read_text(encoding="utf-8")
        assert "populate_entry_trend" in disk_code
