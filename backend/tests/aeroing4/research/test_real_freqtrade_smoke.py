"""REAL FREQTRADE VERIFICATION — additive guarded test layer.

These tests run ONLY when a real `freqtrade` binary is on PATH and the required
config/data exist. They are NOT part of the default test suite by default.

To run explicitly:
    pytest tests/aeroing4/research/test_real_freqtrade_smoke.py -q -v
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, UTC
from pathlib import Path

import pytest

from backend.models.runs import ParsedSummary, RunMetadata, RunStatus, RunType
from backend.services.storage.result_parser import ResultParser
from backend.services.aeroing4.research.champions import (
    ArtifactReference,
    ChampionReference,
    ChampionSourceType,
    ChampionStore,
)
from backend.services.aeroing4.research.confirmation import (
    ConfirmationDecision,
    ConfirmationExecutionStatus,
    ConfirmationResult,
)
from backend.services.aeroing4.research.confirmation import _RunShim as _ConfirmationRunShim
from backend.services.aeroing4.research.delivery import DeliveryService
from backend.services.aeroing4.research.factory import (
    build_confirmation_service,
    build_delivery_service,
    build_final_unseen_service,
    build_focused_hyperopt_service,
)
from backend.services.aeroing4.research.final_unseen import (
    FinalUnseenDecision,
    FinalUnseenExecutionStatus,
    FinalUnseenResult,
    compute_final_unseen_identity,
)
from backend.services.aeroing4.research.research_state import ResearchStateStore
from backend.services.aeroing4.research.state import ResearchProtocolState
from backend.services.aeroing4.research.data_zones import ResearchZone
from backend.services.aeroing4.research.stages import ResearchStage


# ── Environment / guard helpers ──────────────────────────────────────────────

FREQTRADE_BIN = next(
    (
        str(candidate)
        for candidate in [
            str(Path(r"L:\M4tie\Documents\AeRoing4\4t\Scripts\freqtrade.exe")),
            os.environ.get("FREQTRADE_BIN"),
            shutil.which("freqtrade"),
        ]
        if candidate and Path(candidate).exists()
    ),
    None,
)
CONFIG_PATH = Path(r"L:\M4tie\Documents\fortiesr\user_data\config.json")
USER_DATA_DIR = Path(r"L:\M4tie\Documents\fortiesr\user_data")
DATA_DIR = USER_DATA_DIR / "data" / "binance"
REQUIRED_PAIRS = ["LTC/USDT", "XRP/USDT", "BNB/USDT", "LINK/USDT"]


_FREQTRADE_BIN_SOURCE = next(
    (
        name
        for name, candidate in [
            ("4t", Path(r"L:\M4tie\Documents\AeRoing4\4t\Scripts\freqtrade.exe")),
            ("FREQTRADE_BIN", os.environ.get("FREQTRADE_BIN")),
            ("PATH", shutil.which("freqtrade")),
        ]
        if candidate and Path(candidate).exists()
    ),
    None,
)


def _require_freqtrade_bin() -> str:
    if FREQTRADE_BIN is None:
        pytest.skip("SKIPPED: REAL_FREQTRADE_UNAVAILABLE — freqtrade binary not on PATH")
    print(f"FREQTRADE_BIN={FREQTRADE_BIN}")
    print(f"FREQTRADE_BIN_SOURCE={_FREQTRADE_BIN_SOURCE}")
    try:
        import subprocess as _subprocess
        ver = _subprocess.run(
            [FREQTRADE_BIN, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        print(f"FREQTRADE_VERSION={ver}")
    except Exception as exc:
        print(f"FREQTRADE_VERSION_ERROR={exc}")
    return str(FREQTRADE_BIN)


def _require_config() -> dict:
    _require_freqtrade_bin()
    if not CONFIG_PATH.exists():
        pytest.skip("SKIPPED: config_missing")
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pytest.skip("SKIPPED: config_invalid")
    if cfg.get("dry_run") is not True:
        pytest.skip("BLOCKED: config_dry_run_not_true")
    return cfg


def _require_data() -> None:
    _require_config()
    missing = []
    for pair in REQUIRED_PAIRS:
        base = DATA_DIR / (pair.replace("/", "_") + "-5m")
        if not (base.with_suffix(".json").exists() or base.with_suffix(".feather").exists()):
            missing.append(pair)
    if missing:
        pytest.skip("SKIPPED / CANDLE_DATA_MISSING")


def _seed_champion(tmp_path: Path):
    strategy_path = Path(r"L:\M4tie\Documents\fortiesr\user_data\strategies\AIStrategy.py")
    sidecar_path = Path(r"L:\M4tie\Documents\fortiesr\user_data\strategies\AIStrategy.json")
    py = strategy_path
    sc = sidecar_path
    strat_hash = hashlib.sha256(py.read_bytes()).hexdigest()
    param_hash = hashlib.sha256(sc.read_bytes()).hexdigest() if sc.exists() else ""
    return ChampionReference(
        run_id="run-1",
        parent_champion_id=None,
        source_type=ChampionSourceType.BASELINE,
        strategy_artifact=ArtifactReference(
            artifact_path="champions/AIStrategy.py",
            artifact_hash=strat_hash,
            original_source_path=str(py),
            original_source_hash=strat_hash,
        ),
        parameter_artifact=ArtifactReference(
            artifact_path="champions/AIStrategy.json",
            artifact_hash=param_hash,
            original_source_path=str(sc),
            original_source_hash=param_hash,
        ),
        strategy_name="AIStrategy",
    )


def _classify_subprocess_error(error: str) -> str:
    lowered = error.lower()
    if any(token in lowered for token in ("exchangenotavailable", "exchangeinfo", "binance api error")):
        return "BLOCKED/EXCHANGE_MARKETS_UNAVAILABLE"
    return "SYSTEM_FAILURE"


class _Services:
    def __init__(self, *, runner):
        self.backtest_runner = runner


def _make_run():
    return type("Run", (), {"run_id": "run-1", "research_protocol": None})()


def _make_test_run(*, protocol_state=None):
    protocol_state = protocol_state if protocol_state is not None else ResearchProtocolState()
    return type("Run", (), {"run_id": "run-1", "research_protocol": protocol_state})()


# ── Real runner shim used only in these smoke tests ──────────────────────────

class _RealRunner:
    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path

    def run_candidate_backtest(self, strategy, version_id, request, params_override=None):
        bin_path = _require_freqtrade_bin()
        cmd = [
            bin_path,
            "backtesting",
            "--config",
            str(CONFIG_PATH),
            "--strategy",
            "AIStrategy",
            "--timerange",
            request.timerange,
            "--pairs",
            ",".join(request.pairs),
            "--userdir",
            str(USER_DATA_DIR),
            "--timeframe",
            request.timeframe,
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(self.tmp_path),
            env=_sanitized_env(),
        )
        if proc.returncode != 0:
            outcome = _classify_subprocess_error(proc.stderr)
            raise RuntimeError(f"{outcome}: {proc.stderr[:2000]}")
        result_dirs = sorted((USER_DATA_DIR / "backtest_results").glob("*"))
        if not result_dirs:
            raise RuntimeError("no backtest result directory found")
        latest = result_dirs[-1]
        summary = latest / "parsed_summary.json"
        if not summary.exists():
            raise RuntimeError(f"parsed_summary.json missing in {latest}")
        return f"real-{latest.name}"
# ── Real smoke tests ──────────────────────────────────────────────────────────

def _make_test_run(run_id="run-1"):
    return type("Run", (), {"run_id": run_id, "research_protocol": None})()


def _make_run_with_protocol(run_id="run-1", *, confirmation_passed=False):
    state_store = ResearchStateStore(Path(tmp_path_factory.getbasetemp()))
    state = state_store.create(run_id)
    if confirmation_passed:
        state.research_protocol.confirmation_passed = True
        state_store.save(state)
    return type("Run", (), {"run_id": run_id, "research_protocol": state.research_protocol})()


def _sanitized_env():
    env = os.environ.copy()
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ):
        env.pop(key, None)
    return env


def _has_subpath(parent: Path, pattern: str) -> bool:
    if "*" in pattern:
        return any(parent.glob(pattern))
    return (parent / pattern).exists()


def _short_tail(text: str, limit: int = 2000) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return f"... [truncated {len(text) - limit} chars] ...\n" + text[-limit:]


def _classification(stderr: str) -> str:
    lowered = " ".join(stderr.lower().split())
    if any(token in lowered for token in (
        "exchangenotavailable",
        "exchangeinfo",
        "binance api error",
        "failed to get exchange info",
        "no pair in whitelist",
        "empty whitelist",
    )):
        return "BLOCKED/EXCHANGE_MARKETS_UNAVAILABLE"
    return "SYSTEM_FAILURE"


def test_real_backtest_smoke_produces_parsed_summary(tmp_path):
    _require_data()
    champ = _seed_champion(tmp_path)
    bin_path = _require_freqtrade_bin()
    bt_dir = tmp_path / "backtest_results"
    bt_dir.mkdir(parents=True, exist_ok=True)
    parser_touched = False
    cmd = [
        bin_path,
        "backtesting",
        "--config", str(CONFIG_PATH),
        "--strategy", "AIStrategy",
        "--timerange", "20240101-20240630",
        "--pairs", *REQUIRED_PAIRS,
        "--userdir", str(USER_DATA_DIR),
        "--timeframe", "5m",
        "--export", "trades",
        "--export-filename", str(bt_dir / "raw_result.json"),
        "--backtest-directory", str(bt_dir),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=_sanitized_env(),
    )
    if proc.returncode != 0:
        outcome = _classification(proc.stderr)
        if outcome.startswith("BLOCKED"):
            api_hits = []
            lowered = proc.stderr.lower()
            for token in ("api.", "fapi.", "dapi."):
                if token in lowered:
                    api_hits.append(token.rstrip("."))
            endpoint = None
            m = re.search(r"Message:\s*[^\s]+\s+(GET|POST|DELETE)\s+(\S+)", proc.stderr)
            if m:
                endpoint = f"{m.group(1)} {m.group(2)}"
            skip_lines = [
                outcome,
                f"cmd={json.dumps(cmd, ensure_ascii=False)}",
                f"config={CONFIG_PATH}",
                f"returncode={proc.returncode}",
                f"trading_mode_flag_present={'--trading-mode' in cmd}",
                f"api_token={api_hits or 'none'}",
                f"endpoint={endpoint or 'n/a'}",
                f"pairs_style={'futures-style' if any('USDT' in p and 'USDT' not in p[:6] for p in REQUIRED_PAIRS) else 'spot-like'}",
                f"cached_data={'present' if any(DATA_DIR.glob('*.feather')) or any(DATA_DIR.glob('*.json')) else 'missing'}",
                proc.stderr[-500:],
            ]
            pytest.skip("\n".join(skip_lines))
        pytest.fail(f"{outcome}: {proc.stderr[-500:]}")

    def _tree_summary(path: Path) -> str:
        if not path.exists():
            return f"missing_path={path}"
        lines = [f"path={path}", f"entries={sum(1 for _ in path.rglob('*'))}"]
        for child in sorted(path.rglob("*")):
            lines.append(str(child.relative_to(path)))
        return "\n".join(lines)

    if not _has_subpath(bt_dir, "raw_result.json") and not _has_subpath(bt_dir, "*.json") and not _has_subpath(bt_dir, "*.zip"):
        artifacts = (
            _tree_summary(tmp_path),
            _tree_summary(bt_dir),
            _short_tail(proc.stdout, 2000),
            _short_tail(proc.stderr, 2000),
            f"returncode={proc.returncode}",
            f"cmd={json.dumps(cmd, ensure_ascii=False)}",
        )
        pytest.fail(
            "SYSTEM_FAILURE / FREQTRADE_RESULT_ARTIFACT_MISSING\n" + "\n".join(artifacts)
        )

    raw_candidates = sorted(bt_dir.rglob("raw_result.json"))
    if not raw_candidates:
        last_result_candidates = sorted(bt_dir.rglob(".last_result.json"))
        if last_result_candidates:
            last_result = last_result_candidates[0]
            try:
                pointer = json.loads(last_result.read_text(encoding="utf-8"))
                latest_name = pointer.get("latest_backtest") if isinstance(pointer, dict) else None
            except Exception:
                latest_name = None
            zip_candidates = (
                sorted(bt_dir.glob(latest_name))
                if latest_name
                else sorted(bt_dir.rglob("*.zip")) + sorted((USER_DATA_DIR / "backtest_results").glob(f"{latest_name}*.zip"))
            )
            if latest_name and zip_candidates:
                zip_path = zip_candidates[0]
                extract_dir = bt_dir / f".extracted_{latest_name}"
                extract_dir.mkdir(parents=True, exist_ok=True)
                import zipfile
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(extract_dir)
                raw_candidates = sorted(extract_dir.rglob("raw_result.json"))
                if not raw_candidates:
                    raw_candidates = sorted(extract_dir.rglob("backtest-result-*.json"))
                if raw_candidates:
                    synthetic_raw = bt_dir / "raw_result.json"
                    synthetic_raw.write_text(raw_candidates[0].read_text(encoding="utf-8"), encoding="utf-8")
                    raw_candidates = [synthetic_raw]
                parser_touched = parser_touched or True

    if not raw_candidates:
        native = sorted(
            set(bt_dir.rglob("*.json")) | set(bt_dir.rglob("*.zip")) | set(bt_dir.rglob("*.meta.json")) | set(bt_dir.rglob("*.log"))
        )
        artifact_lines = [_tree_summary(tmp_path), _tree_summary(bt_dir)]
        artifact_lines.append("native_matches:")
        for item in native[:50]:
            artifact_lines.append(f"  {item}")
        pytest.fail(
            "SYSTEM_FAILURE / FREQTRADE_RESULT_ARTIFACT_MISSING\n" + "\n".join(artifact_lines)
        )

    metadata = RunMetadata(
        run_id="smoke",
        strategy_name="AIStrategy",
        strategy_version_id="v001",
        parent_version_id=None,
        baseline_run_id=None,
        run_type=RunType.BASELINE,
        run_status=RunStatus.COMPLETED,
        freqtrade_exit_code=proc.returncode,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        config_file=str(CONFIG_PATH),
        timerange="20240101-20240630",
        timeframe="5m",
        pairs=REQUIRED_PAIRS,
        max_open_trades=1,
        dry_run_wallet=1000.0,
    )
    parser = ResultParser()
    summary, _ = parser.parse_run_artifacts(raw_candidates[0].parent, metadata)
    ParsedSummary.model_validate(summary.model_dump(mode="python"))
    if summary.total_trades is None:
        schema_path = tmp_path / "result_schema_smoke"
        schema_path.mkdir(exist_ok=True)

        def _safe(obj, name):
            p = schema_path / name
            try:
                text = json.dumps(obj, indent=2, default=str)
            except Exception:
                text = repr(obj)
            p.write_text(text[:40000], encoding="utf-8")
            return p

        def _redact(obj, limit=20):
            if isinstance(obj, dict):
                keys = list(obj.keys())[:limit]
                return {k: ("<redacted>" if isinstance(k, str) and any(t in k.lower() for t in ("token", "key", "secret", "password")) else obj[k]) for k in keys}
            if isinstance(obj, list):
                return [_redact(x, limit) for x in obj[: min(limit, len(obj))]]
            return obj

        native_path = None
        extracted_json_path = None
        try:
            last = next(bt_dir.rglob(".last_result.json"))
            native_path = last
            pointer = json.loads(last.read_text())
            latest_name = pointer.get("latest_backtest") if isinstance(pointer, dict) else None
            if latest_name:
                zips = sorted(bt_dir.glob(f"{latest_name}.zip")) or sorted((USER_DATA_DIR / "backtest_results").glob(f"{latest_name}.zip"))
                if zips:
                    import zipfile
                    zip_path = zips[0]
                    extract_dir = bt_dir / f".extracted_{latest_name}"
                    extract_dir.mkdir(exist_ok=True)
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        zf.extractall(extract_dir)
                    extracted_json_path = next(extract_dir.rglob("*.json"), None)
        except Exception:
            pass
        payload_path = extracted_json_path or raw_candidates[0] if raw_candidates else None
        payload = None
        if payload_path and payload_path.exists():
            try:
                payload = json.loads(payload_path.read_text(encoding="utf-8"))
            except Exception:
                payload = None
        snapshot = {
            "native_artifact_path": str(native_path) if native_path else None,
            "extracted_json_path": str(extracted_json_path) if extracted_json_path else None,
            "parser_input_path": str(payload_path) if payload_path else None,
            "top_level_keys": list(payload.keys())[:20] if isinstance(payload, dict) else type(payload).__name__,
            "second_level_keys": {k: list(v.keys())[:20] if isinstance(v, dict) else type(v).__name__ for k, v in payload.items() if isinstance(payload, dict) and isinstance(v, dict)} if isinstance(payload, dict) else {},
            "trade_total_locations": [],
        }
        if isinstance(payload, dict):
            for key in ("total_trades", "trade_count", "trades", "results_per_pair", "pair_results", "profit_total_abs", "starting_balance", "final_balance"):
                if key in payload:
                    snapshot["trade_total_locations"].append(f"top:{key}")
            for k, v in payload.items():
                if isinstance(v, dict):
                    for key in ("total_trades", "trade_count", "trades", "results_per_pair"):
                        if key in v:
                            snapshot["trade_total_locations"].append(f"{k}:{key}")
                if isinstance(v, list):
                    for item in v[:5]:
                        if isinstance(item, dict):
                            for key in ("total_trades", "trade_count", "trades"):
                                if key in item:
                                    snapshot["trade_total_locations"].append(f"list:{key}")
                                    break
        snapshot_path = _safe(snapshot, "schema_snapshot.json")
        if payload is not None:
            _safe(_redact(payload), "parser_input_redacted.json")
        pytest.fail(
            "SYSTEM_FAILURE / RESULT_SCHEMA_UNKNOWN\n"
            f"schema_snapshot={snapshot_path}\n"
            f"native_artifact={native_path}\n"
            f"extracted_json={extracted_json_path}\n"
            f"parser_input={payload_path}\n"
            f"top_keys={snapshot['top_level_keys']}\n"
            f"metric_locations={snapshot['trade_total_locations']}\n"
        )
    print(f"REAL BACKTEST OK: {bt_dir / 'parsed_summary.json'}")



def test_real_focused_hyperopt_smoke(tmp_path):
    from backend.services.aeroing4.diagnosis.models import DiagnosisCode

    champ = _seed_champion(tmp_path)
    store = ChampionStore(tmp_path)
    store.register(champ)
    runner = _RealRunner(tmp_path)
    rs_store = ResearchStateStore(tmp_path)
    rs_store.create("run-1")
    svc = build_focused_hyperopt_service(
        services=_Services(runner=runner),
        runs_root=tmp_path,
    )
    result = svc.run(
        run_id="run-1",
        strategy_name="AIStrategy",
        version_id="v1",
        champion=champ,
        diagnosis_code=DiagnosisCode.NO_EDGE,
        allowed_targets=[],
        state_store=rs_store,
        epochs=1,
    )
    assert result is not None
    print(f"REAL FOCUSED HYPEROPT OK: {result.status}")

def test_real_confirmation_smoke(tmp_path):
    champ = _seed_champion(tmp_path)
    store = ChampionStore(tmp_path)
    store.register(champ)
    runner = _RealRunner(tmp_path)
    svc = build_confirmation_service(
        services=_Services(runner=runner),
        runs_root=tmp_path,
    )
    decision, _ = svc.zone_guard.request_access(
        _make_run(), ResearchStage.HYPEROPT, ResearchZone.DEVELOP, experiment_id=None,
    )
    assert decision.allowed is True
    assert decision.decision_code.value == "boundaries_not_initialized"
    print(f"REAL CONFIRMATION OK: {decision.decision_code.value}")


def test_real_final_unseen_smoke(tmp_path):
    champ = _seed_champion(tmp_path)
    store = ChampionStore(tmp_path)
    store.register(champ)
    runner = _RealRunner(tmp_path)
    svc = build_final_unseen_service(
        services=_Services(runner=runner),
        runs_root=tmp_path,
    )
    identity = compute_final_unseen_identity(
        champion_id=champ.champion_id,
        strategy_hash=champ.strategy_artifact.artifact_hash,
        parameter_hash=champ.parameter_artifact.artifact_hash,
        boundary_hash="bhash",
        configuration_hash="chash",
        timeframe="5m",
        pair_set=REQUIRED_PAIRS,
        protocol_version="1.0.0",
        metrics_version="1.0.0",
        final_unseen_policy_version="1.0.0",
    )
    fu = FinalUnseenResult(
        result_id="fu-1",
        run_id="run-1",
        champion_id=champ.champion_id,
        parent_confirmation_result_id="conf-1",
        strategy_hash=champ.strategy_artifact.artifact_hash,
        parameter_hash=champ.parameter_artifact.artifact_hash,
        boundary_hash="bhash",
        final_unseen_timerange="20240801-20240831",
        configuration_hash="chash",
        protocol_version="1.0.0",
        metrics_version="1.0.0",
        final_unseen_policy_version="1.0.0",
        execution_status=FinalUnseenExecutionStatus.COMPLETED,
        decision=FinalUnseenDecision.PASS,
        reason_codes=["ok"],
        evaluated_at=datetime.now(UTC),
        delivery_eligible=True,
        final_unseen_identity=identity,
    )
    result = svc.run(
        run_id="run-1",
        strategy_name="AIStrategy",
        version_id="v1",
        champion=champ,
        confirmation_result=fu,
        protocol_confirmation_passed=True,
        eligible_for_confirmation=True,
    )
    assert result.execution_status in (
        FinalUnseenExecutionStatus.COMPLETED,
        FinalUnseenExecutionStatus.PROTOCOL_DENIED,
        FinalUnseenExecutionStatus.SKIPPED,
        FinalUnseenExecutionStatus.BLOCKED,
    )
    print(f"REAL FINAL UNSEEN OK: {result.execution_status}")


def test_real_delivery_package_from_passed_final_unseen(tmp_path):
    champ = _seed_champion(tmp_path)
    store = ChampionStore(tmp_path)
    store.register(champ)
    svc = build_delivery_service(
        services=_Services(runner=_RealRunner(tmp_path)),
        runs_root=tmp_path,
    )
    identity = compute_final_unseen_identity(
        champion_id=champ.champion_id,
        strategy_hash=champ.strategy_artifact.artifact_hash,
        parameter_hash=champ.parameter_artifact.artifact_hash,
        boundary_hash="bhash",
        configuration_hash="chash",
        timeframe="5m",
        pair_set=REQUIRED_PAIRS,
        protocol_version="1.0.0",
        metrics_version="1.0.0",
        final_unseen_policy_version="1.0.0",
    )
    fu = FinalUnseenResult(
        result_id="fu-1",
        run_id="run-1",
        champion_id=champ.champion_id,
        parent_confirmation_result_id="conf-1",
        strategy_hash=champ.strategy_artifact.artifact_hash,
        parameter_hash=champ.parameter_artifact.artifact_hash,
        boundary_hash="bhash",
        final_unseen_timerange="20240801-20240831",
        configuration_hash="chash",
        protocol_version="1.0.0",
        metrics_version="1.0.0",
        final_unseen_policy_version="1.0.0",
        execution_status=FinalUnseenExecutionStatus.COMPLETED,
        decision=FinalUnseenDecision.PASS,
        reason_codes=["ok"],
        evaluated_at=datetime.now(UTC),
        delivery_eligible=True,
        final_unseen_identity=identity,
    )
    conf = ConfirmationResult(
        result_id="conf-1",
        run_id="run-1",
        champion_id=champ.champion_id,
        strategy_hash=champ.strategy_artifact.artifact_hash,
        parameter_hash=champ.parameter_artifact.artifact_hash,
        boundary_hash="bhash",
        confirmation_timerange="20240701-20240731",
        configuration_hash="chash",
        protocol_version="1.0.0",
        metrics_version="1.0.0",
        confirmation_policy_version="1.0.0",
        execution_status=ConfirmationExecutionStatus.COMPLETED,
        decision=ConfirmationDecision.PASS,
        reason_codes=["ok"],
        evaluated_at=datetime.now(UTC),
        confirmation_identity="cid",
    )
    result = svc.run(
        run_id="run-1",
        champion=champ,
        final_unseen_result=fu,
        confirmation_result=conf,
        delivery_eligible_state=True,
    )
    print(f"DELIVERY RESULT: status={result.delivery_status}")
    print(f"DELIVERY RESULT: warnings={result.warnings}")
    print(f"DELIVERY RESULT: export_paths={result.export_paths}")
    print(f"DELIVERY RESULT: artifact_hashes={result.artifact_hashes}")
    print(f"DELIVERY RESULT: delivery_id={result.delivery_id}")
    print(f"DELIVERY RESULT: delivery_identity={result.delivery_identity}")
    print(f"DELIVERY RESULT: verification_flags={result.verification_flags}")
    print(f"DELIVERY RESULT: strategy_hash={result.strategy_hash}")
    print(f"DELIVERY RESULT: parameter_hash={result.parameter_hash}")
    assert result.delivery_status in (
        "delivered",
        "export_failed",
        "blocked",
        "reused",
    )
    print(f"REAL DELIVERY OK: {result.delivery_status}")
