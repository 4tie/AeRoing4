"""Tests for AeRoing4 Proposal Generator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.aeroing4.metrics.models import (
    CanonicalMetricsSnapshot,
    MetricAvailability,
    MetricProvenance,
    MetricValue,
)
from backend.services.aeroing4.metrics.provenance import SourceType
from backend.services.aeroing4.research.allowed_targets import (
    AllowedMutationTarget,
    MutationTargetRiskClass,
    MutationTargetSource,
)
from backend.services.aeroing4.research.proposal_generator import (
    ProposalOutcome,
    ProposalRequest,
    ProposalResult,
    ProposalSchemaValidationError,
    ProposalGenerator,
    OllamaProposalAdapter,
    _validate_proposal_payload,
)


def make_metrics() -> CanonicalMetricsSnapshot:
    return CanonicalMetricsSnapshot(
        total_trades=MetricValue.available(10),
        winning_trades=MetricValue.available(4),
        losing_trades=MetricValue.available(6),
        net_profit_abs=MetricValue.available(-0.05),
        net_profit_pct=MetricValue.available(-0.5),
        win_rate=MetricValue.available(40.0),
        profit_factor=MetricValue.available(0.8),
        expectancy=MetricValue.available(-0.005),
        sharpe=MetricValue.unavailable(),
        sortino=MetricValue.unavailable(),
        calmar=MetricValue.unavailable(),
        max_drawdown_abs=MetricValue.available(0.2),
        max_drawdown_pct=MetricValue.available(20.0),
        average_trade_duration_minutes=MetricValue.available(45.0),
        bootstrap_sharpe_p5=MetricValue.insufficient_data(),
        provenance=MetricProvenance(
            metrics_version="1.0.0",
            source_type=SourceType.PARSED_SUMMARY,
            source_run_id="run-1",
            calculation_timestamp="2024-01-01T00:00:00Z",
        ),
    )


def test_validate_proposal_payload_accepts_valid():
    payload = {
        "hypothesis_text": "h",
        "diagnosis_code": "no_edge",
        "evidence_refs": ["pf"],
        "exact_change": {"change_type": "parameter", "target": "stoploss", "before_value": -0.05, "after_value": -0.1},
        "expected_effect": "less downside",
        "success_criteria": "PF>1",
        "risk": "whipsaw",
        "confidence": 0.7,
    }
    assert _validate_proposal_payload(payload) == payload


def test_validate_proposal_payload_rejects_executable_fields():
    payload = {"hypothesis_text": "h", "exec": "bad"}
    with pytest.raises(ProposalSchemaValidationError):
        _validate_proposal_payload(payload)


def test_validate_proposal_payload_rejects_unknown_fields():
    payload = {"hypothesis_text": "h", "unknown_field": 1}
    with pytest.raises(ProposalSchemaValidationError):
        _validate_proposal_payload(payload)


def test_parse_response_accepted():
    adapter = OllamaProposalAdapter()
    payload = {
        "hypothesis_text": "h",
        "diagnosis_code": "no_edge",
        "evidence_refs": ["pf"],
        "exact_change": {"change_type": "parameter", "target": "stoploss", "before_value": -0.05, "after_value": -0.1},
        "expected_effect": "less downside",
        "success_criteria": "PF>1",
        "risk": "whipsaw",
        "confidence": 0.7,
    }
    result = adapter._parse_response(json.dumps(payload))
    assert result.outcome == ProposalOutcome.ACCEPTED
    assert result.exact_change.target == "stoploss"


def test_parse_response_malformed_becomes_skipped():
    adapter = OllamaProposalAdapter()
    result = adapter._parse_response("not json at all")
    assert result.outcome == ProposalOutcome.AI_PROPOSAL_SKIPPED
    assert result.rejection_reason is not None


@pytest.mark.asyncio
async def test_generate_unavailable_returns_unavailable():
    with patch(
        "backend.services.ai.ollama_client.OllamaClient",
        side_effect=RuntimeError("no ollama"),
    ):
        generator = ProposalGenerator()
        request = ProposalRequest(
            run_id="run-1",
            hypothesis_id="hyp-1",
            allowed_targets=[AllowedMutationTarget(name="stoploss", type="float")],
            champion_metrics=make_metrics(),
        )
        result = await generator.propose(request)
    assert result.outcome == ProposalOutcome.AI_UNAVAILABLE


@pytest.mark.asyncio
async def test_generate_skipped_for_force_skip():
    generator = ProposalGenerator()
    request = ProposalRequest(run_id="run-1", hypothesis_id="hyp-1", context_limits={"force_skip": True})
    result = await generator.propose(request)
    assert result.outcome == ProposalOutcome.AI_PROPOSAL_SKIPPED
