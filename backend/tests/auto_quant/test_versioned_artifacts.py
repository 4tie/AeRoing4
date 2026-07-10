"""Versioned Artifacts Tests - Verify versioning works correctly.

This test suite verifies that state, report, and config files are written with
proper versioning (v1, latest) and compatibility aliases.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.services.auto_quant.pipeline_modules.state import _write_versioned_json


def test_write_versioned_json_creates_versioned_files(tmp_path):
    """Test that _write_versioned_json creates versioned and latest files."""
    test_dir = tmp_path / "test_versioned_artifacts"
    test_dir.mkdir(parents=True, exist_ok=True)
    
    test_payload = {"key": "value", "number": 42}
    
    artifacts = _write_versioned_json(test_dir, "test", test_payload, legacy_name="test.json")
    
    # Verify versioned file exists
    versioned_file = test_dir / "test_v1.json"
    assert versioned_file.exists()
    
    # Verify latest file exists
    latest_file = test_dir / "test_latest.json"
    assert latest_file.exists()
    
    # Verify legacy alias exists
    legacy_file = test_dir / "test.json"
    assert legacy_file.exists()
    
    # Verify all files have same content
    versioned_content = json.loads(versioned_file.read_text(encoding="utf-8"))
    latest_content = json.loads(latest_file.read_text(encoding="utf-8"))
    legacy_content = json.loads(legacy_file.read_text(encoding="utf-8"))
    
    assert versioned_content == test_payload
    assert latest_content == test_payload
    assert legacy_content == test_payload
    
    # Verify artifacts dict
    assert "test_v1" in artifacts
    assert "test_latest" in artifacts
    assert "test" in artifacts
    


def test_write_versioned_json_without_legacy(tmp_path):
    """Test that _write_versioned_json works without legacy name."""
    test_dir = tmp_path / "test_versioned_artifacts_no_legacy"
    test_dir.mkdir(parents=True, exist_ok=True)
    
    test_payload = {"key": "value"}
    
    artifacts = _write_versioned_json(test_dir, "test", test_payload)
    
    # Verify versioned and latest files exist
    assert (test_dir / "test_v1.json").exists()
    assert (test_dir / "test_latest.json").exists()
    
    # Verify legacy file does not exist
    assert not (test_dir / "test.json").exists()
    
    # Verify artifacts dict
    assert "test_v1" in artifacts
    assert "test_latest" in artifacts
    assert "test" not in artifacts
    


def test_write_versioned_json_overwrites_latest(tmp_path):
    """Test that _write_versioned_json overwrites latest but keeps versioned."""
    test_dir = tmp_path / "test_versioned_artifacts_overwrite"
    test_dir.mkdir(parents=True, exist_ok=True)
    
    # First write
    payload1 = {"version": 1}
    _write_versioned_json(test_dir, "test", payload1, legacy_name="test.json")
    
    # Second write
    payload2 = {"version": 2}
    _write_versioned_json(test_dir, "test", payload2, legacy_name="test.json")
    
    # Verify v1 still has original content
    v1_content = json.loads((test_dir / "test_v1.json").read_text(encoding="utf-8"))
    assert v1_content == payload1
    
    # Verify v2 has the new versioned content
    v2_content = json.loads((test_dir / "test_v2.json").read_text(encoding="utf-8"))
    assert v2_content == payload2
    
    # Verify latest has new content
    latest_content = json.loads((test_dir / "test_latest.json").read_text(encoding="utf-8"))
    assert latest_content == payload2
    
    # Verify legacy has new content
    legacy_content = json.loads((test_dir / "test.json").read_text(encoding="utf-8"))
    assert legacy_content == payload2
    


def test_versioned_files_have_correct_naming(tmp_path):
    """Test that versioned files follow correct naming convention."""
    test_dir = tmp_path / "test_versioned_artifacts_naming"
    test_dir.mkdir(parents=True, exist_ok=True)
    
    test_payload = {"test": "data"}
    
    _write_versioned_json(test_dir, "state", test_payload, legacy_name="state.json")
    _write_versioned_json(test_dir, "report", test_payload, legacy_name="report.json")
    _write_versioned_json(test_dir, "config", test_payload, legacy_name="config.json")
    
    # Verify naming convention
    assert (test_dir / "state_v1.json").exists()
    assert (test_dir / "state_latest.json").exists()
    assert (test_dir / "state.json").exists()
    
    assert (test_dir / "report_v1.json").exists()
    assert (test_dir / "report_latest.json").exists()
    assert (test_dir / "report.json").exists()
    
    assert (test_dir / "config_v1.json").exists()
    assert (test_dir / "config_latest.json").exists()
    assert (test_dir / "config.json").exists()
    


def test_artifacts_dict_returned(tmp_path):
    """Test that _write_versioned_json returns correct artifacts dict."""
    test_dir = tmp_path / "test_versioned_artifacts_dict"
    test_dir.mkdir(parents=True, exist_ok=True)
    
    test_payload = {"test": "data"}
    
    artifacts = _write_versioned_json(test_dir, "test", test_payload, legacy_name="test.json")
    
    # Verify artifacts dict structure
    assert isinstance(artifacts, dict)
    assert len(artifacts) == 3
    assert artifacts["test_v1"] == "test_v1.json"
    assert artifacts["test_latest"] == "test_latest.json"
    assert artifacts["test"] == "test.json"
    

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
