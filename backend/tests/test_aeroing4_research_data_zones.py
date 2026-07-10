"""Tests for the Research Protocol data zone / boundary model (Milestone 3)."""

import pytest

from backend.services.aeroing4.research.data_zones import (
    BOUNDARY_DERIVATION_POLICY_VERSION,
    RESEARCH_PROTOCOL_VERSION,
    BoundarySource,
    ResearchBoundaries,
    compute_boundary_hash,
    derive_boundaries,
    validate_boundary_set,
)
from backend.services.aeroing4.research.errors import BoundaryErrorCode, BoundaryValidationError


class TestValidateBoundarySet:
    def test_valid_non_overlapping_ordered_boundaries_pass(self):
        validate_boundary_set(
            "20240101-20240301", "20240305-20240401", "20240405-20240501"
        )

    def test_rejects_malformed_timerange(self):
        with pytest.raises(BoundaryValidationError) as exc:
            validate_boundary_set("not-a-date", "20240305-20240401", "20240405-20240501")
        assert exc.value.code == BoundaryErrorCode.INVALID_FORMAT

    def test_rejects_open_ended_timerange(self):
        with pytest.raises(BoundaryValidationError) as exc:
            validate_boundary_set("20240101-", "20240305-20240401", "20240405-20240501")
        assert exc.value.code == BoundaryErrorCode.INVALID_FORMAT

    def test_rejects_reversed_zone(self):
        with pytest.raises(BoundaryValidationError) as exc:
            validate_boundary_set(
                "20240301-20240101", "20240305-20240401", "20240405-20240501"
            )
        assert exc.value.code == BoundaryErrorCode.REVERSED_OR_ZERO_DURATION

    def test_rejects_zero_duration_zone(self):
        with pytest.raises(BoundaryValidationError) as exc:
            validate_boundary_set(
                "20240101-20240101", "20240305-20240401", "20240405-20240501"
            )
        assert exc.value.code == BoundaryErrorCode.REVERSED_OR_ZERO_DURATION

    def test_rejects_overlapping_develop_confirmation(self):
        with pytest.raises(BoundaryValidationError) as exc:
            validate_boundary_set(
                "20240101-20240310", "20240305-20240401", "20240405-20240501"
            )
        assert exc.value.code == BoundaryErrorCode.OVERLAPPING_OR_OUT_OF_ORDER

    def test_rejects_overlapping_confirmation_final_unseen(self):
        with pytest.raises(BoundaryValidationError) as exc:
            validate_boundary_set(
                "20240101-20240301", "20240305-20240410", "20240405-20240501"
            )
        assert exc.value.code == BoundaryErrorCode.OVERLAPPING_OR_OUT_OF_ORDER

    def test_rejects_out_of_order_zones(self):
        with pytest.raises(BoundaryValidationError) as exc:
            validate_boundary_set(
                "20240405-20240501", "20240305-20240401", "20240101-20240301"
            )
        assert exc.value.code == BoundaryErrorCode.OVERLAPPING_OR_OUT_OF_ORDER


class TestComputeBoundaryHash:
    def test_deterministic_for_same_input(self):
        h1 = compute_boundary_hash(
            "20240101-20240301", "20240305-20240401", "20240405-20240501",
            RESEARCH_PROTOCOL_VERSION,
        )
        h2 = compute_boundary_hash(
            "20240101-20240301", "20240305-20240401", "20240405-20240501",
            RESEARCH_PROTOCOL_VERSION,
        )
        assert h1 == h2

    def test_differs_for_different_input(self):
        h1 = compute_boundary_hash(
            "20240101-20240301", "20240305-20240401", "20240405-20240501",
            RESEARCH_PROTOCOL_VERSION,
        )
        h2 = compute_boundary_hash(
            "20240101-20240302", "20240305-20240401", "20240405-20240501",
            RESEARCH_PROTOCOL_VERSION,
        )
        assert h1 != h2

    def test_differs_across_protocol_versions(self):
        h1 = compute_boundary_hash(
            "20240101-20240301", "20240305-20240401", "20240405-20240501", "1.0.0"
        )
        h2 = compute_boundary_hash(
            "20240101-20240301", "20240305-20240401", "20240405-20240501", "2.0.0"
        )
        assert h1 != h2


