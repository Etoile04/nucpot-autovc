import logging
from typing import Any
from ase.build import bulk

logger = logging.getLogger(__name__)

_PROP_DEFS = {
    "lattice_constant": {"unit": "angstrom", "desc": "Equilibrium lattice constant"},
    "cohesive_energy": {"unit": "eV/atom", "desc": "Cohesive energy per atom"},
    "elastic_constants": {"unit": "GPa", "desc": "Elastic constants C11/C12/C44"},
    "bulk_modulus": {"unit": "GPa", "desc": "Bulk modulus"},
}

class PropertyCalculator:
    def supported_properties(self) -> list[str]:
        return list(_PROP_DEFS.keys())

    @staticmethod
    def get_property_info(name: str) -> dict:
        return _PROP_DEFS.get(name, {})

    def compute_lattice_constant(self, kim_model: str, species: str = "U", structure: str = "BCC", lattice_guess: float | None = None) -> dict:
        from autovc.core.calculator import KimCalculator
        calc = KimCalculator(kim_model=kim_model)
        guess = lattice_guess or 3.4
        atoms = bulk(species, structure.lower(), a=guess)
        try:
            from ase.optimize import BFGS
            atoms.calc = calc._get_calculator()
            opt = BFGS(atoms)
            opt.run(fmax=0.001, steps=200)
            cell = atoms.get_cell()
            a = cell[0][0]
            return {"value": a, "unit": "angstrom", "property": "lattice_constant"}
        except Exception as e:
            logger.error(f"Lattice constant calc failed: {e}")
            raise

    def compute_cohesive_energy(self, kim_model: str, species: str = "U", structure: str = "BCC", lattice_guess: float | None = None) -> dict:
        from autovc.core.calculator import KimCalculator
        from ase import Atoms
        calc = KimCalculator(kim_model=kim_model)
        guess = lattice_guess or 3.4
        atoms_bulk = bulk(species, structure.lower(), a=guess)
        atoms_bulk.calc = calc._get_calculator()
        e_bulk = atoms_bulk.get_potential_energy()
        atom_single = Atoms(species, positions=[[0,0,0]], cell=[20,20,20], pbc=False)
        atom_single.calc = calc._get_calculator()
        e_atom = atom_single.get_potential_energy()
        return {"value": e_atom - e_bulk, "unit": "eV/atom", "property": "cohesive_energy"}

    def compute_elastic_constants(self, kim_model: str, species: str = "U", structure: str = "BCC", lattice_guess: float | None = None) -> dict:
        return {"value": {"C11": None, "C12": None, "C44": None}, "unit": "GPa", "property": "elastic_constants", "error": "Requires kimvv"}
