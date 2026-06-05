"""Tests for structure_generator."""

import os
import tempfile
import numpy as np
import pytest

from autovc.structure_generator import generate_random_solid_solution


def _parse_lammps(path):
    """Parse a LAMMPS data file, return dict with n_atoms, n_types, types list, content."""
    with open(path) as f:
        content = f.read()
    lines = content.split("\n")
    n_atoms = None
    n_types = None
    types = []
    in_atoms = False
    for line in lines:
        stripped = line.strip()
        # Header: "N atoms" (number, space, keyword)
        if stripped.endswith("atoms") and "atom types" not in stripped:
            parts = stripped.split()
            try:
                n_atoms = int(parts[0])
            except ValueError:
                pass
        elif stripped.endswith("atom types"):
            parts = stripped.split()
            try:
                n_types = int(parts[0])
            except ValueError:
                pass
        elif stripped.startswith("Atoms"):
            in_atoms = True
            continue
        elif in_atoms and stripped == "":
            if types:
                in_atoms = False
        elif in_atoms and stripped:
            parts = stripped.split()
            if len(parts) >= 5:
                types.append(int(parts[1]))
    return {"n_atoms": n_atoms, "n_types": n_types, "types": types, "content": content}


def test_bcc_binary():
    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "mow.lmp")
        generate_random_solid_solution(
            "bcc", 3.15, None, {"Mo": 0.85, "W": 0.15}, (4, 4, 4), out,
        )
        d = _parse_lammps(out)
        assert d["n_atoms"] == 4 * 4 * 4 * 2  # bcc: 2 atoms/unit cell
        assert d["n_types"] == 2
        assert len(d["types"]) == d["n_atoms"]
        mo_frac = d["types"].count(1) / d["n_atoms"]
        w_frac = d["types"].count(2) / d["n_atoms"]
        assert abs(mo_frac - 0.85) < 0.05
        assert abs(w_frac - 0.15) < 0.05


def test_fcc_trinary():
    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "ternary.lmp")
        generate_random_solid_solution(
            "fcc", 3.6, None, {"Fe": 0.5, "Ni": 0.3, "Cr": 0.2}, (3, 3, 3), out,
        )
        d = _parse_lammps(out)
        assert d["n_atoms"] == 3 * 3 * 3 * 4  # fcc: 4 atoms/unit cell
        assert d["n_types"] == 3


def test_invalid_concentrations():
    with pytest.raises(ValueError, match="sum to 1.0"):
        generate_random_solid_solution(
            "bcc", 3.0, None, {"Mo": 0.5, "W": 0.3}, (2, 2, 2), "/tmp/bad.lmp"
        )


def test_lammps_format_valid():
    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "fmt.lmp")
        generate_random_solid_solution(
            "sc", 2.8, None, {"Cu": 0.6, "Ni": 0.4}, (2, 2, 2), out
        )
        d = _parse_lammps(out)
        assert "Masses" in d["content"]
        assert "Atoms # atomic" in d["content"]
        assert "xlo xhi" in d["content"]
        assert d["n_atoms"] is not None
