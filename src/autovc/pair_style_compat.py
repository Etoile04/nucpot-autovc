"""
LAMMPS pair_style compatibility layer.
Runtime version detection + MTP auto-adapt (D002).
"""

import os
import re
import shutil
import subprocess
import tempfile
from typing import Optional


def detect_lammps_version(lammps_exec: Optional[str] = None) -> Optional[tuple]:
    """Detect LAMMPS version from executable. Returns (year, month, day) or None."""
    if lammps_exec is None:
        lammps_exec = _find_lammps()
    if lammps_exec is None:
        return None

    try:
        result = subprocess.run(
            [lammps_exec, "-h"],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout + result.stderr
    except Exception:
        return None

    # Match "23 Jun 2022" or "23 Jun 2022 - Update X"
    m = re.search(r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})", output)
    if m:
        month_map = {
            "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
            "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
            "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
        }
        return (int(m.group(3)), month_map[m.group(2)], int(m.group(1)))

    # Match version like "LAMMPS (29 Aug 2024)"
    return None


def _find_lammps() -> Optional[str]:
    """Search common locations for LAMMPS executable."""
    candidates = [
        os.path.expanduser("~/nucpot-autovc/lmp_serial"),
        os.path.expanduser("~/nucpot-autovc/lmp"),
        "/usr/bin/lmp",
        "/usr/bin/lmp_serial",
        "/usr/local/bin/lmp",
        "/usr/local/bin/lmp_serial",
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    for name in ("lmp_serial", "lmp", "lmp_mpi"):
        found = shutil.which(name)
        if found:
            return found
    return None


def get_mtp_pair_style_config(
    lammps_version: Optional[tuple],
    potential_file: str,
    mtp_config: Optional[str] = None,
) -> dict:
    """Return MTP pair_style config adapted to LAMMPS version.

    Returns dict with: pair_style_line, pair_coeff_line, config_file (or None), extra_lines (or [])
    """
    # New-style: LAMMPS >= 2025.0.0 uses built-in USER-MTP (pair_style mtp without ini)
    is_new = lammps_version is not None and lammps_version >= (2025, 0, 0)

    if is_new:
        return {
            "pair_style_line": "pair_style mtp",
            "pair_coeff_line": f"pair_coeff * * {potential_file}",
            "config_file": None,
            "extra_lines": [],
        }

    # Old-style: needs mlip.ini
    ini_path = mtp_config or os.path.join(
        tempfile.gettempdir(), "mlip.ini"
    )
    ini_content = _generate_mlip_ini(potential_file)
    config_file = ini_path

    return {
        "pair_style_line": f"pair_style mtp {ini_path}",
        "pair_coeff_line": f"pair_coeff * * {potential_file}",
        "config_file": config_file,
        "config_file_content": ini_content,
        "extra_lines": [],
    }


def _generate_mlip_ini(potential_file: str) -> str:
    """Generate mlip.ini content for old LAMMPS MTP support."""
    abs_path = os.path.abspath(potential_file)
    return (
        "mtp-filename = {potential}\n"
        "species = {{species}}\n"  # placeholder, filled at runtime
    ).format(potential=abs_path)
    # Simplified; actual mlip.ini may need more fields depending on MLIP version
    return f"mtp-filename = {abs_path}\n"


# --- Standard (non-MTP) pair styles ---

_STANDARD_STYLES = {
    "eam":       {"pair_style": "pair_style eam", "fmt": "pair_coeff * * {file}"},
    "eam/alloy": {"pair_style": "pair_style eam/alloy", "fmt": "pair_coeff * * {file}"},
    "eam/fs":    {"pair_style": "pair_style eam/fs", "fmt": "pair_coeff * * {file}"},
    "meam":      {"pair_style": "pair_style meam", "fmt": "pair_coeff * * {libfile} {potential_file} {elem1} {elem2}"},
    "tersoff":   {"pair_style": "pair_style tersoff", "fmt": "pair_coeff * * {file}"},
    "dp":        {"pair_style": "pair_style deepmd", "fmt": "pair_coeff * * {file}"},
}


def get_pair_style_config(
    potential_type: str,
    potential_file: str,
    lammps_exec: Optional[str] = None,
    extra_config: Optional[dict] = None,
) -> dict:
    """Unified entry point for pair_style config generation.

    Returns dict: pair_style_line, pair_coeff_line, config_file (optional), extra_lines (optional)
    """
    pt = potential_type.lower().strip()

    if pt == "mtp":
        version = detect_lammps_version(lammps_exec)
        return get_mtp_pair_style_config(version, potential_file, extra_config)

    info = _STANDARD_STYLES.get(pt)
    if info is None:
        raise ValueError(f"Unsupported potential_type: {potential_type!r}")

    coeff_line = info["fmt"].format(file=potential_file)
    return {
        "pair_style_line": info["pair_style"],
        "pair_coeff_line": coeff_line,
        "config_file": None,
        "extra_lines": [],
    }
