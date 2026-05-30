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

# Progress milestones
PROGRESS_MAP = {
    "lattice_constant": 0.2,
    "cohesive_energy": 0.4,
    "elastic_constants": 0.7,
    "bulk_modulus": 0.85,
    "vacancy_formation_energy": 1.0,
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
    if "meam" in ptype:
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
) -> str:
    """Generate LAMMPS input for lattice constant + cohesive energy."""
    element = elements[0] if elements else "U"
    return f"""units metal
dimension 3
boundary p p p
atom_style atomic

lattice {structure} {guess_a}
region box block 0 {size} 0 {size} 0 {size}
create_box 1 box
create_atoms 1 box

{pair_style}
{pair_coeff}

minimize 1e-10 1e-10 1000 10000

variable natom equal count(all)
variable ecoh equal pe/v_natom
variable a equal lx/{size}

print "RESULT lattice_constant ${{a}}"
print "RESULT cohesive_energy ${{ecoh}}"
print "RESULT total_energy ${{pe}}"
"""


def _generate_elastic_input(
    elements: list[str],
    pair_style: str,
    pair_coeff: str,
    guess_a: float = 3.4,
    structure: str = "bcc",
    size: int = 3,
) -> str:
    """Generate LAMMPS input for elastic constants via strain-energy method.

    Computes C11 (uniaxial xx), C12 (uniaxial yy), C44 (shear xy).
    For cubic crystals: C11 = dE/(eps^2 * V), C12 similar, C44 = dE/(gamma^2 * V).
    """
    element = elements[0] if elements else "U"
    return f"""units metal
dimension 3
boundary p p p
atom_style atomic

lattice {structure} {guess_a}
region box block 0 {size} 0 {size} 0 {size}
create_box 1 box
create_atoms 1 box

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
clear
lattice {structure} {guess_a}
region box block 0 {size} 0 {size} 0 {size}
create_box 1 box
create_atoms 1 box
{pair_style}
{pair_coeff}
change_box all x delta ${{eps}} ${{eps}} remap units box
minimize 1e-10 1e-10 500 5000
variable e_exx equal pe
print "RESULT e_exx ${{e_exx}}"

# eyy strain (for C12)
clear
lattice {structure} {guess_a}
region box block 0 {size} 0 {size} 0 {size}
create_box 1 box
create_atoms 1 box
{pair_style}
{pair_coeff}
change_box all y delta ${{eps}} ${{eps}} remap units box
minimize 1e-10 1e-10 500 5000
variable e_eyy equal pe
print "RESULT e_eyy ${{e_eyy}}"

# shear xy strain (for C44)
clear
lattice {structure} {guess_a}
region box block 0 {size} 0 {size} 0 {size}
create_box 1 box
create_atoms 1 box
{pair_style}
{pair_coeff}
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
    return f"""units metal
dimension 3
boundary p p p
atom_style atomic

lattice {structure} {guess_a}
region box block 0 {size} 0 {size} 0 {size}
create_box 1 box
create_atoms 1 box

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
        potential_dir: str = "/tmp/lammps-potentials",
    ):
        self.meta = potential_meta
        self.settings = get_settings()
        self.lammps_bin = lammps_bin or getattr(self.settings, "LAMMPS_BIN", "lmp_serial")
        self.potential_dir = potential_dir
        self.elements = potential_meta.get("elements", [])
        self.structure = "bcc"  # Default

    def _resolve_pot_file(self) -> str | None:
        """Find the potential file on disk."""
        cfg = self.meta.get("lammps_config") or {}
        pot_file = cfg.get("pot_file", "")
        if pot_file and os.path.isfile(pot_file):
            return pot_file
        # Try potential_dir
        name = self.meta.get("name", "")
        for ext in [".eam.alloy", ".eam", ".meam", ".fs.eam", ""]:
            path = os.path.join(self.potential_dir, f"{name}{ext}")
            if os.path.isfile(path):
                return path
        # Try any file in potential_dir
        if os.path.isdir(self.potential_dir):
            files = os.listdir(self.potential_dir)
            if files:
                return os.path.join(self.potential_dir, files[0])
        return None

    def _get_pair_config(self, pot_file: str) -> tuple[str, str]:
        """Get pair_style and pair_coeff with resolved pot_file path."""
        cfg = self.meta.get("lammps_config") or {}
        element = self.elements[0] if self.elements else "U"

        pair_style = cfg.get("pair_style", "eam/alloy")
        if "eam" in pair_style.lower():
            pair_coeff = f"pair_coeff * * {pot_file} {element}"
        elif "meam" in pair_style.lower():
            pair_coeff = f"pair_coeff * * {pot_file} {element} {element}"
        else:
            pair_coeff = f"pair_coeff * * {pot_file} {element}"
        return f"pair_style {pair_style}", pair_coeff

    async def _run_lammps(self, input_script: str) -> str:
        """Run LAMMPS with given input script, return stdout."""
        with tempfile.TemporaryDirectory(prefix="lammps_") as tmpdir:
            input_path = os.path.join(tmpdir, "in.lammps")
            with open(input_path, "w") as f:
                f.write(input_script)
            cmd = f"{self.lammps_bin} -in {input_path} -screen none -log {tmpdir}/log.lammps"
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmpdir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"LAMMPS failed (rc={proc.returncode}): {stderr.decode()[-500:]}"
                )
            return stdout.decode()

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
        element = self.elements[0] if self.elements else "U"
        guess = 3.4
        # Check reference for a better guess
        ref_lc = _get_ref_value(element, "BCC", "lattice_constant")
        if ref_lc is not None:
            guess = ref_lc

        if prop_name in ("lattice_constant", "cohesive_energy"):
            script = _generate_lattice_input(
                self.elements, pair_style, pair_coeff, guess, self.structure
            )
            output = await self._run_lammps(script)
            parsed = _parse_lammps_output(output)
            results = {}
            if "lattice_constant" in parsed:
                v = parsed["lattice_constant"]
                ref_v = _get_ref_value(element, "BCC", "lattice_constant")
                g = _grade_property(v, ref_v)
                results["lattice_constant"] = {
                    "value": v, "unit": "angstrom", "reference": ref_v, **g,
                }
            if "cohesive_energy" in parsed:
                v = parsed["cohesive_energy"]
                ref_v = _get_ref_value(element, "BCC", "cohesive_energy")
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
                self.elements, pair_style, pair_coeff, guess, self.structure, size=3
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
            ref_c11 = _get_ref_value(element, "BCC", "C11")
            ref_c12 = _get_ref_value(element, "BCC", "C12")
            ref_c44 = _get_ref_value(element, "BCC", "C44")

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
                self.elements, pair_style, pair_coeff, guess, self.structure, size=3
            )
            output = await self._run_lammps(script)
            parsed = _parse_lammps_output(output)
            evf = parsed.get("vacancy_formation_energy")
            result = {"value": evf, "unit": "eV"}
            if progress_callback:
                await progress_callback(1.0, "vacancy_formation_energy done")
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
