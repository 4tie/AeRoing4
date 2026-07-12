from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
STRATEGY_VIEW = REPO_ROOT / "frontend" / "components" / "aero" / "StrategyLibraryView.tsx"
AUTOQUANT_TAB = REPO_ROOT / "frontend" / "components" / "aero" / "TabAutoQuant.tsx"
STRATEGIES_TAB = REPO_ROOT / "frontend" / "components" / "aero" / "TabStrategies.tsx"
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


PARTIAL_ARTIFACT_FLOW_FIXTURE = {
    "run_id": "partial-artifact-run",
    "candidate": {
        "run_id": "partial-artifact-run",
        "experiment_id": "partial-experiment",
        "candidate_id": None,
        "strategy_name": "MultiMa",
        "official_source_strategy_path": "user_data/strategies/MultiMa.py",
        "official_source_json_path": "user_data/strategies/MultiMa.json",
        "candidate_directory": "user_data/aeroing4/runs/partial-artifact-run/experiments/partial-experiment/candidate",
        "copied_candidate_py": "user_data/aeroing4/runs/partial-artifact-run/experiments/partial-experiment/candidate/MultiMa.py",
        "copied_candidate_json": "user_data/aeroing4/runs/partial-artifact-run/experiments/partial-experiment/candidate/MultiMa.json",
        "official_files_unchanged": None,
        "freqtrade_command": "freqtrade backtesting --strategy-path user_data/aeroing4/runs/partial-artifact-run/experiments/partial-experiment/candidate --strategy MultiMa",
        "strategy_path_argument": "user_data/aeroing4/runs/partial-artifact-run/experiments/partial-experiment/candidate",
        "strategy_path_points_to_candidate_dir": True,
        "strategy_path_points_to_run_dir": False,
        "strategy_path_points_to_candidate_or_run_dir": True,
        "output_zip_path": "user_data/aeroing4/runs/partial-artifact-run/experiments/partial-experiment/backtest_results/backtest-result.zip",
        "output_zip_contains_py": True,
        "output_zip_contains_json": True,
        "parsed_metrics": {},
        "decision": "UNAVAILABLE",
        "reason_codes": ["INCOMPLETE_EXPERIMENT_RECORD"],
        "steps": [
            {
                "name": "Source Strategy",
                "status": "done",
                "paths": {
                    "official_strategy": "user_data/strategies/MultiMa.py",
                    "official_json": "user_data/strategies/MultiMa.json",
                },
                "message": "Official strategy source loaded.",
                "technical_details": {"strategy_name": "MultiMa"},
            },
            {
                "name": "Candidate Copy",
                "status": "done",
                "paths": {
                    "candidate_dir": "user_data/aeroing4/runs/partial-artifact-run/experiments/partial-experiment/candidate",
                    "candidate_py": "user_data/aeroing4/runs/partial-artifact-run/experiments/partial-experiment/candidate/MultiMa.py",
                    "candidate_json": "user_data/aeroing4/runs/partial-artifact-run/experiments/partial-experiment/candidate/MultiMa.json",
                },
                "message": "Candidate copy created from artifacts.",
                "technical_details": {"official_files_unchanged": None},
            },
            {
                "name": "Freqtrade Execution",
                "status": "done",
                "paths": {
                    "strategy_path": "user_data/aeroing4/runs/partial-artifact-run/experiments/partial-experiment/candidate",
                },
                "message": "Freqtrade command captured with run-local --strategy-path.",
                "technical_details": {"command": "freqtrade backtesting --strategy-path user_data/aeroing4/runs/partial-artifact-run/experiments/partial-experiment/candidate --strategy MultiMa", "contains_strategy_path": True},
            },
            {
                "name": "Metrics Parsing",
                "status": "done",
                "paths": {"output_zip": "user_data/aeroing4/runs/partial-artifact-run/experiments/partial-experiment/backtest_results/backtest-result.zip"},
                "message": "Output zip available.",
                "technical_details": {
                    "zip_contains_py": True,
                    "zip_contains_json": True,
                },
            },
            {
                "name": "Decision",
                "status": "missing",
                "paths": {},
                "message": "Research decision not available (incomplete experiment record).",
                "technical_details": {"status": "missing", "reason": "ExperimentRecord incomplete"},
            },
            {
                "name": "Next Action",
                "status": "missing",
                "paths": {},
                "message": "Next action not available (research decision incomplete).",
                "technical_details": {"status": "missing", "reason": "ExperimentRecord incomplete"},
            },
        ],
    },
    "message": "Candidate flow built from partial artifacts (research decision incomplete).",
}


