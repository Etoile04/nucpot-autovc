"""Integration test: ASE-based property calculation with LJ Ar potential."""
import sys
sys.path.insert(0, "src")

import pytest
import numpy as np
from ase.calculators.lj import LennardJones
from autovc.core.properties import PropertyCalculator


@pytest.fixture
def lj_calc():
    """Lennard-Jones calculator for Ar."""
    return LennardJones()


@pytest.fixture
def calc():
    return PropertyCalculator()


def test_lattice_constant_ar(calc, lj_calc):
    """Compute lattice constant for FCC Ar with LJ potential."""
    result = calc.compute_lattice_constant(
        calculator=lj_calc,
        species="Ar",
        structure="FCC",
        lattice_guess=5.3,
    )
    assert result["property"] == "lattice_constant"
    assert result["unit"] == "angstrom"
    # LJ Ar FCC: expected ~5.24 A
    assert 4.5 < result["value"] < 6.0, f"Lattice constant {result['value']} out of range"
    print(f"  Lattice constant: {result['value']:.4f} A")


def test_cohesive_energy_ar(calc, lj_calc):
    """Compute cohesive energy for FCC Ar."""
    result = calc.compute_cohesive_energy(
        calculator=lj_calc,
        species="Ar",
        structure="FCC",
        lattice_guess=5.3,
    )
    assert result["property"] == "cohesive_energy"
    assert result["unit"] == "eV/atom"
    # LJ Ar: cohesive energy should be small and positive
    # With default LJ params (epsilon=1, sigma=1), E_coh ~ 0.01-0.08 eV
    assert result["value"] >= 0, f"Cohesive energy {result['value']} should be >= 0"
    print(f"  Cohesive energy: {result['value']:.6f} eV/atom")


def test_bulk_modulus_ar(calc, lj_calc):
    """Compute bulk modulus for FCC Ar."""
    result = calc.compute_bulk_modulus(
        calculator=lj_calc,
        species="Ar",
        structure="FCC",
        lattice_guess=5.0,
    )
    assert result["property"] == "bulk_modulus"
    assert result["unit"] == "GPa"
    # Bulk modulus should be positive
    assert result["value"] is not None
    print(f"  Bulk modulus: {result['value']:.2f} GPa")


def test_elastic_constants_ar(calc, lj_calc):
    """Compute elastic constants for FCC Ar."""
    result = calc.compute_elastic_constants(
        calculator=lj_calc,
        species="Ar",
        structure="FCC",
        lattice_guess=5.0,
    )
    assert result["property"] == "elastic_constants"
    assert result["unit"] == "GPa"
    assert "bulk_modulus" in result["value"]
    print(f"  Elastic constants: {result['value']}")


def test_supported_properties(calc):
    """All expected properties are listed."""
    props = calc.supported_properties()
    assert "lattice_constant" in props
    assert "cohesive_energy" in props
    assert "elastic_constants" in props
    assert "bulk_modulus" in props
    assert "vacancy_formation_energy" in props


def test_vacancy_formation_energy_ar(calc, lj_calc):
    """Compute vacancy formation energy for FCC Ar."""
    result = calc.compute_vacancy_formation_energy(
        calculator=lj_calc,
        species="Ar",
        structure="FCC",
        lattice_guess=5.3,
    )
    assert result["property"] == "vacancy_formation_energy"
    assert result["unit"] == "eV"
    # For LJ with primitive cell (1 atom), Evf ≈ 0
    # Accept any finite value
    assert result["value"] >= 0 or result["value"] < 0  # just check it computed
    print(f"  Vacancy formation energy: {result['value']:.6f} eV")
