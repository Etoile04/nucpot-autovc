"""mp_adapter: fetch elastic, thermodynamic, and structural properties from Materials Project.

Provides a thin wrapper around mp-api to extract reference-quality DFT data
for the nuclear material systems defined in gap_analyzer.TARGET_SYSTEMS.

Usage:
    # 需要设置 MP_API_KEY 环境变量，或传入 api_key
    export MP_API_KEY="your_key_here"
    python3 scripts/mp_adapter.py --dry-run
    python3 scripts/mp_adapter.py --output data/mp-extracted.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Element system → MP chemsys mapping
# ---------------------------------------------------------------------------

# MP uses chemsys like "U-Mo" which matches our element_system names directly
# for pure elements, chemsys = element symbol
SYSTEM_TO_CHEMSYS = {
    "U": "U",
    "Mo": "Mo",
    "Zr": "Zr",
    "Nb": "Nb",
    "Pu": "Pu",
    "Fe": "Fe",
    "Cr": "Cr",
    "U-Mo": "U-Mo",
    "U-Zr": "U-Zr",
    "U-Nb": "U-Nb",
    "U-Pu": "U-Pu",
    "U-Pu-Zr": "U-Pu-Zr",
    "SiC": "Si-C",
}

# MP crystal system → our phase mapping
CRYSTAL_SYSTEM_TO_PHASE = {
    "cubic": "BCC",       # most nuclear metals are BCC at high T
    "tetragonal": "BCT",
    "hexagonal": "HCP",
    "trigonal": "HCP",
    "orthorhombic": "ORC",
    "monoclinic": "MON",
    "triclinic": "TRI",
}

# Preferred structure match: for BCC systems, look for cubic with spacegroup Im-3m (229)
# For HCP, look for hexagonal with P6_3/mmc (194)
BCC_SPACEGROUPS = {229, 211, 221}  # Im-3m, Pm-3m, Pm-3m
HCP_SPACEGROUPS = {194, 191, 187}  # P6_3/mmc, P6/mmm, P-6m2

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class MpProperty:
    """A single extracted property from MP."""
    element_system: str
    phase: str
    property: str          # ref-gap-fill property name (C11, lattice_constant, etc.)
    value: float
    unit: str
    method: str            # always "DFT" for MP data
    source: str            # "Materials Project (mp-XXXXX)"
    confidence: str        # "medium" (DFT, not experimental)
    mp_id: str
    chemsys: str
    crystal_system: str
    spacegroup_number: int
    functional: str = "PBE"  # MP default


@dataclass
class MpExtractionResult:
    """Summary of MP extraction run."""
    total_queried: int = 0
    total_materials: int = 0
    total_properties: int = 0
    properties: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped_systems: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Property extraction
# ---------------------------------------------------------------------------


def _extract_elastic_props(
    doc,
    element_system: str,
    phase: str,
) -> list[MpProperty]:
    """Extract elastic constants from a summary document.

    MP summary provides bulk_modulus and shear_modulus (Voigt-Reuss-Hill averages).
    Individual C_ij require a separate query to the elasticity endpoint.
    """
    props = []
    mp_id = str(doc.material_id)

    # bulk_modulus is available directly in summary
    bm = getattr(doc, "bulk_modulus", None)
    if bm is not None:
        # bulk_modulus may be a dict {"VRH": value} or a float
        k_vrh = bm if isinstance(bm, (int, float)) else bm.get("VRH", None)
        if k_vrh is not None and k_vrh > 0:
            props.append(MpProperty(
                element_system=element_system, phase=phase,
                property="bulk_modulus", value=round(float(k_vrh), 2),
                unit="GPa", method="DFT",
                source=f"Materials Project ({mp_id})",
                confidence="medium", mp_id=mp_id,
                chemsys=element_system,
                crystal_system=str(getattr(doc, "symmetry", None) and doc.symmetry.crystal_system or ""),
                spacegroup_number=getattr(doc, "symmetry", None) and doc.symmetry.number,
            ))

    return props


def _extract_lattice_constant(
    doc,
    element_system: str,
    phase: str,
) -> list[MpProperty]:
    """Extract lattice constant from structure."""
    props = []
    structure = getattr(doc, "structure", None)
    if structure is None:
        return props

    mp_id = str(doc.material_id)
    try:
        a = structure.lattice.a
        # Only record if reasonable for our systems
        if 2.0 <= a <= 7.0:
            props.append(MpProperty(
                element_system=element_system, phase=phase,
                property="lattice_constant", value=round(a, 4),
                unit="Å", method="DFT",
                source=f"Materials Project ({mp_id})",
                confidence="medium", mp_id=mp_id,
                chemsys=element_system,
                crystal_system=str(getattr(doc, "symmetry", None) and doc.symmetry.crystal_system or ""),
                spacegroup_number=getattr(doc, "symmetry", None) and doc.symmetry.number,
            ))
    except Exception:
        pass

    return props


def _extract_thermo_props(
    doc,
    element_system: str,
    phase: str,
) -> list[MpProperty]:
    """Extract formation energy from summary doc."""
    props = []
    mp_id = str(doc.material_id)

    # formation_energy_per_atom
    fe = getattr(doc, "formation_energy_per_atom", None)
    if fe is not None:
        props.append(MpProperty(
            element_system=element_system, phase=phase,
            property="formation_energy", value=round(fe, 4),
            unit="eV/atom", method="DFT",
            source=f"Materials Project ({mp_id})",
            confidence="medium", mp_id=mp_id,
            chemsys=element_system,
            crystal_system=str(getattr(doc, "symmetry", None) and doc.symmetry.crystal_system or ""),
            spacegroup_number=getattr(doc, "symmetry", None) and doc.symmetry.number,
        ))

    return props


def _determine_phase(doc) -> str:
    """Determine our phase label from MP crystal system / spacegroup."""
    sym = getattr(doc, "symmetry", None)
    if sym is None:
        return "unknown"

    sg = getattr(sym, "number", None)
    cs = getattr(sym, "crystal_system", None)

    # Check spacegroup first for disambiguation
    if sg in BCC_SPACEGROUPS:
        return "BCC"
    if sg in HCP_SPACEGROUPS:
        return "HCP"

    # Fall back to crystal system
    return CRYSTAL_SYSTEM_TO_PHASE.get(cs, str(cs) if cs else "unknown")


def _fetch_elastic_tensor(
    mpr,
    mp_id: str,
    element_system: str,
    phase: str,
) -> list[MpProperty]:
    """Fetch individual C_ij from the elasticity endpoint for a specific material."""
    props = []
    try:
        elast_docs = mpr.materials.elasticity.search(
            material_ids=[mp_id],
        )
        if not elast_docs:
            return props

        ed = elast_docs[0]
        raw_tensor = getattr(ed, "elastic_tensor", None)
        if raw_tensor is None:
            return props

        # elastic_tensor is a named-tuple-like object with 'raw' and 'ieee_format' components
        # Use ieee_format for rounded values, raw for precision
        # The object iterates as list of (name, matrix) pairs
        # Access the matrix directly via indexing
        try:
            # Try ieee_format first (rounded)
            if hasattr(raw_tensor, 'ieee_format'):
                matrix = raw_tensor.ieee_format
            elif hasattr(raw_tensor, 'raw'):
                matrix = raw_tensor.raw
            else:
                matrix = raw_tensor
        except Exception:
            matrix = raw_tensor

        # Convert to list of lists
        t = [list(row) for row in matrix]
        if len(t) < 6:
            return props

        # Voigt notation: [[C11,C12,C12,0,0,0],[C12,...],[C12,C12,C11,...],[0,0,0,C44,...],...]
        c11 = t[0][0]
        c12 = t[0][1]
        c44 = t[3][3] if len(t) > 3 else None

        if c11 and c11 > 0:
            props.append(MpProperty(
                element_system=element_system, phase=phase,
                property="C11", value=round(float(c11), 2),
                unit="GPa", method="DFT",
                source=f"Materials Project ({mp_id})",
                confidence="medium", mp_id=mp_id,
                chemsys=element_system,
                crystal_system="", spacegroup_number=0,
            ))
        if c12 is not None:
            props.append(MpProperty(
                element_system=element_system, phase=phase,
                property="C12", value=round(float(c12), 2),
                unit="GPa", method="DFT",
                source=f"Materials Project ({mp_id})",
                confidence="medium", mp_id=mp_id,
                chemsys=element_system,
                crystal_system="", spacegroup_number=0,
            ))
        if c44 is not None and c44 > 0:
            props.append(MpProperty(
                element_system=element_system, phase=phase,
                property="C44", value=round(float(c44), 2),
                unit="GPa", method="DFT",
                source=f"Materials Project ({mp_id})",
                confidence="medium", mp_id=mp_id,
                chemsys=element_system,
                crystal_system="", spacegroup_number=0,
            ))
    except Exception as e:
        print(f"    ⚠️  Elasticity fetch failed for {mp_id}: {e}", file=sys.stderr)

    return props


def _pick_best_material(docs: list, element_system: str, preferred_phase: str | None = None) -> list:
    """Pick the best material(s) from search results.

    Priority:
    1. Matching phase + lowest energy_above_hull
    2. Any phase + lowest energy_above_hull
    """
    if not docs:
        return []

    # Score each doc
    scored = []
    for doc in docs:
        phase = _determine_phase(doc)
        e_hull = getattr(doc, "energy_above_hull", None)
        e_hull_val = e_hull if e_hull is not None else 999.0
        has_elastic = getattr(doc, "bulk_modulus", None) is not None

        # Prefer: phase match > on hull > has elastic data
        score = 0
        if preferred_phase and phase == preferred_phase:
            score -= 1000
        if e_hull_val <= 0.01:
            score -= 100
        if has_elastic:
            score -= 10
        score += e_hull_val  # lower hull distance is better

        scored.append((score, doc))

    scored.sort(key=lambda x: x[0])

    # Return top candidate per unique phase
    seen_phases = set()
    result = []
    for score, doc in scored:
        phase = _determine_phase(doc)
        if phase not in seen_phases:
            seen_phases.add(phase)
            result.append(doc)
        if len(result) >= 3:  # max 3 phases per system
            break

    return result


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------


def extract_system(
    mpr,
    element_system: str,
    chemsys: str,
    preferred_phase: str | None = None,
) -> list[MpProperty]:
    """Extract all available properties for a single material system."""
    props = []

    try:
        docs = mpr.materials.summary.search(
            chemsys=chemsys,
            fields=[
                "material_id", "formula_pretty", "structure",
                "symmetry", "bulk_modulus", "shear_modulus",
                "formation_energy_per_atom",
                "energy_above_hull", "band_gap", "density",
            ],
        )
    except Exception as e:
        print(f"  ❌ Error querying {chemsys}: {e}", file=sys.stderr)
        return props

    if not docs:
        print(f"  ⚠️  No materials found for {chemsys}", file=sys.stderr)
        return props

    # Pick best candidates
    best = _pick_best_material(docs, element_system, preferred_phase)
    print(f"  📦 {chemsys}: {len(docs)} total, {len(best)} selected", file=sys.stderr)

    for doc in best:
        phase = _determine_phase(doc)
        mp_id = str(doc.material_id)

        # Extract all property types
        props.extend(_extract_elastic_props(doc, element_system, phase))
        props.extend(_extract_lattice_constant(doc, element_system, phase))
        props.extend(_extract_thermo_props(doc, element_system, phase))

        # Fetch individual C_ij from elasticity endpoint
        tensor_props = _fetch_elastic_tensor(mpr, mp_id, element_system, phase)
        if tensor_props:
            props.extend(tensor_props)
            print(f"    ✅ Elastic tensor for {mp_id}: {len(tensor_props)} C_ij values", file=sys.stderr)

    return props


def extract_all(
    api_key: str | None = None,
    systems: list[str] | None = None,
    dry_run: bool = False,
) -> MpExtractionResult:
    """Main entry: extract properties for all target systems."""
    from mp_api.client import MPRester

    key = api_key or os.environ.get("MP_API_KEY", "")
    if not key and not dry_run:
        return MpExtractionResult(errors=["MP_API_KEY not set and no api_key provided"])

    result = MpExtractionResult()

    # Determine which systems to query
    target_chemsys = SYSTEM_TO_CHEMSYS
    if systems:
        target_chemsys = {k: v for k, v in SYSTEM_TO_CHEMSYS.items() if k in systems}

    if dry_run:
        print("=== DRY RUN ===")
        print(f"Would query {len(target_chemsys)} systems:")
        for name, chem in target_chemsys.items():
            print(f"  {name:15s} → chemsys={chem}")
        print(f"\nExtractable properties per material:")
        print("  lattice_constant, C11, C12, C44, bulk_modulus, formation_energy")
        print(f"\nConfidence: medium (DFT computed, not experimental)")
        result.total_queried = len(target_chemsys)
        return result

    with MPRester(key) as mpr:
        for element_system, chemsys in target_chemsys.items():
            result.total_queried += 1
            print(f"\n🔍 Querying {element_system} ({chemsys})...", file=sys.stderr)

            # Determine preferred phase
            preferred = None
            for ts in [{"element_system": "U", "phase": "BCC", "priority": 1},
                       {"element_system": "Mo", "phase": "BCC", "priority": 1},
                       {"element_system": "Zr", "phase": "BCC", "priority": 1},
                       {"element_system": "Zr", "phase": "HCP", "priority": 1},
                       {"element_system": "Nb", "phase": "BCC", "priority": 1},
                       {"element_system": "U-Mo", "phase": "BCC", "priority": 1},
                       {"element_system": "U-Zr", "phase": "BCC", "priority": 2},
                       {"element_system": "U-Nb", "phase": "BCC", "priority": 2},
                       {"element_system": "U-Pu", "phase": "BCC", "priority": 2},
                       {"element_system": "U-Pu-Zr", "phase": "BCC", "priority": 2},
                       {"element_system": "Pu", "phase": "BCC", "priority": 2},
                       {"element_system": "Fe", "phase": "BCC", "priority": 3},
                       {"element_system": "Cr", "phase": "BCC", "priority": 3},
                       {"element_system": "SiC", "phase": None, "priority": 3}]:
                if ts["element_system"] == element_system:
                    preferred = ts["phase"]
                    break

            try:
                props = extract_system(mpr, element_system, chemsys, preferred)
                for p in props:
                    result.properties.append(asdict(p))
                    result.total_properties += 1
                if props:
                    result.total_materials += 1
            except Exception as e:
                result.errors.append(f"{element_system}: {e}")

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Extract properties from Materials Project")
    parser.add_argument("--api-key", help="MP API key (or set MP_API_KEY env)")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be queried")
    parser.add_argument("--systems", nargs="*", help="Specific systems to query (e.g. U Mo U-Mo)")
    args = parser.parse_args()

    result = extract_all(
        api_key=args.api_key,
        systems=args.systems,
        dry_run=args.dry_run,
    )

    # Output
    output = {
        "summary": {
            "total_queried": result.total_queried,
            "total_materials": result.total_materials,
            "total_properties": result.total_properties,
            "errors": result.errors,
            "skipped": result.skipped_systems,
        },
        "properties": result.properties,
    }

    output_json = json.dumps(output, indent=2, ensure_ascii=False, default=str)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"\n✅ Written to {args.output}")
    else:
        print(output_json)

    # Print summary
    print(f"\n📊 Summary: {result.total_properties} properties from {result.total_materials} materials", file=sys.stderr)
    if result.errors:
        print(f"⚠️  Errors: {len(result.errors)}", file=sys.stderr)
        for e in result.errors:
            print(f"  - {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
