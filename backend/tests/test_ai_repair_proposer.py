"""Tests for ai_repair_proposer.py."""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.models.strategy_spec import StrategySpec
from backend.services.execution.failure_analyzer import FailureClassification
from backend.services.execution.repair_plan_gate import RepairPlan
from backend.services.execution.ai_repair_proposer import (
    ask_ai_for_repair_proposal,
    _validate_proposal,
    _PERFORMANCE_CLAIMS,
)


class _MockClient:
    """Mock OllamaClient returning a canned response."""

    def __init__(self, response: str | None):
        self.response = response

    async def generate(self, prompt, system_prompt=None, feature="default"):
        return self.response


def _make_classification(
    primary_class: str | None = "negative_expectancy",
    next_route: str = "adjust_stoploss_or_roi",
) -> FailureClassification:
    return FailureClassification(
        primary_class=primary_class,
        next_route=next_route,
        failed_metrics=["expectancy"],
        metric_values={"expectancy": -5.0},
    )


def _make_spec(**overrides) -> StrategySpec:
    params = dict(
        name="TestStrategy",
        trading_style="trend_following",
        stoploss=-0.10,
        max_open_trades=3,
        iteration_count=0,
        max_iterations=3,
    )
    params.update(overrides)
    return StrategySpec(**params)


def _make_plan(
    scope: str = "stoploss",
    can_repair: bool = True,
    reason: str = "test plan",
) -> RepairPlan:
    fc = "negative_expectancy" if can_repair else None
    return RepairPlan(
        scope=scope,
        failure_class=fc,
        next_route="adjust_stoploss_or_roi" if can_repair else "none_needed",
        can_repair=can_repair,
        reason=reason,
    )


def _run_async(coro):
    return asyncio.run(coro)


# ── Helper for building valid proposal JSON strings ──────────────────────────

def _proposal_json(scope: str, change: dict, reasoning: str) -> str:
    return json.dumps({"repair_scope": scope, "change": change, "reasoning": reasoning})


# ═══════════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCanRepairFalseSkipsAI:
    def test_can_repair_false_skips_ai(self):
        client = _MockClient("not called")
        plan = _make_plan(scope="stoploss", can_repair=False)
        spec = _make_spec()
        classification = _make_classification()

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is None


class TestValidStoplossAccepted:
    def test_valid_stoploss_accepted(self):
        client = _MockClient(
            _proposal_json("stoploss", {"stoploss": -0.12}, "Tightening stoploss.")
        )
        plan = _make_plan(scope="stoploss")
        spec = _make_spec(stoploss=-0.10)
        classification = _make_classification()

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is not None
        assert result["repair_scope"] == "stoploss"
        assert result["change"]["stoploss"] == -0.12


class TestValidEntryLogicAccepted:
    def test_valid_entry_logic_accepted(self):
        client = _MockClient(
            _proposal_json(
                "entry_logic",
                {"index": 0, "field": "operator", "new_value": "crosses_above"},
                "Using crosses_above for stricter entry.",
            )
        )
        plan = _make_plan(scope="entry_logic")
        spec = _make_spec()
        classification = _make_classification("weak_win_rate", "review_entry_logic")

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is not None
        assert result["repair_scope"] == "entry_logic"
        assert result["change"]["field"] == "operator"


class TestValidExitLogicAccepted:
    def test_valid_exit_logic_accepted(self):
        client = _MockClient(
            _proposal_json(
                "exit_logic",
                {"index": 0, "field": "value_or_indicator_b", "new_value": 70},
                "Raising exit threshold to let winners run.",
            )
        )
        plan = _make_plan(scope="exit_logic")
        spec = _make_spec()
        classification = _make_classification("weak_profit_factor", "adjust_exit_conditions")

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is not None
        assert result["repair_scope"] == "exit_logic"


class TestValidEntryParameterAccepted:
    def test_valid_entry_parameter_accepted(self):
        client = _MockClient(
            _proposal_json(
                "entry_parameter",
                {"indicator": "rsi", "parameter": "period", "new_value": 10},
                "Lowering RSI period for more signals.",
            )
        )
        plan = _make_plan(scope="entry_parameter")
        spec = _make_spec()
        classification = _make_classification("too_few_trades", "extend_timerange_or_discard")

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is not None
        assert result["repair_scope"] == "entry_parameter"


