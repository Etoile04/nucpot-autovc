"""Test NFMD parameter → reference_value adapter."""
import pytest
from pathlib import Path

from autovc.reference.adapters.nfmd import adapt_nfmd_param, NfmdAdapterError


def test_basic_adaptation():
    param = {
        "material_raw": "U-Mo",
        "name": "elastic constant C11",
        "symbol": "C11",
        "value_scalar": 286.0,
        "unit": "GPa",
        "temperature_k": 0,
        "method": "DFT (PBE)",
        "source_file": "hu-2016-jnm.md",
    }
    result = adapt_nfmd_param(param, phase="BCC")
    assert result["element_system"] == "U-Mo"
    assert result["phase"] == "BCC"
    assert result["property"] == "C11"
    assert result["value"] == 286.0
    assert result["unit"] == "GPa"
    assert result["confidence"] == "medium"


def test_unknown_property_raises():
    param = {
        "material_raw": "U",
        "name": "unknown property",
        "symbol": "X",
        "value_scalar": 1.0,
        "unit": "m",
        "temperature_k": 0,
        "method": "experiment",
        "source_file": "test.md",
    }
    with pytest.raises(NfmdAdapterError, match="Cannot map"):
        adapt_nfmd_param(param, phase="BCC")


def test_missing_source_gets_low_confidence():
    param = {
        "material_raw": "U",
        "name": "lattice parameter",
        "symbol": "a",
        "value_scalar": 3.39,
        "unit": "Å",
        "temperature_k": 0,
        "method": "DFT",
        "source_file": "Experiment",
    }
    result = adapt_nfmd_param(param, phase="BCC")
    assert result["confidence"] == "low"


def test_unit_conversion_angstrom():
    param = {
        "material_raw": "Mo",
        "name": "lattice parameter",
        "symbol": "a",
        "value_scalar": 3.15,
        "unit": "Å",
        "temperature_k": 0,
        "method": "DFT",
        "source_file": "test.md",
    }
    result = adapt_nfmd_param(param, phase="BCC")
    assert result["unit"] == "angstrom"
    assert abs(result["value"] - 3.15) < 0.001
