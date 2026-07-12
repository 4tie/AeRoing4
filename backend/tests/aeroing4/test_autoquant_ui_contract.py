from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
STRATEGY_VIEW = REPO_ROOT / "frontend" / "components" / "aero" / "StrategyLibraryView.tsx"
AUTOQUANT_TAB = REPO_ROOT / "frontend" / "components" / "aero" / "TabAutoQuant.tsx"
API_CLIENT = REPO_ROOT / "frontend" / "lib" / "api.ts"

EMPTY_FLOW_RESPONSE_FIXTURE = {
    "run_id": "fixture-empty-run",
    "candidate": None,
    "message": "No candidate experiment artifacts found yet.",
}

POPULATED_FLOW_FIXTURE = {
    "run_id": "fixture-run-ui-only",
    "candidate": {
        "run_id": "fixture-run-ui-only",
        "experiment_id": "fixture-experiment-ui-only",
        "candidate_id": "fixture-candidate-ui-only",
        "strategy_name": "FixtureStrategy",
        "official_source_strategy_path": "user_data/strategies/FixtureStrategy.py",
        "official_source_json_path": "user_data/strategies/FixtureStrategy.json",
        "candidate_directory": "user_data/aeroing4/runs/fixture-run-ui-only/candidates/fixture-candidate-ui-only",
        "copied_candidate_py": "user_data/aeroing4/runs/fixture-run-ui-only/candidates/fixture-candidate-ui-only/FixtureStrategy.py",
        "copied_candidate_json": "user_data/aeroing4/runs/fixture-run-ui-only/candidates/fixture-candidate-ui-only/FixtureStrategy.json",
        "official_files_unchanged": True,
        "freqtrade_command": (
            "freqtrade backtesting --strategy-path "
            "user_data/aeroing4/runs/fixture-run-ui-only/candidates/fixture-candidate-ui-only "
            "--strategy FixtureStrategy"
        ),
        "strategy_path_argument": "user_data/aeroing4/runs/fixture-run-ui-only/candidates/fixture-candidate-ui-only",
        "strategy_path_points_to_candidate_dir": True,
        "strategy_path_points_to_run_dir": False,
        "strategy_path_points_to_candidate_or_run_dir": True,
        "output_zip_path": "user_data/aeroing4/runs/fixture-run-ui-only/artifacts/fixture-result.zip",
        "output_zip_contains_py": True,
        "output_zip_contains_json": True,
        "parsed_metrics": {
            "total_trades": 12,
            "profit_factor": 0.82,
            "expectancy": -0.01,
            "max_drawdown_pct": 18.4,
        },
        "decision": "DROP",
        "reason_codes": ["fixture:test_data", "decision:drop", "insufficient_edge_fixture"],
        "steps": [
            {
                "name": "Source Strategy",
                "status": "done",
                "paths": {
                    "official_strategy": "user_data/strategies/FixtureStrategy.py",
                    "official_json": "user_data/strategies/FixtureStrategy.json",
                },
                "message": "Fixture source files loaded for UI contract testing only.",
                "technical_details": {"fixture": True},
            },
            {
                "name": "Candidate Copy",
                "status": "done",
                "paths": {
                    "candidate_dir": "user_data/aeroing4/runs/fixture-run-ui-only/candidates/fixture-candidate-ui-only",
                    "candidate_py": "user_data/aeroing4/runs/fixture-run-ui-only/candidates/fixture-candidate-ui-only/FixtureStrategy.py",
                    "candidate_json": "user_data/aeroing4/runs/fixture-run-ui-only/candidates/fixture-candidate-ui-only/FixtureStrategy.json",
                },
                "message": "Fixture candidate files copied for UI contract testing only.",
                "technical_details": {"official_files_unchanged": True},
            },
            {
                "name": "Freqtrade Execution",
                "status": "done",
                "paths": {
                    "strategy_path": "user_data/aeroing4/runs/fixture-run-ui-only/candidates/fixture-candidate-ui-only",
                },
                "message": "Fixture command contains --strategy-path.",
                "technical_details": {"contains_strategy_path": True},
            },
            {
                "name": "Metrics Parsing",
                "status": "done",
                "paths": {"output_zip": "user_data/aeroing4/runs/fixture-run-ui-only/artifacts/fixture-result.zip"},
                "message": "Fixture metrics parsed for UI contract testing only.",
                "technical_details": {"zip_contains_py": True, "zip_contains_json": True},
            },
            {
                "name": "Decision",
                "status": "done",
                "paths": {},
                "message": "Decision: DROP.",
                "technical_details": {"reason_codes": ["fixture:test_data", "decision:drop"]},
            },
            {
                "name": "Next Action",
                "status": "done",
                "paths": {},
                "message": "Keep parent champion and move to the next fixture hypothesis.",
                "technical_details": {"fixture": True},
            },
        ],
    },
    "message": "Fixture populated flow for UI contract tests only.",
}


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


