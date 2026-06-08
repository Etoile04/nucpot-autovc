"""LAMMPS-based computation backend for interatomic potential verification.

Runs LAMMPS simulations to compute material properties:
- lattice_constant: minimize → extract equilibrium lattice parameter
- cohesive_energy: energy/atom from minimized structure
- elastic_constants: strain-energy method (6 independent strains)
- bulk_modulus: derived from elastic constants B = (C11+2*C12)/3
- vacancy_formation_energy: remove atom → minimize → Evac = E_defect - (N-1)/N*E_perfect
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

from autovc.config import get_settings

logger = logging.getLogger(__name__)


# ── Reference value lookup via PG ─────────────────────────────────
def _get_ref_value(material: str, structure: str, prop: str) -> float | None:
    """Look up reference value from PG (with fallback)."""
    try:
        from autovc.reference.data import get_reference_value
        result = get_reference_value(material, structure, prop)
        if result and result.get("value") is not None:
            return float(result["value"])
    except Exception as e:
        logger.debug(f"PG ref lookup failed for {material}/{structure}/{prop}: {e}")
    # Minimal fallback for initial lattice guess
    _GUESS: dict[str, float] = {
        "U": 2.85, "Mo": 3.15, "Zr": 3.61,
        "U-Mo": 3.40, "U-Zr": 3.45,
    }
    if prop == "lattice_constant":
        return _GUESS.get(material, 3.4)
    return None

# Grading thresholds: A < 2%, B < 5%, C < 10%, D < 20%, F >= 20%
GRADE_THRESHOLDS = (0.02, 0.05, 0.10, 0.20)

# LAMMPS lattice type mapping
LAMMPS_LATTICE_MAP = {
    "bcc": "bcc",
    "BCC": "bcc",
    "fcc": "fcc",
    "FCC": "fcc",
    "hcp": "hcp",
    "HCP": "hcp",
    "diamond": "diamond",
    "Diamond": "diamond",
    "diamond_cubic": "diamond",
    "Cubic": "fcc",      # generic cubic defaults to fcc
    "SC": "sc",
    "sc": "sc",
}

# Ideal c/a ratio for HCP
HCP_IDEAL_CA = 1.633


# Progress milestones
PROGRESS_MAP = {
    "lattice_constant": 0.15,
    "cohesive_energy": 0.3,
    "elastic_constants": 0.5,
    "bulk_modulus": 0.6,
    "vacancy_formation_energy": 0.75,
    "surface_energy": 0.9,
}

# ── LAMMPS input templates ─────────────────────────────────────────

def _pair_style_config(lammps_config: dict | None, potential_type: str | None) -> tuple[str, str]:
    """Return (pair_style line, pair_coeff line) based on config/type."""
    cfg = lammps_config or {}
    pair_style = cfg.get("pair_style", "")
    pair_coeff = cfg.get("pair_coeff", "")
    pot_file = cfg.get("pot_file", "")

    if pair_style and pair_coeff:
        return pair_style, pair_coeff

    # Auto-detect from type
    ptype = (potential_type or "").lower()
    if "deepmd" in ptype or "dp" in ptype:
        return "pair_style deepmd " + (pot_file or "model.pb"), "pair_coeff * *"
    elif "meam" in ptype:
        return "pair_style meam", f"pair_coeff * * {pot_file} U U"
    elif "hybrid" in ptype:
        return f"pair_style hybrid/overlay {cfg.get('sub_styles', 'eam/alloy')}", f"pair_coeff * * {pot_file} U"
    else:
        # Default EAM/alloy
        return "pair_style eam/alloy", f"pair_coeff * * {pot_file} U"


def _generate_lattice_input(
    elements: list[str],
    pair_style: str,
    pair_coeff: str,
    guess_a: float = 3.4,
    structure: str = "bcc",
    size: int = 4,
    is_dp: bool = False,
) -> str:
    """Generate LAMMPS input for lattice constant + cohesive energy."""
    element = elements[0] if elements else "U"
    lammps_struct = LAMMPS_LATTICE_MAP.get(structure, structure.lower())
    if lammps_struct == "hcp":
        lattice_line = f"lattice {lammps_struct} {guess_a} a1 1 0 0 a2 0 1 0 a3 0 0 {HCP_IDEAL_CA}"
    else:
        lattice_line = f"lattice {lammps_struct} {guess_a}"
    plugin_load = "plugin load /opt/deepmd/lib/libdeepmd_lmpplugin.so\n" if is_dp else ""
    n_types = len(elements)
    MASSES = {"U": 238.03, "Mo": 95.95, "Zr": 91.22, "Nb": 92.91, "Fe": 55.85,
              "Cr": 52.00, "W": 183.84, "Ta": 180.95, "V": 50.94, "Ti": 47.87,
              "Ni": 58.69, "Cu": 63.55, "Al": 26.98, "O": 16.00, "H": 1.008,
              "He": 4.003, "Sn": 118.71, "Ce": 140.12, "Ag": 107.87,
              "In": 114.82, "Se": 78.96, "Si": 28.09, "C": 12.011,
              "N": 14.007, "Mg": 24.31, "Li": 6.941, "Na": 22.99,
              "K": 39.098, "Ca": 40.08, "Mn": 54.94, "Co": 58.93,
              "Zn": 65.38, "Ga": 69.72, "Ge": 72.63, "As": 74.92,
              "Br": 79.90, "Pd": 106.42, "Cd": 112.41, "Au": 196.97,
              "Pb": 207.2, "Bi": 208.98, "Th": 232.04, "Pu": 244.06,
              "Y": 88.91, "La": 138.91, "Pr": 140.91, "Nd": 144.24,
              "Sm": 150.36, "Eu": 151.96, "Gd": 157.25, "Tb": 158.93,
              "Dy": 162.50, "Ho": 164.93, "Er": 167.26, "Tm": 168.93,
              "Yb": 173.05, "Lu": 174.97, "Hf": 178.49, "Re": 186.21,
              "Os": 190.23, "Ir": 192.22, "Pt": 195.08}
    if n_types <= 1:
        el = elements[0] if elements else "U"
        mass_line = f"mass 1 {MASSES.get(el, 100.0)}"
        box_block = f"create_box 1 box\n{mass_line}\ncreate_atoms 1 box"
    else:
        mass_lines = "\n".join(
            f"mass {i+1} {MASSES.get(elements[i], 100.0)}" for i in range(n_types)
        )
        box_block = f"create_box {n_types} box\n{mass_lines}\ncreate_atoms 1 box"
        # For DP multi-element: random type assignment (equiatomic approximation)
        frac = 1.0 / n_types
        for i in range(1, n_types):
            remaining_frac = 1.0 - frac * i
            box_block += f"\nset type {i} type/fraction {i+1} {1.0/n_types:.4f} {12345+i}"
    return f"""units metal
