"""Property calculation engine.

Supports two backends:
1. kimvv (requires kimpy/KIM API) — preferred for production
2. ASE native calculators — fallback when KIM API is unavailable

For MVP, ASE backend is the default. kimvv backend activates when kimpy is importable.
"""

from __future__ import annotations

import logging
import numpy as np
from typing import Any

from ase.build import bulk
from ase.optimize import BFGS

logger = logging.getLogger(__name__)

_PROPERTY_DEFS: dict[str, dict[str, str]] = {
    "lattice_constant": {"unit": "angstrom", "description": "Equilibrium lattice constant"},
    "cohesive_energy": {"unit": "eV/atom", "description": "Cohesive energy per atom"},
    "elastic_constants": {"unit": "GPa", "description": "Elastic constants C11/C12/C44"},
    "bulk_modulus": {"unit": "GPa", "description": "Bulk modulus from EV curve or elastic constants"},
    "vacancy_formation_energy": {"unit": "eV", "description": "Monovacancy formation energy"},
}

# Try to detect kimvv availability
_HAS_KIMVV = False
try:
    import kimvv
    _HAS_KIMVV = True
except ImportError:
    pass


def _has_kimpy() -> bool:
    try:
        import kimpy
        return True
    except ImportError:
        return False


class PropertyCalculator:
    """High-level interface for computing material properties."""

    def supported_properties(self) -> list[str]:
        return list(_PROPERTY_DEFS.keys())

    @staticmethod
    def get_property_info(name: str) -> dict[str, str]:
        return _PROPERTY_DEFS.get(name, {})

    def _get_relaxed_atoms(self, calc, species: str, structure: str, guess: float) -> Any:
        """Relax structure and return relaxed atoms."""
        atoms = bulk(species, structure.lower(), a=guess)
        atoms.calc = calc
        opt = BFGS(atoms, logfile=None)
        opt.run(fmax=0.001, steps=200)
        return atoms

    def _extract_lattice_constant(self, atoms, structure: str) -> float:
        """Extract conventional cubic lattice constant from relaxed cell."""
        cell = atoms.get_cell()
        vol = atoms.get_volume()
        n = len(atoms)
        atoms_per_conventional = {"bcc": 2, "fcc": 4, "sc": 1, "diamond": 8}
        n_conv = atoms_per_conventional.get(structure.lower(), n)
        v_conv = vol * n_conv / n
        a = v_conv ** (1.0 / 3.0)
        return float(a)

    def _get_calculator(self, calculator=None, kim_model=None, species="U"):
        """Resolve calculator, raising if none available."""
        if calculator is not None:
            return calculator
        from autovc.core.calculator import KimCalculator
        kc = KimCalculator(kim_model=kim_model or species)
        return kc._get_calculator()

    def compute_lattice_constant(
        self,
        calculator=None,
        kim_model: str | None = None,
        species: str = "U",
        structure: str = "BCC",
        lattice_guess: float | None = None,
    ) -> dict[str, Any]:
        """Compute equilibrium lattice constant."""
        guess = lattice_guess or 3.4
        calc = self._get_calculator(calculator, kim_model, species)
        atoms = self._get_relaxed_atoms(calc, species, structure, guess)
        a = self._extract_lattice_constant(atoms, structure)
        return {"value": a, "unit": "angstrom", "property": "lattice_constant"}

    def compute_cohesive_energy(
        self,
        calculator=None,
        kim_model: str | None = None,
        species: str = "U",
        structure: str = "BCC",
        lattice_guess: float | None = None,
    ) -> dict[str, Any]:
        """Compute cohesive energy = E_isolated_atom - E_bulk/N."""
        from ase import Atoms
        guess = lattice_guess or 3.4
        calc = self._get_calculator(calculator, kim_model, species)

        atoms_bulk = bulk(species, structure.lower(), a=guess)
        atoms_bulk.calc = calc
        e_bulk = atoms_bulk.get_potential_energy()
        n_atoms = len(atoms_bulk)

        atom_single = Atoms(species, positions=[[0, 0, 0]], cell=[20, 20, 20], pbc=False)
        atom_single.calc = calc
        e_atom = atom_single.get_potential_energy()

        cohesive_e = (e_atom - e_bulk) / n_atoms
        return {"value": cohesive_e, "unit": "eV/atom", "property": "cohesive_energy"}

    def compute_elastic_constants(
        self,
        calculator=None,
        kim_model: str | None = None,
        species: str = "U",
        structure: str = "BCC",
        lattice_guess: float | None = None,
    ) -> dict[str, Any]:
        """Compute elastic constants using finite strain method."""
        guess = lattice_guess or 3.4
        calc = self._get_calculator(calculator, kim_model, species)

        atoms = bulk(species, structure.lower(), a=guess)
        atoms.calc = calculator if calculator else calc

        v0 = atoms.get_volume()
        e0 = atoms.get_potential_energy()

        strains = np.linspace(-0.02, 0.02, 9)
        volumes = []
        energies = []
        for eps in strains:
            strain_matrix = np.eye(3) * (1 + eps)
            strained = atoms.copy()
            strained.set_cell(strained.get_cell() @ strain_matrix, scale_atoms=True)
            strained.calc = calc
            volumes.append(strained.get_volume())
            energies.append(strained.get_potential_energy())

        volumes = np.array(volumes)
        energies = np.array(energies)
        coeffs = np.polyfit(volumes, energies, 2)
        B = 2 * coeffs[0] * v0  # eV/A^3
        B_GPa = B * 160.2176634  # convert eV/A^3 to GPa

        return {
            "value": {"C11": None, "C12": None, "C44": None, "bulk_modulus": round(B_GPa, 2)},
            "unit": "GPa",
            "property": "elastic_constants",
        }

    def compute_bulk_modulus(
        self,
        calculator=None,
        kim_model: str | None = None,
        species: str = "U",
        structure: str = "BCC",
        lattice_guess: float | None = None,
        method: str = "ev_curve",
        elastic_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compute bulk modulus.

        Two methods:
        1. 'ev_curve': Fit energy-volume curve (default)
        2. 'elastic': Derive from elastic constants B = (C11 + 2*C12) / 3
        """
        if method == "elastic" and elastic_result is not None:
            c11 = elastic_result.get("C11")
            c12 = elastic_result.get("C12")
            if c11 is not None and c12 is not None:
                B = (c11 + 2 * c12) / 3.0
                return {"value": round(B, 2), "unit": "GPa", "property": "bulk_modulus", "method": "elastic_constants"}

        # Fallback: EV curve fitting
        result = self.compute_elastic_constants(
            calculator=calculator, kim_model=kim_model,
            species=species, structure=structure, lattice_guess=lattice_guess,
        )
        bm = result["value"].get("bulk_modulus")
        return {"value": bm, "unit": "GPa", "property": "bulk_modulus", "method": "ev_curve"}

    def compute_vacancy_formation_energy(
        self,
        calculator=None,
        kim_model: str | None = None,
        species: str = "U",
        structure: str = "BCC",
        lattice_guess: float | None = None,
        supercell_size: int = 3,
    ) -> dict[str, Any]:
        """Compute monovacancy formation energy.

        Uses a supercell for better accuracy:
        Evf = E(N-1) - (N-1)/N * E(N)

        Args:
            supercell_size: Size of supercell (default 3 = 3x3x3).
                           Larger = more accurate but slower.
        """
        from ase import Atoms
        guess = lattice_guess or 3.4
        calc = self._get_calculator(calculator, kim_model, species)

        # Build supercell for better vacancy convergence
        atoms_prim = bulk(species, structure.lower(), a=guess)
        atoms_perfect = atoms_prim * (supercell_size, supercell_size, supercell_size)
        n = len(atoms_perfect)

        atoms_perfect.calc = calc
        e_perfect = atoms_perfect.get_potential_energy()

        # Remove one atom to create vacancy
        atoms_vac = atoms_perfect.copy()
        atoms_vac.pop(0)
        atoms_vac.calc = calc
        e_vac = atoms_vac.get_potential_energy()

        # Vacancy formation energy
        e_vf = e_vac - (n - 1) / n * e_perfect
        return {
            "value": round(e_vf, 4),
            "unit": "eV",
            "property": "vacancy_formation_energy",
            "supercell_size": f"{supercell_size}x{supercell_size}x{supercell_size}",
            "n_atoms": n,
        }
