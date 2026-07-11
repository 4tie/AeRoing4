"""Tests for PROMPT 12 Delivery / Export Package (constraints #1–#7, scenario A–O).

Packaging only — no real Freqtrade. The fake uses real filesystem ops on tmp_path
so atomic build, hash verification, and overwrite-safety are exercised for real.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from backend.services.aeroing4.research.champions import (
    ArtifactReference, ChampionReference, ChampionSourceType, ChampionStore,
)
from backend.services.aeroing4.research.confirmation import (
    ConfirmationDecision, ConfirmationExecutionStatus, ConfirmationResult,
)
from backend.services.aeroing4.research.delivery import DeliveryPackage, DeliveryService
from backend.services.aeroing4.research.delivery_policy import DeliveryStatus
from backend.services.aeroing4.research.final_unseen import (
    FinalUnseenDecision, FinalUnseenExecutionStatus, FinalUnseenResult, compute_final_unseen_identity,
)


def _seed_champion(tmp_path: Path, params: dict, *, strat_hash=None, param_hash=None):
    sd = tmp_path / "strategies"
    sd.mkdir(parents=True, exist_ok=True)
    py = sd / "AIStrategy.py"
    py.write_text("class AIStrategy:\n    pass\n", encoding="utf-8")
    sc = sd / "AIStrategy.json"
    sc.write_text(json.dumps({"parameters": params}), encoding="utf-8")
    # Use real content hashes so disk verification (constraint #6) matches.
    import hashlib
    strat_hash = strat_hash or hashlib.sha256(py.read_bytes()).hexdigest()
    param_hash = param_hash or hashlib.sha256(sc.read_bytes()).hexdigest()
    return ChampionReference(
        run_id="run-1", parent_champion_id=None, source_type=ChampionSourceType.HYPEROPT,
        strategy_artifact=ArtifactReference(artifact_path="champions/AIStrategy.py", artifact_hash=strat_hash,
                                            original_source_path=str(py), original_source_hash=strat_hash),
        parameter_artifact=ArtifactReference(artifact_path="champions/AIStrategy.json", artifact_hash=param_hash,
                                             original_source_path=str(sc), original_source_hash=param_hash),
        strategy_name="AIStrategy",
    )


def _pass_final_unseen(tmp_path, champ, *, delivery_eligible=True) -> FinalUnseenResult:
    identity = compute_final_unseen_identity(
        champion_id=champ.champion_id, strategy_hash=champ.strategy_artifact.artifact_hash,
        parameter_hash=champ.parameter_artifact.artifact_hash, boundary_hash="bhash",
        configuration_hash="chash", timeframe="5m", pair_set=["BTC/USDT"],
        protocol_version="1.0.0", metrics_version="1.0.0", final_unseen_policy_version="1.0.0",
    )
    return FinalUnseenResult(
        result_id="fu-1", run_id="run-1", champion_id=champ.champion_id,
        parent_confirmation_result_id="conf-1", strategy_hash=champ.strategy_artifact.artifact_hash,
        parameter_hash=champ.parameter_artifact.artifact_hash, boundary_hash="bhash",
        final_unseen_timerange="20240801-20240831", configuration_hash="chash",
        protocol_version="1.0.0", metrics_version="1.0.0", final_unseen_policy_version="1.0.0",
        execution_status=FinalUnseenExecutionStatus.COMPLETED, decision=FinalUnseenDecision.PASS,
        reason_codes=["ok"], evaluated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        delivery_eligible=delivery_eligible, final_unseen_identity=identity,
    )


def _pass_confirmation(tmp_path, champ) -> ConfirmationResult:
    return ConfirmationResult(
        result_id="conf-1", run_id="run-1", champion_id=champ.champion_id,
        strategy_hash=champ.strategy_artifact.artifact_hash, parameter_hash=champ.parameter_artifact.artifact_hash,
        boundary_hash="bhash", confirmation_timerange="20240701-20240731", configuration_hash="chash",
        protocol_version="1.0.0", metrics_version="1.0.0", confirmation_policy_version="1.0.0",
        execution_status=ConfirmationExecutionStatus.COMPLETED, decision=ConfirmationDecision.PASS,
        reason_codes=["ok"], evaluated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        confirmation_identity="cid",
    )


def _make(tmp_path, *, delivery_eligible=True, params=None):
    params = params or {"rsi_threshold": {"type": "int", "editable": True, "current": 30, "min": 10, "max": 50},
                        "stoploss": {"type": "float", "editable": True, "current": -0.1, "min": -0.5, "max": -0.01}}
    champ = _seed_champion(tmp_path, params)
    store = ChampionStore(tmp_path)
    store.register(champ)
    fu = _pass_final_unseen(tmp_path, champ, delivery_eligible=delivery_eligible)
    conf = _pass_confirmation(tmp_path, champ)
    svc = DeliveryService(runs_root=tmp_path, champion_store=store)
    return svc, champ, fu, conf, store


# ── A–G: eligibility gate (typed BLOCKED) ────────────────────────────────────

def test_A_blocked_no_final_unseen(tmp_path):
    svc, champ, fu, conf, store = _make(tmp_path)
    r = svc.run(run_id="run-1", champion=champ, final_unseen_result=None,
               confirmation_result=conf, delivery_eligible_state=True)
    assert r.delivery_status == DeliveryStatus.BLOCKED


def test_B_blocked_decision_not_pass(tmp_path):
    svc, champ, fu, conf, store = _make(tmp_path)
    fu.decision = FinalUnseenDecision.FAIL
    r = svc.run(run_id="run-1", champion=champ, final_unseen_result=fu,
               confirmation_result=conf, delivery_eligible_state=True)
    assert r.delivery_status == DeliveryStatus.BLOCKED


def test_C_blocked_delivery_eligible_false(tmp_path):
    svc, champ, fu, conf, store = _make(tmp_path, delivery_eligible=False)
    r = svc.run(run_id="run-1", champion=champ, final_unseen_result=fu,
               confirmation_result=conf, delivery_eligible_state=True)
    assert r.delivery_status == DeliveryStatus.BLOCKED


def test_D_blocked_champion_differs(tmp_path):
    svc, champ, fu, conf, store = _make(tmp_path)
    other = _seed_champion(tmp_path, {"rsi_threshold": {"type": "int", "editable": True, "current": 30, "min": 10, "max": 50}},
                            strat_hash="other-strat", param_hash="other-param")
    fu.champion_id = "other-id"
    r = svc.run(run_id="run-1", champion=other, final_unseen_result=fu,
               confirmation_result=conf, delivery_eligible_state=True)
    assert r.delivery_status == DeliveryStatus.BLOCKED


def test_E_blocked_strategy_hash_changed(tmp_path):
    svc, champ, fu, conf, store = _make(tmp_path)
    champ.strategy_artifact.artifact_hash = "TAMPERED"
    r = svc.run(run_id="run-1", champion=champ, final_unseen_result=fu,
               confirmation_result=conf, delivery_eligible_state=True,
               paused=False, requires_reconciliation=False)
    assert r.delivery_status == DeliveryStatus.BLOCKED


def test_F_blocked_parameter_hash_changed(tmp_path):
    svc, champ, fu, conf, store = _make(tmp_path)
    champ.parameter_artifact.artifact_hash = "TAMPERED"
    r = svc.run(run_id="run-1", champion=champ, final_unseen_result=fu,
               confirmation_result=conf, delivery_eligible_state=True)
    assert r.delivery_status == DeliveryStatus.BLOCKED


def test_G_blocked_reconciliation(tmp_path):
    svc, champ, fu, conf, store = _make(tmp_path)
    r = svc.run(run_id="run-1", champion=champ, final_unseen_result=fu,
               confirmation_result=conf, delivery_eligible_state=True,
               requires_reconciliation=True)
    assert r.delivery_status == DeliveryStatus.BLOCKED


# ── H: successful run-local delivery creates .py + .json + manifest ──────────

def test_H_run_local_creates_package(tmp_path):
    svc, champ, fu, conf, store = _make(tmp_path)
    r = svc.run(run_id="run-1", champion=champ, final_unseen_result=fu,
               confirmation_result=conf, delivery_eligible_state=True)
    assert r.delivery_status == DeliveryStatus.DELIVERED
    ddir = tmp_path / "run-1" / "delivery"
    assert (ddir / "AIStrategy.py").exists()
    assert (ddir / "AIStrategy.json").exists()
    assert (ddir / "delivery_manifest.json").exists()
    assert (ddir / "frozen_config_snapshot.json").exists()
    assert (ddir / "metrics_summary.json").exists()
    assert (ddir / "audit_provenance.json").exists()
    assert (ddir / "warnings.json").exists()


# ── I: same identity rerun reuses metadata (no rewrite) ──────────────────────

def test_I_same_identity_reused(tmp_path):
    svc, champ, fu, conf, store = _make(tmp_path)
    r1 = svc.run(run_id="run-1", champion=champ, final_unseen_result=fu,
                confirmation_result=conf, delivery_eligible_state=True)
    r2 = svc.run(run_id="run-1", champion=champ, final_unseen_result=fu,
                confirmation_result=conf, delivery_eligible_state=True)
    assert r1.delivery_id == r2.delivery_id
    assert r2.delivery_status == DeliveryStatus.REUSED


# ── J: existing target file not overwritten by default ───────────────────────

def test_J_existing_target_not_overwritten(tmp_path):
    svc, champ, fu, conf, store = _make(tmp_path)
    ddir = tmp_path / "run-1" / "delivery"
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "AIStrategy.py").write_text("OLD CONTENT — DO NOT OVERWRITE", encoding="utf-8")
    r = svc.run(run_id="run-1", champion=champ, final_unseen_result=fu,
               confirmation_result=conf, delivery_eligible_state=True)
    assert r.delivery_status == DeliveryStatus.BLOCKED
    assert (ddir / "AIStrategy.py").read_text(encoding="utf-8") == "OLD CONTENT — DO NOT OVERWRITE"


# ── K: explicit versioned export creates unique filename ─────────────────────

def test_K_versioned_export_unique_filename(tmp_path):
    svc, champ, fu, conf, store = _make(tmp_path)
    svc.export_profile = "freqtrade_user_data"
    svc.force_overwrite = False
    r = svc.run(run_id="run-1", champion=champ, final_unseen_result=fu,
               confirmation_result=conf, delivery_eligible_state=True)
    assert r.delivery_status == DeliveryStatus.DELIVERED
    export_dir = tmp_path / "export" / "freqtrade_user_data" / "strategies"
    py_files = list(export_dir.glob("AIStrategy_*.py"))
    json_files = list(export_dir.glob("AIStrategy_*.json"))
    assert len(py_files) == 1 and len(json_files) == 1


# ── L: manifest contains all required provenance fields ──────────────────────

def test_L_manifest_provenance_fields(tmp_path):
    svc, champ, fu, conf, store = _make(tmp_path)
    r = svc.run(run_id="run-1", champion=champ, final_unseen_result=fu,
               confirmation_result=conf, delivery_eligible_state=True)
    manifest = json.loads((tmp_path / "run-1" / "delivery" / "delivery_manifest.json").read_text(encoding="utf-8"))
    for f in ("delivery_id", "run_id", "champion_id", "strategy_name", "strategy_hash",
              "parameter_hash", "final_unseen_result_id", "confirmation_result_id",
              "source_champion_type", "parent_champion_id", "metrics_version", "protocol_version",
              "confirmation_policy_version", "final_unseen_policy_version", "delivery_policy_version",
              "created_at", "delivery_status", "artifact_hashes", "export_paths",
              "verification_flags", "delivery_identity", "export_profile"):
        assert f in manifest, f"missing manifest field: {f}"
    assert manifest["verification_flags"]["real_freqtrade_verified"] is False


# ── M: artifact hashes match written files ───────────────────────────────────

def test_M_artifact_hashes_match(tmp_path):
    import hashlib
    svc, champ, fu, conf, store = _make(tmp_path)
    r = svc.run(run_id="run-1", champion=champ, final_unseen_result=fu,
               confirmation_result=conf, delivery_eligible_state=True)
    ddir = tmp_path / "run-1" / "delivery"
    assert r.artifact_hashes["strategy_py"] == hashlib.sha256(
        (ddir / "AIStrategy.py").read_bytes()).hexdigest()
    assert r.artifact_hashes["params_json"] == hashlib.sha256(
        (ddir / "AIStrategy.json").read_bytes()).hexdigest()


# ── N: missing sidecar prevents delivery ─────────────────────────────────────

def test_N_missing_sidecar_blocks(tmp_path):
    svc, champ, fu, conf, store = _make(tmp_path)
    # Remove the sidecar original source; champion artifact path still recorded.
    Path(champ.parameter_artifact.original_source_path).unlink()
    r = svc.run(run_id="run-1", champion=champ, final_unseen_result=fu,
               confirmation_result=conf, delivery_eligible_state=True)
    assert r.delivery_status == DeliveryStatus.BLOCKED


# ── O: partial write failure → EXPORT_FAILED, not DELIVERED ──────────────────

def test_O_partial_write_export_failed(tmp_path):
    svc, champ, fu, conf, store = _make(tmp_path)
    # Inject a writer that fails on the SECOND write (after .py) → partial write.
    written = {"count": 0}

    def failing_fs(path, content):
        written["count"] += 1
        if written["count"] >= 2:
            raise IOError("simulated disk failure")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    svc._fs = failing_fs
    r = svc.run(run_id="run-1", champion=champ, final_unseen_result=fu,
               confirmation_result=conf, delivery_eligible_state=True)
    assert r.delivery_status == DeliveryStatus.EXPORT_FAILED
    # package is NOT marked DELIVERED
    assert r.delivery_status != DeliveryStatus.DELIVERED
    # no finalized manifest in target (temp cleaned up)
    assert not (tmp_path / "run-1" / "delivery" / "delivery_manifest.json").exists()