def test_strategy_library_warning_codes_have_readable_messages():
    source = STRATEGY_VIEW.read_text(encoding="utf-8")

    expected_messages = {
        "PYTHON_ONLY_PARAMS": "These parameters exist in the Python strategy but are missing from the JSON sidecar.",
        "EMPTY_JSON_BUY_SELL_WITH_PYTHON_PARAMS": (
            "The JSON buy/sell parameter blocks are empty, but the Python file defines tunable parameters."
        ),
        "PARAMS_NOT_RUNTIME_EXECUTABLE": (
            "Some detected parameters cannot be changed safely through the JSON sidecar yet."
        ),
    }
    assert "WARNING_COPY" in source
    assert "readableStrategyWarning" in source
    for code, message in expected_messages.items():
        assert code in source
        assert message in source


def test_empty_autoquant_flow_renders_clear_empty_state():
    source = STRATEGY_VIEW.read_text(encoding="utf-8")

    assert EMPTY_FLOW_RESPONSE_FIXTURE["candidate"] is None
    assert 'data-testid="candidate-flow-empty-state"' in source
    assert (
        "No candidate has been created yet. Select a strategy and start a DEVELOP test to populate this flow."
        in source
    )
    for step_name in (
        "Source Strategy",
        "Candidate Copy",
        "Freqtrade Execution",
        "Metrics Parsing",
        "Decision",
        "Next Action",
    ):
        assert step_name in source


def test_populated_autoquant_flow_fixture_renders_all_six_steps():
    source = STRATEGY_VIEW.read_text(encoding="utf-8")
    candidate = POPULATED_FLOW_FIXTURE["candidate"]

    assert candidate is not None
    assert [step["name"] for step in candidate["steps"]] == [
        "Source Strategy",
        "Candidate Copy",
        "Freqtrade Execution",
        "Metrics Parsing",
        "Decision",
        "Next Action",
    ]
    assert 'data-testid="candidate-flow-step-card"' in source
    assert "stepSentence" in source
    assert "StatusBadge" in source


def test_populated_autoquant_flow_fixture_shows_strategy_path_and_paths():
    source = STRATEGY_VIEW.read_text(encoding="utf-8")
    candidate = POPULATED_FLOW_FIXTURE["candidate"]

    assert candidate is not None
    assert "--strategy-path" in candidate["freqtrade_command"]
    for field in (
        "flow.official_source_strategy_path",
        "flow.official_source_json_path",
        "flow.candidate_directory",
        "flow.copied_candidate_py",
        "flow.copied_candidate_json",
        "flow.strategy_path_argument",
    ):
        assert field in source


def test_populated_autoquant_flow_fixture_shows_metrics_decision_and_reasons():
    source = STRATEGY_VIEW.read_text(encoding="utf-8")
    candidate = POPULATED_FLOW_FIXTURE["candidate"]

    assert candidate is not None
    assert set(candidate["parsed_metrics"]) == {
        "total_trades",
        "profit_factor",
        "expectancy",
        "max_drawdown_pct",
    }
    assert candidate["decision"] == "DROP"
    assert "fixture:test_data" in candidate["reason_codes"]
    assert "flow.reason_codes" in source
    assert "DECISION REASONS" in source
    assert "PARSED METRICS" in source


def test_populated_fixture_does_not_trigger_real_research_or_late_stage_work():
    fixture_text = json.dumps(POPULATED_FLOW_FIXTURE).lower()

    assert "fixture" in fixture_text
    assert "freqtrade backtesting" in fixture_text
    for prohibited in (
        "hyperopt",
        "ai repair",
        "confirmation",
        "final unseen",
        "delivery",
    ):
        assert prohibited not in fixture_text


def test_autoquant_tab_includes_strategy_library_view():
    tab_source = AUTOQUANT_TAB.read_text(encoding="utf-8")
    api_source = API_CLIENT.read_text(encoding="utf-8")

    assert "StrategyLibraryView" in tab_source
    assert "@/components/aero/StrategyLibraryView" in tab_source
    assert "<StrategyLibraryView />" in tab_source
    assert "getStrategyLibraryScan" in api_source
    assert "getLatestAutoQuantFlow" in api_source