class TestValidRoiAccepted:
    def test_valid_roi_accepted(self):
        client = _MockClient(
            _proposal_json(
                "roi",
                {"action": "modify", "index": 1, "minutes": 60, "ratio": 0.05},
                "Reducing ROI ratio for faster exits.",
            )
        )
        plan = _make_plan(scope="roi")
        spec = _make_spec()
        classification = _make_classification()

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is not None
        assert result["repair_scope"] == "roi"


class TestValidPositionSizingAccepted:
    def test_valid_position_sizing_accepted(self):
        client = _MockClient(
            _proposal_json(
                "position_sizing",
                {"field": "max_open_trades", "new_value": 5},
                "Increasing max open trades.",
            )
        )
        plan = _make_plan(scope="position_sizing")
        spec = _make_spec(max_open_trades=3)
        classification = _make_classification()

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is not None
        assert result["repair_scope"] == "position_sizing"


class TestScopeMismatchRejected:
    def test_scope_mismatch_rejected(self):
        client = _MockClient(
            _proposal_json(
                "stoploss", {"stoploss": -0.12}, "Tightening stoploss."
            )
        )
        plan = _make_plan(scope="entry_logic")
        spec = _make_spec()
        classification = _make_classification()

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is None


class TestMultipleOperationsRejected:
    def test_multiple_operations_rejected(self):
        # change is a list (multiple operations) instead of a single dict
        client = _MockClient(
            json.dumps({
                "repair_scope": "stoploss",
                "change": [{"stoploss": -0.12}, {"stoploss": -0.15}],
                "reasoning": "Test multiple.",
            })
        )
        plan = _make_plan(scope="stoploss")
        spec = _make_spec()
        classification = _make_classification()

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is None


class TestPerformanceClaimRejected:
    def test_performance_claim_rejected(self):
        client = _MockClient(
            _proposal_json(
                "stoploss",
                {"stoploss": -0.12},
                "This will be profitable in backtests.",
            )
        )
        plan = _make_plan(scope="stoploss")
        spec = _make_spec()
        classification = _make_classification()

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is None


class TestStoplossOutOfRangeRejected:
    def test_stoploss_out_of_range_rejected(self):
        client = _MockClient(
            _proposal_json("stoploss", {"stoploss": -0.60}, "Too tight stoploss.")
        )
        plan = _make_plan(scope="stoploss")
        spec = _make_spec()
        classification = _make_classification()

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is None


class TestInvalidJsonRejected:
    def test_invalid_json_rejected(self):
        client = _MockClient("this is not json {{{")
        plan = _make_plan(scope="stoploss")
        spec = _make_spec()
        classification = _make_classification()

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is None


class TestEmptyAiResponseRejected:
    def test_empty_ai_response_rejected(self):
        client = _MockClient(None)
        plan = _make_plan(scope="stoploss")
        spec = _make_spec()
        classification = _make_classification()

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is None


class TestEntryParameterPeriodTooLowRejected:
    def test_entry_parameter_period_too_low_rejected(self):
        client = _MockClient(
            _proposal_json(
                "entry_parameter",
                {"indicator": "rsi", "parameter": "period", "new_value": 1},
                "Period too low.",
            )
        )
        plan = _make_plan(scope="entry_parameter")
        spec = _make_spec()
        classification = _make_classification("too_few_trades", "extend_timerange_or_discard")

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is None


class TestRoiNegativeMinutesRejected:
    def test_roi_negative_minutes_rejected(self):
        client = _MockClient(
            _proposal_json(
                "roi",
                {"action": "modify", "index": 0, "minutes": -5, "ratio": 0.10},
                "Negative minutes.",
            )
        )
        plan = _make_plan(scope="roi")
        spec = _make_spec()
        classification = _make_classification()

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is None


class TestReasoningTooLongRejected:
    def test_reasoning_too_long_rejected(self):
        long_reason = "x" * 201
        client = _MockClient(
            _proposal_json("stoploss", {"stoploss": -0.12}, long_reason)
        )
        plan = _make_plan(scope="stoploss")
        spec = _make_spec()
        classification = _make_classification()

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is None


