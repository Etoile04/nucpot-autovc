"""Test property-mapping.json loads and validates correctly."""
import json
import pytest
from pathlib import Path
import importlib.resources

MAPPING_PATH = Path(importlib.resources.files("autovc") / "reference" / "data" / "property-mapping.json")


def test_file_exists():
    assert MAPPING_PATH.exists(), f"property-mapping.json not found at {MAPPING_PATH}"


def test_valid_json():
    with open(MAPPING_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict)


def test_has_required_top_level_keys():
    with open(MAPPING_PATH) as f:
        data = json.load(f)
    assert "version" in data
    assert "mappings" in data
    assert isinstance(data["mappings"], list)


def test_each_mapping_has_required_fields():
    with open(MAPPING_PATH) as f:
        data = json.load(f)
    required = {"ref_property", "ref_unit", "nfmd_names", "nfmd_symbols", "ontofuel_keys", "range"}
    for m in data["mappings"]:
        assert required.issubset(m.keys()), f"Mapping for {m.get('ref_property', '?')} missing: {required - m.keys()}"


def test_range_has_min_and_max():
    with open(MAPPING_PATH) as f:
        data = json.load(f)
    for m in data["mappings"]:
        assert "min" in m["range"], f"{m['ref_property']} range missing min"
        assert "max" in m["range"], f"{m['ref_property']} range missing max"
        assert m["range"]["min"] < m["range"]["max"], f"{m['ref_property']} range min >= max"


def test_all_required_properties_covered():
    """Ensure the 12 target properties are all mapped."""
    required_props = {
        "lattice_constant", "cohesive_energy",
        "C11", "C12", "C44", "C33",
        "bulk_modulus", "vacancy_formation_energy",
        "formation_energy", "surface_energy",
        "melting_point", "thermal_conductivity"
    }
    with open(MAPPING_PATH) as f:
        data = json.load(f)
    mapped_props = {m["ref_property"] for m in data["mappings"]}
    missing = required_props - mapped_props
    assert not missing, f"Missing mappings for: {missing}"


def test_no_duplicate_ref_properties():
    with open(MAPPING_PATH) as f:
        data = json.load(f)
    props = [m["ref_property"] for m in data["mappings"]]
    assert len(props) == len(set(props)), f"Duplicate ref_properties: {[p for p in props if props.count(p) > 1]}"