dimension 3
boundary p p p
atom_style atomic

{lattice_line}
region box block 0 {size} 0 {size} 0 {size}
{box_block}

{plugin_load}{pair_style}
{pair_coeff}

fix 1 all box/relax iso 0.0
minimize 1e-10 1e-10 1000 10000
unfix 1

variable natom equal count(all)
variable ecoh equal pe/v_natom
variable a equal lx/{size}

print "RESULT lattice_constant ${{a}}"
print "RESULT cohesive_energy ${{ecoh}}"
variable pe equal pe
print "RESULT total_energy ${{pe}}"
"""


def _multi_element_box_block(elements: list[str], MASSES: dict) -> str:
    """Generate create_box + mass + create_atoms for multi-element support."""
    n_types = len(elements)
    if n_types <= 1:
        return "create_box 1 box\ncreate_atoms 1 box"
    mass_lines = "\n".join(
        f"mass {i+1} {MASSES.get(elements[i], 100.0)}" for i in range(n_types)
    )
    return f"create_box {n_types} box\n{mass_lines}\ncreate_atoms 1 box"


def _generate_elastic_input(
    elements: list[str],
    pair_style: str,
    pair_coeff: str,
    is_dp: bool = False,
    guess_a: float = 3.4,
    structure: str = "bcc",
    size: int = 3,
) -> str:
    """Generate LAMMPS input for elastic constants via strain-energy method.

    Computes C11 (uniaxial xx), C12 (uniaxial yy), C44 (shear xy).
    For cubic crystals: C11 = dE/(eps^2 * V), C12 similar, C44 = dE/(gamma^2 * V).
    """
    element = elements[0] if elements else "U"
    lammps_struct = LAMMPS_LATTICE_MAP.get(structure, structure.lower())
    if lammps_struct == "hcp":
        lattice_line = f"lattice {lammps_struct} {guess_a} a1 1 0 0 a2 0 1 0 a3 0 0 {HCP_IDEAL_CA}"
    else:
        lattice_line = f"lattice {lammps_struct} {guess_a}"
        plugin_load = "plugin load /opt/deepmd/lib/libdeepmd_lmpplugin.so\n" if is_dp else ""

    MASSES = {"U": 238.03, "Mo": 95.95, "Zr": 91.22, "Nb": 92.91, "Fe": 55.85,
              "Cr": 52.00, "W": 183.84, "Ta": 180.95, "V": 50.94, "Ti": 47.87,
              "Ni": 58.69, "Cu": 63.55, "Al": 26.98, "O": 16.00, "H": 1.008,
              "He": 4.003, "Sn": 118.71, "Ce": 140.12, "Ag": 107.87,
              "In": 114.82, "Se": 78.96, "Si": 28.09, "C": 12.011,
              "N": 14.007, "Mg": 24.31, "Li": 6.941, "Na": 22.99,
              "K": 39.098, "Ca": 40.08, "Mn": 54.94, "Co": 58.93,
              "Zn": 65.38, "Ga": 69.72, "Ge": 72.63, "As": 74.92,
              "Br": 79.90, "Pd": 106.42, "Cd": 112.41, "Au": 196.97,
              "Pb": 207.2, "Bi": 208.98, "Th": 232.04, "Pu": 244.06,
              "Y": 88.91, "La": 138.91, "Pr": 140.91, "Nd": 144.24,
              "Sm": 150.36, "Eu": 151.96, "Gd": 157.25, "Tb": 158.93,
              "Dy": 162.50, "Ho": 164.93, "Er": 167.26, "Tm": 168.93,
              "Yb": 173.05, "Lu": 174.97, "Hf": 178.49, "Re": 186.21,
              "Os": 190.23, "Ir": 192.22, "Pt": 195.08}
    n_types = len(elements)
    box_block = _multi_element_box_block(elements, MASSES)

    def _clear_block() -> str:
        lines = ["clear", lattice_line, f"region box block 0 {size} 0 {size} 0 {size}"]
        lines.append(f"create_box {n_types if n_types > 0 else 1} box")
        for i, e in enumerate(elements[:max(n_types, 1)], 1):
            lines.append(f"mass {i} {MASSES.get(e, 100.0)}")
        lines.extend(["create_atoms 1 box", pair_style, pair_coeff])
        return "\n".join(lines)

    return f"""units metal
