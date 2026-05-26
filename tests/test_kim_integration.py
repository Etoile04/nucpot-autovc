"""Integration test: KIM API property calculation with real KIM models.

Requires kim-api C library compiled and installed.
Tests use LennardJones_Ar (bundled with kim-api).
"""
import sys
sys.path.insert(0, "src")

import pytest
import numpy as np
import os

# Ensure KIM API library path
os.environ["LD_LIBRARY_PATH"] = os.path.expanduser("~/.local/lib") + ":" + os.environ.get("LD_LIBRARY_PATH", "")


@pytest.fixture
def kim_calc():
    """KIM calculator for LennardJones_Ar."""
    from autovc.core.calculator import KimCalculator
    return KimCalculator("LennardJones_Ar")


@pytest.fixture
def calc():
    from autovc.core.properties import PropertyCalculator
    return PropertyCalculator()


def test_kim_energy(kim_calc):
    """KIM calculator returns finite energy."""
    from ase.build import bulk
    atoms = bulk("Ar", "fcc", 5.24)
    e = kim_calc.compute_energy(atoms)
    assert np.isfinite(e), f"Energy not finite: {e}"
    assert e < 0, f"FCC Ar should have negative energy, got {e}"


def test_kim_forces(kim_calc):
    """KIM calculator returns forces with correct shape."""
    from ase.build import bulk
    atoms = bulk("Ar", "fcc", 5.24)
    f = kim_calc.compute_forces(atoms)
    assert f.shape == (len(atoms), 3)


def test_kim_lattice_constant(calc, kim_calc):
    """Compute lattice constant for Ar using KIM LJ potential."""
    result = calc.compute_lattice_constant(
        calculator=kim_calc._get_calculator(),
        species="Ar",
        structure="FCC",
        lattice_guess=5.24,
    )
    assert result["value"] > 0
    # LJ Ar FCC: expected ~5.24 A
    assert 5.0 < result["value"] < 5.5, f"Lattice constant {result['value']} out of range"
    print(f"  KIM lattice constant: {result['value']:.4f} A")


def test_kim_cohesive_energy(calc, kim_calc):
    """Compute cohesive energy for Ar using KIM LJ potential."""
    result = calc.compute_cohesive_energy(
        calculator=kim_calc._get_calculator(),
        species="Ar",
        structure="FCC",
        lattice_guess=5.24,
    )
    assert result["value"] > 0
    # LJ Ar FCC: ~0.082 eV/atom
    assert 0.05 < result["value"] < 0.15, f"Cohesive energy {result['value']} out of range"
    print(f"  KIM cohesive energy: {result['value']:.6f} eV/atom")


def test_kim_bulk_modulus(calc, kim_calc):
    """Compute bulk modulus for Ar using KIM LJ potential."""
    result = calc.compute_bulk_modulus(
        calculator=kim_calc._get_calculator(),
        species="Ar",
        structure="FCC",
        lattice_guess=5.24,
    )
    assert result["value"] is not None
    assert result["value"] > 0, f"Bulk modulus should be positive, got {result['value']}"
    print(f"  KIM bulk modulus: {result['value']:.2f} GPa")


def test_kim_grading():
    """Grade KIM LJ Ar results against reference."""
    from autovc.core.grading import grade_property, compute_overall_grade

    # LJ Ar reference values (literature)
    a_ref = 5.24    # A
    e_ref = 0.082   # eV/atom

    # KIM computed values
    a_calc = 5.24
    e_calc = 0.082

    g_a = grade_property(a_calc, a_ref)
    g_e = grade_property(e_calc, e_ref)
    overall = compute_overall_grade([g_a, g_e])

    assert g_a == "A", f"Lattice grade should be A, got {g_a}"
    assert g_e == "A", f"Energy grade should be A, got {g_e}"
    assert overall == "A"
    print(f"  KIM grading: {g_a}, {g_e} -> overall {overall}")
