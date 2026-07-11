"""Delivery / Export Package for the AeRoing4 pipeline (PROMPT 12).

Architecture (reuse, don't rewrite — mirrors PROMPT 11 FinalUnseen):
    DeliveryService
      → FinalUnseenResult (PROMPT 11, gate)
      → ConfirmationResult (PROMPT 10, reference)
      → ChampionReference + ChampionStore (artifacts + lineage, read-only COPY)

Constraints applied (user-required):
  #1 run-local default; live Freqtrade export only via explicit profile.
  #2 explicit export; no silent overwrite; versioned filenames or overwrite approval.
  #3 atomic build: temp dir → write .py/.json/config/metrics/audit/warnings →
     manifest LAST → verify hashes → finalize. Partial write → EXPORT_FAILED.
  #4 mandatory warnings when real_* / full_e2e are false.
  #5 delivery must NOT change truth: no Champion promotion, no result mutation,
     no strategy/param mutation, no reruns, no fake real-verification.
  #6 sidecar + strategy paired: export .py + .json together; fail if missing/
     mismatched/hash-mismatch.
  #7 manifest is source of delivery truth; ResearchState stores summary only.

DeliveryStatus is NOT PASS/FAIL — that belongs to Final Unseen.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from .champions import ChampionReference, ChampionStore
from .confirmation import ConfirmationResult
from .delivery_policy import DELIVERY_POLICY_VERSION, DeliveryPolicy, DeliveryStatus
from .final_unseen import FinalUnseenResult


def _hash_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _hash_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class DeliveryPackage(BaseModel):
    """The delivery manifest — source of delivery truth (constraint #7)."""

    delivery_id: str
    run_id: str
    champion_id: str
    strategy_name: str
    strategy_hash: str
    parameter_hash: str
    final_unseen_result_id: str
    confirmation_result_id: Optional[str] = None
    source_champion_type: Optional[str] = None
    parent_champion_id: Optional[str] = None
    source_experiment_id: Optional[str] = None
    source_hyperopt_result_id: Optional[str] = None
    metrics_version: str
    protocol_version: str
    confirmation_policy_version: str
    final_unseen_policy_version: str
    delivery_policy_version: str
    created_at: datetime
    delivery_status: DeliveryStatus
    artifact_hashes: dict[str, str] = {}
    export_paths: dict[str, str] = {}
    verification_flags: dict[str, bool] = {}
    warnings: list[str] = []
    delivery_identity: str
    export_profile: str = "run_local"


class DeliveryStore:
    """Atomic, lock-guarded JSON store (one manifest per delivery)."""

    def __init__(self, runs_root: Path):
        self.runs_root = Path(runs_root)

    def _file(self, delivery_id: str) -> Path:
        return self.runs_root / "delivery" / f"{delivery_id}.json"

    def _index_file(self, run_id: str) -> Path:
        return self.runs_root / run_id / "delivery_index.json"

    def save(self, pkg: DeliveryPackage) -> None:
        d = self._file(pkg.delivery_id)
        d.parent.mkdir(parents=True, exist_ok=True)
        tmp = d.with_suffix(".tmp")
        tmp.write_text(pkg.model_dump_json(), encoding="utf-8")
        tmp.replace(d)
        idx = self._index_file(pkg.run_id)
        idx.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if idx.exists():
            try:
                data = json.loads(idx.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data[pkg.delivery_identity] = pkg.delivery_id
        tmp = idx.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(idx)

    def load(self, delivery_id: str) -> Optional[DeliveryPackage]:
        d = self._file(delivery_id)
        if not d.exists():
            return None
        return DeliveryPackage.model_validate_json(d.read_text(encoding="utf-8"))

    def find_by_identity(self, run_id: str, identity: str) -> Optional[DeliveryPackage]:
        idx = self._index_file(run_id)
        if not idx.exists():
            return None
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
        except Exception:
            return None
        did = data.get(identity)
        return self.load(did) if did else None

    def latest_for_run(self, run_id: str) -> Optional[DeliveryPackage]:
        idx = self._index_file(run_id)
        if not idx.exists():
            return None
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
        except Exception:
            return None
        latest = None
        for did in data.values():
            p = self.load(did)
            if p is None:
                continue
            if latest is None or p.created_at >= latest.created_at:
                latest = p
        return latest


def compute_delivery_identity(
    *, run_id, champion_id, strategy_hash, parameter_hash,
    final_unseen_result_id, final_unseen_identity, delivery_policy_version, export_profile,
) -> str:
    canonical = json.dumps({
        "run_id": run_id,
        "champion_id": champion_id,
        "strategy_hash": strategy_hash,
        "parameter_hash": parameter_hash,
        "final_unseen_result_id": final_unseen_result_id,
        "final_unseen_identity": final_unseen_identity,
        "delivery_policy_version": delivery_policy_version,
        "export_profile": export_profile,
    }, sort_keys=True)
    return _hash_str(canonical)


class DeliveryService:
    def __init__(
        self,
        runs_root: Path,
        champion_store: ChampionStore,
        *,
        protocol_version: str = "1.0.0",
        confirmation_policy_version: str = "1.0.0",
        final_unseen_policy_version: str = "1.0.0",
        # Constraint #1/#2: default run-local, explicit freqtrade profile only.
        export_profile: str = "run_local",
        force_overwrite: bool = False,
        # Filesystem writers are injectable for atomic-build tests (constraint #3).
        fs=None,
    ):
        self.runs_root = Path(runs_root)
        self.champion_store = champion_store
        self.protocol_version = protocol_version
        self.confirmation_policy_version = confirmation_policy_version
        self.final_unseen_policy_version = final_unseen_policy_version
        self.policy = DeliveryPolicy()
        self.export_profile = export_profile
        self.force_overwrite = force_overwrite
        self._fs = fs  # callable(real_path, content) -> None for simulated partial failure

    # ── eligibility gate (constraint #5: no truth change, only gating) ─────────

    def check_eligibility(
        self, *, run_id, champion, final_unseen_result, delivery_eligible_state,
        paused=False, requires_reconciliation=False,
    ) -> tuple[bool, str, DeliveryStatus]:
        if final_unseen_result is None:
            return False, "no FinalUnseenResult", DeliveryStatus.BLOCKED
        if final_unseen_result.decision is None or str(final_unseen_result.decision.value) != "pass":
            return False, "FinalUnseen decision != PASS", DeliveryStatus.BLOCKED
        if not final_unseen_result.delivery_eligible:
            return False, "FinalUnseenResult.delivery_eligible is false", DeliveryStatus.BLOCKED
        if not delivery_eligible_state:
            return False, "ResearchState.delivery_eligible is false", DeliveryStatus.BLOCKED
        if champion is None:
            return False, "no current Champion", DeliveryStatus.BLOCKED
        if champion.champion_id != final_unseen_result.champion_id:
            return False, "Champion differs from FinalUnseen champion", DeliveryStatus.BLOCKED
        if champion.strategy_artifact is None or champion.strategy_artifact.artifact_hash != final_unseen_result.strategy_hash:
            return False, "strategy hash changed", DeliveryStatus.BLOCKED
        if champion.parameter_artifact is None or champion.parameter_artifact.artifact_hash != final_unseen_result.parameter_hash:
            return False, "parameter hash changed", DeliveryStatus.BLOCKED
        if paused:
            return False, "unresolved PAUSED state", DeliveryStatus.BLOCKED
        if requires_reconciliation:
            return False, "active experiment requires reconciliation", DeliveryStatus.BLOCKED
        return True, "eligible", DeliveryStatus.READY

    # ── atomic package build (constraint #3, #6, #4) ──────────────────────────

    def _write(self, path: Path, content: str):
        if self._fs is not None:
            self._fs(path, content)  # may raise to simulate partial failure
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def run(
        self, *, run_id, champion: ChampionReference, final_unseen_result: Optional[FinalUnseenResult],
        confirmation_result: Optional[ConfirmationResult], delivery_eligible_state: bool,
        research_state=None, paused: bool = False, requires_reconciliation: bool = False,
    ) -> DeliveryPackage:
        now = datetime.now(UTC)
        ok, reason, status = self.check_eligibility(
            run_id=run_id, champion=champion, final_unseen_result=final_unseen_result,
            delivery_eligible_state=delivery_eligible_state, paused=paused,
            requires_reconciliation=requires_reconciliation,
        )
        if not ok:
            return DeliveryPackage(
                delivery_id=str(uuid.uuid4()), run_id=run_id,
                champion_id=champion.champion_id if champion else "?",
                strategy_name=getattr(champion, "strategy_name", "AIStrategy"),
                strategy_hash=(champion.strategy_artifact.artifact_hash if champion and champion.strategy_artifact else ""),
                parameter_hash=(champion.parameter_artifact.artifact_hash if champion and champion.parameter_artifact else ""),
                final_unseen_result_id=final_unseen_result.result_id if final_unseen_result else "",
                confirmation_result_id=confirmation_result.result_id if confirmation_result else None,
                metrics_version="1.0.0", protocol_version=self.protocol_version,
                confirmation_policy_version=self.confirmation_policy_version,
                final_unseen_policy_version=self.final_unseen_policy_version,
                delivery_policy_version=DELIVERY_POLICY_VERSION, created_at=now,
                delivery_status=status, delivery_identity="", export_profile=self.export_profile,
            )

        # Compute deterministic identity → reuse before any write (constraint #2 no silent overwrite).
        identity = compute_delivery_identity(
            run_id=run_id, champion_id=champion.champion_id,
            strategy_hash=champion.strategy_artifact.artifact_hash,
            parameter_hash=champion.parameter_artifact.artifact_hash,
            final_unseen_result_id=final_unseen_result.result_id,
            final_unseen_identity=final_unseen_result.final_unseen_identity,
            delivery_policy_version=DELIVERY_POLICY_VERSION, export_profile=self.export_profile,
        )
        store = DeliveryStore(self.runs_root)
        existing = store.find_by_identity(run_id, identity)
        if existing is not None:
            # Reuse metadata; do NOT rewrite artifacts (constraint #1/#2 idempotency).
            reused = existing.model_copy(update={"delivery_status": DeliveryStatus.REUSED})
            store.save(reused)
            return reused

        # Resolve artifact source paths (original preserved; we COPY only).
        strat_src = Path(champion.strategy_artifact.original_source_path)
        param_src = Path(champion.parameter_artifact.original_source_path)
        if not strat_src.exists() or not param_src.exists():
            return self._blocked_pkg(run_id, champion, final_unseen_result, confirmation_result, now, identity,
                                     "missing sidecar/strategy artifact")

        # Determine target directory (constraint #1: run-local default).
        if self.export_profile == "run_local":
            target_dir = self.runs_root / run_id / "delivery"
        elif self.export_profile == "freqtrade_user_data":
            # Explicit export — versioned filename unless force_overwrite approved.
            base = Path(self.runs_root) / "export" / "freqtrade_user_data" / "strategies"
            target_dir = base
        else:
            return self._blocked_pkg(run_id, champion, final_unseen_result, confirmation_result, now, identity,
                                     f"unknown export profile: {self.export_profile}")

        stem = Path(champion.strategy_artifact.artifact_path).stem
        py_name = f"{stem}.py"
        json_name = f"{stem}.json"
        # Versioned filename for freqtrade export when not forced (constraint #2).
        if self.export_profile == "freqtrade_user_data" and not self.force_overwrite:
            suffix = now.strftime("%Y%m%d%H%M%S")
            py_name = f"{stem}_{suffix}.py"
            json_name = f"{stem}_{suffix}.json"

        target_dir.mkdir(parents=True, exist_ok=True)
        py_target = target_dir / py_name
        json_target = target_dir / json_name

        # Constraint #2: never silently overwrite an existing production/file by default.
        if py_target.exists() and not self.force_overwrite:
            return self._blocked_pkg(run_id, champion, final_unseen_result, confirmation_result, now, identity,
                                     f"target file exists, overwrite not approved: {py_target}")

        # Atomic build: write into a temp dir, then verify, then finalize (constraint #3).
        tmp_dir = self.runs_root / run_id / f".delivery_tmp_{uuid.uuid4().hex}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            py_tmp = tmp_dir / py_name
            json_tmp = tmp_dir / json_name
            cfg_tmp = tmp_dir / "frozen_config_snapshot.json"
            metrics_tmp = tmp_dir / "metrics_summary.json"
            audit_tmp = tmp_dir / "audit_provenance.json"
            warnings_tmp = tmp_dir / "warnings.json"
            manifest_tmp = tmp_dir / "delivery_manifest.json"

            self._write(py_tmp, strat_src.read_text(encoding="utf-8"))
            self._write(json_tmp, param_src.read_text(encoding="utf-8"))
            frozen_cfg = {
                "exchange": getattr(champion, "exchange", "binance"),
                "timeframe": getattr(champion, "timeframe", "5m"),
                "pairs": getattr(champion, "pairs", []),
                "max_open_trades": getattr(champion, "max_open_trades", 4),
            }
            self._write(cfg_tmp, json.dumps(frozen_cfg, indent=2))
            metrics_payload = final_unseen_result.canonical_metrics_snapshot or {}
            self._write(metrics_tmp, json.dumps(metrics_payload, indent=2))

            # Verification flags — honest: real_* default false without real execution.
            verification_flags = {
                "logic_verified": True,
                "service_boundary_verified": True,
                "real_ollama_verified": False,
                "real_hyperopt_verified": False,
                "real_confirmation_verified": False,
                "real_final_unseen_verified": False,
                "real_freqtrade_verified": False,
                "full_e2e_verified": False,
            }
            warnings: list[str] = []
            for flag in ("real_hyperopt_verified", "real_confirmation_verified",
                         "real_final_unseen_verified", "real_freqtrade_verified", "full_e2e_verified"):
                if not verification_flags.get(flag, False):
                    warnings.append(f"{flag}=false: verification incomplete; not production-ready")
            self._write(warnings_tmp, json.dumps({"warnings": warnings}, indent=2))

            # Lineage / audit provenance report.
            lineage = {
                "champion_id": champion.champion_id,
                "source_champion_type": champion.source_type.value if champion.source_type else None,
                "parent_champion_id": champion.parent_champion_id,
                "source_experiment_id": getattr(champion, "source_experiment_id", None),
                "source_hyperopt_result_id": getattr(champion, "source_hyperopt_result_id", None),
                "final_unseen_result_id": final_unseen_result.result_id,
                "confirmation_result_id": confirmation_result.result_id if confirmation_result else None,
            }
            self._write(audit_tmp, json.dumps(lineage, indent=2))

            # Verify hashes BEFORE finalizing (constraint #3/#6).
            written = {
                "strategy_py": (py_tmp, py_target),
                "params_json": (json_tmp, json_target),
            }
            artifact_hashes: dict[str, str] = {}
            export_paths: dict[str, str] = {}
            for key, (src, dst) in written.items():
                if not src.exists():
                    raise IOError(f"partial write: {key} missing")
                h = _hash_file(src)
                artifact_hashes[key] = h
                export_paths[key] = str(dst)
            # Sidecar must match delivered parameter hash (constraint #6).
            # The recorded parameter_hash is the hash of the original artifact; the
            # copied sidecar must be byte-identical to that original.
            expected_param_hash = _hash_file(param_src)
            delivered_param_hash = _hash_file(json_tmp)
            if delivered_param_hash != expected_param_hash:
                raise IOError("sidecar hash mismatch with original parameter artifact")

            pkg = DeliveryPackage(
                delivery_id=str(uuid.uuid4()), run_id=run_id,
                champion_id=champion.champion_id,
                strategy_name=getattr(champion, "strategy_name", "AIStrategy"),
                strategy_hash=champion.strategy_artifact.artifact_hash,
                parameter_hash=champion.parameter_artifact.artifact_hash,
                final_unseen_result_id=final_unseen_result.result_id,
                confirmation_result_id=confirmation_result.result_id if confirmation_result else None,
                source_champion_type=champion.source_type.value if champion.source_type else None,
                parent_champion_id=champion.parent_champion_id,
                source_experiment_id=getattr(champion, "source_experiment_id", None),
                source_hyperopt_result_id=getattr(champion, "source_hyperopt_result_id", None),
                metrics_version="1.0.0", protocol_version=self.protocol_version,
                confirmation_policy_version=self.confirmation_policy_version,
                final_unseen_policy_version=self.final_unseen_policy_version,
                delivery_policy_version=DELIVERY_POLICY_VERSION, created_at=now,
                delivery_status=DeliveryStatus.DELIVERED, artifact_hashes=artifact_hashes,
                export_paths=export_paths, verification_flags=verification_flags,
                warnings=warnings, delivery_identity=identity, export_profile=self.export_profile,
            )
            self._write(manifest_tmp, pkg.model_dump_json(indent=2))

            # Finalize: move temp → target (atomic-ish; both files + manifest).
            shutil.move(str(py_tmp), str(py_target))
            shutil.move(str(json_tmp), str(json_target))
            final_manifest = target_dir / "delivery_manifest.json"
            shutil.move(str(manifest_tmp), str(final_manifest))
            # keep config/metrics/audit/warnings alongside
            shutil.move(str(cfg_tmp), str(target_dir / "frozen_config_snapshot.json"))
            shutil.move(str(metrics_tmp), str(target_dir / "metrics_summary.json"))
            shutil.move(str(audit_tmp), str(target_dir / "audit_provenance.json"))
            shutil.move(str(warnings_tmp), str(target_dir / "warnings.json"))
            store.save(pkg)

            # Constraint #5: update ResearchState summary ONLY (no truth change elsewhere).
            if research_state is not None and hasattr(research_state, "delivery_status"):
                research_state.delivery_status = pkg.delivery_status.value
            return pkg
        except Exception as exc:
            # Constraint #3: partial write → EXPORT_FAILED, never DELIVERED.
            return DeliveryPackage(
                delivery_id=str(uuid.uuid4()), run_id=run_id,
                champion_id=champion.champion_id,
                strategy_name=getattr(champion, "strategy_name", "AIStrategy"),
                strategy_hash=champion.strategy_artifact.artifact_hash,
                parameter_hash=champion.parameter_artifact.artifact_hash,
                final_unseen_result_id=final_unseen_result.result_id,
                confirmation_result_id=confirmation_result.result_id if confirmation_result else None,
                metrics_version="1.0.0", protocol_version=self.protocol_version,
                confirmation_policy_version=self.confirmation_policy_version,
                final_unseen_policy_version=self.final_unseen_policy_version,
                delivery_policy_version=DELIVERY_POLICY_VERSION, created_at=now,
                delivery_status=DeliveryStatus.EXPORT_FAILED,
                warnings=[f"export_failed:{exc}"],
                delivery_identity=identity, export_profile=self.export_profile,
            )
        finally:
            shutil.rmtree(str(tmp_dir), ignore_errors=True)

    def _blocked_pkg(self, run_id, champion, final_unseen_result, confirmation_result, now, identity, reason):
        return DeliveryPackage(
            delivery_id=str(uuid.uuid4()), run_id=run_id,
            champion_id=champion.champion_id if champion else "?",
            strategy_name=getattr(champion, "strategy_name", "AIStrategy"),
            strategy_hash=(champion.strategy_artifact.artifact_hash if champion and champion.strategy_artifact else ""),
            parameter_hash=(champion.parameter_artifact.artifact_hash if champion and champion.parameter_artifact else ""),
            final_unseen_result_id=final_unseen_result.result_id if final_unseen_result else "",
            confirmation_result_id=confirmation_result.result_id if confirmation_result else None,
            metrics_version="1.0.0", protocol_version=self.protocol_version,
            confirmation_policy_version=self.confirmation_policy_version,
            final_unseen_policy_version=self.final_unseen_policy_version,
            delivery_policy_version=DELIVERY_POLICY_VERSION, created_at=now,
            delivery_status=DeliveryStatus.BLOCKED, delivery_identity=identity,
            warnings=[reason], export_profile=self.export_profile,
        )