dimension 3
boundary p p p
atom_style atomic

{lattice_line}
region box block 0 {size} 0 {size} 0 {size}
{box_block}

{pair_style}
{pair_coeff}

# First minimize to get reference
minimize 1e-10 1e-10 1000 10000
variable e0 equal pe
variable v0 equal vol
run 0

# Apply strains and compute energy differences
variable eps equal 0.01

# exx strain (for C11)
{_clear_block()}
change_box all x delta ${{eps}} ${{eps}} remap units box
minimize 1e-10 1e-10 500 5000
variable e_exx equal pe
print "RESULT e_exx ${{e_exx}}"

# eyy strain (for C12)
{_clear_block()}
change_box all y delta ${{eps}} ${{eps}} remap units box
minimize 1e-10 1e-10 500 5000
variable e_eyy equal pe
print "RESULT e_eyy ${{e_eyy}}"

# shear xy strain (for C44)
{_clear_block()}
change_box all xy delta ${{eps}} remap units box
minimize 1e-10 1e-10 500 5000
variable e_shear_xy equal pe
print "RESULT e_shear_xy ${{e_shear_xy}}"

print "RESULT reference_energy ${{e0}}"
print "RESULT volume ${{v0}}"
print "RESULT strain ${{eps}}"
"""


def _generate_vacancy_input(
    elements: list[str],
    pair_style: str,
    pair_coeff: str,
    guess_a: float = 3.4,
    structure: str = "bcc",
    size: int = 3,
) -> str:
    """Generate LAMMPS input for vacancy formation energy."""
    element = elements[0] if elements else "U"
    lammps_struct = LAMMPS_LATTICE_MAP.get(structure, structure.lower())
    if lammps_struct == "hcp":
        lattice_line = f"lattice {lammps_struct} {guess_a} a1 1 0 0 a2 0 1 0 a3 0 0 {HCP_IDEAL_CA}"
    else:
        lattice_line = f"lattice {lammps_struct} {guess_a}"
    MASSES = {"U": 238.03, "Mo": 95.95, "Zr": 91.22, "Nb": 92.91, "Fe": 55.85,
              "Cr": 52.00, "W": 183.84, "Ta": 180.95, "V": 50.94, "Ti": 47.87,
              "Ni": 58.69, "Cu": 63.55, "Al": 26.98, "O": 16.00, "H": 1.008,
              "He": 4.003, "Sn": 118.71, "Ce": 140.12, "Ag": 107.87,
              "In": 114.82, "Se": 78.96, "Si": 28.09, "C": 12.011,
              "N": 14.007, "Mg": 24.31, "Li": 6.941, "Na": 22.99,
              "K": 39.098, "Ca": 40.08, "Mn": 54.94, "Co": 58.93,
              "Zn": 65.38, "Ga": 69.72, "Ge": 72.63, "As": 74.92,
              "Br": 79.90, "Pd": 106.42, "Cd": 112.41, "Au": 196.97,
              "Pb": 207.2, "Bi": 208.98, "Th": 232.04, "Pu": 244.06,
              "Y": 88.91, "La": 138.91, "Pr": 140.91, "Nd": 144.24,
              "Sm": 150.36, "Eu": 151.96, "Gd": 157.25, "Tb": 158.93,
              "Dy": 162.50, "Ho": 164.93, "Er": 167.26, "Tm": 168.93,
              "Yb": 173.05, "Lu": 174.97, "Hf": 178.49, "Re": 186.21,
              "Os": 190.23, "Ir": 192.22, "Pt": 195.08}
    box_block = _multi_element_box_block(elements, MASSES)
    return f"""units metal
