"""AeRoing4 Research Control Layer — Research Protocol / Data Zone Guard.

Public API surface for `backend.services.aeroing4.research`. See
`docs/AEROING4_RESEARCH_PROTOCOL.md` for the conceptual overview.

Milestone 4 additions:
- ResearchState / ResearchStateStore (research_state.py)
- RESEARCH_BUDGET_POLICY_VERSION / BudgetService / BudgetDecision (budgets.py)
- HypothesisRecord / HypothesisStore (hypotheses.py)
- ExperimentRecord / ExperimentStore (experiments.py)
- ChampionReference / ChampionStore (champions.py)
- compute_experiment_identity_hash / compute_original_strategy_provenance_hash (identity.py)
"""

from .access_guard import BoundaryManager, DataZoneGuard
from .data_zones import (
    BOUNDARY_DERIVATION_POLICY_VERSION,
    RESEARCH_PROTOCOL_VERSION,
    BoundarySource,
    ResearchBoundaries,
    ResearchZone,
    compute_boundary_hash,
    derive_boundaries,
    validate_boundary_set,
)
from .errors import (
    BoundaryErrorCode,
    BoundaryFrozenError,
    BoundaryValidationError,
    LedgerIntegrityError,
    ResearchProtocolError,
)
from .hashing import compute_parameter_hash, compute_pair_set_hash, compute_strategy_hash
from .ledger import AccessDecision, AccessDecisionCode, AccessLedger, AccessLedgerEntry
from .stages import (
    STAGE_ALLOWED_ZONES,
    STAGE_CLASSIFICATIONS,
    ResearchStage,
    StageClassification,
    allowed_zones_for_stage,
    classification_for_stage,
)
from .state import ResearchProtocolState, ResearchProtocolSummary

# ── Milestone 4: Research Memory ──────────────────────────────────────────────
from .research_state import (
    ResearchState,
    ResearchStateStore,
    ResearchStatus,
    ResearchStateIntegrityError,
)
from .budgets import (
    RESEARCH_BUDGET_POLICY_VERSION,
    DEFAULT_MAX_TOTAL_EXPERIMENTS,
    DEFAULT_MAX_EXPERIMENTS_PER_HYPOTHESIS,
    BudgetDecision,
    BudgetDecisionCode,
    BudgetService,
)
from .hypotheses import (
    HypothesisRecord,
    HypothesisStore,
    HypothesisSource,
    HypothesisStatus,
    HypothesisEvidenceRef,
    HypothesisTransitionError,
    HypothesisIntegrityError,
)
from .experiments import (
    ExperimentRecord,
    ExperimentStore,
    ExperimentStatus,
    ExperimentDecision,
    OriginalStrategyProvenance,
    ExactChange,
    DuplicateExperimentDecision,
    ResumeSafetyReport,
    ExperimentTransitionError,
    ExperimentIntegrityError,
    TERMINAL_STATUSES,
    IN_FLIGHT_STATUSES,
)
from .champions import (
    ChampionReference,
    ChampionStore,
    ChampionSourceType,
    ArtifactReference,
    ChampionPromotionError,
    ChampionIntegrityError,
)
from .identity import (
    compute_experiment_identity_hash,
    compute_original_strategy_provenance_hash,
    compute_config_hash,
    compute_change_hash,
    compute_pair_set_hash,
)

__all__ = [
    # Protocol (Milestone 3)
    "BoundaryManager",
    "DataZoneGuard",
    "BOUNDARY_DERIVATION_POLICY_VERSION",
    "RESEARCH_PROTOCOL_VERSION",
    "BoundarySource",
    "ResearchBoundaries",
    "ResearchZone",
    "compute_boundary_hash",
    "derive_boundaries",
    "validate_boundary_set",
    "BoundaryErrorCode",
    "BoundaryFrozenError",
    "BoundaryValidationError",
    "LedgerIntegrityError",
    "ResearchProtocolError",
    "compute_parameter_hash",
    "compute_pair_set_hash",
    "compute_strategy_hash",
    "AccessDecision",
    "AccessDecisionCode",
    "AccessLedger",
    "AccessLedgerEntry",
    "STAGE_ALLOWED_ZONES",
    "STAGE_CLASSIFICATIONS",
    "ResearchStage",
    "StageClassification",
    "allowed_zones_for_stage",
    "classification_for_stage",
    "ResearchProtocolState",
    "ResearchProtocolSummary",
    # Research Memory (Milestone 4)
    "ResearchState",
    "ResearchStateStore",
    "ResearchStatus",
    "ResearchStateIntegrityError",
    "RESEARCH_BUDGET_POLICY_VERSION",
    "DEFAULT_MAX_TOTAL_EXPERIMENTS",
    "DEFAULT_MAX_EXPERIMENTS_PER_HYPOTHESIS",
    "BudgetDecision",
    "BudgetDecisionCode",
    "BudgetService",
    "HypothesisRecord",
    "HypothesisStore",
    "HypothesisSource",
    "HypothesisStatus",
    "HypothesisEvidenceRef",
    "HypothesisTransitionError",
    "HypothesisIntegrityError",
    "ExperimentRecord",
    "ExperimentStore",
    "ExperimentStatus",
    "ExperimentDecision",
    "OriginalStrategyProvenance",
    "ExactChange",
    "DuplicateExperimentDecision",
    "ResumeSafetyReport",
    "ExperimentTransitionError",
    "ExperimentIntegrityError",
    "TERMINAL_STATUSES",
    "IN_FLIGHT_STATUSES",
    "ChampionReference",
    "ChampionStore",
    "ChampionSourceType",
    "ArtifactReference",
    "ChampionPromotionError",
    "ChampionIntegrityError",
    "compute_experiment_identity_hash",
    "compute_original_strategy_provenance_hash",
    "compute_config_hash",
    "compute_change_hash",
    "compute_pair_set_hash",
]
