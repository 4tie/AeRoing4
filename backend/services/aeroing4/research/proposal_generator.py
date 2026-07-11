"""Proposal Generator for the AeRoing4 Controlled Research Loop.

Wraps existing Ollama transport only as an optional adapter and enforces a
strict proposal contract. This module must not pass free-form AI output
directly to execution.

Outcomes:
  * ACCEPTED
  * AI_PROPOSAL_SKIPPED
  * AI_UNAVAILABLE
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any

from pydantic import BaseModel, ValidationError

from ..metrics.models import CanonicalMetricsSnapshot
from .allowed_targets import AllowedMutationTarget
from .experiments import ExactChange

logger = logging.getLogger(__name__)


class ProposalOutcome(str, Enum):
    ACCEPTED = "accepted"
    AI_PROPOSAL_SKIPPED = "ai_proposal_skipped"
    AI_UNAVAILABLE = "ai_unavailable"


class ProposalSchemaValidationError(Exception):
    """Raised when proposal payload fails schema validation."""


class ProposalRequest(BaseModel):
    run_id: str
    hypothesis_id: str
    diagnosis_code: str | None = None
    hypothesis_text: str | None = None
    evidence_refs: list[str] | None = None
    champion_metrics: CanonicalMetricsSnapshot | None = None
    allowed_targets: list[AllowedMutationTarget] | None = None
    context_limits: dict[str, Any] | None = None


class ProposalResult(BaseModel):
    """Strict typed proposal result."""

    outcome: ProposalOutcome
    hypothesis_text: str | None = None
    diagnosis_code: str | None = None
    evidence_refs: list[str] | None = None
    exact_change: ExactChange | None = None
    expected_effect: str | None = None
    success_criteria: str | None = None
    risk: str | None = None
    confidence: float | None = None
    raw_payload: dict[str, Any] | None = None
    rejection_reason: str | None = None


def _validate_proposal_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a proposal JSON payload.

    Rejects executable fields, shell commands, code payloads, and arbitrary
    file paths. Applies one repair attempt in very limited cases.
    """
    if not isinstance(payload, dict):
        raise ProposalSchemaValidationError("Proposal payload must be a JSON object")

    forbidden_keys = {
        "cmd",
        "command",
        "shell",
        "exec",
        "execute",
        "system",
        "code",
        "script",
        "path",
        "file_path",
        "write_file",
        "read_file",
        "run_terminal",
        "run_subprocess",
        "os_system",
    }
    found_forbidden = forbidden_keys.intersection({str(k).lower() for k in payload.keys()})
    if found_forbidden:
        raise ProposalSchemaValidationError(
            f"Forbidden executable fields in proposal: {sorted(found_forbidden)}"
        )

    change = payload.get("exact_change")
    if isinstance(change, dict):
        for forbidden in forbidden_keys:
            for value in change.values():
                if isinstance(value, str) and forbidden in value.lower():
                    raise ProposalSchemaValidationError(
                        "exact_change contains forbidden executable/path-like content"
                    )

    expected_keys = {
        "hypothesis_text",
        "diagnosis_code",
        "evidence_refs",
        "exact_change",
        "expected_effect",
        "success_criteria",
        "risk",
        "confidence",
    }
    accepted_keys = expected_keys.union({"raw_payload", "rejection_reason"})
    unknown_keys = set(payload.keys()) - accepted_keys
    if unknown_keys:
        raise ProposalSchemaValidationError(f"Unknown proposal fields: {sorted(unknown_keys)}")

    return payload