dimension 3
boundary p p p
atom_style atomic

{lattice_line}
region box block 0 {size} 0 {size} 0 {size}
{box_block}

{pair_style}
{pair_coeff}

# Perfect crystal energy
minimize 1e-10 1e-10 1000 10000
variable e_perfect equal pe
variable natom equal count(all)
print "RESULT e_perfect ${{e_perfect}}"
print "RESULT natom ${{natom}}"

# Create vacancy by removing atom 1
delete_atoms atom 1
minimize 1e-10 1e-10 1000 10000
variable e_vacancy equal pe
variable natom2 equal count(all)
print "RESULT e_vacancy ${{e_vacancy}}"
print "RESULT natom2 ${{natom2}}"

# Vacancy formation energy: Evf = E(N-1) - (N-1)/N * E(N)
variable evf equal v_e_vacancy - (v_natom2)/(v_natom)*v_e_perfect
print "RESULT vacancy_formation_energy ${{evf}}"
"""



def _generate_surface_energy_input(
    elements: list[str],
    pair_style: str,
    pair_coeff: str,
    guess_a: float = 3.4,
    structure: str = "bcc",
    size: int = 4,
    is_dp: bool = False,
) -> str:
    """Generate LAMMPS input for surface energy calculation.
    
    Creates a slab with a free surface and computes:
    E_surface = (E_slab - N_slab/N_bulk * E_bulk) / (2 * A)
    Factor 2 for two free surfaces.
    """
    element = elements[0] if elements else "U"
    lammps_struct = LAMMPS_LATTICE_MAP.get(structure, structure.lower())
    
    if lammps_struct == "hcp":
        c_param = guess_a * HCP_IDEAL_CA
        lattice_line = f"lattice {lammps_struct} {guess_a} a1 1 0 0 a2 0 1 0 a3 0 0 {HCP_IDEAL_CA}"
    else:
        lattice_line = f"lattice {lammps_struct} {guess_a}"

    MASSES = {"U": 238.03, "Mo": 95.95, "Zr": 91.22, "Nb": 92.91, "Fe": 55.85,
              "Cr": 52.00, "W": 183.84, "Ta": 180.95, "V": 50.94, "Ti": 47.87,
              "Ni": 58.69, "Cu": 63.55, "Al": 26.98, "O": 16.00, "H": 1.008,
              "He": 4.003, "Sn": 118.71, "Ce": 140.12, "Ag": 107.87,
              "In": 114.82, "Se": 78.96, "Si": 28.09, "C": 12.011,
              "N": 14.007, "Mg": 24.31, "Li": 6.941, "Na": 22.99,
              "K": 39.098, "Ca": 40.08, "Mn": 54.94, "Co": 58.93,
              "Zn": 65.38, "Ga": 69.72, "Ge": 72.63, "As": 74.92,
              "Br": 79.90, "Pd": 106.42, "Cd": 112.41, "Au": 196.97,
              "Pb": 207.2, "Bi": 208.98, "Th": 232.04, "Pu": 244.06,
              "Y": 88.91, "La": 138.91, "Pr": 140.91, "Nd": 144.24,
              "Sm": 150.36, "Eu": 151.96, "Gd": 157.25, "Tb": 158.93,
              "Dy": 162.50, "Ho": 164.93, "Er": 167.26, "Tm": 168.93,
              "Yb": 173.05, "Lu": 174.97, "Hf": 178.49, "Re": 186.21,
              "Os": 190.23, "Ir": 192.22, "Pt": 195.08}
    box_block = _multi_element_box_block(elements, MASSES)
    
    return f"""units metal
dimension 3
boundary p p s
atom_style atomic

{lattice_line}
region box block 0 {size} 0 {size} 0 {size*2}
{box_block}

{pair_style}
{pair_coeff}

