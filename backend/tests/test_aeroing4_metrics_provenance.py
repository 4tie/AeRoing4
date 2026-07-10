"""Provenance and versioning tests for the AeRoing4 Metrics SSOT (Prompt 2)."""

from backend.services.aeroing4.metrics.provenance import (
    METRICS_VERSION,
    SourceType,
    build_provenance,
    is_version_current,
)


class TestProvenance:
    def test_metrics_version_present(self):
        prov = build_provenance(source_type=SourceType.PARSED_SUMMARY, source_run_id="r1")
        assert prov["metrics_version"] == METRICS_VERSION

    def test_source_run_id_survives(self):
        prov = build_provenance(source_type=SourceType.RAW_TRADES, source_run_id="run-123")
        assert prov["source_run_id"] == "run-123"

    def test_source_type_survives(self):
        prov = build_provenance(source_type=SourceType.PAIR_DISCOVERY_GROUP, source_run_id=None)
        assert prov["source_type"] == SourceType.PAIR_DISCOVERY_GROUP

    def test_adapted_and_derived_metrics_identified(self):
        prov = build_provenance(
            source_type=SourceType.PARSED_SUMMARY,
            source_run_id="r1",
            adapted_metrics=["profit_factor"],
            derived_metrics=["bootstrap_sharpe_p5"],
        )
        assert prov["adapted_metrics"] == ["profit_factor"]
        assert prov["derived_metrics"] == ["bootstrap_sharpe_p5"]

    def test_unavailable_metrics_identified_and_sorted(self):
        prov = build_provenance(
            source_type=SourceType.PARSED_SUMMARY,
            source_run_id="r1",
            unavailable_metrics=["sortino", "calmar"],
        )
        assert prov["unavailable_metrics"] == ["calmar", "sortino"]


class TestVersioning:
    def test_same_version_is_current(self):
        assert is_version_current(METRICS_VERSION) is True

    def test_mismatched_version_detected(self):
        assert is_version_current("0.9.0") is False

    def test_version_is_single_hardcoded_source(self):
        """METRICS_VERSION must only be defined in provenance.py — every
        provenance record must reference the same constant, not a private
        copy."""
        prov1 = build_provenance(source_type=SourceType.PARSED_SUMMARY, source_run_id="a")
        prov2 = build_provenance(source_type=SourceType.RAW_TRADES, source_run_id="b")
        assert prov1["metrics_version"] == prov2["metrics_version"] == METRICS_VERSION
