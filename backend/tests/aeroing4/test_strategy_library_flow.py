from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routers import aeroing4
from backend.services.aeroing4.research.experiments import (
    ExperimentDecision,
    ExperimentRecord,
    ExperimentStatus,
    OriginalStrategyProvenance,
)
from backend.services.aeroing4.strategy_library import (
    build_candidate_flow_for_run,
    scan_strategy_library,
)
from backend.services.storage.run_repository import RunRepository


def test_strategy_library_scan_returns_multima_correctly(tmp_path: Path):
    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    _write_multima(strategies_dir)

    scan = scan_strategy_library(strategies_dir)
    item = next(s for s in scan.strategies if s.strategy_name == "MultiMa")

    assert item.py_exists is True
    assert item.json_exists is True
    assert item.class_name == "MultiMa"
    assert item.json_strategy_name == "MultiMa"
    assert item.timeframe == "4h"
    assert {p.name for p in item.python_parameters} == {
        "buy_ma_count",
        "buy_ma_gap",
        "sell_ma_count",
        "sell_ma_gap",
    }
    assert item.python_only_params == []
    assert item.json_only_params == []
    assert "CLASS_FILE_MISMATCH" not in {w.code for w in item.warnings}


def test_strategy_library_scan_returns_scalpmomentum_python_only_params(tmp_path: Path):
    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    _write_scalp_momentum(strategies_dir)

    scan = scan_strategy_library(strategies_dir)
    item = next(s for s in scan.strategies if s.strategy_name == "ScalpMomentum_v1")

    assert item.class_name == "ScalpMomentum_v1"
    assert {p.name for p in item.python_parameters} == {"ema_fast", "ema_slow", "atr_window"}
    assert item.python_only_params == ["atr_window", "ema_fast", "ema_slow"]
    warning_codes = {w.code for w in item.warnings}
    assert "EMPTY_JSON_BUY_SELL_WITH_PYTHON_PARAMS" in warning_codes
    assert "PARAMS_NOT_RUNTIME_EXECUTABLE" in warning_codes


def test_strategy_library_missing_json_warning(tmp_path: Path):
    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    (strategies_dir / "NoJson.py").write_text(
        "from freqtrade.strategy import IStrategy\nclass NoJson(IStrategy):\n    timeframe = '5m'\n",
        encoding="utf-8",
    )

    item = scan_strategy_library(strategies_dir).strategies[0]
    assert item.strategy_name == "NoJson"
    assert "MISSING_JSON" in {w.code for w in item.warnings}


def test_strategy_library_class_file_mismatch_warning(tmp_path: Path):
    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    (strategies_dir / "FileName.py").write_text(
        "from freqtrade.strategy import IStrategy\nclass ClassName(IStrategy):\n    timeframe = '5m'\n",
        encoding="utf-8",
    )
    (strategies_dir / "FileName.json").write_text('{"strategy_name": "FileName", "params": {}}', encoding="utf-8")

    item = scan_strategy_library(strategies_dir).strategies[0]
    warning_codes = {w.code for w in item.warnings}
    assert "CLASS_FILE_MISMATCH" in warning_codes
    assert "JSON_STRATEGY_NAME_MISMATCH" in warning_codes


def test_candidate_flow_metadata_includes_source_and_candidate_paths(tmp_path: Path):
    runs_root, strategies_dir, repo = _seed_candidate_flow(tmp_path)

    response = build_candidate_flow_for_run(
        run_id="run-1",
        runs_root=runs_root,
        run_repository=repo,
        strategies_dir=strategies_dir,
    )

    candidate = response.candidate
    assert candidate is not None
    assert candidate.official_source_strategy_path == str(strategies_dir / "MultiMa.py")
    assert candidate.official_source_json_path == str(strategies_dir / "MultiMa.json")
    assert candidate.candidate_directory == str(runs_root / "run-1" / "candidates" / "cand-1")
    assert candidate.copied_candidate_py == str(runs_root / "run-1" / "candidates" / "cand-1" / "MultiMa.py")
    assert candidate.copied_candidate_json == str(runs_root / "run-1" / "candidates" / "cand-1" / "MultiMa.json")
    assert candidate.official_files_unchanged is True


