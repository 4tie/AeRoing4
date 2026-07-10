"""Tests for candidate workflow models."""

from backend.services.candidate.models import (
    CandidateConfig,
    CandidateGateResult,
    CandidateVerdict,
    RepairAttempt,
)


def test_candidate_config_construction():
    config = CandidateConfig(
        timerange="20230101-20231231",
        timeframe="1h",
        pairs=["BTC/USDT", "ETH/USDT"],
        user_data_dir="/tmp/user_data",
    )
    assert config.timerange == "20230101-20231231"
    assert config.timeframe == "1h"
    assert config.pairs == ["BTC/USDT", "ETH/USDT"]
    assert config.user_data_dir == "/tmp/user_data"
    assert config.exchange == "binance"
    assert config.max_repair_iterations == 3
    assert config.auto_download_data is True
    assert config.max_data_download_attempts == 1


def test_candidate_config_defaults():
    config = CandidateConfig(
        timerange="20230101-20231231",
        timeframe="1h",
        pairs=[],
        user_data_dir="/tmp/user_data",
    )
    assert config.exchange == "binance"
    assert config.max_repair_iterations == 3
    assert config.auto_download_data is True
    assert config.max_data_download_attempts == 1


def test_candidate_gate_result_construction():
    result = CandidateGateResult(
        gate_name="data_quality",
        passed=True,
        details={"checks": 5, "failed": 0},
    )
    assert result.gate_name == "data_quality"
    assert result.passed is True
    assert result.details == {"checks": 5, "failed": 0}
    assert result.metrics is None


def test_candidate_gate_result_failed():
    result = CandidateGateResult(
        gate_name="backtest",
        passed=False,
        details={"error": "no trades"},
        metrics={"trades": 0},
    )
    assert result.passed is False
    assert result.metrics == {"trades": 0}


def test_repair_attempt_construction():
    attempt = RepairAttempt(
        iteration=1,
        scope="stoploss",
        change_applied={"stoploss": -0.15},
        outcome="applied",
    )
    assert attempt.iteration == 1
    assert attempt.scope == "stoploss"
    assert attempt.change_applied == {"stoploss": -0.15}
    assert attempt.outcome == "applied"


def test_repair_attempt_defaults():
    attempt = RepairAttempt(iteration=0)
    assert attempt.scope is None
    assert attempt.change_applied is None
    assert attempt.outcome == "unknown"


def test_candidate_verdict_construction():
    verdict = CandidateVerdict(passed=True)
    assert verdict.passed is True
    assert verdict.gate_results == []
    assert verdict.repair_attempts == []
    assert verdict.final_pair_set == []
    assert verdict.portfolio_metrics == {}
    assert verdict.failure_reason is None


def test_candidate_verdict_with_gate_results():
    verdict = CandidateVerdict(
        passed=False,
        gate_results=[
            CandidateGateResult(gate_name="gate_1", passed=True),
            CandidateGateResult(gate_name="gate_2", passed=False),
        ],
        repair_attempts=[
            RepairAttempt(iteration=1, outcome="applied"),
        ],
        final_pair_set=["BTC/USDT"],
        portfolio_metrics={"profit_factor": 1.2},
        failure_reason="gate_2 failed",
    )
    assert verdict.passed is False
    assert len(verdict.gate_results) == 2
    assert verdict.gate_results[0].gate_name == "gate_1"
    assert verdict.gate_results[1].passed is False
    assert len(verdict.repair_attempts) == 1
    assert verdict.final_pair_set == ["BTC/USDT"]
    assert verdict.portfolio_metrics == {"profit_factor": 1.2}
    assert verdict.failure_reason == "gate_2 failed"


def test_candidate_verdict_serialization():
    verdict = CandidateVerdict(
        passed=True,
        gate_results=[
            CandidateGateResult(gate_name="g1", passed=True),
        ],
    )
    d = verdict.model_dump()
    assert d["passed"] is True
    assert len(d["gate_results"]) == 1
    assert d["gate_results"][0]["gate_name"] == "g1"
    assert d["gate_results"][0]["passed"] is True