# Bulk energy reference
minimize 1e-10 1e-10 1000 10000
variable e_bulk equal pe
variable n_bulk equal count(all)
variable area equal lx*ly
print "RESULT e_bulk ${{e_bulk}}"
print "RESULT n_bulk ${{n_bulk}}"
print "RESULT area ${{area}}"

# Create free surface by deleting top half
region top block INF INF INF INF {size} INF
delete_atoms region top
minimize 1e-10 1e-10 1000 10000
variable e_slab equal pe
variable n_slab equal count(all)
print "RESULT e_slab ${{e_slab}}"
print "RESULT n_slab ${{n_slab}}"
"""

# ── Result parsing ──────────────────────────────────────────────────

def _parse_lammps_output(output: str) -> dict[str, float]:
    """Parse RESULT lines from LAMMPS output."""
    results = {}
    for line in output.splitlines():
        m = re.match(r"RESULT\s+(\S+)\s+(-?[\d.eE+-]+)", line.strip())
        if m:
            results[m.group(1)] = float(m.group(2))
    return results


def _grade_property(computed: float, reference: float | None) -> dict:
    """Grade a computed property against reference value."""
    if reference is None:
        return {"grade": None, "absolute_error": None, "relative_error": None}
    rel_err = abs(computed - reference) / abs(reference) if reference != 0 else float("inf")
    abs_err = abs(computed - reference)
    grade = "F"
    for g, th in zip(["A", "B", "C", "D"], GRADE_THRESHOLDS):
        if rel_err <= th:
            grade = g
            break
    return {"grade": grade, "absolute_error": abs_err, "relative_error": rel_err}


# ── LAMMPS runner ───────────────────────────────────────────────────

class LAMMPSRunner:
    """Run LAMMPS calculations for potential verification."""

    def __init__(
        self,
        potential_meta: dict,
        lammps_bin: str | None = None,
        potential_dir: str | None = None,
        structure: str | None = None,
    ):
        self.meta = potential_meta
        self.settings = get_settings()
        # Auto-detect potential type and select appropriate LAMMPS binary
        ptype_init = (potential_meta.get("type") or "").lower()
        is_dp = "dp" in ptype_init or "deepmd" in ptype_init
        is_meam = "meam" in ptype_init
        if is_dp:
            self.lammps_bin = lammps_bin or "/usr/local/bin/lmp-with-dp"
            self._is_dp = True
            self._is_meam = False
        elif is_meam:
            self.lammps_bin = lammps_bin or os.environ.get("LAMMPS_BIN_MEAM", "/app/lmp-full")
            self._is_dp = False
            self._is_meam = True
        else:
            self.lammps_bin = lammps_bin or getattr(self.settings, "LAMMPS_BIN", "lmp_serial")
            self._is_dp = False
            self._is_meam = False
        self.potential_dir = potential_dir or os.environ.get("POTENTIAL_DIR", "/app/uploads")
        self.elements = potential_meta.get("elements", [])
        # Structure detection: explicit arg > meta.structure > meta.phase > meta.lammps_config.structure > "bcc"
        self.structure = (
            structure
            or potential_meta.get("structure")
            or potential_meta.get("phase")
            or (potential_meta.get("lammps_config") or {}).get("structure")
            or "bcc"
        )

    def _resolve_pot_file(self) -> str | None:
        """Find the potential file on disk using multiple strategies."""
        cfg = self.meta.get("lammps_config") or {}

        # Strategy 1: explicit pot_file in config
        pot_file = cfg.get("pot_file", "")
        if pot_file and os.path.isfile(pot_file):
            return pot_file

        # Strategy 2: extract filename from pair_coeff string
        pair_coeff = cfg.get("pair_coeff", "")
        if pair_coeff:
            parts = pair_coeff.split()
            for part in parts:
                if "." in part and not part.startswith("*") and not part.startswith("map"):
                    candidate = os.path.join(self.potential_dir, part)
                    if os.path.isfile(candidate):
                        return candidate

        # Strategy 3: download from file_url (Supabase storage)
        # Supports comma-separated URLs for multi-file potentials (e.g., MEAM)
        file_url = self.meta.get("file_url", "")
        if file_url:
            import httpx
            urls = [u.strip() for u in file_url.split(",") if u.strip()]
            for single_url in urls:
                resolved = single_url
                if resolved.startswith("/"):
                    from autovc.config import get_settings
                    settings = get_settings()
                    base_url = settings.SUPABASE_URL.rstrip("/")
                    resolved = f"{base_url}{resolved}"
                fname = resolved.split("/")[-1]
                local_path = os.path.join(self.potential_dir, fname)
                if os.path.isfile(local_path):
                    continue  # already downloaded
                try:
                    resp = httpx.get(resolved, follow_redirects=True, timeout=60)
                    if resp.status_code == 200:
                        with open(local_path, "wb") as f:
                            f.write(resp.content)
                        logger.info(f"Downloaded {fname} ({len(resp.content)} bytes)")
                except Exception as e:
                    logger.warning(f"Failed to download {resolved}: {e}")
            # Return the primary pot_file if it's now on disk
            cfg = self.meta.get("lammps_config") or {}
            pot_file_name = cfg.get("pot_file", "")
            if pot_file_name:
                # pot_file might be absolute or relative
                if os.path.isfile(pot_file_name):
                    return pot_file_name
                candidate = os.path.join(self.potential_dir, pot_file_name)
                if os.path.isfile(candidate):
                    return candidate
            # Fallback: return first downloaded file
            if urls:
                first_fname = urls[0].split("/")[-1]
                first_path = os.path.join(self.potential_dir, first_fname)
                if os.path.isfile(first_path):
                    return first_path

        # Strategy 4: try matching by name
        name = self.meta.get("name", "")
        for ext in [".eam.alloy", ".eam", ".meam", ".fs.eam", ".eam.fs", ".mtp", ".pb", ".pth", ""]:
            path = os.path.join(self.potential_dir, f"{name}{ext}")
            if os.path.isfile(path):
                return path

        # Strategy 5: fuzzy match by elements
        if os.path.isdir(self.potential_dir):
            elements = self.meta.get("elements", [])
            if elements:
                elem_str = "-".join(elements)
                for fname in os.listdir(self.potential_dir):
                    if elem_str in fname:
                        return os.path.join(self.potential_dir, fname)

        return None

    def _get_pair_config(self, pot_file: str) -> tuple[str, str]:
        """Get pair_style and pair_coeff with resolved pot_file path."""
        cfg = self.meta.get("lammps_config") or {}
        all_elements = " ".join(self.elements) if self.elements else "U"

        pair_style = cfg.get("pair_style", "eam/alloy")
        if "deepmd" in pair_style.lower():
            # DP: pair_style deepmd /path/to/model.pb
            return f"pair_style {pair_style} {pot_file}", "pair_coeff * *"
        elif "mtp" in pair_style.lower():
            # MTP: pair_style mtp /path/to/model.mtp
            return f"pair_style {pair_style} {pot_file}", "pair_coeff * *"
        elif "eam" in pair_style.lower():
            pair_coeff = f"pair_coeff * * {pot_file} {all_elements}"
        elif "meam" in pair_style.lower():
            # MEAM needs library.meam + specific.meam
            # Use pair_coeff from config if available (author-specified format)
            raw_pc = cfg.get("pair_coeff", "")
            if raw_pc:
                # Replace bare filenames with absolute paths from potential_dir
                pair_coeff = raw_pc
                # Extract all tokens that look like filenames (contain '.')
                for token in raw_pc.split():
                    if "." in token and not token.startswith("*"):
                        abs_path = os.path.join(self.potential_dir, token)
                        if os.path.isfile(abs_path):
                            pair_coeff = pair_coeff.replace(token, abs_path)
            else:
                # Fallback: auto-construct from file_url
                file_url = self.meta.get("file_url", "") or ""
                lib_file = None
                spec_file = pot_file
                if "," in file_url:
                    parts = [p.strip().split("/")[-1] for p in file_url.split(",")]
                    if len(parts) >= 2:
                        lib_name = parts[0]
                        spec_name = parts[1]
                        lib_candidate = os.path.join(self.potential_dir, lib_name)
                        spec_candidate = os.path.join(self.potential_dir, spec_name)
                        if os.path.isfile(lib_candidate):
                            lib_file = lib_candidate
                        if os.path.isfile(spec_candidate):
                            spec_file = spec_candidate
                if not lib_file:
                    pot_dir = self.potential_dir
                    for fn in os.listdir(pot_dir) if os.path.isdir(pot_dir) else []:
                        if fn.startswith("library-") and fn.endswith(".meam"):
                            lib_file = os.path.join(pot_dir, fn)
                            break
                if lib_file:
                    pair_coeff = f"pair_coeff * * {lib_file} {all_elements} {spec_file} {all_elements}"
                else:
                    pair_coeff = f"pair_coeff * * {pot_file} {all_elements} {all_elements}"
        else:
            pair_coeff = f"pair_coeff * * {pot_file} {all_elements}"
        return f"pair_style {pair_style}", pair_coeff

    async def _run_lammps(self, input_script: str) -> str:
        """Run LAMMPS with given input script, return combined output (stdout + log)."""
        with tempfile.TemporaryDirectory(prefix="lammps_") as tmpdir:
            input_path = os.path.join(tmpdir, "in.lammps")
            with open(input_path, "w") as f:
                f.write(input_script)
            log_path = os.path.join(tmpdir, "log.lammps")
            cmd = f"{self.lammps_bin} -in {input_path} -screen none -log {log_path}"
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmpdir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

            # Read log file for RESULT lines (LAMMPS prints to log with -screen none)
            log_output = ""
            if os.path.isfile(log_path):
                with open(log_path) as lf:
                    log_output = lf.read()
            combined = stdout.decode() + "\n" + log_output

            if proc.returncode != 0:
                error_lines = [l for l in log_output.split("\n") if "ERROR" in l]
                error_detail = error_lines[-1] if error_lines else stderr.decode()[-500:]
                raise RuntimeError(
                    f"LAMMPS failed (rc={proc.returncode}): {error_detail}"
                )
            return combined
    async def run_property(
        self,
        prop_name: str,
        progress_callback: Callable[[float, str], Any] | None = None,
    ) -> dict:
        """Run a single property calculation via LAMMPS."""
        pot_file = self._resolve_pot_file()
        if not pot_file:
            raise FileNotFoundError(
                "缺少势函数文件，请先上传"
            )

        pair_style, pair_coeff = self._get_pair_config(pot_file)
        all_elements = " ".join(self.elements) if self.elements else "U"
        element = self.elements[0] if self.elements else "U"
        guess = 3.4
        # Check reference for a better guess
        ref_lc = _get_ref_value(element, self.structure, "lattice_constant")
        if ref_lc is not None:
            guess = ref_lc

        if prop_name in ("lattice_constant", "cohesive_energy"):
            script = _generate_lattice_input(
                self.elements, pair_style, pair_coeff, guess, self.structure, is_dp=getattr(self, '_is_dp', False)
            )
            output = await self._run_lammps(script)
            parsed = _parse_lammps_output(output)
            results = {}
            if "lattice_constant" in parsed:
                v = parsed["lattice_constant"]
                ref_v = _get_ref_value(element, self.structure, "lattice_constant")
                g = _grade_property(v, ref_v)
                results["lattice_constant"] = {
                    "value": v, "unit": "angstrom", "reference": ref_v, **g,
                }
            if "cohesive_energy" in parsed:
                v = parsed["cohesive_energy"]
                ref_v = _get_ref_value(element, self.structure, "cohesive_energy")
                g = _grade_property(v, ref_v)
                results["cohesive_energy"] = {
                    "value": v, "unit": "eV/atom", "reference": ref_v, **g,
                }
            if progress_callback and prop_name == "lattice_constant" and "lattice_constant" in results:
                await progress_callback(0.2, "lattice_constant done")
            if progress_callback and prop_name == "cohesive_energy" and "cohesive_energy" in results:
                await progress_callback(0.4, "cohesive_energy done")
            return results.get(prop_name, {"value": None, "error": "not computed"})

        elif prop_name == "elastic_constants":
            script = _generate_elastic_input(
                self.elements, pair_style, pair_coeff, guess, self.structure, size=3, is_dp=getattr(self, '_is_dp', False)
            )
            output = await self._run_lammps(script)
            parsed = _parse_lammps_output(output)
            # Extract elastic constants from strain energies
            e0 = parsed.get("reference_energy", 0)
            e_exx = parsed.get("e_exx", 0)
            e_eyy = parsed.get("e_eyy", 0)
            e_shear = parsed.get("e_shear_xy", 0)
            eps = parsed.get("strain", 0.01)
            vol = parsed.get("volume", 1)

            # eV/A^3 → GPa: multiply by 160.2177
            conv = 160.2177
            C11 = (e_exx - e0) / (eps ** 2 * vol) * conv if vol else 0
            C12 = (e_eyy - e0) / (eps ** 2 * vol) * conv if vol else 0
            C44 = (e_shear - e0) / (eps ** 2 * vol) * conv if vol else 0

            # Grade individual constants
            ref_c11 = _get_ref_value(element, self.structure, "C11")
            ref_c12 = _get_ref_value(element, self.structure, "C12")
            ref_c44 = _get_ref_value(element, self.structure, "C44")

            result = {
                "value": {
                    "C11": round(C11, 2),
                    "C12": round(C12, 2),
                    "C44": round(C44, 2),
                },
                "unit": "GPa",
                "grades": {
                    "C11": _grade_property(C11, ref_c11),
                    "C12": _grade_property(C12, ref_c12),
                    "C44": _grade_property(C44, ref_c44),
                },
                "reference": {
                    "C11": ref_c11, "C12": ref_c12, "C44": ref_c44,
                },
            }
            if progress_callback:
                await progress_callback(0.7, "elastic_constants done")
            return result

        elif prop_name == "bulk_modulus":
            # First get elastic constants
            elastic = await self.run_property("elastic_constants", progress_callback=None)
            c11 = elastic.get("value", {}).get("C11")
            c12 = elastic.get("value", {}).get("C12")
            if c11 is not None and c12 is not None:
                B = (c11 + 2 * c12) / 3.0
                result = {"value": round(B, 2), "unit": "GPa"}
            else:
                result = {"value": None, "unit": "GPa", "error": "could not derive from elastic constants"}
            if progress_callback:
                await progress_callback(0.85, "bulk_modulus done")
            return result

        elif prop_name == "vacancy_formation_energy":
            script = _generate_vacancy_input(
                self.elements, pair_style, pair_coeff, guess, self.structure, size=3, is_dp=getattr(self, '_is_dp', False)
            )
            output = await self._run_lammps(script)
            parsed = _parse_lammps_output(output)
            evf = parsed.get("vacancy_formation_energy")
            ref_evf = _get_ref_value(element, self.structure, "vacancy_formation_energy")
            g = _grade_property(evf, ref_evf) if evf is not None else {"grade": None, "absolute_error": None, "relative_error": None}
            result = {"value": evf, "unit": "eV", "reference": ref_evf, **g}
            if progress_callback:
                await progress_callback(1.0, "vacancy_formation_energy done")
            return result

        elif prop_name == "surface_energy":
            script = _generate_surface_energy_input(
                self.elements, pair_style, pair_coeff, guess, self.structure, size=4
            )
            output = await self._run_lammps(script)
            parsed = _parse_lammps_output(output)
            e_bulk = parsed.get("e_bulk", 0)
            e_slab = parsed.get("e_slab", 0)
            n_bulk = parsed.get("n_bulk", 1)
            n_slab = parsed.get("n_slab", 1)
            area = parsed.get("area", 1)
            # Surface energy: gamma = (E_slab - N_slab/N_bulk * E_bulk) / (2 * A)
            # Convert eV/A^2 to J/m^2: multiply by 16.0218
            if area > 0 and n_bulk > 0:
                gamma_ev = (e_slab - n_slab / n_bulk * e_bulk) / (2 * area)
                gamma_jm2 = gamma_ev * 16.0218
            else:
                gamma_jm2 = None
            ref_se = _get_ref_value(element, self.structure, "surface_energy")
            g = _grade_property(gamma_jm2, ref_se) if gamma_jm2 is not None else {"grade": None}
            result = {"value": round(gamma_jm2, 4) if gamma_jm2 else None, "unit": "J/m²", "reference": ref_se, **g}
            if progress_callback:
                await progress_callback(1.0, "surface_energy done")
            return result

        else:
            return {"value": None, "error": f"unknown property: {prop_name}"}

    async def run_template(
        self,
        template: str,
        progress_callback: Callable[[float, str, dict], Any] | None = None,
    ) -> dict:
        """Run all properties for a given template."""
        TEMPLATE_PROPERTIES = {
            "basic": ["lattice_constant", "cohesive_energy"],
            "mechanical": ["lattice_constant", "cohesive_energy", "elastic_constants", "bulk_modulus"],
            "defect": ["lattice_constant", "cohesive_energy", "vacancy_formation_energy"],
            "comprehensive": ["lattice_constant", "cohesive_energy", "elastic_constants", "bulk_modulus", "vacancy_formation_energy"],
        }
        props = TEMPLATE_PROPERTIES.get(template, TEMPLATE_PROPERTIES["basic"])
        all_results = {}
        current_progress = 0.0

        for prop in props:
            try:
                result = await self.run_property(prop)
                all_results[prop] = result
                # Update progress
                target_progress = PROGRESS_MAP.get(prop, current_progress)
                current_progress = max(current_progress, target_progress)
                if progress_callback:
                    await progress_callback(current_progress, f"{prop} done", all_results)
            except Exception as e:
                logger.error(f"Property {prop} failed: {e}")
                all_results[prop] = {"value": None, "error": str(e)}
                if progress_callback:
                    await progress_callback(current_progress, f"{prop} failed: {e}", all_results)

        # Compute overall grade
        grades = []
        for v in all_results.values():
            g = v.get("grade")
            if g:
                grades.append(g)
        overall = max(grades, key=lambda x: {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}.get(x, 4)) if grades else None

        return {"results": all_results, "overall_grade": overall, "template": template}