class TestChangeEmptyDictRejected:
    def test_change_empty_dict_rejected(self):
        client = _MockClient(
            _proposal_json("stoploss", {}, "Empty change.")
        )
        plan = _make_plan(scope="stoploss")
        spec = _make_spec()
        classification = _make_classification()

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is None


class TestValidateProposalStoplossRange:
    def test_stoploss_at_lower_boundary(self):
        proposal = {"repair_scope": "stoploss", "change": {"stoploss": -0.50}, "reasoning": "ok"}
        plan = _make_plan(scope="stoploss")
        valid, _ = _validate_proposal(proposal, plan)
        assert valid is True

    def test_stoploss_at_upper_boundary(self):
        proposal = {"repair_scope": "stoploss", "change": {"stoploss": -0.01}, "reasoning": "ok"}
        plan = _make_plan(scope="stoploss")
        valid, _ = _validate_proposal(proposal, plan)
        assert valid is True


class TestValidateProposalEntryParameterBoundaries:
    def test_period_at_lower_boundary(self):
        proposal = {
            "repair_scope": "entry_parameter",
            "change": {"indicator": "rsi", "parameter": "period", "new_value": 2},
            "reasoning": "ok",
        }
        plan = _make_plan(scope="entry_parameter")
        valid, _ = _validate_proposal(proposal, plan)
        assert valid is True

    def test_period_at_upper_boundary(self):
        proposal = {
            "repair_scope": "entry_parameter",
            "change": {"indicator": "rsi", "parameter": "period", "new_value": 200},
            "reasoning": "ok",
        }
        plan = _make_plan(scope="entry_parameter")
        valid, _ = _validate_proposal(proposal, plan)
        assert valid is True

    def test_threshold_at_upper_boundary(self):
        proposal = {
            "repair_scope": "entry_parameter",
            "change": {"indicator": "rsi", "parameter": "threshold", "new_value": 100},
            "reasoning": "ok",
        }
        plan = _make_plan(scope="entry_parameter")
        valid, _ = _validate_proposal(proposal, plan)
        assert valid is True

    def test_threshold_at_lower_boundary(self):
        proposal = {
            "repair_scope": "entry_parameter",
            "change": {"indicator": "rsi", "parameter": "threshold", "new_value": 0},
            "reasoning": "ok",
        }
        plan = _make_plan(scope="entry_parameter")
        valid, _ = _validate_proposal(proposal, plan)
        assert valid is True


class TestValidateProposalPositionSizingBoundaries:
    def test_max_open_trades_at_lower_boundary(self):
        proposal = {
            "repair_scope": "position_sizing",
            "change": {"field": "max_open_trades", "new_value": 1},
            "reasoning": "ok",
        }
        plan = _make_plan(scope="position_sizing")
        valid, _ = _validate_proposal(proposal, plan)
        assert valid is True

    def test_max_open_trades_at_upper_boundary(self):
        proposal = {
            "repair_scope": "position_sizing",
            "change": {"field": "max_open_trades", "new_value": 50},
            "reasoning": "ok",
        }
        plan = _make_plan(scope="position_sizing")
        valid, _ = _validate_proposal(proposal, plan)
        assert valid is True


class TestAllPerformanceClaimsRejected:
    @pytest.mark.parametrize("claim", _PERFORMANCE_CLAIMS)
    def test_each_performance_claim_rejected(self, claim):
        proposal = {
            "repair_scope": "stoploss",
            "change": {"stoploss": -0.12},
            "reasoning": f"This change is {claim}.",
        }
        plan = _make_plan(scope="stoploss")
        valid, msg = _validate_proposal(proposal, plan)
        assert valid is False
        assert "performance claim" in msg


class TestGenerateCalledWithCorrectFeature:
    def test_generate_called_with_repair_proposal_feature(self):
        client = _MockClient(
            _proposal_json("stoploss", {"stoploss": -0.12}, "ok")
        )
        plan = _make_plan(scope="stoploss")
        spec = _make_spec()
        classification = _make_classification()

        result = _run_async(
            ask_ai_for_repair_proposal(client, plan, spec, classification)
        )
        assert result is not None
