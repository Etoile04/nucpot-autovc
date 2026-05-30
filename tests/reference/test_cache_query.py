"""Test three-level cache query logic."""
import json
import pytest
from pathlib import Path
import sys

from autovc.reference.cache_query import (
    load_property_mapping,
    CacheResult,
    CacheLevel,
    query_l1,
    query_l2,
    query_l3_wiki,
    cache_query,
)


def test_load_property_mapping():
    mapping = load_property_mapping()
    assert "lattice_constant" in mapping
    assert mapping["lattice_constant"]["ref_unit"] in ("Å", "angstrom")


def test_cache_result_dataclass():
    cr = CacheResult(
        level=CacheLevel.L1,
        element_system="U",
        phase="BCC",
        property="lattice_constant",
        value=3.39,
        unit="angstrom",
        method="DFT",
        source="test",
        confidence="high",
    )
    d = cr.to_ref_value_dict()
    assert d["element_system"] == "U"
    assert d["value"] == 3.39


def test_query_l1_with_mock():
    """Test L1 query with mocked PG result."""
    mock_rows = [
        {"element_system": "U", "phase": "BCC", "property": "lattice_constant",
         "value": 3.39, "unit": "angstrom", "method": "DFT (PBE)",
         "source": "Test", "source_doi": None, "needs_review": False},
    ]
    result = query_l1("U", "BCC", "lattice_constant", _mock_rows=mock_rows)
    assert result is not None
    assert result.level == CacheLevel.L1
    assert result.value == 3.39


def test_query_l1_miss_returns_none():
    result = query_l1("U", "BCC", "cohesive_energy", _mock_rows=[])
    assert result is None


def test_query_l2_with_mock():
    """Test L2 query with mocked Supabase result."""
    mock_params = [
        {"material_raw": "U", "name": "lattice parameter", "symbol": "a",
         "value_scalar": 3.39, "unit": "Å", "temperature_k": 0,
         "method": "DFT", "source_file": "test.md"},
    ]
    mapping = load_property_mapping()
    result = query_l2("U", "BCC", "lattice_constant", mapping, _mock_params=mock_params)
    assert result is not None
    assert result.level == CacheLevel.L2


def test_query_l2_miss_returns_none():
    mapping = load_property_mapping()
    result = query_l2("U", "BCC", "cohesive_energy", mapping, _mock_params=[])
    assert result is None


def test_cache_query_l1_hit():
    """If L1 hits, return immediately without L2/L3."""
    result = cache_query("U", "BCC", "lattice_constant",
                         _l1_rows=[{"element_system": "U", "phase": "BCC",
                                    "property": "lattice_constant", "value": 3.39,
                                    "unit": "angstrom", "method": "DFT",
                                    "source": "test", "source_doi": None,
                                    "needs_review": False}])
    assert result is not None
    assert result.level == CacheLevel.L1