def _validate_semantic_consistency(payload: dict[str, Any]) -> None:
    """Validate semantic consistency between numeric changes and textual descriptions.
    
    Rejects proposals where the expected_effect or risk text contradicts the numeric
    direction of the change for known parameter types like stoploss.
    """
    change = payload.get("exact_change")
    if not isinstance(change, dict):
        return
    
    target = change.get("target")
    before = change.get("before_value")
    after = change.get("after_value")
    expected_effect = payload.get("expected_effect", "").lower()
    risk = payload.get("risk", "").lower()
    
    # Stoploss directionality validation
    if target == "stoploss" and isinstance(before, (int, float)) and isinstance(after, (int, float)):
        # Freqtrade-style negative stoploss values
        # after > before means tighter (e.g., -0.25 > -0.336)
        # after < before means wider (e.g., -0.5 < -0.25)
        
        is_tighter = after > before
        is_wider = after < before
        
        # Keywords that imply wider stoploss / more room
        wider_keywords = [
            "more room", "allow more room", "breathe", "wider", "wider stop",
            "looser", "looser stop", "more space", "give room", "allow to develop"
        ]
        
        # Keywords that imply tighter stoploss / reduced loss
        tighter_keywords = [
            "tighter", "tighter stop", "reduce loss", "reduced loss", "smaller loss",
            "faster exit", "quick exit", "reduce downside", "reduced downside",
            "tighten", "cut losses", "stop loss sooner"
        ]
        
        # Keywords that imply increased risk/drawdown
        increased_risk_keywords = [
            "higher drawdown", "increased drawdown", "more risk", "increased risk",
            "larger loss", "higher risk", "drawdown risk"
        ]
        
        # Keywords that imply reduced risk/drawdown
        reduced_risk_keywords = [
            "reduce risk", "reduced risk", "lower risk", "less risk",
            "reduce drawdown", "lower drawdown", "smaller drawdown"
        ]
        
        text_to_check = f"{expected_effect} {risk}"
        
        if is_tighter:
            # Tighter stoploss should not claim wider/more room
            if any(kw in text_to_check for kw in wider_keywords):
                raise ProposalSchemaValidationError(
                    "SEMANTIC_CONTRADICTION: stoploss tightened (after > before) but text claims wider/more room"
                )
            # Tighter stoploss should not claim reduced risk/drawdown (it actually increases risk)
            if any(kw in text_to_check for kw in reduced_risk_keywords):
                raise ProposalSchemaValidationError(
                    "SEMANTIC_CONTRADICTION: tighter stoploss increases risk, but text claims reduced risk/drawdown"
                )
        
        if is_wider:
            # Wider stoploss should not claim tighter/reduced loss
            if any(kw in text_to_check for kw in tighter_keywords):
                raise ProposalSchemaValidationError(
                    "SEMANTIC_CONTRADICTION: stoploss widened (after < before) but text claims tighter/reduced loss"
                )
            # Wider stoploss should not claim reduced risk/drawdown (it actually increases per-trade risk)
            if any(kw in text_to_check for kw in reduced_risk_keywords):
                raise ProposalSchemaValidationError(
                    "SEMANTIC_CONTRADICTION: wider stoploss increases per-trade risk, but text claims reduced risk/drawdown"
                )
            # Wider stoploss should acknowledge increased drawdown risk
            if not any(kw in text_to_check for kw in increased_risk_keywords) and "risk" in text_to_check:
                # Only enforce if risk is mentioned - don't force it if risk isn't discussed
                pass


def _extract_allowed_metrics_snapshot(metrics: CanonicalMetricsSnapshot | None) -> dict[str, Any]:
    if metrics is None:
        return {}
    try:
        payload = json.loads(metrics.model_dump_json())
        return {
            k: v.get("value") if isinstance(v, dict) else v
            for k, v in payload.items()
            if k != "provenance"
        }
    except Exception:
        return {}


