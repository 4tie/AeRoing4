"""Diagnosis engine for AeRoing4.

Orchestrates rule evaluation, primary diagnosis selection, and evidence quality assessment.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Optional

from ..metrics.models import CanonicalMetricsSnapshot
from ..portfolio_baseline.models import PortfolioBaselineResult
from ..research.champions import ChampionReference
from .models import (
    DiagnosisCategory,
    DiagnosisCode,
    DiagnosisFinding,
    DiagnosisInput,
    DiagnosisOutcome,
    DiagnosisResult,
    EvidenceQuality,
    Severity,
)
from .registry import RuleRegistry
from .resolver import EvidenceResolver
from .rules.base import BaseRule, RuleEvaluationContext
from .thresholds import classify_evidence_quality
from .models import DIAGNOSIS_POLICY_VERSION
from .persistence import DiagnosisStore


class DiagnosisEngine:
    """Deterministic diagnosis engine for AeRoing4.

    Evaluates registered rules against evidence, selects primary diagnosis,
    and produces a complete diagnosis result.
    """

    def __init__(self, runs_root: str):
        """Initialize the diagnosis engine.

        Args:
            runs_root: Path to the runs directory for persistence
        """
        self.runs_root = runs_root
        self.registry = RuleRegistry()
        self.store = DiagnosisStore(runs_root)

    def diagnose(self, input_data: DiagnosisInput) -> DiagnosisResult:
        """Run diagnosis on the provided input.

        Args:
            input_data: DiagnosisInput with all evidence references

        Returns:
            DiagnosisResult with findings and metadata
        """
        start_time = datetime.now(UTC)

        # Calculate input hash for idempotency check
        input_hash = self._compute_input_hash(input_data)

        # Check for existing diagnosis with same input hash (idempotency)
        existing_diagnoses = self.store.list_by_champion(input_data.champion_id)
        for existing in existing_diagnoses:
            if existing.input_hash == input_hash:
                # Reuse existing diagnosis
                return existing

        # Verify champion integrity
        integrity_error = self._verify_champion_integrity(input_data)
        if integrity_error:
            return self._create_integrity_error_result(input_data, integrity_error)

        # Initialize resolver
        resolver = EvidenceResolver(input_data.baseline_result)

        # Classify evidence quality
        evidence_quality = classify_evidence_quality(
            input_data.baseline_result,
            input_data.baseline_result.canonical_metrics,
            input_data.timeframe,
        )

        # Check for insufficient evidence
        if evidence_quality == EvidenceQuality.INSUFFICIENT:
            return self._create_insufficient_evidence_result(
                input_data, resolver, evidence_quality, start_time
            )

        # Evaluate all rules
        context = RuleEvaluationContext(
            resolver=resolver,
            evidence_quality=evidence_quality,
            timeframe=input_data.timeframe,
            run_id=input_data.run_id,
            champion_id=input_data.champion_id,
        )

        all_findings = []
        evaluated_rules = []
        skipped_rules = []
        skipped_reasons = {}

        for rule in self.registry.get_all_rules():
            evaluated_rules.append(rule.rule_id)

            # Check required evidence
            if not rule.check_required_evidence(context):
                skipped_rules.append(rule.rule_id)
                skipped_reasons[rule.rule_id] = "Required evidence unavailable"
                continue

            # Evaluate rule
            finding = rule.evaluate(context)
            if finding:
                all_findings.append(finding)

        # Separate findings by category
        primary_findings = [f for f in all_findings if not self._is_derived_finding(f)]
        derived_findings = [f for f in all_findings if self._is_derived_finding(f)]

        # Select primary diagnosis
        primary_diagnosis = self._select_primary_diagnosis(
            primary_findings, evidence_quality
        )

        # Separate secondary and informational findings
        secondary_findings, informational_findings = self._categorize_findings(
            all_findings, primary_diagnosis
        )

        # Generate derived parameter research findings if needed
        if primary_diagnosis:
            derived = self._generate_derived_findings(primary_diagnosis, context)
            derived_findings.extend(derived)

        # Combine findings
        all_findings = primary_findings + derived_findings

        # Determine outcome
        if primary_diagnosis:
            outcome = DiagnosisOutcome.DIAGNOSIS_COMPLETE
        elif evidence_quality in [EvidenceQuality.HIGH, EvidenceQuality.MEDIUM]:
            outcome = DiagnosisOutcome.NO_ACTIONABLE_FINDING
        else:
            outcome = DiagnosisOutcome.INSUFFICIENT_EVIDENCE

        # Calculate input hash for idempotency
        input_hash = self._compute_input_hash(input_data)

        # Calculate duration
        duration_seconds = (datetime.now(UTC) - start_time).total_seconds()

        # Create result
        return DiagnosisResult(
            run_id=input_data.run_id,
            champion_id=input_data.champion_id,
            diagnosis_id=str(uuid.uuid4()),
            outcome=outcome,
            primary_diagnosis=primary_diagnosis,
            secondary_findings=secondary_findings,
            informational_findings=informational_findings,
            evidence_quality=evidence_quality,
            unavailable_evidence=self._get_unavailable_evidence(context),
            evaluated_rules=evaluated_rules,
            skipped_rules=skipped_rules,
            skipped_reasons=skipped_reasons,
            input_hash=input_hash,
            duration_seconds=duration_seconds,
        )

    def _verify_champion_integrity(self, input_data: DiagnosisInput) -> Optional[str]:
        """Verify champion integrity before diagnosis.

        Args:
            input_data: DiagnosisInput

        Returns:
            Error message if integrity check fails, None otherwise
        """
        # Check if champion reference is provided
        if input_data.champion_reference is None:
            return "Champion reference not provided"

        # Check champion ID match
        if input_data.champion_reference.champion_id != input_data.champion_id:
            return (
                f"Champion ID mismatch: input={input_data.champion_id}, "
                f"reference={input_data.champion_reference.champion_id}"
            )

        # Check strategy hash match
        if input_data.champion_reference.strategy_artifact:
            if (
                input_data.champion_reference.strategy_artifact.artifact_hash
                != input_data.champion_strategy_hash
            ):
                return "Strategy hash mismatch between input and champion reference"

        # Check parameter hash match
        if input_data.champion_reference.parameter_artifact:
            if (
                input_data.champion_reference.parameter_artifact.artifact_hash
                != input_data.champion_parameter_hash
            ):
                return "Parameter hash mismatch between input and champion reference"

        return None

    def _create_integrity_error_result(
        self, input_data: DiagnosisInput, error_message: str
    ) -> DiagnosisResult:
        """Create a diagnosis result for integrity error.

        Args:
            input_data: DiagnosisInput
            error_message: Integrity error message

        Returns:
            DiagnosisResult with integrity error outcome
        """
        return DiagnosisResult(
            run_id=input_data.run_id,
            champion_id=input_data.champion_id,
            diagnosis_id=str(uuid.uuid4()),
            outcome=DiagnosisOutcome.INTEGRITY_ERROR,
            primary_diagnosis=None,
            secondary_findings=[],
            informational_findings=[],
            evidence_quality=EvidenceQuality.INSUFFICIENT,
            unavailable_evidence=[],
            evaluated_rules=[],
            skipped_rules=[],
            skipped_reasons={},
            input_hash=self._compute_input_hash(input_data),
            error_message=error_message,
        )

    def _create_insufficient_evidence_result(
        self,
        input_data: DiagnosisInput,
        resolver: EvidenceResolver,
        evidence_quality: EvidenceQuality,
        start_time: datetime,
    ) -> DiagnosisResult:
        """Create a diagnosis result for insufficient evidence.

        Args:
            input_data: DiagnosisInput
            resolver: EvidenceResolver
            evidence_quality: Evidence quality classification
            start_time: Start time for duration calculation

        Returns:
            DiagnosisResult with insufficient evidence outcome
        """
        duration_seconds = (datetime.now(UTC) - start_time).total_seconds()

        return DiagnosisResult(
            run_id=input_data.run_id,
            champion_id=input_data.champion_id,
            diagnosis_id=str(uuid.uuid4()),
            outcome=DiagnosisOutcome.INSUFFICIENT_EVIDENCE,
            primary_diagnosis=None,
            secondary_findings=[],
            informational_findings=[],
            evidence_quality=evidence_quality,
            unavailable_evidence=self._get_unavailable_evidence(
                RuleEvaluationContext(
                    resolver=resolver,
                    evidence_quality=evidence_quality,
                    timeframe=input_data.timeframe,
                    run_id=input_data.run_id,
                    champion_id=input_data.champion_id,
                )
            ),
            evaluated_rules=[],
            skipped_rules=[r.rule_id for r in self.registry.get_all_rules()],
            skipped_reasons={
                r.rule_id: "Insufficient evidence" for r in self.registry.get_all_rules()
            },
            input_hash=self._compute_input_hash(input_data),
            duration_seconds=duration_seconds,
        )

    def _select_primary_diagnosis(
        self, findings: list[DiagnosisFinding], evidence_quality: EvidenceQuality
    ) -> Optional[DiagnosisFinding]:
        """Select the primary diagnosis from findings.

        Uses deterministic order:
        1. Evidence sufficiency/actionability gate
        2. Severity
        3. Confidence
        4. Fixed rule priority
        5. Stable diagnosis_code tie-break

        Args:
            findings: List of diagnosis findings
            evidence_quality: Evidence quality classification

        Returns:
            Primary diagnosis finding, or None if no findings
        """
        if not findings:
            return None

        # Filter out derived findings from primary consideration
        primary_candidates = [f for f in findings if not self._is_derived_finding(f)]

        if not primary_candidates:
            return None

        # Evidence-quality gate: only HIGH or MEDIUM quality findings can be primary
        if evidence_quality == EvidenceQuality.LOW:
            # With LOW evidence, only CRITICAL findings with high confidence can be primary
            primary_candidates = [
                f for f in primary_candidates
                if f.severity == Severity.CRITICAL and f.confidence >= 0.85
            ]
        elif evidence_quality == EvidenceQuality.INSUFFICIENT:
            # No primary diagnosis with insufficient evidence
            return None

        if not primary_candidates:
            return None

        # Sort by deterministic order
        sorted_findings = sorted(
            primary_candidates,
            key=lambda f: (
                -self._severity_score(f.severity),
                -f.confidence,
                -self._get_rule_priority(f.diagnosis_code),
                f.diagnosis_code.value,
            ),
        )

        return sorted_findings[0]

    def _severity_score(self, severity: Severity) -> int:
        """Convert severity to numeric score for sorting.

        Args:
            severity: Severity enum

        Returns:
            Numeric score (higher = more severe)
        """
        scores = {
            Severity.CRITICAL: 5,
            Severity.HIGH: 4,
            Severity.MEDIUM: 3,
            Severity.LOW: 2,
            Severity.INFO: 1,
        }
        return scores.get(severity, 0)

    def _get_rule_priority(self, code: DiagnosisCode) -> int:
        """Get the priority of a rule by diagnosis code.

        Args:
            code: Diagnosis code

        Returns:
            Rule priority (higher = more important)
        """
        rule = self.registry.get_rule_by_diagnosis_code(code.value)
        return rule.priority if rule else 0

    def _categorize_findings(
        self, all_findings: list[DiagnosisFinding], primary: Optional[DiagnosisFinding]
    ) -> tuple[list[DiagnosisFinding], list[DiagnosisFinding]]:
        """Categorize findings into secondary and informational.

        Args:
            all_findings: All findings
            primary: Primary diagnosis finding

        Returns:
            Tuple of (secondary_findings, informational_findings)
        """
        if not primary:
            return [], []

        secondary = []
        informational = []

        for finding in all_findings:
            if finding == primary:
                continue

            if finding.severity in [Severity.HIGH, Severity.CRITICAL, Severity.MEDIUM]:
                secondary.append(finding)
            else:
                informational.append(finding)

        return secondary, informational

    def _is_derived_finding(self, finding: DiagnosisFinding) -> bool:
        """Check if a finding is derived/routing (parameter research).

        Args:
            finding: Diagnosis finding

        Returns:
            True if derived, False otherwise
        """
        return finding.category == DiagnosisCategory.PARAMETER_RESEARCH

    def _generate_derived_findings(
        self, primary: DiagnosisFinding, context: RuleEvaluationContext
    ) -> list[DiagnosisFinding]:
        """Generate derived parameter research findings based on primary diagnosis.

        Args:
            primary: Primary diagnosis finding
            context: Evaluation context

        Returns:
            List of derived findings
        """
        derived = []

        # Map primary categories to parameter research suggestions
        category_mapping = {
            DiagnosisCategory.EXIT_BEHAVIOR: DiagnosisCode.EXIT_PARAMETER_RESEARCH_NEEDED,
            DiagnosisCategory.RISK_QUALITY: DiagnosisCode.RISK_PARAMETER_RESEARCH_NEEDED,
            DiagnosisCategory.ENTRY_BEHAVIOR: DiagnosisCode.ENTRY_PARAMETER_RESEARCH_NEEDED,
        }

        target_code = category_mapping.get(primary.category)
        if target_code:
            derived.append(
                DiagnosisFinding(
                    diagnosis_code=target_code,
                    category=DiagnosisCategory.PARAMETER_RESEARCH,
                    severity=Severity.INFO,
                    confidence=primary.confidence * 0.9,  # Slightly lower confidence
                    evidence_refs=primary.evidence_refs,
                    evidence_values=primary.evidence_values,
                    explanation=f"Parameter research suggested based on primary diagnosis: {primary.diagnosis_code.value}",
                    suggested_research_area="parameter_research",
                    limitations=["Derived finding based on primary diagnosis"],
                    rule_version="1.0.0",
                )
            )

        return derived

    def _get_unavailable_evidence(self, context: RuleEvaluationContext) -> list[str]:
        """Get list of unavailable evidence items.

        Args:
            context: Evaluation context

        Returns:
            List of unavailable evidence identifiers
        """
        unavailable = []
        resolver = context.resolver

        evidence_checks = {
            "total_trades": resolver.get_total_trades() is None,
            "profit_factor": not resolver.is_metric_available("profit_factor"),
            "expectancy": not resolver.is_metric_available("expectancy"),
            "max_drawdown_pct": not resolver.is_metric_available("max_drawdown_pct"),
            "calmar": not resolver.is_metric_available("calmar"),
            "sortino": not resolver.is_metric_available("sortino"),
            "per_pair_contribution": len(resolver.get_per_pair_contributions()) == 0,
            "concentration_summary": resolver.get_concentration_summary() is None,
            "exit_reason_distribution": len(resolver.get_exit_reason_distribution()) == 0,
            "selected_pairs": len(resolver.get_selected_pairs()) == 0,
        }

        for evidence, unavailable_flag in evidence_checks.items():
            if unavailable_flag:
                unavailable.append(evidence)

        return unavailable

    def _compute_input_hash(self, input_data: DiagnosisInput) -> str:
        """Compute deterministic hash of input for idempotency.

        Args:
            input_data: DiagnosisInput

        Returns:
            SHA-256 hash of input
        """
        # Create a deterministic representation of the input
        input_dict = {
            "run_id": input_data.run_id,
            "champion_id": input_data.champion_id,
            "champion_strategy_hash": input_data.champion_strategy_hash,
            "champion_parameter_hash": input_data.champion_parameter_hash,
            "baseline_input_hash": input_data.baseline_input_hash,
            "canonical_metrics_hash": input_data.canonical_metrics_hash,
            "timeframe": input_data.timeframe,
            "develop_timerange": input_data.develop_timerange,
            "metrics_version": input_data.metrics_version,
            "policy_version": DIAGNOSIS_POLICY_VERSION,
        }

        # Sort keys for deterministic ordering
        input_json = json.dumps(input_dict, sort_keys=True)
        return hashlib.sha256(input_json.encode()).hexdigest()