def test_candidate_flow_includes_command_and_strategy_path(tmp_path: Path):
    runs_root, strategies_dir, repo = _seed_candidate_flow(tmp_path)

    candidate = build_candidate_flow_for_run(
        run_id="run-1",
        runs_root=runs_root,
        run_repository=repo,
        strategies_dir=strategies_dir,
    ).candidate

    assert candidate is not None
    assert candidate.freqtrade_command is not None
    assert "--strategy-path" in candidate.freqtrade_command
    assert candidate.strategy_path_points_to_run_dir is True
    assert candidate.output_zip_contains_py is True
    assert candidate.output_zip_contains_json is True
    assert candidate.parsed_metrics["total_trades"] == 42
    assert candidate.decision == "KEEP"
    assert [step.name for step in candidate.steps] == [
        "Source Strategy",
        "Candidate Copy",
        "Freqtrade Execution",
        "Metrics Parsing",
        "Decision",
        "Next Action",
    ]


def test_aeroing4_strategy_library_endpoint(tmp_path: Path):
    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    _write_multima(strategies_dir)
    app = _app_with_services(tmp_path, strategies_dir)

    with TestClient(app) as client:
        response = client.get("/api/aeroing4/strategy-library")

    assert response.status_code == 200
    body = response.json()
    assert body["strategies"][0]["strategy_name"] == "MultiMa"


def test_aeroing4_candidate_flow_endpoint(tmp_path: Path):
    runs_root, strategies_dir, _repo = _seed_candidate_flow(tmp_path)
    app = _app_with_services(tmp_path, strategies_dir, runs_root=runs_root)

    with TestClient(app) as client:
        response = client.get("/api/aeroing4/runs/run-1/candidate-flow")

    assert response.status_code == 200
    body = response.json()
    assert body["candidate"]["freqtrade_command"]
    assert body["candidate"]["strategy_path_points_to_run_dir"] is True


def _write_multima(strategies_dir: Path) -> None:
    (strategies_dir / "MultiMa.py").write_text(
        """
from freqtrade.strategy import IntParameter, IStrategy

class MultiMa(IStrategy):
    timeframe = "4h"
    count_max = 20
    gap_max = 100
    buy_ma_count = IntParameter(1, count_max, default=5, space="buy")
    buy_ma_gap = IntParameter(1, gap_max, default=13, space="buy")
    sell_ma_count = IntParameter(1, count_max, default=14, space="sell")
    sell_ma_gap = IntParameter(1, gap_max, default=66, space="sell")
""",
        encoding="utf-8",
    )
    (strategies_dir / "MultiMa.json").write_text(
        json.dumps(
            {
                "strategy_name": "MultiMa",
                "params": {
                    "buy": {"buy_ma_count": 6, "buy_ma_gap": 14},
                    "sell": {"sell_ma_count": 14, "sell_ma_gap": 66},
                    "roi": {"0": 0.5},
                    "stoploss": {"stoploss": -0.345},
                    "trailing": {"trailing_stop": False},
                },
            }
        ),
        encoding="utf-8",
    )


def _write_scalp_momentum(strategies_dir: Path) -> None:
    (strategies_dir / "ScalpMomentum_v1.py").write_text(
        """
from freqtrade.strategy import IntParameter, IStrategy

class ScalpMomentum_v1(IStrategy):
    timeframe = "5m"
    ema_fast = IntParameter(5, 20, default=9, space="buy", optimize=True)
    ema_slow = IntParameter(15, 50, default=21, space="buy", optimize=True)
    atr_window = IntParameter(10, 50, default=14, space="buy", optimize=True)
""",
        encoding="utf-8",
    )
    (strategies_dir / "ScalpMomentum_v1.json").write_text(
        json.dumps(
            {
                "strategy_name": "ScalpMomentum_v1",
                "params": {
                    "buy": {},
                    "sell": {},
                    "roi": {"0": 0.08},
                    "stoploss": {"stoploss": -0.05},
                    "trailing": {"trailing_stop": False},
                },
            }
        ),
        encoding="utf-8",
    )