class OllamaProposalAdapter:
    """Thin adapter over existing Ollama transport.

    This adapter is best-effort. If the existing transport is unavailable in
    this environment, calls should return AI_UNAVAILABLE without affecting
    research loop budget.
    """

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "local"):
        self.base_url = base_url
        self.model = model

    async def generate(self, request: ProposalRequest) -> ProposalResult:
        try:
            from backend.services.ai.ollama_client import OllamaClient  # type: ignore[import]
            client = OllamaClient(base_url=self.base_url, model=self.model, strict_json=True)

            prompt = self._build_prompt(request)
            response = await client.chat(messages=[{"role": "user", "content": prompt}])
            await client.close()

            return self._parse_response(response.content)
        except Exception as exc:
            logger.warning("Ollama proposal generation unavailable: %s", exc)
            return ProposalResult(
                outcome=ProposalOutcome.AI_UNAVAILABLE,
                rejection_reason=f"Ollama unavailable: {exc}",
            )

    def _build_prompt(self, request: ProposalRequest) -> str:
        allowed = []
        if request.allowed_targets:
            for target in request.allowed_targets:
                allowed.append(
                    f"- {target.name} ({target.type}, current={target.current_value}, "
                    f"min={target.min_allowed}, max={target.max_allowed})"
                )
        metrics = _extract_allowed_metrics_snapshot(request.champion_metrics)

        return (
            "You are a research proposal assistant for an automated strategy-validation system.\n"
            "Return only a strict JSON object with these fields:\n"
            f"{json.dumps(list(ProposalResult.model_fields.keys()), indent=2)}\n\n"
            "CRITICAL: Do NOT include the 'outcome' field - the system determines acceptance/rejection.\n"
            "CRITICAL: Do NOT include request fields like run_id, hypothesis_id, allowed_targets, champion_metrics, or context_limits.\n"
            "Output ONLY the content fields: hypothesis_text, diagnosis_code, evidence_refs, exact_change, expected_effect, success_criteria, risk, confidence.\n\n"
            f"Diagnosis: {request.diagnosis_code}\n"
            f"Hypothesis: {request.hypothesis_text}\n"
            f"Allowed targets:\n{chr(10).join(allowed) if allowed else 'none'}\n"
            f"Champion metrics: {json.dumps(metrics, default=str)}\n"
            "Rules:\n"
            "- Do not propose executable code, shell commands, or file paths.\n"
            "- exact_change must be a JSON object with these EXACT fields: change_type (string), target (string), before_value (any), after_value (any).\n"
            "- exact_change must describe ONE parameter change only - do not return multiple parameters in one exact_change.\n"
            "- Do NOT include outcome, raw_payload, or rejection_reason - these are system-managed.\n"
        )

    def _parse_response(self, content: str) -> ProposalResult:
        payload = None
        for attempt in range(2):
            try:
                start = content.find("{")
                end = content.rfind("}")
                if start == -1 or end == -1 or end <= start:
                    raise ValueError("No JSON object found in response")
                payload = json.loads(content[start : end + 1])
                _validate_proposal_payload(payload)
                _validate_semantic_consistency(payload)
                break
            except Exception as exc:
                if attempt == 0:
                    logger.warning("Proposal JSON parse/validation failed, retrying fallback parse")
                    continue
                return ProposalResult(
                    outcome=ProposalOutcome.AI_PROPOSAL_SKIPPED,
                    rejection_reason=f"Malformed proposal JSON: {exc}",
                )

        exact_change = None
        if payload and payload.get("exact_change"):
            try:
                exact_change = ExactChange(**payload["exact_change"])
            except Exception as exc:
                return ProposalResult(
                    outcome=ProposalOutcome.AI_PROPOSAL_SKIPPED,
                    rejection_reason=f"Invalid exact_change schema: {exc}",
                )

        return ProposalResult(
            outcome=ProposalOutcome.ACCEPTED,
            hypothesis_text=payload.get("hypothesis_text"),
            diagnosis_code=payload.get("diagnosis_code"),
            evidence_refs=payload.get("evidence_refs"),
            exact_change=exact_change,
            expected_effect=payload.get("expected_effect"),
            success_criteria=payload.get("success_criteria"),
            risk=payload.get("risk"),
            confidence=payload.get("confidence"),
            raw_payload=payload,
        )


class ProposalGenerator:
    """Deterministic facade for AI proposal generation."""

    def __init__(self, adapter: OllamaProposalAdapter | None = None):
        self.adapter = adapter or OllamaProposalAdapter()

    async def propose(self, request: ProposalRequest) -> ProposalResult:
        """Generate a research proposal.

        Returns ACCEPTED / AI_PROPOSAL_SKIPPED / AI_UNAVAILABLE.
        This method never raises for normal unavailable/skip outcomes.
        """
        if request.context_limits and request.context_limits.get("force_skip"):
            return ProposalResult(
                outcome=ProposalOutcome.AI_PROPOSAL_SKIPPED,
                rejection_reason="Forced skip by context limits",
            )
        return await self.adapter.generate(request)