class TestDeriveBoundaries:
    def test_splits_deterministically_70_15_15(self):
        develop, confirmation, final_unseen = derive_boundaries("20240101-20240630")
        validate_boundary_set(develop, confirmation, final_unseen)

        # Same input + policy version always produces the same output.
        develop2, confirmation2, final_unseen2 = derive_boundaries("20240101-20240630")
        assert (develop, confirmation, final_unseen) == (develop2, confirmation2, final_unseen2)

    def test_zones_are_non_overlapping_and_ordered(self):
        develop, confirmation, final_unseen = derive_boundaries("20230101-20231231")
        # validate_boundary_set raises if anything is wrong; a clean call is the assertion.
        validate_boundary_set(develop, confirmation, final_unseen)

    def test_rejects_too_short_source_range(self):
        with pytest.raises(BoundaryValidationError) as exc:
            derive_boundaries("20240101-20240103")
        assert exc.value.code == BoundaryErrorCode.SOURCE_RANGE_TOO_SHORT

    def test_rejects_unsupported_policy_version(self):
        with pytest.raises(BoundaryValidationError) as exc:
            derive_boundaries("20240101-20240630", policy_version="9.9.9")
        assert exc.value.code == BoundaryErrorCode.UNSUPPORTED_DERIVATION_POLICY

    def test_develop_zone_is_majority_of_range(self):
        develop, confirmation, final_unseen = derive_boundaries("20240101-20241231")

        def days(tr):
            start, end = tr.split("-")
            from datetime import datetime
            return (datetime.strptime(end, "%Y%m%d") - datetime.strptime(start, "%Y%m%d")).days

        develop_days = days(develop)
        confirmation_days = days(confirmation)
        final_unseen_days = days(final_unseen)
        assert develop_days > confirmation_days
        assert develop_days > final_unseen_days


class TestResearchBoundariesModel:
    def _boundaries(self) -> ResearchBoundaries:
        return ResearchBoundaries(
            develop_timerange="20240101-20240301",
            confirmation_timerange="20240305-20240401",
            final_unseen_timerange="20240405-20240501",
            boundary_source=BoundarySource.EXPLICIT,
            boundary_hash="deadbeef",
        )

    def test_not_frozen_by_default(self):
        boundaries = self._boundaries()
        assert boundaries.is_frozen is False
        assert boundaries.frozen_at is None

    def test_frozen_copy_sets_frozen_at(self):
        boundaries = self._boundaries()
        frozen = boundaries.frozen_copy()
        assert frozen.is_frozen is True
        assert frozen.frozen_at is not None
        # Original instance is untouched (pydantic model_copy is not in-place).
        assert boundaries.is_frozen is False

    def test_frozen_copy_is_idempotent(self):
        boundaries = self._boundaries().frozen_copy()
        frozen_again = boundaries.frozen_copy()
        assert frozen_again.frozen_at == boundaries.frozen_at

    def test_round_trip_serialization(self):
        boundaries = self._boundaries()
        payload = boundaries.model_dump_json()
        reloaded = ResearchBoundaries.model_validate_json(payload)
        assert reloaded == boundaries

    def test_boundary_hash_stable(self):
        """Same boundary values always produce the same hash (no randomness)."""
        h1 = compute_boundary_hash(
            "20240101-20240301", "20240305-20240401", "20240405-20240501",
            RESEARCH_PROTOCOL_VERSION,
        )
        h2 = compute_boundary_hash(
            "20240101-20240301", "20240305-20240401", "20240405-20240501",
            RESEARCH_PROTOCOL_VERSION,
        )
        assert isinstance(h1, str) and len(h1) == 64  # sha256 hex
        assert h1 == h2


class TestDerivationPolicyDrift:
    """Derivation-policy drift must never alter already-frozen run boundaries."""

    def test_same_input_produces_same_derived_boundaries(self):
        """Identical input + policy version always yields identical concrete zones."""
        source = "20230101-20231231"
        result1 = derive_boundaries(source)
        result2 = derive_boundaries(source)
        assert result1 == result2

    def test_frozen_boundaries_unaffected_by_later_derivation_attempt(self):
        """Once persisted and frozen, concrete boundary values are fixed regardless
        of any future call to derive_boundaries (which may change with policy bumps).
        The frozen hash encodes the concrete values, not the derivation parameters.
        """
        source = "20230101-20231231"
        dev, conf, fu = derive_boundaries(source)
        frozen = ResearchBoundaries(
            develop_timerange=dev,
            confirmation_timerange=conf,
            final_unseen_timerange=fu,
            boundary_source=BoundarySource.DERIVED,
            boundary_hash=compute_boundary_hash(dev, conf, fu, RESEARCH_PROTOCOL_VERSION),
            derivation_source_timerange=source,
            derivation_policy_version=BOUNDARY_DERIVATION_POLICY_VERSION,
        ).frozen_copy()

        # The hash reflects concrete values, not derivation parameters.
        expected_hash = compute_boundary_hash(dev, conf, fu, RESEARCH_PROTOCOL_VERSION)
        assert frozen.boundary_hash == expected_hash

        # Re-deriving with the same input still matches.
        dev2, conf2, fu2 = derive_boundaries(source)
        assert dev2 == dev
        assert conf2 == conf
        assert fu2 == fu
        assert compute_boundary_hash(dev2, conf2, fu2, RESEARCH_PROTOCOL_VERSION) == frozen.boundary_hash

    def test_frozen_boundary_hash_detects_changed_input(self):
        """A different source range produces a different hash — changed input is detectable."""
        dev_a, conf_a, fu_a = derive_boundaries("20230101-20231231")
        dev_b, conf_b, fu_b = derive_boundaries("20220101-20221231")
        hash_a = compute_boundary_hash(dev_a, conf_a, fu_a, RESEARCH_PROTOCOL_VERSION)
        hash_b = compute_boundary_hash(dev_b, conf_b, fu_b, RESEARCH_PROTOCOL_VERSION)
        assert hash_a != hash_b
