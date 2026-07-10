"""Research Budget Policy — versioned, typed, atomic budget service.

RESEARCH_BUDGET_POLICY_VERSION is the single authoritative version constant.
Default limits: 5 total experiments per run, 3 per hypothesis.

Results are always typed (never bare booleans).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


RESEARCH_BUDGET_POLICY_VERSION = "1.0.0"

# Default budget limits (authoritative — not scattered elsewhere)
DEFAULT_MAX_TOTAL_EXPERIMENTS = 5
DEFAULT_MAX_EXPERIMENTS_PER_HYPOTHESIS = 3


class BudgetDecisionCode(str, Enum):
    """Typed reason codes for budget decisions."""

    ALLOWED = "allowed"
    TOTAL_BUDGET_EXHAUSTED = "total_budget_exhausted"
    HYPOTHESIS_BUDGET_EXHAUSTED = "hypothesis_budget_exhausted"
    DUPLICATE_EXPERIMENT = "duplicate_experiment"
    RUN_NOT_FOUND = "run_not_found"
    HYPOTHESIS_NOT_FOUND = "hypothesis_not_found"


class BudgetDecision(BaseModel):
    """Typed result of a budget check — never a bare boolean."""

    allowed: bool
    code: BudgetDecisionCode
    reason: str
    total_reserved: int = 0
    total_max: int = 0
    remaining_total: int = 0
    hypothesis_experiment_count: int = 0
    hypothesis_max: int = 0
    remaining_hypothesis: int = 0
    policy_version: str = RESEARCH_BUDGET_POLICY_VERSION


class BudgetService:
    """Stateless budget evaluation service.

    All checks read from the state/hypothesis counts passed in — this
    service never owns state itself; that lives in ResearchStateStore and
    HypothesisStore. Atomic reservation is enforced by ExperimentStore,
    which calls these checks under its lock before persisting.
    """

    def __init__(
        self,
        max_total_experiments: int = DEFAULT_MAX_TOTAL_EXPERIMENTS,
        max_experiments_per_hypothesis: int = DEFAULT_MAX_EXPERIMENTS_PER_HYPOTHESIS,
    ):
        if max_total_experiments < 1:
            raise ValueError("max_total_experiments must be >= 1")
        if max_experiments_per_hypothesis < 1:
            raise ValueError("max_experiments_per_hypothesis must be >= 1")
        self.max_total_experiments = max_total_experiments
        self.max_experiments_per_hypothesis = max_experiments_per_hypothesis

    def can_reserve(
        self,
        *,
        total_reserved: int,
        hypothesis_experiment_count: int,
    ) -> BudgetDecision:
        """Check whether another experiment can be reserved.

        Args:
            total_reserved: Count of already-reserved experiments for the run.
            hypothesis_experiment_count: Count of experiments for the target hypothesis.

        Returns:
            BudgetDecision (allowed=True) or denial with typed reason.
        """
        remaining_total = self.max_total_experiments - total_reserved
        remaining_hyp = self.max_experiments_per_hypothesis - hypothesis_experiment_count

        base = dict(
            total_reserved=total_reserved,
            total_max=self.max_total_experiments,
            remaining_total=remaining_total,
            hypothesis_experiment_count=hypothesis_experiment_count,
            hypothesis_max=self.max_experiments_per_hypothesis,
            remaining_hypothesis=remaining_hyp,
        )

        if total_reserved >= self.max_total_experiments:
            return BudgetDecision(
                allowed=False,
                code=BudgetDecisionCode.TOTAL_BUDGET_EXHAUSTED,
                reason=(
                    f"Total experiment budget exhausted: {total_reserved}/"
                    f"{self.max_total_experiments} reserved"
                ),
                **base,
            )

        if hypothesis_experiment_count >= self.max_experiments_per_hypothesis:
            return BudgetDecision(
                allowed=False,
                code=BudgetDecisionCode.HYPOTHESIS_BUDGET_EXHAUSTED,
                reason=(
                    f"Per-hypothesis budget exhausted: {hypothesis_experiment_count}/"
                    f"{self.max_experiments_per_hypothesis} experiments for this hypothesis"
                ),
                **base,
            )

        return BudgetDecision(
            allowed=True,
            code=BudgetDecisionCode.ALLOWED,
            reason=(
                f"Budget available: {remaining_total} total slot(s) remaining, "
                f"{remaining_hyp} per-hypothesis slot(s) remaining"
            ),
            **base,
        )

    def is_run_exhausted(self, *, total_reserved: int) -> bool:
        """Whether the run has consumed all its experiment budget."""
        return total_reserved >= self.max_total_experiments

    def remaining_total(self, *, total_reserved: int) -> int:
        """How many total experiment slots remain."""
        return max(0, self.max_total_experiments - total_reserved)

    def remaining_for_hypothesis(self, *, hypothesis_experiment_count: int) -> int:
        """How many experiment slots remain for a specific hypothesis."""
        return max(0, self.max_experiments_per_hypothesis - hypothesis_experiment_count)
