"""Test write-ref-value: quality gate, dedup, confidence-based write."""
import pytest
from pathlib import Path

from autovc.reference.write_ref_value import (
    passes_range_check,
    passes_quality_gate,
    dedup_check,
    write_ref_value,
    WriteResult,
    WriteStatus,
)


def test_range_check_pass():
    assert passes_range_check("lattice_constant", 3.39) is True


def test_range_check_fail_low():
    assert passes_range_check("lattice_constant", 0.5) is False


def test_range_check_fail_high():
    assert passes_range_check("C11", 9999.0) is False


def test_quality_gate_requires_source():
    ref = {
        "element_system": "U", "phase": "BCC", "property": "lattice_constant",
        "value": 3.39, "unit": "angstrom", "method": "DFT",
        "source": "", "confidence": "high",
    }
    assert passes_quality_gate(ref) is False


def test_quality_gate_passes_with_source():
    ref = {
        "element_system": "U", "phase": "BCC", "property": "lattice_constant",
        "value": 3.39, "unit": "angstrom", "method": "DFT",
        "source": "Test 2024", "confidence": "high",
    }
    assert passes_quality_gate(ref) is True


def test_quality_gate_rejects_out_of_range():
    ref = {
        "element_system": "U", "phase": "BCC", "property": "lattice_constant",
        "value": 0.01, "unit": "angstrom", "method": "DFT",
        "source": "Test 2024", "confidence": "high",
    }
    assert passes_quality_gate(ref) is False


def test_dedup_detects_existing():
    existing = [
        {"element_system": "U", "phase": "BCC", "property": "lattice_constant",
         "method": "DFT", "source": "Test 2024"},
    ]
    ref = {
        "element_system": "U", "phase": "BCC", "property": "lattice_constant",
        "method": "DFT", "source": "Test 2024",
    }
    assert dedup_check(ref, existing) is True  # is duplicate


def test_dedup_allows_different_method():
    existing = [
        {"element_system": "U", "phase": "BCC", "property": "lattice_constant",
         "method": "DFT", "source": "Test 2024"},
    ]
    ref = {
        "element_system": "U", "phase": "BCC", "property": "lattice_constant",
        "method": "experiment", "source": "Test 2024",
    }
    assert dedup_check(ref, existing) is False  # not duplicate


def test_write_high_confidence_auto():
    ref = {
        "element_system": "U", "phase": "BCC", "property": "lattice_constant",
        "value": 3.39, "unit": "angstrom", "method": "DFT (PBE)",
        "source": "Test 2024", "source_doi": "10.1234/test",
        "confidence": "high", "uncertainty": None, "temperature": 0,
    }
    result = write_ref_value(ref, _existing=[])
    assert result.status == WriteStatus.WRITTEN_AUTO


def test_write_medium_confidence_needs_review():
    ref = {
        "element_system": "U", "phase": "BCC", "property": "lattice_constant",
        "value": 3.39, "unit": "angstrom", "method": "DFT (PBE)",
        "source": "Test 2024", "source_doi": None,
        "confidence": "medium", "uncertainty": None, "temperature": 0,
    }
    result = write_ref_value(ref, _existing=[])
    assert result.status == WriteStatus.WRITTEN_PENDING_REVIEW


def test_write_duplicate_skipped():
    existing = [
        {"element_system": "U", "phase": "BCC", "property": "lattice_constant",
         "method": "DFT (PBE)", "source": "Test 2024"},
    ]
    ref = {
        "element_system": "U", "phase": "BCC", "property": "lattice_constant",
        "value": 3.39, "unit": "angstrom", "method": "DFT (PBE)",
        "source": "Test 2024", "source_doi": "10.1234/test",
        "confidence": "high", "uncertainty": None, "temperature": 0,
    }
    result = write_ref_value(ref, _existing=existing)
    assert result.status == WriteStatus.DUPLICATE


def test_write_rejected_by_quality():
    ref = {
        "element_system": "U", "phase": "BCC", "property": "lattice_constant",
        "value": 0.01, "unit": "angstrom", "method": "DFT",
        "source": "Test", "confidence": "high",
        "uncertainty": None, "temperature": 0,
    }
    result = write_ref_value(ref, _existing=[])
    assert result.status == WriteStatus.REJECTED