def _seed_candidate_flow(tmp_path: Path):
    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    _write_multima(strategies_dir)
    runs_root = tmp_path / "user_data" / "aeroing4" / "runs"
    candidate_dir = runs_root / "run-1" / "candidates" / "cand-1"
    candidate_dir.mkdir(parents=True)
    (candidate_dir / "MultiMa.py").write_text((strategies_dir / "MultiMa.py").read_text(encoding="utf-8"), encoding="utf-8")
    (candidate_dir / "MultiMa.json").write_text((strategies_dir / "MultiMa.json").read_text(encoding="utf-8"), encoding="utf-8")

    backtest_root = tmp_path / "user_data" / "backtest_results"
    exec_dir = backtest_root / "MultiMa" / "exec-1"
    exec_dir.mkdir(parents=True)
    command = f'freqtrade backtesting --strategy-path "{exec_dir}" --strategy MultiMa'
    (exec_dir / "freqtrade_command.txt").write_text(command, encoding="utf-8")
    (exec_dir / "parsed_summary.json").write_text(
        json.dumps({"total_trades": 42, "profit_factor": 1.7, "net_profit_pct": 9.5}),
        encoding="utf-8",
    )
    with zipfile.ZipFile(exec_dir / "freqtrade_native_result.zip", "w") as archive:
        archive.writestr("strategy/MultiMa.py", "class MultiMa: pass")
        archive.writestr("strategy/MultiMa.json", "{}")

    record = ExperimentRecord(
        run_id="run-1",
        hypothesis_id="hyp-1",
        candidate_id="cand-1",
        original_strategy_provenance=OriginalStrategyProvenance(
            logical_name="MultiMa",
            path_reference=str(strategies_dir / "MultiMa.py"),
            source_hash=_hash(strategies_dir / "MultiMa.py"),
            version_id="v1",
        ),
        experiment_identity_hash="identity-1",
        underlying_execution_id="exec-1",
        status=ExperimentStatus.COMPLETED,
        decision=ExperimentDecision.KEEP,
        result="material_improvement_guardrails_hold",
        artifacts={
            "official_source_strategy_path": str(strategies_dir / "MultiMa.py"),
            "official_source_strategy_hash": _hash(strategies_dir / "MultiMa.py"),
            "official_source_json_path": str(strategies_dir / "MultiMa.json"),
            "official_source_json_hash": _hash(strategies_dir / "MultiMa.json"),
            "candidate_dir": str(candidate_dir),
            "candidate_strategy": str(candidate_dir / "MultiMa.py"),
            "candidate_sidecar": str(candidate_dir / "MultiMa.json"),
            "freqtrade_execution_id": "exec-1",
            "underlying_run_dir": str(exec_dir),
        },
    )
    experiments_path = runs_root / "run-1" / "experiments.json"
    experiments_path.parent.mkdir(parents=True, exist_ok=True)
    experiments_path.write_text(json.dumps([json.loads(record.model_dump_json())], indent=2), encoding="utf-8")
    return runs_root, strategies_dir, RunRepository(backtest_root)


def _app_with_services(tmp_path: Path, strategies_dir: Path, runs_root: Path | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(aeroing4.router)
    backtest_root = tmp_path / "user_data" / "backtest_results"
    backtest_root.mkdir(parents=True, exist_ok=True)
    services = SimpleNamespace(
        paths=SimpleNamespace(strategies_dir=strategies_dir),
        run_repository=RunRepository(backtest_root),
        aeroing4_orchestrator=SimpleNamespace(
            state_store=SimpleNamespace(runs_root=runs_root or (tmp_path / "user_data" / "aeroing4" / "runs"))
        ),
    )
    app.state.services = services
    return app


def _hash(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()
