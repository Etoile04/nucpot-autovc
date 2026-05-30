"""Test gap analyzer: compare target matrix vs existing data."""
import json
import pytest
from pathlib import Path

from autovc.reference.gap_analyzer import (
    load_target_systems,
    load_existing_refs,
    compute_gaps,
    GapItem,
)


def test_load_target_systems_returns_dict():
    systems = load_target_systems()
    assert isinstance(systems, list)
    assert len(systems) > 0
    for s in systems:
        assert "element_system" in s
        assert "phase" in s
        assert "priority" in s


def test_load_existing_refs_parses_json():
    refs = [
        {"element_system": "U", "phase": "BCC", "property": "lattice_constant", "value": 3.39},
    ]
    result = load_existing_refs(refs)
    assert ("U", "BCC", "lattice_constant") in result


def test_compute_gaps_identifies_missing():
    targets = [
        {"element_system": "U", "phase": "BCC", "priority": 1,
         "properties": ["lattice_constant", "C11", "cohesive_energy"]},
    ]
    existing = {("U", "BCC", "lattice_constant")}
    gaps = compute_gaps(targets, existing)
    gap_keys = [(g.element_system, g.phase, g.property) for g in gaps]
    assert ("U", "BCC", "C11") in gap_keys
    assert ("U", "BCC", "cohesive_energy") in gap_keys
    assert ("U", "BCC", "lattice_constant") not in gap_keys


def test_compute_gaps_sorted_by_priority():
    targets = [
        {"element_system": "U-Pu-Zr", "phase": "BCC", "priority": 2,
         "properties": ["C11"]},
        {"element_system": "U", "phase": "BCC", "priority": 1,
         "properties": ["C11"]},
    ]
    existing = set()
    gaps = compute_gaps(targets, existing)
    assert gaps[0].element_system == "U"
    assert gaps[1].element_system == "U-Pu-Zr"


def test_gap_item_serializes_to_json():
    gap = GapItem(element_system="U-Mo", phase="BCC", property="C44", priority=1)
    d = gap.to_dict()
    assert d["element_system"] == "U-Mo"
    json.dumps(d)
