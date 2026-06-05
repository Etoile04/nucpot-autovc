"""Random solid solution structure generator using Atomsk + Python post-processing."""

import subprocess
import tempfile
import os
import numpy as np
from pathlib import Path


def generate_random_solid_solution(
    lattice: str,
    a: float,
    c: float | None,
    species_concentrations: dict[str, float],
    supercell: tuple[int, int, int],
    output_file: str,
) -> str:
    """Generate a random solid solution supercell as a LAMMPS data file.

    Args:
        lattice: Crystal lattice type (bcc, fcc, hcp, diamond, sc).
        a: Lattice parameter a (Angstroms).
        c: Lattice parameter c (Angstroms), used for hcp; ignored otherwise.
        species_concentrations: Dict mapping element symbol to concentration fraction.
            e.g. {"Mo": 0.85, "W": 0.15}. Must sum to ~1.0.
        supercell: Tuple (nx, ny, nz) for supercell replication.
        output_file: Path to output LAMMPS data file.

    Returns:
        Path to the generated LAMMPS data file.
    """
    # Validate concentrations
    total = sum(species_concentrations.values())
    if not np.isclose(total, 1.0, atol=0.01):
        raise ValueError(f"Concentrations must sum to 1.0, got {total}")

    # Sort species by concentration descending; most abundant is the base
    sorted_species = sorted(species_concentrations.items(), key=lambda x: -x[1])
    base_element = sorted_species[0][0]

    # Atomsk binary
    atomsk_bin = os.environ.get("ATOMSK_BIN", "/home/z203/bin/atomsk/atomsk")

    with tempfile.TemporaryDirectory() as tmpdir:
        base_lmp = os.path.join(tmpdir, "base.lmp")

        # Step 1: Create base lattice with Atomsk
        cmd = [atomsk_bin, "--create", lattice, str(a)]
        if lattice == "hcp" and c is not None:
            cmd.append(str(c))
        cmd.append(base_element)
        cmd.append(base_lmp)
        cmd.extend(["-duplicate", *[str(s) for s in supercell]])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Atomsk failed: {result.stderr}")

        # Step 2: Parse the LAMMPS data file
        with open(base_lmp) as f:
            lines = f.readlines()

        # Parse header
        n_atoms = None
        box_bounds = []
        masses_section = []
        atoms_section = []
        reading_masses = False
        reading_atoms = False
        header_done = False

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            if line.startswith("Atoms"):
                reading_atoms = True
                reading_masses = False
                i += 1  # skip the section header line
                continue

            if line.startswith("Masses"):
                reading_masses = True
                reading_atoms = False
                i += 1
                continue

            if reading_atoms and line == "":
                if atoms_section:  # end of atoms section
                    reading_atoms = False
                i += 1
                continue

            if reading_masses and line == "":
                if masses_section:
                    reading_masses = False
                i += 1
                continue

            if reading_atoms:
                atoms_section.append(lines[i])
            elif reading_masses:
                masses_section.append(lines[i])
            else:
                # Header parsing
                if "atoms" in line and n_atoms is None:
                    parts = line.split()
                    n_atoms = int(parts[0])
                elif "xlo xhi" in line:
                    parts = line.split()
                    box_bounds.append((float(parts[0]), float(parts[1])))
                elif "ylo yhi" in line:
                    parts = line.split()
                    box_bounds.append((float(parts[0]), float(parts[1])))
                elif "zlo zhi" in line:
                    parts = line.split()
                    box_bounds.append((float(parts[0]), float(parts[1])))
            i += 1

        if n_atoms is None:
            raise RuntimeError("Failed to parse atom count from LAMMPS file")

        # Step 3: Build species list and assign random types
        species_list = [s for s, _ in sorted_species]
        concentrations = [c for _, c in sorted_species]
        n_types = len(species_list)

        # Random assignment based on concentrations
        rng = np.random.default_rng()
        type_assignments = rng.choice(n_types, size=n_atoms, p=concentrations) + 1  # 1-indexed

        # Step 4: Write output LAMMPS data file
        # Atomic masses (common values)
        MASS_TABLE = {
            "H": 1.008, "He": 4.003, "Li": 6.941, "Be": 9.012, "B": 10.81,
            "C": 12.011, "N": 14.007, "O": 15.999, "F": 18.998, "Ne": 20.180,
            "Na": 22.990, "Mg": 24.305, "Al": 26.982, "Si": 28.086, "P": 30.974,
            "S": 32.065, "Cl": 35.453, "Ar": 39.948, "K": 39.098, "Ca": 40.078,
            "Sc": 44.956, "Ti": 47.867, "V": 50.942, "Cr": 51.996, "Mn": 54.938,
            "Fe": 55.845, "Co": 58.933, "Ni": 58.693, "Cu": 63.546, "Zn": 65.380,
            "Nb": 92.906, "Mo": 95.950, "Ru": 101.07, "Rh": 102.91, "Pd": 106.42,
            "Ag": 107.87, "Ta": 180.95, "W": 183.84, "Re": 186.21, "Os": 190.23,
            "Ir": 192.22, "Pt": 195.08, "Au": 196.97, "Zr": 91.224, "Hf": 178.49,
        }

        with open(output_file, "w") as f:
            f.write(f"Random solid solution (atomsk + python)\n\n")
            f.write(f"{n_atoms} atoms\n")
            f.write(f"{n_types} atom types\n")
            for label, (lo, hi) in zip(["xlo xhi", "ylo yhi", "zlo zhi"], box_bounds):
                f.write(f"{lo:.10f} {hi:.10f} {label}\n")
            f.write("\nMasses\n\n")
            for idx, elem in enumerate(species_list, 1):
                mass = MASS_TABLE.get(elem, 1.0)
                f.write(f"{idx} {mass:.6f} # {elem}\n")
            f.write("\nAtoms # atomic\n\n")
            for j, atom_line in enumerate(atoms_section):
                parts = atom_line.split()
                # parts: id type x y z (possibly more columns)
                atom_id = parts[0]
                # Replace type with our random assignment
                rest = parts[2:]  # x, y, z, ...
                f.write(f"{atom_id} {type_assignments[j]} {' '.join(rest)}\n")

    return output_file