def test_partial_artifact_flow_shows_available_fields():
    """Test that partial artifact flow shows available fields and marks missing decision."""
    candidate = PARTIAL_ARTIFACT_FLOW_FIXTURE["candidate"]
    
    # Required fields should be present
    assert candidate["official_source_strategy_path"] is not None
    assert candidate["official_source_json_path"] is not None
    assert candidate["candidate_directory"] is not None
    assert candidate["copied_candidate_py"] is not None
    assert candidate["copied_candidate_json"] is not None
    assert candidate["freqtrade_command"] is not None
    assert candidate["strategy_path_argument"] is not None
    assert candidate["output_zip_path"] is not None
    assert candidate["output_zip_contains_py"] is True
    assert candidate["output_zip_contains_json"] is True
    
    # Decision should be marked as unavailable
    assert candidate["decision"] == "UNAVAILABLE"
    assert "INCOMPLETE_EXPERIMENT_RECORD" in candidate["reason_codes"]
    
    # Metrics should be empty (not available)
    assert candidate["parsed_metrics"] == {}
    
    # Steps should show missing status for decision and next action
    decision_step = next(s for s in candidate["steps"] if s["name"] == "Decision")
    assert decision_step["status"] == "missing"
    assert "incomplete experiment record" in decision_step["message"].lower()
    
    next_action_step = next(s for s in candidate["steps"] if s["name"] == "Next Action")
    assert next_action_step["status"] == "missing"
    assert "incomplete" in next_action_step["message"].lower()
    
    # Other steps should show done status
    source_step = next(s for s in candidate["steps"] if s["name"] == "Source Strategy")
    assert source_step["status"] == "done"
    
    candidate_copy_step = next(s for s in candidate["steps"] if s["name"] == "Candidate Copy")
    assert candidate_copy_step["status"] == "done"
    
    execution_step = next(s for s in candidate["steps"] if s["name"] == "Freqtrade Execution")
    assert execution_step["status"] == "done"
    assert execution_step["technical_details"]["contains_strategy_path"] is True
    
    metrics_step = next(s for s in candidate["steps"] if s["name"] == "Metrics Parsing")
    assert metrics_step["status"] == "done"


def test_partial_artifact_flow_does_not_invent_metrics_or_decision():
    """Test that partial artifact flow does not invent fake metrics or decisions."""
    candidate = PARTIAL_ARTIFACT_FLOW_FIXTURE["candidate"]
    
    # Decision should not be a real trading decision
    assert candidate["decision"] not in ["KEEP", "DROP", "INCONCLUSIVE"]
    assert candidate["decision"] == "UNAVAILABLE"
    
    # Metrics should be empty, not fake values
    assert candidate["parsed_metrics"] == {}
    assert "total_trades" not in candidate["parsed_metrics"]
    assert "profit_factor" not in candidate["parsed_metrics"]
    
    # Reason codes should clearly indicate incomplete record
    assert "INCOMPLETE_EXPERIMENT_RECORD" in candidate["reason_codes"]


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
    # After UI/UX reset, Strategy Library is now in its own tab (TabStrategies.tsx)
    # This test verifies the new structure
    tab_source = AUTOQUANT_TAB.read_text(encoding="utf-8")
    strategies_tab_source = STRATEGIES_TAB.read_text(encoding="utf-8")
    api_source = API_CLIENT.read_text(encoding="utf-8")

    # AutoQuant tab should NOT contain StrategyLibraryView anymore
    assert "StrategyLibraryView" not in tab_source
    assert "<StrategyLibraryView />" not in tab_source

    # Strategy Library tab should contain StrategyLibraryView
    assert "StrategyLibraryView" in strategies_tab_source
    assert "@/components/aero/StrategyLibraryView" in strategies_tab_source
    assert "<StrategyLibraryTable" in strategies_tab_source

    # API should still have the endpoints
    assert "getStrategyLibraryScan" in api_source
    assert "getLatestAutoQuantFlow" in api_source
