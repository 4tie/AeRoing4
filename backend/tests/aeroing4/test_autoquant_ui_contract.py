from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
STRATEGY_VIEW = REPO_ROOT / "frontend" / "components" / "aero" / "StrategyLibraryView.tsx"
AUTOQUANT_TAB = REPO_ROOT / "frontend" / "components" / "aero" / "TabAutoQuant.tsx"
API_CLIENT = REPO_ROOT / "frontend" / "lib" / "api.ts"


def test_ui_renders_strategy_library_rows():
    source = STRATEGY_VIEW.read_text(encoding="utf-8")

    assert 'data-testid="strategy-library-view"' in source
    assert 'data-testid="strategy-library-row"' in source
    for field in (
        "item.strategy_name",
        "item.py_exists",
        "item.json_exists",
        "item.class_name",
        "item.json_strategy_name",
        "item.timeframe",
        "item.python_parameters",
        "item.json_runtime_params",
    ):
        assert field in source


def test_ui_renders_candidate_execution_timeline_step_cards():
    source = STRATEGY_VIEW.read_text(encoding="utf-8")

    assert 'data-testid="candidate-flow-view"' in source
    assert 'data-testid="candidate-flow-step-card"' in source
    for step_name in (
        "Source Strategy",
        "Candidate Copy",
        "Freqtrade Execution",
        "Metrics Parsing",
        "Decision",
        "Next Action",
    ):
        assert step_name in source
    for field in (
        "flow.official_source_strategy_path",
        "flow.official_source_json_path",
        "flow.candidate_directory",
        "flow.freqtrade_command",
        "flow.strategy_path_points_to_candidate_or_run_dir",
        "flow.output_zip_contains_py",
        "flow.output_zip_contains_json",
        "parsed_metrics",
        "decision",
    ):
        assert field in source


def test_ui_shows_python_only_and_json_only_param_warnings():
    source = STRATEGY_VIEW.read_text(encoding="utf-8")

    assert 'data-testid="strategy-warning-list"' in source
    assert "item.python_only_params" in source
    assert "item.json_only_params" in source
    assert "strategy-${label}-warning" in source
    assert "python-only" in source
    assert "json-only" in source


def test_autoquant_tab_includes_strategy_library_view():
    tab_source = AUTOQUANT_TAB.read_text(encoding="utf-8")
    api_source = API_CLIENT.read_text(encoding="utf-8")

    assert "StrategyLibraryView" in tab_source
    assert "@/components/aero/StrategyLibraryView" in tab_source
    assert "<StrategyLibraryView />" in tab_source
    assert "getStrategyLibraryScan" in api_source
    assert "getLatestAutoQuantFlow" in api_source
