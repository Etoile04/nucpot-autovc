"""Test ontofuel individual → reference_value adapter."""
import pytest
from pathlib import Path

from autovc.reference.adapters.ontology import adapt_ontology_individual, OntologyAdapterError


def test_density_not_in_target_returns_empty():
    """Density is not in our 12 target properties, should return empty."""
    individual = {
        "class": "Uranium",
        "properties": {
            "hasDensity": {"value": 19.1, "unit": "g/cm³"},
        },
        "source": "ontofuel extraction",
    }
    result = adapt_ontology_individual(individual)
    assert result is None or len(result) == 0


def test_lattice_constant_mapping():
    individual = {
        "class": "UraniumMolybdenumAlloy",
        "properties": {
            "latticeConstant": {"value": 3.39, "unit": "Å"},
        },
        "source": "ontofuel extraction",
    }
    results = adapt_ontology_individual(individual)
    assert results is not None
    assert len(results) > 0
    assert any(r["property"] == "lattice_constant" for r in results)


def test_formation_energy_mapping():
    individual = {
        "class": "UraniumZirconiumAlloy",
        "properties": {
            "formationEnergy": {"value": -0.15, "unit": "eV/atom"},
        },
        "source": "ontofuel extraction",
    }
    results = adapt_ontology_individual(individual)
    assert any(r["property"] == "formation_energy" for r in results)


def test_empty_properties_returns_none():
    individual = {
        "class": "Uranium",
        "properties": {},
        "source": "test",
    }
    result = adapt_ontology_individual(individual)
    assert result is None or len(result) == 0
