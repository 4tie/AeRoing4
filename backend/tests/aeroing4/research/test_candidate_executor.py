"""Tests for Candidate Executor (PROMPT 8 §3).

Uses a FAKE BacktestRunner so no Freqtrade is required. Verifies:
  * DEVELOP timerange is used (not confirmation/final_unseen).
  * run_candidate_backtest is called with params_override (champion version untouched).
  * status / metrics / artifacts returned via the existing adapter path.
  * failure classifications (system failure, no trades) work.
  * strategies/sidecar are never executed against the champion's original file.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from backend.services.aeroing4.metrics.adapters import from_parsed_summary
from backend.services.aeroing4.research.candidate_artifacts import (
    CandidateArtifactService,
)
from backend.services.aeroing4.research.candidate_executor import (
    CandidateExecutor,
    CandidateExecutionStatus,
)
from backend.services.aeroing4.research.champions import (
    ArtifactReference,
    ChampionReference,
    ChampionSourceType,
)
from backend.services.aeroing4.research.experiments import ExactChange


def _seed_champion(runs_root: Path, strategy_name: str = "AIStrategy"):
    strategies_dir = runs_root / "strategies"
    strategies_dir.mkdir(parents=True, exist_ok=True)
    orig_py = strategies_dir / f"{strategy_name}.py"
    orig_py.write_text("class AIStrategy:\n    pass\n", encoding="utf-8")
    orig_sidecar = strategies_dir / f"{strategy_name}.json"
    orig_sidecar.write_text(
        json.dumps(
            {
                "params": {
                    "buy": {"buy_ma_count": 18, "buy_ma_gap": 95},
                    "sell": {"sell_ma_count": 17, "sell_ma_gap": 54},
                    "roi": {"0": 0.192, "145": 0.0},
                    "stoploss": {"stoploss": -0.336},
                    "trailing": {
                        "trailing_stop": False,
                        "trailing_stop_positive_offset": 0.0,
                        "trailing_only_offset_is_reached": False,
                    },
                },
                "parameters": {
                    "buy_ma_count": {
                        "type": "int",
                        "editable": True,
                        "current": 18,
                        "min": 1,
                        "max": 20,
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return orig_py, orig_sidecar


def _make_champion(orig_py: Path, orig_sidecar: Path) -> ChampionReference:
    return ChampionReference(
        run_id="run-1",
        parent_champion_id=None,
        source_type=ChampionSourceType.BASELINE,
        strategy_artifact=ArtifactReference(
            artifact_path="champions/x.py",
            artifact_hash="abc",
            original_source_path=str(orig_py),
            original_source_hash="src-hash",
        ),
        parameter_artifact=ArtifactReference(
            artifact_path="champions/x.json",
            artifact_hash="def",
            original_source_path=str(orig_sidecar),
            original_source_hash="param-hash",
        ),
    )


def _make_fake_runner(with_summary: bool = True, raise_on_run: bool = False):
    calls = {}

    def run_candidate_backtest(strategy, version_id, request, *, params_override=None):
        calls["request"] = request
        calls["params_override"] = params_override
        calls["strategy"] = strategy
        if raise_on_run:
            raise RuntimeError("freqtrade exploded")
        if with_summary:
            calls["summary"] = {
                "total_trades": 120,
                "profit_factor": 1.6,
                "expectancy": 0.01,
                "max_drawdown_pct": 12.0,
                "win_rate": 0.62,
            }
        return "fake-exec-id"

    def find_run_dir(exec_id):
        # Materialize a parsed summary where the real runner would, so the
        # adapter path (_load_backtest_summary) is exercised.
        d = Path(tempfile.mkdtemp())
        if with_summary:
            (d / "parsed_summary.json").write_text(
                json.dumps(calls.get("summary", {})), encoding="utf-8"
            )
        return d

    runner = SimpleNamespace(
        run_candidate_backtest=run_candidate_backtest,
        run_repository=SimpleNamespace(find_run_dir=find_run_dir),
    )
    return runner, calls


def test_executor_uses_develop_timerange_and_override(tmp_path: Path):
    orig_py, orig_sidecar = _seed_champion(tmp_path)
    champ = _make_champion(orig_py, orig_sidecar)
    svc = CandidateArtifactService(tmp_path)
    change = ExactChange(
        change_type="parameter", target="buy_ma_count", before_value=18, after_value=15
    )
    artifact = svc.create(
        run_id="run-1", strategy_name="AIStrategy", champion=champ, exact_change=change
    )

    runner, calls = _make_fake_runner()
    executor = CandidateExecutor(tmp_path, runner)
    result = executor.execute(
        run_id="run-1",
        strategy_name="AIStrategy",
        version_id="v1",
        champion=champ,
        candidate_artifact_result=artifact,
        exact_change=change,
        develop_timerange="20240101-20240630",  # DEVELOP only
        pairs=["BTC/USDT"],
        timeframe="5m",
    )

    # DEVELOP timerange used.
    assert calls["request"].timerange == "20240101-20240630"
    # params_override supplied (champion version untouched by design).
    assert calls["params_override"] is not None
    assert calls["params_override"].strategy_name == "AIStrategy"
    # Candidate strategy .py copy used, never the champion original.
    assert "candidates" in calls["strategy"].file_path
    # Result shape.
    assert result.status == CandidateExecutionStatus.SUCCESS
    assert result.underlying_execution_id == "fake-exec-id"
    assert result.metrics is not None
    assert result.metrics.profit_factor.value == 1.6


def test_executor_system_failure_on_run_error(tmp_path: Path):
    orig_py, orig_sidecar = _seed_champion(tmp_path)
    champ = _make_champion(orig_py, orig_sidecar)
    svc = CandidateArtifactService(tmp_path)
    change = ExactChange(
        change_type="parameter", target="buy_ma_count", before_value=18, after_value=15
    )
    artifact = svc.create(
        run_id="run-1", strategy_name="AIStrategy", champion=champ, exact_change=change
    )
    runner, _ = _make_fake_runner(raise_on_run=True)
    executor = CandidateExecutor(tmp_path, runner)
    result = executor.execute(
        run_id="run-1",
        strategy_name="AIStrategy",
        version_id="v1",
        champion=champ,
        candidate_artifact_result=artifact,
        exact_change=change,
        develop_timerange="20240101-20240630",
        pairs=["BTC/USDT"],
        timeframe="5m",
    )
    assert result.status == CandidateExecutionStatus.SYSTEM_FAILURE
    assert result.underlying_execution_id is None
    assert result.failure_classification is not None


def test_executor_no_trades_classification(tmp_path: Path):
    orig_py, orig_sidecar = _seed_champion(tmp_path)
    champ = _make_champion(orig_py, orig_sidecar)
    svc = CandidateArtifactService(tmp_path)
    change = ExactChange(
        change_type="parameter", target="buy_ma_count", before_value=18, after_value=15
    )
    artifact = svc.create(
        run_id="run-1", strategy_name="AIStrategy", champion=champ, exact_change=change
    )

    # Fake runner returns an exec id; we pre-write a zero-trade summary.
    def run_candidate_backtest(strategy, version_id, request, *, params_override=None):
        return "fake-exec-id-zero"

    runner = SimpleNamespace(
        run_candidate_backtest=run_candidate_backtest,
        run_repository=SimpleNamespace(
            find_run_dir=lambda _id: tmp_path / "runs" / _id
        ),
    )
    (tmp_path / "runs" / "fake-exec-id-zero").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs" / "fake-exec-id-zero" / "parsed_summary.json").write_text(
        json.dumps({"total_trades": 0, "profit_factor": 1.0}), encoding="utf-8"
    )

    executor = CandidateExecutor(tmp_path, runner)
    result = executor.execute(
        run_id="run-1",
        strategy_name="AIStrategy",
        version_id="v1",
        champion=champ,
        candidate_artifact_result=artifact,
        exact_change=change,
        develop_timerange="20240101-20240630",
        pairs=["BTC/USDT"],
        timeframe="5m",
    )
    assert result.status == CandidateExecutionStatus.NO_TRADES
    assert result.metrics.total_trades.value == 0
